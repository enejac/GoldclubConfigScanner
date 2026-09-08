# Put the MUX/SAS board back on COM11 and get SAS talking again - no reboot.
#
# Symptom this fixes: the game sits on "Locked by Host. NO SAS COMMUNICATIONS!".
#
# Cause: the MUX board (STM32 VCP, VID_0483&PID_5740) does not report a stable
# USB serial, so Windows mints a new device node per identity and each node
# keeps its own COM number. The one node that carries PortName=COM11 and the
# "MUX/SAS" friendly name is usually a ghost, and it holds COM11 reserved in the
# COM Name Arbiter. CommCtrlSAS therefore cannot open COM11 and only listens on
# its control port 40000; the live board ends up on some other COM behind
# generic CommCtrl; Aurum's SASControler1 dials localhost:31100, finds nothing,
# and LockGameWhenNoComms locks the game.
#
# Sequence proven on GST22377, 31 Aug 2026:
#   1. remove the non-present MUX nodes            -> frees the COM11 reservation
#   2. run the stock 17-SetSerialPorts.ps1         -> vendor logic assigns COM11
#   3. stop CommCtrlSAS then CommCtrl              -> releases the open handle
#   4. devcon disable / enable the live MUX        -> driver re-reads PortName
#   5. start both services again
#
# Step 3 is what makes this work without a reboot. While CommCtrl holds the port
# open, devcon can only answer "Disabled on reboot ... requires reboot to
# complete" and SERIALCOMM keeps the old number.
#
# Healthy afterwards: SERIALCOMM \Device\USBSER000 = COM11, CommCtrlSAS
# listening on 31100 as well as 40000, no stray 31400, and OneHand drops the
# OnlineLock by itself within a few seconds.
#
# This is a workaround. The unstable serial is a board fault - the real fix is
# reflashing or replacing the MUX.
#
# Never edits layout.json / locations.json. Those are board port maps.
#
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    [string]$HardwareId = 'VID_0483&PID_5740',
    [int]$TargetComPort = 11,
    [string[]]$ServiceDisplayNames = @(
        'GoldClub Serial Communication Gateway SAS',
        'GoldClub Serial Communication Gateway'
    ),
    [string]$SetSerialPortsScript = 'C:\Goldclub\platform\user\init\onlogon\17-SetSerialPorts.ps1',
    [switch]$SkipGhostCleanup,
    [switch]$WhatIfOnly
)

$ErrorActionPreference = 'Continue'

function Write-RepairLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] [mux-repair] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @('C:\Platform\Security\mux-repair.log', 'C:\tmp\mux-repair.log')) {
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

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-Devcon {
    # pnputil on 1809 (17763) has no /remove-device, so devcon is required.
    foreach ($p in @(
            'C:\Platform\Security\devcon.exe',
            'C:\Goldclub\bin\devcon.exe',
            'G:\bin\devcon.exe')) {
        if ([IO.File]::Exists($p)) { return $p }
    }
    return $null
}

function Get-MuxInstances {
    param([string]$HardwareId)
    $base = "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\$HardwareId"
    if (-not (Test-Path -LiteralPath $base)) { return @() }
    $result = @()
    foreach ($key in (Get-ChildItem -LiteralPath $base -ErrorAction SilentlyContinue)) {
        $serial = $key.PSChildName
        $props = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
        $dp = Get-ItemProperty -LiteralPath (Join-Path $key.PSPath 'Device Parameters') -ErrorAction SilentlyContinue
        $instanceId = "USB\$HardwareId\$serial"
        $pnp = Get-PnpDevice -InstanceId $instanceId -ErrorAction SilentlyContinue
        $result += [pscustomobject]@{
            Serial     = $serial
            InstanceId = $instanceId
            PortName   = $dp.PortName
            Friendly   = $props.FriendlyName
            Present    = [bool]($pnp -and $pnp.Present)
        }
    }
    return $result
}

function Get-ActiveUsbSerialPort {
    return (Get-ItemProperty 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM' -ErrorAction SilentlyContinue).'\Device\USBSER000'
}

function Test-PortListening {
    param([int]$Port)
    try {
        return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    }
    catch {
        return [bool]((netstat -ano) -match ":$Port\s+.*LISTENING")
    }
}

Write-RepairLog '--- begin ---'

if (-not (Test-Elevated)) {
    Write-RepairLog 'NOT ELEVATED - device removal and service control need admin; aborting'
    Write-Host 'RESULT=NOT_ELEVATED'
    exit 2
}

$target = "COM$TargetComPort"

$instances = @(Get-MuxInstances -HardwareId $HardwareId)
if (-not $instances) {
    Write-RepairLog "no $HardwareId instances found - is the MUX plugged in?"
    Write-Host 'RESULT=NO_DEVICE'
    exit 3
}
foreach ($i in $instances) {
    Write-RepairLog ("  {0} serial={1} COM={2} name={3}" -f `
            $(if ($i.Present) { 'PRESENT' } else { 'ghost  ' }), $i.Serial, $i.PortName, $i.Friendly)
}

$live = @($instances | Where-Object { $_.Present })
if ($live.Count -lt 1) {
    Write-RepairLog 'no PRESENT MUX - refusing to touch anything'
    Write-Host 'RESULT=NO_LIVE_DEVICE'
    exit 3
}
$liveNode = $live[0]

if ($WhatIfOnly) {
    $ghostCount = @($instances | Where-Object { -not $_.Present }).Count
    Write-RepairLog ("WhatIf: live={0} on {1}, {2} ghost(s), would assign {3}" -f `
            $liveNode.Serial, $liveNode.PortName, $ghostCount, $target)
    Write-Host 'RESULT=WHATIF'
    exit 0
}

# --- 1. drop the ghosts so the target COM reservation is released --------------
if (-not $SkipGhostCleanup) {
    $cleaner = Join-Path (Split-Path -Parent $PSCommandPath) 'Clear-MuxGhostPorts.ps1'
    if ([IO.File]::Exists($cleaner)) {
        Write-RepairLog "ghost cleanup: $cleaner"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleaner -HardwareId $HardwareId 2>&1 |
            ForEach-Object { Write-RepairLog "  $_" }
    }
    else {
        Write-RepairLog "ghost cleanup skipped - Clear-MuxGhostPorts.ps1 not found beside this script"
    }
}

# --- 2. let the vendor script do the assignment --------------------------------
# It uses absolute C:\Goldclub paths, so it runs standalone with no task runner.
if ([IO.File]::Exists($SetSerialPortsScript)) {
    Write-RepairLog "running stock $SetSerialPortsScript"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SetSerialPortsScript 2>&1 |
        ForEach-Object { Write-RepairLog "  $_" }
}
else {
    Write-RepairLog "WARN: $SetSerialPortsScript missing - relying on existing registry assignment"
}

$assigned = @(Get-MuxInstances -HardwareId $HardwareId | Where-Object { $_.Present })
if ($assigned) {
    Write-RepairLog ("live node {0} now assigned {1} ({2})" -f `
            $assigned[0].Serial, $assigned[0].PortName, $assigned[0].Friendly)
    $liveNode = $assigned[0]
}

# --- 3. release the port ------------------------------------------------------
# devcon cannot restart a device whose port a service still holds open; without
# this it reports "requires reboot to complete" and SERIALCOMM keeps the old COM.
$stopped = @()
foreach ($name in $ServiceDisplayNames) {
    $svc = Get-Service -DisplayName $name -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-RepairLog "service not installed: $name"
        continue
    }
    if ($svc.Status -eq 'Stopped') {
        Write-RepairLog "already stopped: $name"
        continue
    }
    try {
        Stop-Service -InputObject $svc -Force -ErrorAction Stop
        $stopped += $name
        Write-RepairLog "stopped: $name"
    }
    catch {
        Write-RepairLog ("FAILED to stop {0}: {1}" -f $name, $_.Exception.Message)
    }
}
Start-Sleep -Seconds 5

# --- 4. bounce the live board so the driver re-reads PortName ------------------
$devcon = Find-Devcon
if (-not $devcon) {
    Write-RepairLog 'FATAL: devcon.exe not found'
    foreach ($name in ($ServiceDisplayNames | Sort-Object -Descending)) {
        $svc = Get-Service -DisplayName $name -ErrorAction SilentlyContinue
        if ($svc) { try { Start-Service -InputObject $svc -ErrorAction Stop } catch {} }
    }
    Write-Host 'RESULT=NO_DEVCON'
    exit 4
}
Write-RepairLog "devcon: $devcon"
foreach ($verb in @('disable', 'enable')) {
    & $devcon $verb "@$($liveNode.InstanceId)" 2>&1 | ForEach-Object { Write-RepairLog "  devcon $verb : $_" }
    Start-Sleep -Seconds 4
}
Start-Sleep -Seconds 8

# --- 5. bring the services back ------------------------------------------------
# Reverse order: the generic gateway must be up before the SAS one.
foreach ($name in @($ServiceDisplayNames)[($ServiceDisplayNames.Count - 1)..0]) {
    $svc = Get-Service -DisplayName $name -ErrorAction SilentlyContinue
    if (-not $svc) { continue }
    try {
        Start-Service -InputObject $svc -ErrorAction Stop
        Write-RepairLog "started: $name"
    }
    catch {
        Write-RepairLog ("FAILED to start {0}: {1}" -f $name, $_.Exception.Message)
    }
    Start-Sleep -Seconds 3
}
Start-Sleep -Seconds 10

# --- verify --------------------------------------------------------------------
$activePort = Get-ActiveUsbSerialPort
$sasListening = Test-PortListening -Port 31100
Write-RepairLog ("SERIALCOMM USBSER000 = {0} (want {1})" -f $activePort, $target)
Write-RepairLog ("31100 listening = {0}" -f $sasListening)
Write-Host ("ACTIVE_PORT={0}" -f $activePort)
Write-Host ("SAS_LISTENING={0}" -f $sasListening)

if ($activePort -eq $target -and $sasListening) {
    Write-RepairLog 'repair OK - SAS gateway is on the MUX'
    Write-Host 'RESULT=OK'
    Write-RepairLog '--- end ---'
    exit 0
}

if ($activePort -eq $target) {
    Write-RepairLog "port is $target but nothing is listening on 31100 yet - check CommCtrlSAS"
    Write-Host 'RESULT=PORT_OK_NO_LISTENER'
    Write-RepairLog '--- end ---'
    exit 5
}

Write-RepairLog "port is still $activePort - a reboot may be needed to complete the device restart"
Write-Host 'RESULT=PORT_NOT_APPLIED'
Write-RepairLog '--- end ---'
exit 6
