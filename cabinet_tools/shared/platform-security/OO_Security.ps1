# GoldClub custom shell. eshell runs this via powershell.exe -File ...
# MUST keep param([string]$WorkingDirectory) or eshell black-screens.
#
# Order: UnlockerDisk -> G:\Bootstrap.exe -> (async) lab USB extras -> fallback.
#
# The boot is identical with and without the lab USB. Bootstrap owns the game:
# it runs the stock G:\platform\user\init\onlogon.ps1, which executes the whole
# numbered onlogon chain (05-03 service install, 05-04 ramclear, 17-SetSerialPorts,
# 90-StartServices) and then starts the game. Verified running on GST22377 on
# 31 Aug 2026 - an earlier note claiming that chain was dead was wrong.
#
# So do NOT start the stack / onlogon / game alongside Bootstrap: that ran every
# step twice and raced 17-SetSerialPorts against the service start. The lab
# helpers are a fallback that only fires when no game appears within 3 minutes.
# USB extras are strictly additive and live in Start-LabDesktop.ps1.
#
# Do not probe C:\goldclub (BitLocker junction hangs while G: is locked).
# Do not run USB CopyOnlogon from here (USB at POST can reboot this EGM).
#
# Failures seen 30-31 Aug 2026: UnlockerDisk often loses the early-boot race
# (G: stays Locked). Retries without -Wait also missed the unlock. Keep retrying
# with -Wait for several minutes; free letter G: if a Removable USB stole it.

param(
    [string]$WorkingDirectory
)

$ErrorActionPreference = 'Continue'

function Write-OoLog {
    param([string]$Message)
    try {
        $line = "[$(Get-Date -Format o)] $Message$([Environment]::NewLine)"
        [IO.File]::AppendAllText('C:\Platform\Security\oo-security.log', $line)
    }
    catch {}
}

function Test-GoldClubReady {
    try {
        $d = [IO.DriveInfo]::new('G:\')
        if (-not $d.IsReady) { return $false }
        return [IO.File]::Exists('G:\Bootstrap.exe')
    }
    catch {
        return $false
    }
}

function Clear-RemovableLetterG {
    # Only strip Removable media from G:. Never remove a Fixed/BitLocker GOLDCLUB
    # letter - that broke unlock when tried earlier (Protect-GoldClubLetter bug).
    try {
        $vol = Get-Volume -DriveLetter 'G' -ErrorAction SilentlyContinue
        if (-not $vol) { return }
        if ($vol.DriveType -ne 'Removable') { return }
        Write-OoLog ("Clearing Removable G: label={0}" -f $vol.FileSystemLabel)
        $part = Get-Partition -DriveLetter 'G' -ErrorAction SilentlyContinue
        if ($part) {
            Remove-PartitionAccessPath -DiskNumber $part.DiskNumber `
                -PartitionNumber $part.PartitionNumber -AccessPath 'G:\' `
                -ErrorAction SilentlyContinue
        }
    }
    catch {
        Write-OoLog ("Clear-RemovableLetterG: {0}" -f $_.Exception.Message)
    }
}

function Repair-GoldClubDriveLetter {
    # UnlockerDisk sometimes unlocks GOLDCLUB onto a letter other than G:.
    if (Test-GoldClubReady) { return $true }
    try {
        foreach ($vol in @(Get-Volume -ErrorAction SilentlyContinue)) {
            $letter = $vol.DriveLetter
            if (-not $letter -or $letter -eq 'G') { continue }
            if ($vol.FileSystemLabel -ne 'GOLDCLUB') { continue }
            $boot = ('{0}:\Bootstrap.exe' -f $letter)
            if (-not [IO.File]::Exists($boot)) { continue }
            Write-OoLog ("GOLDCLUB unlocked on {0}: - moving letter to G:" -f $letter)
            $gVol = Get-Volume -DriveLetter 'G' -ErrorAction SilentlyContinue
            if ($gVol -and $gVol.DriveType -eq 'Removable') {
                Clear-RemovableLetterG
            }
            elseif ($gVol) {
                Write-OoLog 'G: occupied by non-removable volume; cannot reassign'
                return $false
            }
            $part = Get-Partition -DriveLetter $letter -ErrorAction SilentlyContinue
            if (-not $part) { continue }
            Set-Partition -DiskNumber $part.DiskNumber -PartitionNumber $part.PartitionNumber `
                -NewDriveLetter 'G' -ErrorAction Stop
            Start-Sleep -Seconds 2
            return (Test-GoldClubReady)
        }
    }
    catch {
        Write-OoLog ("Repair-GoldClubDriveLetter: {0}" -f $_.Exception.Message)
    }
    return $false
}

function Invoke-UnlockerDisk {
    param([switch]$Wait)
    $exe = 'C:\Platform\Security\UnlockerDisk.exe'
    if (-not [IO.File]::Exists($exe)) {
        Write-OoLog 'UnlockerDisk.exe missing'
        return
    }
    try {
        if ($Wait) {
            $p = Start-Process -FilePath $exe -PassThru -Wait -ErrorAction Stop
            Write-OoLog ("UnlockerDisk exit={0}" -f $p.ExitCode)
        }
        else {
            Start-Process -FilePath $exe -ErrorAction Stop
        }
    }
    catch {
        Write-OoLog ("UnlockerDisk start failed: {0}" -f $_.Exception.Message)
    }
}

function Wait-GoldClubReady {
    param([int]$TimeoutSeconds)
    $waited = 0
    while (-not (Test-GoldClubReady) -and $waited -lt $TimeoutSeconds) {
        Start-Sleep -Seconds 2
        $waited += 2
        if (Repair-GoldClubDriveLetter) { return $waited }
    }
    return $waited
}

function Test-Elevated {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        return $false
    }
}

function Start-UnlockTask {
    # The AtStartup SYSTEM task does the real work. Kicking it here is only a
    # nudge for the case where the startup trigger has not fired yet; a
    # filtered token may be refused, which is fine and non-fatal.
    try {
        $out = cmd /c "schtasks /Run /TN `"GoldClub-Unlock-Volume`" 2>&1"
        Write-OoLog ("unlock task kick: {0}" -f (($out | Select-Object -First 1) -replace '\s+', ' '))
        return $true
    }
    catch {
        Write-OoLog ("unlock task kick failed: {0}" -f $_.Exception.Message)
        return $false
    }
}

function Test-HwSubsysRunning {
    $svc = Get-Service -DisplayName 'GoldClub Hardware Subsystem' -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service -Name 'GoldClub Hardware Subsystem' -ErrorAction SilentlyContinue
    }
    return [bool]($svc -and $svc.Status -eq 'Running')
}

function Wait-HwSubsysRunning {
    param([int]$TimeoutSeconds)
    $waited = 0
    while (-not (Test-HwSubsysRunning) -and $waited -lt $TimeoutSeconds) {
        Start-Sleep -Seconds 2
        $waited += 2
    }
    return (Test-HwSubsysRunning)
}

function Test-GameRunning {
    return [bool]@(
        Get-Process -Name 'Bootstrap', 'Start-SlotGameWatch', 'game-start', 'Start-Game', 'OneHand', 'HIH', 'Ruleta' `
            -ErrorAction SilentlyContinue
    )
}

function Wait-GameRunning {
    param([int]$TimeoutSeconds)
    $waited = 0
    while (-not (Test-GameRunning) -and $waited -lt $TimeoutSeconds) {
        Start-Sleep -Seconds 5
        $waited += 5
    }
    return (Test-GameRunning)
}

function Start-HiddenPowerShell {
    param([string]$File, [string[]]$Extra = @())
    if (-not [IO.File]::Exists($File)) { return $false }
    $psArgs = @(
        '-WindowStyle', 'Hidden', '-NoLogo', '-NonInteractive', '-NoProfile',
        '-ExecutionPolicy', 'Bypass', '-File', $File
    ) + $Extra
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $psArgs -ErrorAction Stop
        return $true
    }
    catch {
        Write-OoLog ("start failed {0}: {1}" -f $File, $_.Exception.Message)
        return $false
    }
}

cmd /c "echo %date% %time% OO_Security>>C:\tmp\boot-kick.txt" 2>$null
Write-OoLog 'OO_Security start'

Clear-RemovableLetterG

# The unlock itself belongs to the AtStartup SYSTEM task. eshell runs this shell
# as "goldclub" with a UAC-filtered token (BUILTIN\Administrators = "Group used
# for deny only"), and BitLocker unlock of a data volume needs a real admin
# token - which is why 18 UnlockerDisk retries from here failed on 31 Aug 2026
# while one elevated run succeeded in ~5 s. Log the token so the next black
# screen is diagnosable from oo-security.log alone.
$elevated = Test-Elevated
Write-OoLog ("shell token elevated={0}" -f $elevated)
$null = Start-UnlockTask
if ($elevated) {
    Invoke-UnlockerDisk -Wait
    Write-OoLog 'UnlockerDisk direct pass done (shell is elevated)'
}

$waited = Wait-GoldClubReady -TimeoutSeconds 30
Write-OoLog ("GOLDCLUB ready={0} after {1}s" -f (Test-GoldClubReady), $waited)

# Keep waiting rather than giving up: the SYSTEM task may still be working, and
# a shell that returns here leaves the cabinet with no game at all (the 12:11
# boot on 31 Aug did exactly that - G: unlocked later and nothing started).
$deadline = (Get-Date).AddMinutes(12)
$attempt = 1
$retryStarted = $false
while (-not (Test-GoldClubReady) -and (Get-Date) -lt $deadline) {
    $attempt++
    Write-OoLog "unlock wait $attempt"
    Clear-RemovableLetterG
    $null = Start-UnlockTask
    if ($elevated) { Invoke-UnlockerDisk -Wait }
    elseif (-not $retryStarted) {
        # Unlock only. Must not start Bootstrap/onlogon (that raced the shell).
        $retryStarted = Start-HiddenPowerShell 'C:\Platform\Security\Unlock-GoldClubRetry.ps1'
        if ($retryStarted) { Write-OoLog 'started Unlock-GoldClubRetry.ps1 (unlock only)' }
    }
    $waited = Wait-GoldClubReady -TimeoutSeconds 20
    Write-OoLog ("GOLDCLUB ready={0} after wait {1} (+{2}s)" -f (Test-GoldClubReady), $attempt, $waited)
}

if (-not (Test-GoldClubReady)) {
    Write-OoLog 'FATAL: G: never unlocked. Register GoldClub-Unlock-Volume (Install-GoldClubBootTasks.ps1).'
    Start-Sleep -Seconds 600
    return
}

Write-OoLog 'GOLDCLUB ready'

# Services are Auto but their binaries are on G:. SCM already failed them
# while the volume was locked and will not retry. The SYSTEM task
# GoldClub-Ensure-HwStack waits for G: then Start-Service. This shell cannot
# Start-Service (filtered token) and often cannot schtasks /Run either.
Write-OoLog 'waiting for HWSubsys before Bootstrap'
$hwOk = Wait-HwSubsysRunning -TimeoutSeconds 120
Write-OoLog ("HWSubsys Running={0}" -f $hwOk)
if ($hwOk) {
    Write-OoLog 'HWSubsys Running - settle 8s'
    Start-Sleep -Seconds 8
}
else {
    Write-OoLog 'WARN HWSubsys still Stopped - OneHand will HW-timeout. Check GoldClub-Ensure-HwStack.'
}

# --- 1. Game: exactly one unconditional start, USB or no USB. ---
Start-Process -FilePath 'G:\Bootstrap.exe' -WorkingDirectory 'G:\' -ErrorAction SilentlyContinue
Write-OoLog 'started G:\Bootstrap.exe'

# --- 2. Lab USB extras: additive, async, never gate the game. ---
if (Start-HiddenPowerShell 'C:\Platform\Security\Start-LabDesktop.ps1' @('-PollForUsb', '-MinDelaySeconds', '45')) {
    Write-OoLog 'started Start-LabDesktop PollForUsb async (USB extras are additive)'
}

# --- 3. Fallback: only if Bootstrap produced no game. Do NOT start
# Start-GoldClubHardware / lab onlogon here - goldclub cannot Start-Service.
if (Wait-GameRunning -TimeoutSeconds 180) {
    Write-OoLog 'game is up from Bootstrap - no fallback needed'
}
else {
    Write-OoLog 'no game after 180s - retrying G:\Bootstrap.exe'
    Start-Process -FilePath 'G:\Bootstrap.exe' -WorkingDirectory 'G:\' -ErrorAction SilentlyContinue
}

Write-OoLog 'OO_Security done'
Write-OoLog 'holding shell 600s'
Start-Sleep -Seconds 600
