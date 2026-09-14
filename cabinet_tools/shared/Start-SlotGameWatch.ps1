#Requires -Version 5.1
# GameBinRun wrapper. Bootstrap watches this process, not game-start.
# Escape (OneHand exit 11) must NOT reach Bootstrap or it logs
# "Unexpected game stop! >> Restart the machine" and reboots.
# Must stay pure ASCII.

[CmdletBinding()]
param(
    [int]$ReadyTimeoutSec = 45,
    [int]$HwWaitSec = 40
)

$ErrorActionPreference = 'Continue'
$HwTask = 'GoldClub-Ensure-HwStack'

function Write-WatchLog([string]$Message) {
    $line = "[$(Get-Date -Format o)] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @(
        'G:\var\log\Start-SlotGameWatch.log',
        'C:\Platform\Security\Start-SlotGameWatch.log',
        'C:\tmp\Start-SlotGameWatch.log'
    )) {
        try {
            $dir = Split-Path -Parent $logPath
            if ($dir -and -not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }
            [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
        } catch {}
    }
    Write-Host $line
}

function Test-ProcessUp([string[]]$Names) {
    return [bool](Get-Process -Name $Names -ErrorAction SilentlyContinue)
}

function Wait-ProcessesGone {
    param([string[]]$Names, [int]$TimeoutSec)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        if (-not (Test-ProcessUp $Names)) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return -not (Test-ProcessUp $Names)
}

function Test-SharedPreferencesFree {
    $cands = @(
        'G:\slot\var\SharedPreferences.bin',
        'C:\goldclub\slot\var\SharedPreferences.bin'
    )
    foreach ($p in $cands) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        try {
            $fs = [IO.File]::Open($p, 'Open', 'ReadWrite', 'None')
            $fs.Close()
        } catch {
            return $false
        }
    }
    return $true
}

function Wait-SharedPreferencesFree([int]$TimeoutSec) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        if (Test-SharedPreferencesFree) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return (Test-SharedPreferencesFree)
}

function Get-HwSubsysRunning {
    $svc = Get-Service -Name 'GoldClub Hardware Subsystem' -ErrorAction SilentlyContinue
    if (-not $svc) {
        $svc = Get-Service -DisplayName 'GoldClub Hardware Subsystem' -ErrorAction SilentlyContinue
    }
    return [bool]($svc -and $svc.Status -eq 'Running')
}

function Get-AurumRunning {
    $svc = Get-Service -Name 'GoldClub.Aurum.Services' -ErrorAction SilentlyContinue
    return [bool]($svc -and $svc.Status -eq 'Running')
}

function Get-HwStackReady {
    return (Get-HwSubsysRunning) -and (Get-AurumRunning)
}

function Invoke-HwStackReady {
    param([switch]$Restart)
    if (Test-ProcessUp @('OneHand', 'BiOS2')) {
        Write-WatchLog 'skip HW bounce - OneHand or BiOS2 still running'
        return (Get-HwStackReady)
    }
    # The ONSTART task is registered with -Restart, so any schtasks /Run
    # tears down HWSubsys. Live Push already bounced it: do not kick again
    # when HW and Aurum are both up. Aurum down + HW up used to skip and
    # leave LockGameWhenNoComms inert.
    if ((Get-HwStackReady) -and -not $Restart) {
        Write-WatchLog 'HWSubsys already Running - skip bounce'
        return $true
    }
    Write-WatchLog "schtasks $HwTask"
    cmd /c "schtasks /Run /TN `"$HwTask`" /I" 2>&1 | ForEach-Object { Write-WatchLog ("  " + $_) }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $HwWaitSec) {
        if (Get-HwStackReady) {
            Write-WatchLog 'HWSubsys Running'
            if ($Restart) {
                Write-WatchLog 'settle 12s after HW bounce'
                Start-Sleep -Seconds 12
            }
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-WatchLog 'WARN HWSubsys still not Running'
    return $false
}

function Wait-SlotGameReady {
    param([switch]$BounceHw)
    Write-WatchLog 'Wait-SlotGameReady'
    if (-not (Wait-ProcessesGone -Names @('OneHand') -TimeoutSec $ReadyTimeoutSec)) {
        Write-WatchLog 'WARN OneHand still present'
    }
    if (-not (Wait-SharedPreferencesFree -TimeoutSec 20)) {
        Write-WatchLog 'WARN SharedPreferences.bin still locked'
    }
    [void](Invoke-HwStackReady -Restart:$BounceHw)
}

function Find-GameStart {
    foreach ($p in @('G:\slot\game-start.exe', 'C:\goldclub\slot\game-start.exe')) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Find-BiOS2 {
    foreach ($p in @('G:\BiOS\BiOS2.exe', 'C:\goldclub\BiOS\BiOS2.exe')) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Start-And-Wait([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return -1 }
    $base = [IO.Path]::GetFileNameWithoutExtension($Exe)
    $existing = @(Get-Process -Name $base -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        Write-WatchLog "already running $base - waiting"
        $existing | Wait-Process
        return 0
    }
    $dir = Split-Path -Parent $Exe
    Write-WatchLog "start $Exe"
    $p = Start-Process -FilePath $Exe -WorkingDirectory $dir -PassThru
    if (-not $p) { return -1 }
    Wait-Process -Id $p.Id -ErrorAction SilentlyContinue
    try { return [int]$p.ExitCode } catch { return 0 }
}

$mutex = $null
try {
    $mutex = New-Object System.Threading.Mutex($false, 'Global\GoldClub-Start-SlotGameWatch')
    if (-not $mutex.WaitOne(0)) {
        Write-WatchLog 'another watcher holds mutex - waiting'
        [void]$mutex.WaitOne()
        Write-WatchLog 'mutex acquired'
    }
    Write-WatchLog 'Start-SlotGameWatch begin'
    while ($true) {
        try {
            if (Test-ProcessUp @('OneHand')) {
                Write-WatchLog 'OneHand already running - waiting'
                Get-Process -Name OneHand -ErrorAction SilentlyContinue | Wait-Process
                Start-Sleep -Seconds 1
                continue
            }

            $gs = Find-GameStart
            if (-not $gs) {
                Write-WatchLog 'ERROR game-start.exe missing - sleep'
                Start-Sleep -Seconds 5
                continue
            }

            # Do not bounce HW here. Live Push / USB fullstack just did.
            Wait-SlotGameReady
            $code = Start-And-Wait $gs
            Write-WatchLog "game-start exit=$code"

            if (Test-ProcessUp @('OneHand')) {
                Write-WatchLog 'game-start returned but OneHand still running - waiting'
                Get-Process -Name OneHand -ErrorAction SilentlyContinue | Wait-Process
                continue
            }

            # Operator Escape is 11. A Live Push / USB kill is -1 (or 0).
            # Only Escape opens BiOS2; anything else restarts the game.
            if ($code -ne 11) {
                Write-WatchLog "not Escape (exit=$code) - restarting game"
                Start-Sleep -Seconds 2
                continue
            }

            Wait-SlotGameReady -BounceHw
            $bios = Find-BiOS2
            if ($bios) {
                $bcode = Start-And-Wait $bios
                Write-WatchLog "BiOS2 exit=$bcode"
            } else {
                Write-WatchLog 'WARN BiOS2.exe missing - restarting game'
            }
        } catch {
            Write-WatchLog ("loop error: " + $_.Exception.Message)
            Start-Sleep -Seconds 5
        }
    }
} finally {
    if ($mutex) {
        try { [void]$mutex.ReleaseMutex() } catch {}
        $mutex.Dispose()
    }
}
