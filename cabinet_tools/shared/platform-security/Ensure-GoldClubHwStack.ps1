#Requires -Version 5.1
# Start or bounce the Slot hardware services. Must run elevated / SYSTEM.
# goldclub's UAC-filtered token cannot Start-Service (Administrators = deny only).
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    [switch]$Restart,
    [int]$SettleSec = 12
)

$ErrorActionPreference = 'Continue'

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-HwStackLog([string]$Message) {
    $line = "[$(Get-Date -Format o)] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @(
        'C:\Platform\Security\hw-stack.log',
        'C:\tmp\hw-stack.log'
    )) {
        try {
            $dir = Split-Path -Parent $logPath
            if ($dir -and -not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }
            [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
        } catch {}
    }
    try {
        $gd = [IO.DriveInfo]::new('G:\')
        if ($gd.IsReady) {
            $glog = 'G:\var\log\hw-stack.log'
            $gdir = Split-Path -Parent $glog
            if (-not (Test-Path -LiteralPath $gdir)) {
                New-Item -ItemType Directory -Path $gdir -Force | Out-Null
            }
            [IO.File]::AppendAllText($glog, $line + [Environment]::NewLine, $utf8)
        }
    } catch {}
    Write-Host $line
}

function Get-NamedGoldClubService([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($svc) { return $svc }
    return (Get-Service -DisplayName $Name -ErrorAction SilentlyContinue)
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

if (-not (Test-Elevated)) {
    Write-HwStackLog 'NOT ELEVATED - refusing (goldclub token cannot start services)'
    exit 2
}

# Binaries live on G:. ONSTART fires while GOLDCLUB is still BitLocker-locked
# (11:25:46 4 Sep 2026: every Start-Service failed, Last Result=1, then nothing
# retried after unlock). Wait here so Auto services get a real start.
$gWait = 0
while (-not (Test-GoldClubReady) -and $gWait -lt 600) {
    if ($gWait -eq 0) { Write-HwStackLog 'waiting for G: GOLDCLUB before starting services' }
    Start-Sleep -Seconds 2
    $gWait += 2
}
if (-not (Test-GoldClubReady)) {
    Write-HwStackLog 'G: still locked - cannot start services whose binaries live on G:'
    exit 1
}
Write-HwStackLog ("G: ready after {0}s" -f $gWait)

$names = @(
    'GoldClub.Logging.LogDaemon',
    'GoldClub Serial Communication Gateway',
    'GoldClub Serial Communication Gateway SAS',
    'GoldClub Hardware Subsystem',
    'GoldClub.Aurum.Services'
)

Write-HwStackLog ("Ensure-GoldClubHwStack begin restart=" + [bool]$Restart)
foreach ($name in $names) {
    $svc = Get-NamedGoldClubService $name
    if (-not $svc) {
        Write-HwStackLog "missing $name"
        continue
    }
    $bounce = $Restart -and (
        $name -eq 'GoldClub Hardware Subsystem' -or
        $name -eq 'GoldClub.Aurum.Services'
    )
    try {
        if ($bounce) {
            Restart-Service -Name $svc.Name -Force -ErrorAction Stop
            Write-HwStackLog "restarted $($svc.Name)"
        } elseif ($svc.Status -ne 'Running') {
            Start-Service -Name $svc.Name -ErrorAction Stop
            Write-HwStackLog "started $($svc.Name)"
        } else {
            Write-HwStackLog "already Running $($svc.Name)"
        }
    } catch {
        Write-HwStackLog "failed $name : $($_.Exception.Message)"
    }
}

$deadline = (Get-Date).AddSeconds(25)
$hw = $null
do {
    $hw = Get-NamedGoldClubService 'GoldClub Hardware Subsystem'
    if ($hw -and $hw.Status -eq 'Running') { break }
    Start-Sleep -Milliseconds 400
    if ($hw) { $hw.Refresh() }
} while ((Get-Date) -lt $deadline)

if (-not $hw -or $hw.Status -ne 'Running') {
    $st = if ($hw) { [string]$hw.Status } else { 'missing' }
    Write-HwStackLog "HWSubsys not Running ($st)"
    exit 1
}

if ($SettleSec -gt 0) {
    Write-HwStackLog "settle ${SettleSec}s"
    Start-Sleep -Seconds $SettleSec
}
Write-HwStackLog 'Ensure-GoldClubHwStack ok'
exit 0
