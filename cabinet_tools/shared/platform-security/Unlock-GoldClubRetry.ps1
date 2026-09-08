# Background unlock when OO_Security hit the early-boot BitLocker race.
# Unlock only. Must not start Bootstrap or onlogon (that raced the shell
# and started OneHand before GoldClub services were up).

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
        return [bool]($d.IsReady -and [IO.File]::Exists('G:\Bootstrap.exe'))
    }
    catch {
        return $false
    }
}

Write-OoLog 'Unlock-GoldClubRetry start (unlock only)'
for ($i = 1; $i -le 60 -and -not (Test-GoldClubReady); $i++) {
    Write-OoLog "bg UnlockerDisk pass $i"
    try {
        Start-Process -FilePath 'C:\Platform\Security\UnlockerDisk.exe' -Wait -ErrorAction SilentlyContinue
    }
    catch {}
    Start-Sleep -Seconds 15
}

if (-not (Test-GoldClubReady)) {
    Write-OoLog 'bg unlock gave up'
    exit 1
}

Write-OoLog 'bg unlock OK - not starting Bootstrap/onlogon'
exit 0
