#Requires -Version 5.1
<#
.SYNOPSIS
  Lab USB extras only: SMB share slot=G:\, TeamViewer, Total Commander, WinRM.

  Started from OO_Security when a lab USB stick is present (or -PollForUsb after
  the game is on screen). Exits immediately when no USB and -PollForUsb is off.
#>
[CmdletBinding()]
param(
    [string]$LabUsbRoot,
    [switch]$PollForUsb,
    [int]$MinDelaySeconds = 0
)

$ErrorActionPreference = 'Continue'

function Write-LabLog([string]$Message) {
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

function Test-IsGoldClubGameVolume {
    param([string]$Root)
    $base = $Root.TrimEnd('\')
    return (
        [IO.File]::Exists("$base\Bootstrap.exe") -or
        [IO.File]::Exists("$base\slot\OneHand.exe") -or
        [IO.File]::Exists("$base\ruleta\Ruleta.exe")
    )
}

function Find-LabUsbRoot {
    foreach ($d in [IO.DriveInfo]::GetDrives()) {
        try {
            if (-not $d.IsReady) { continue }
            $root = $d.Name.TrimEnd('\')
            if ($root -in @('C:', 'G:')) { continue }
            if ($d.DriveType -notin @('Removable', 'Fixed')) { continue }
            if (Test-IsGoldClubGameVolume -Root $root) { continue }
            foreach ($rel in @(
                    'CopyOnlogon.bat',
                    'TeamViewerPortable\TeamViewer.exe',
                    'totalcmd\TOTALCMD64.EXE',
                    'totalcmd\TOTALCMD.EXE',
                    'TeamViewer_LoginBackup\restore_tv_login.cmd'
                )) {
                if ([IO.File]::Exists(($root + '\' + $rel))) { return $root }
            }
        } catch {}
    }
    return $null
}

function Get-AutoLogonUser {
    try {
        $wl = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -ErrorAction Stop
        if ($wl.DefaultUserName) { return [string]$wl.DefaultUserName }
    } catch {}
    return 'goldclub'
}

function Test-IsSystemAccount {
    return ([Security.Principal.WindowsIdentity]::GetCurrent().Name -match '\\SYSTEM$')
}

function Find-TeamViewerExe {
    param([string]$UsbRoot)
    $candidates = @('C:\Platform\Tools\TeamViewerPortable\TeamViewer.exe')
    if ($UsbRoot) { $candidates += (Join-Path $UsbRoot 'TeamViewerPortable\TeamViewer.exe') }
    $candidates += 'C:\Users\goldclub\AppData\Local\TeamViewer\TeamViewer.exe'
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

function Find-TotalCommanderExe {
    param([string]$UsbRoot)
    $candidates = @(
        'C:\Platform\Tools\totalcmd\TOTALCMD64.EXE',
        'C:\Platform\Tools\totalcmd\TOTALCMD.EXE'
    )
    if ($UsbRoot) {
        $candidates += (Join-Path $UsbRoot 'totalcmd\TOTALCMD64.EXE')
        $candidates += (Join-Path $UsbRoot 'totalcmd\TOTALCMD.EXE')
    }
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

function Test-AppRunning([string[]]$Names) {
    return [bool]@(Get-Process -Name $Names -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -gt 0 })
}

function Disable-TeamViewerPortablePrinter([string]$TvExe) {
    if (-not $TvExe) { return }
    $dir = Split-Path -Parent $TvExe
    $printer = Join-Path $dir 'Printer'
    $off = Join-Path $dir 'Printer.disabled'
    if ((Test-Path -LiteralPath $printer) -and -not (Test-Path -LiteralPath $off)) {
        try {
            Rename-Item -LiteralPath $printer -NewName 'Printer.disabled'
            Write-LabLog 'TeamViewer: moved Printer to Printer.disabled'
        } catch {}
    }
}

function Invoke-UsbShareBatch {
    param([string]$UsbRoot)
    foreach ($name in @('_share.bat', 'share.bat')) {
        $path = Join-Path $UsbRoot $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        Write-LabLog "running USB share batch: $path"
        try {
            $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$path`" -nopause" -PassThru -WindowStyle Hidden
            if ($p -and -not $p.WaitForExit(30000)) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                Write-LabLog 'USB share batch timed out'
            }
            elseif ($p) {
                Write-LabLog ("USB share batch exit={0}" -f $p.ExitCode)
            }
        } catch {
            Write-LabLog "USB share batch failed: $($_.Exception.Message)"
        }
        return
    }
    Write-LabLog 'USB share batch not found'
}

function Invoke-RestoreTeamViewerLogin {
    param([string]$UsbRoot)
    $tvCmd = Join-Path $UsbRoot 'TeamViewer_LoginBackup\restore_tv_login.cmd'
    if (-not (Test-Path -LiteralPath $tvCmd)) { return }
    Write-LabLog 'running restore_tv_login.cmd'
    try {
        $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$tvCmd`"" -PassThru -WindowStyle Hidden
        if ($p -and -not $p.WaitForExit(90000)) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Write-LabLog 'restore_tv_login timed out'
        }
        elseif ($p) {
            Write-LabLog ("restore_tv_login exit={0}" -f $p.ExitCode)
        }
    } catch {
        Write-LabLog "restore_tv_login failed: $($_.Exception.Message)"
    }
}

function Start-LabUserApp {
    param(
        [string]$TaskName,
        [string]$Tool,
        [string]$Arguments,
        [string[]]$ProcessNames,
        [string]$Label,
        [string]$UsbRoot
    )
    if (Test-AppRunning $ProcessNames) {
        Write-LabLog "$Label already running - skip second instance"
        return
    }
    $launcherPs1 = 'C:\Platform\Security\Launch-LabUsbTool.ps1'
    if (-not (Test-Path -LiteralPath $launcherPs1)) {
        Write-LabLog "$Label missing Launch-LabUsbTool.ps1"
        return
    }
    $user = Get-AutoLogonUser
    $argList = "-WindowStyle Hidden -NoLogo -NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"$launcherPs1`" -Tool $Tool"
    if ($Arguments) { $argList += " -Arguments $Arguments" }
    $tr = "powershell.exe $argList"
    $existing = schtasks /Query /TN $TaskName 2>&1 | Out-String
    if ($existing -notmatch 'ERROR') {
        Write-LabLog "$Label task already registered - skip schtasks recreate"
    } else {
        cmd /c "schtasks /Create /TN `"$TaskName`" /TR `"$tr`" /SC ONLOGON /RU `"$user`" /IT /RL HIGHEST /F" 2>&1 |
            ForEach-Object { Write-LabLog "schtasks-create $Label : $_" }
    }
    $exe = if ($Tool -eq 'TeamViewer') { Find-TeamViewerExe -UsbRoot $UsbRoot } else { Find-TotalCommanderExe -UsbRoot $UsbRoot }
    if (-not $exe) {
        Write-LabLog "$Label exe not found on USB"
        return
    }
    Disable-TeamViewerPortablePrinter -TvExe $(if ($Tool -eq 'TeamViewer') { $exe } else { $null })
    if (Test-IsSystemAccount) {
        cmd /c "schtasks /Run /TN `"$TaskName`"" 2>&1 |
            ForEach-Object { Write-LabLog "schtasks-run $Label : $_" }
    } else {
        try {
            if ($Arguments) {
                Start-Process -FilePath $exe -ArgumentList $Arguments -WorkingDirectory (Split-Path -Parent $exe) -ErrorAction Stop
            } else {
                Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -ErrorAction Stop
            }
            Write-LabLog "started $Label $exe"
        } catch {
            Write-LabLog "$Label Start-Process failed: $($_.Exception.Message)"
            cmd /c "schtasks /Run /TN `"$TaskName`"" 2>&1 |
                ForEach-Object { Write-LabLog "schtasks-run $Label : $_" }
        }
    }
}

Write-LabLog 'Start-LabDesktop begin'

if ($MinDelaySeconds -gt 0) {
    Write-LabLog ("MinDelaySeconds: waiting {0}s for game before lab USB work" -f $MinDelaySeconds)
    Start-Sleep -Seconds $MinDelaySeconds
}

if (-not $LabUsbRoot) { $LabUsbRoot = Find-LabUsbRoot }
if (-not $LabUsbRoot -and $PollForUsb) {
    Write-LabLog 'PollForUsb: scanning up to 90s for lab USB stick'
    for ($i = 0; $i -lt 18; $i++) {
        Start-Sleep -Seconds 5
        $LabUsbRoot = Find-LabUsbRoot
        if ($LabUsbRoot) { break }
    }
}
if (-not $LabUsbRoot) {
    Write-LabLog 'Start-LabDesktop skipped - no lab USB'
    return 0
}

Write-LabLog ("lab USB root: {0}" -f $LabUsbRoot)

# --- SMB share slot=G:\ only (never the SYSTEM junction) ---
try {
    $svc = Get-Service -Name 'LanmanServer' -ErrorAction Stop
    if ($svc.StartType -eq 'Disabled') { Set-Service -Name 'LanmanServer' -StartupType Automatic }
    if ($svc.Status -ne 'Running') { Start-Service -Name 'LanmanServer' -ErrorAction Stop }
    Write-LabLog 'LanmanServer Running'
} catch {
    Write-LabLog "LanmanServer: $($_.Exception.Message)"
}

cmd /c 'net user test test /add' 2>&1 | Out-Null
cmd /c 'net user test test' 2>&1 | Out-Null
cmd /c 'net user test /active:yes' 2>&1 | Out-Null
cmd /c 'net localgroup administrators test /add' 2>&1 | ForEach-Object { Write-LabLog "admin: $_" }

try {
    $uacKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
    New-Item -Path $uacKey -Force -ErrorAction SilentlyContinue | Out-Null
    Set-ItemProperty -LiteralPath $uacKey -Name 'LocalAccountTokenFilterPolicy' -Value 1 -Type DWord -Force
} catch {}

cmd /c 'netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes' 2>&1 |
    ForEach-Object { Write-LabLog "firewall: $_" }

if (Test-GoldClubReady) {
    cmd /c 'net share slot=G:\ /grant:everyone,FULL' 2>&1 | ForEach-Object { Write-LabLog "share-cmd: $_" }
} else {
    Write-LabLog 'share skipped: GOLDCLUB volume not ready'
}

try {
    $winrm = Get-Service -Name 'WinRM' -ErrorAction SilentlyContinue
    if ($winrm) {
        if ($winrm.StartType -eq 'Disabled') { Set-Service -Name 'WinRM' -StartupType Automatic }
        if ($winrm.Status -ne 'Running') { Start-Service -Name 'WinRM' -ErrorAction SilentlyContinue }
        Write-LabLog ("WinRM {0}" -f (Get-Service WinRM).Status)
    }
} catch {
    Write-LabLog "WinRM start skipped: $($_.Exception.Message)"
}

Invoke-UsbShareBatch -UsbRoot $LabUsbRoot
Invoke-RestoreTeamViewerLogin -UsbRoot $LabUsbRoot

$tcNames = @('TOTALCMD', 'TOTALCMD64')
Start-LabUserApp -TaskName 'GoldClub-TeamViewer-Start' -Tool 'TeamViewer' -ProcessNames @('TeamViewer') -Label 'TeamViewer' -UsbRoot $LabUsbRoot
Start-LabUserApp -TaskName 'GoldClub-TotalCommander-USB' -Tool 'TotalCommander' -Arguments '/O' -ProcessNames $tcNames -Label 'TotalCommander' -UsbRoot $LabUsbRoot

Write-LabLog 'Start-LabDesktop end'
return 0
