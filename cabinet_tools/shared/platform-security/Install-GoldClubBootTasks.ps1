# Register the two AtStartup SYSTEM tasks the shell cannot do for itself.
#
# eshell runs OO_Security.ps1 as "goldclub" with a UAC-filtered token
# (BUILTIN\Administrators = "Group used for deny only"), so from the shell:
#   - BitLocker unlock silently no-ops -> black screen
#   - device removal is refused        -> COM11 stays owned by a ghost MUX node
#
# Both jobs therefore run as SYSTEM on an AtStartup trigger instead of being
# launched by the shell. AtStartup also means no privileged handoff is needed:
# OO_Security just waits for G: to appear.
#
# Run this ONCE per cabinet from an elevated session. Idempotent.
#
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    [string]$SecurityDir = 'C:\Platform\Security',
    [switch]$Remove
)

$ErrorActionPreference = 'Continue'

$UnlockTask = 'GoldClub-Unlock-Volume'
$MuxTask = 'GoldClub-Clear-MuxGhosts'
$HwStackTask = 'GoldClub-Ensure-HwStack'

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Elevated)) {
    Write-Error 'Install-GoldClubBootTasks must run elevated.'
    exit 1
}

if ($Remove) {
    foreach ($t in @($UnlockTask, $MuxTask, $HwStackTask)) {
        cmd /c "schtasks /Delete /TN `"$t`" /F" 2>&1 | ForEach-Object { "  $_" }
    }
    exit 0
}

function Register-StartupSystemTask {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string]$Arguments = ''
    )
    if (-not [IO.File]::Exists($ScriptPath)) {
        Write-Warning "skip ${Name}: $ScriptPath missing"
        return $false
    }
    $tr = "powershell.exe -WindowStyle Hidden -NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    if ($Arguments) { $tr += " $Arguments" }
    # /RU SYSTEM gives a full (unfiltered) token; /SC ONSTART needs no logon.
    $out = cmd /c "schtasks /Create /TN `"$Name`" /TR `"$tr`" /SC ONSTART /RU SYSTEM /RL HIGHEST /F" 2>&1
    $ok = ($LASTEXITCODE -eq 0)
    # Write-Host, not the pipeline: emitting here would make the function return
    # the schtasks banner alongside the boolean.
    $out | ForEach-Object { Write-Host "  $_" }
    return $ok
}

# devcon lives on G:, which is still BitLocker-locked when the MUX cleanup runs.
# Keep a copy on C: so the task has no dependency on the encrypted volume.
$devconLocal = Join-Path $SecurityDir 'devcon.exe'
if (-not [IO.File]::Exists($devconLocal)) {
    foreach ($src in @('G:\bin\devcon.exe', 'C:\goldclub\bin\devcon.exe')) {
        if ([IO.File]::Exists($src)) {
            try {
                Copy-Item -LiteralPath $src -Destination $devconLocal -Force -ErrorAction Stop
                "  copied devcon.exe from $src"
            }
            catch {
                Write-Warning "devcon copy failed: $($_.Exception.Message)"
            }
            break
        }
    }
}
if (-not [IO.File]::Exists($devconLocal)) {
    Write-Warning "devcon.exe not staged at $devconLocal - MUX cleanup will fall back to G:\bin"
}

"registering $UnlockTask ..."
$okUnlock = Register-StartupSystemTask -Name $UnlockTask `
    -ScriptPath (Join-Path $SecurityDir 'Unlock-GoldClubVolume.ps1')

"registering $MuxTask ..."
$okMux = Register-StartupSystemTask -Name $MuxTask `
    -ScriptPath (Join-Path $SecurityDir 'Clear-MuxGhostPorts.ps1')

"registering $HwStackTask ..."
# Do not pass -Restart: ONSTART must Start services after G: unlocks, not
# tear them down. Live Push / Escape watcher pass -Restart when they need a bounce.
$okHw = Register-StartupSystemTask -Name $HwStackTask `
    -ScriptPath (Join-Path $SecurityDir 'Ensure-GoldClubHwStack.ps1')

"`nresult: unlock=$okUnlock muxGhosts=$okMux hwStack=$okHw"
foreach ($t in @($UnlockTask, $MuxTask, $HwStackTask)) {
    $q = cmd /c "schtasks /Query /TN `"$t`" /FO LIST" 2>&1
    ($q | Where-Object { $_ -match 'TaskName|Status|Run As User' }) | ForEach-Object { "  $_" }
}
exit 0
