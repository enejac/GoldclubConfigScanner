# Unlock the BitLocker GOLDCLUB volume (G:) as SYSTEM.
#
# Why this exists: eshell launches OO_Security.ps1 as "goldclub", and although
# that account IS in the administrators group, the shell gets a UAC-filtered
# token - "whoami /groups" reports BUILTIN\Administrators as "Group used for
# deny only". BitLocker unlock of a data volume needs real admin rights, so
# UnlockerDisk.exe exits 0 and does nothing. On 31 Aug 2026 the shell retried 18
# times over 8 minutes and never unlocked G:; one elevated run unlocked it in
# ~5 s. That is the black-screen boot, and it is a privilege problem, not the
# BitLocker "race" it was mistaken for.
#
# Registered by Install-GoldClubBootTasks.ps1 as an AtStartup task running as
# SYSTEM, so it never depends on the interactive token.
#
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    [int]$TimeoutMinutes = 10
)

$ErrorActionPreference = 'Continue'

function Write-UnlockLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] [unlock-task] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @('C:\Platform\Security\oo-security.log', 'C:\tmp\oo-security.log')) {
        try {
            $dir = Split-Path -Parent $logPath
            if ($dir -and -not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }
            [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
        }
        catch {}
    }
    Write-Host $line
}

function Test-GoldClubReady {
    try {
        $d = [IO.DriveInfo]::new('G:\')
        return [bool]($d.IsReady -and [IO.File]::Exists('G:\Bootstrap.exe'))
    }
    catch {
        return $false
    }
}

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-HwStackAfterUnlock {
    $ensure = 'C:\Platform\Security\Ensure-GoldClubHwStack.ps1'
    if (-not [IO.File]::Exists($ensure)) {
        Write-UnlockLog 'Ensure-GoldClubHwStack.ps1 missing - services not started'
        return
    }
    Write-UnlockLog 'G: ready - starting GoldClub services'
    try {
        & $ensure
        Write-UnlockLog ("Ensure-GoldClubHwStack exit={0}" -f $LASTEXITCODE)
    }
    catch {
        Write-UnlockLog ("Ensure-GoldClubHwStack failed: {0}" -f $_.Exception.Message)
    }
}

if (Test-GoldClubReady) {
    Write-UnlockLog 'G: already unlocked'
    Invoke-HwStackAfterUnlock
    exit 0
}

if (-not (Test-Elevated)) {
    # Do not spin for 10 minutes on a token that cannot possibly succeed.
    Write-UnlockLog 'NOT ELEVATED - UnlockerDisk cannot unlock BitLocker from here'
    exit 2
}

Write-UnlockLog ("elevated unlock starting (timeout {0} min)" -f $TimeoutMinutes)

$exe = 'C:\Platform\Security\UnlockerDisk.exe'
if (-not [IO.File]::Exists($exe)) {
    Write-UnlockLog "FATAL: $exe missing"
    exit 3
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$pass = 0
while (-not (Test-GoldClubReady) -and (Get-Date) -lt $deadline) {
    $pass++
    try {
        $p = Start-Process -FilePath $exe -PassThru -Wait -WindowStyle Hidden -ErrorAction Stop
        Write-UnlockLog ("UnlockerDisk pass {0} exit={1}" -f $pass, $p.ExitCode)
    }
    catch {
        Write-UnlockLog ("UnlockerDisk pass {0} failed: {1}" -f $pass, $_.Exception.Message)
    }
    for ($i = 0; $i -lt 5 -and -not (Test-GoldClubReady); $i++) { Start-Sleep -Seconds 1 }
}

if (Test-GoldClubReady) {
    Write-UnlockLog ("G: GOLDCLUB unlocked after {0} pass(es)" -f $pass)
    Invoke-HwStackAfterUnlock
    exit 0
}

Write-UnlockLog ("gave up after {0} pass(es) - G: still locked" -f $pass)
exit 1
