#Requires -Version 5.1
<#
.SYNOPSIS
  Start GoldClub hardware Windows services from G:\Services after GOLDCLUB is unlocked.

  Does not write licence files or serialport maps.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

function Write-HwLog([string]$Message) {
    $line = "[$(Get-Date -Format o)] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @('C:\Platform\Security\oo-security.log', 'C:\tmp\oo-security.log', 'C:\tmp\boot-trace.log')) {
        try {
            $dir = Split-Path -Parent $logPath
            if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
        } catch {}
    }
    Write-Host $line
}

function Test-GoldClubReady {
    try {
        $d = [IO.DriveInfo]::new('G:\')
        return [bool]($d.IsReady -and [IO.File]::Exists('G:\Bootstrap.exe'))
    } catch {
        return $false
    }
}

function Test-NamedGoldClubService([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($svc) { return $svc }
    return (Get-Service -DisplayName $Name -ErrorAction SilentlyContinue)
}

function Install-GoldClubExeService {
    param([string]$ExePath, [string]$InstallArg = '--install')
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-HwLog "install skip missing $ExePath"
        return
    }
    $dir = Split-Path -Parent $ExePath
    Write-HwLog "install $ExePath $InstallArg"
    try {
        $p = Start-Process -FilePath $ExePath -ArgumentList $InstallArg -WorkingDirectory $dir -PassThru -WindowStyle Hidden -ErrorAction Stop
        if (-not $p.WaitForExit(12000)) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Write-HwLog "install timeout $ExePath"
        }
    } catch {
        Write-HwLog "install failed: $($_.Exception.Message)"
    }
}

function Start-NamedGoldClubService([string]$Name) {
    $svc = Test-NamedGoldClubService $Name
    if (-not $svc) {
        Write-HwLog "missing service $Name"
        return
    }
    if ($svc.Status -eq 'Running') {
        Write-HwLog "already Running $($svc.Name)"
        return
    }
    try {
        Start-Service -InputObject $svc -ErrorAction Stop
        Write-HwLog "started $($svc.Name)"
    } catch {
        Write-HwLog "start failed $($svc.Name): $($_.Exception.Message)"
    }
}

Write-HwLog 'Start-GoldClubHardware begin'
$waited = 0
while (-not (Test-GoldClubReady) -and $waited -lt 90) {
    Start-Sleep -Seconds 3
    $waited += 3
}
if (-not (Test-GoldClubReady)) {
    Write-HwLog ("G: not ready after {0}s - skip hardware" -f $waited)
    return 1
}
Write-HwLog ("G: ready after {0}s" -f $waited)

$svcRoot = 'G:\Services'
if (-not (Test-Path -LiteralPath (Join-Path $svcRoot 'LogDaemon\GoldClub.Logging.LogDaemon.exe'))) {
    $svcRoot = 'G:\services'
}

if (-not (Test-NamedGoldClubService 'GoldClub.Logging.LogDaemon')) {
    Install-GoldClubExeService (Join-Path $svcRoot 'LogDaemon\GoldClub.Logging.LogDaemon.exe')
}
if (-not (Test-NamedGoldClubService 'GoldClub Serial Communication Gateway')) {
    Install-GoldClubExeService (Join-Path $svcRoot 'CommCtrl\XYNTService.exe') '-i'
}
if (-not (Test-NamedGoldClubService 'GoldClub Serial Communication Gateway SAS')) {
    Install-GoldClubExeService (Join-Path $svcRoot 'CommCtrlSAS\XYNTService.exe') '-i'
}
if (-not (Test-NamedGoldClubService 'GoldClub Hardware Subsystem')) {
    $hw = Join-Path $svcRoot 'HWSubsys\hwsubsys.exe'
    if (-not (Test-Path -LiteralPath $hw)) { $hw = Join-Path $svcRoot 'HWSubsys\HWSubsys.exe' }
    Install-GoldClubExeService $hw
}
if (-not (Test-NamedGoldClubService 'GoldClub.Aurum.Services')) {
    $bin = 'G:\services\aurum\bin\GoldClub.Aurum.Services.exe'
    Write-HwLog 'sc create GoldClub.Aurum.Services'
    cmd /c "sc.exe create GoldClub.Aurum.Services binPath= `"$bin`" start= auto DisplayName= `"GoldClub.Aurum.Services`"" | ForEach-Object { Write-HwLog "sc: $_" }
}

foreach ($name in @(
        'GoldClub.Logging.LogDaemon',
        'GoldClub Serial Communication Gateway',
        'GoldClub Serial Communication Gateway SAS',
        'GoldClub Hardware Subsystem',
        'GoldClub.Aurum.Services'
    )) {
    Start-NamedGoldClubService $name
    Start-Sleep -Seconds 1
}

Write-HwLog 'Start-GoldClubHardware end'
return 0
