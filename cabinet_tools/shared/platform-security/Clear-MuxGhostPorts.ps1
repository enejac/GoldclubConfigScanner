# Remove ghost MUX device nodes so COM11 is free before 17-SetSerialPorts runs.
#
# The MUX board (STM32 VCP, VID_0483&PID_5740) does not report a stable USB
# serial number across power cycles. Windows therefore creates a NEW device node
# per identity, each keeping its own COM assignment. On GST22377 there were six
# nodes at the same physical port Port_#0003.Hub_#0003:
#
#   207C39555241 COM3   206237634741 COM10  2062375B4741 COM11 (MUX/SAS)
#   206937794741 COM12  205E31524B42 COM13  206139555241 COM14 (present)
#
# Only the COM11 node carries the MUX/SAS name CommCtrlSAS needs, and it is a
# ghost. COM11 stays reserved for it in the COM Name Arbiter, so stock
# 17-SetSerialPorts cannot hand COM11 to the live board and SAS stays locked
# ("NO SAS COMMUNICATIONS"). A reboot only helps when the board happens to come
# up as that one identity - roughly one boot in six.
#
# Removing the non-present nodes releases their COM reservations, so whichever
# identity enumerates can be given COM11 and it sticks.
#
# Safety rules, deliberately narrow:
#   - only VID_0483&PID_5740
#   - only instances that are NOT present
#   - never the live device
#   - never touches layout.json / locations.json (board port maps - forbidden)
#
# Runs as SYSTEM from an AtStartup task (device removal needs real admin), well
# before the stock onlogon chain reaches 17-SetSerialPorts.
#
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    [string]$HardwareId = 'VID_0483&PID_5740',
    # Documented GoldClub port map (TCP = 30000 + COM#): bill/keyboard COM3,
    # ticket COM4, switch COM6, lights COM7. A MUX ghost squatting on one of
    # those must still lose the device node, but do not hand the number back to
    # the free pool where an unrelated device could take it.
    [int[]]$PreserveComPorts = @(3, 4, 6, 7),
    [switch]$WhatIfOnly
)

$ErrorActionPreference = 'Continue'

function Write-MuxLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] [mux-ghosts] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @('C:\Platform\Security\mux-ghosts.log', 'C:\tmp\mux-ghosts.log')) {
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
    # Prefer the C: copy: G: is BitLocker-locked this early in boot.
    foreach ($p in @(
            'C:\Platform\Security\devcon.exe',
            'C:\goldclub\bin\devcon.exe',
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
            Location   = $props.LocationInformation
            Present    = [bool]($pnp -and $pnp.Present)
        }
    }
    return $result
}

function Get-ReservedComPorts {
    $db = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\COM Name Arbiter' `
            -Name ComDB -ErrorAction SilentlyContinue).ComDB
    if (-not $db) { return @() }
    $taken = @()
    for ($byte = 0; $byte -lt $db.Length; $byte++) {
        for ($bit = 0; $bit -lt 8; $bit++) {
            if ($db[$byte] -band (1 -shl $bit)) { $taken += ($byte * 8 + $bit + 1) }
        }
    }
    return $taken
}

function Get-LiveComPorts {
    $sc = Get-ItemProperty 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM' -ErrorAction SilentlyContinue
    if (-not $sc) { return @() }
    return @(
        $sc.PSObject.Properties |
            Where-Object { $_.Name -notlike 'PS*' } |
            ForEach-Object { $_.Value }
    )
}

function Clear-ComReservation {
    param([int]$Number)
    $path = 'HKLM:\SYSTEM\CurrentControlSet\Control\COM Name Arbiter'
    $db = (Get-ItemProperty -LiteralPath $path -Name ComDB -ErrorAction SilentlyContinue).ComDB
    if (-not $db) { return $false }
    $idx = [math]::Floor(($Number - 1) / 8)
    $bit = ($Number - 1) % 8
    if ($idx -ge $db.Length) { return $false }
    if (-not ($db[$idx] -band (1 -shl $bit))) { return $false }
    $db[$idx] = $db[$idx] -band (-bnot (1 -shl $bit))
    Set-ItemProperty -LiteralPath $path -Name ComDB -Value $db -ErrorAction SilentlyContinue
    return $true
}

Write-MuxLog '--- begin ---'

if (-not (Test-Elevated)) {
    Write-MuxLog 'NOT ELEVATED - device removal needs admin; aborting'
    exit 2
}

$instances = @(Get-MuxInstances -HardwareId $HardwareId)
if (-not $instances) {
    Write-MuxLog "no $HardwareId instances found - nothing to do"
    exit 0
}

foreach ($i in $instances) {
    Write-MuxLog ("  {0} serial={1} COM={2} loc={3} name={4}" -f `
        $(if ($i.Present) { 'PRESENT' } else { 'ghost  ' }), $i.Serial, $i.PortName, $i.Location, $i.Friendly)
}

$live = @($instances | Where-Object { $_.Present })
if ($live.Count -lt 1) {
    # Removing every node while the board is absent would delete the live one's
    # config too, and it would just re-enumerate as a fresh identity anyway.
    Write-MuxLog 'no PRESENT MUX right now - refusing to remove anything'
    exit 0
}

$ghosts = @($instances | Where-Object { -not $_.Present })
if (-not $ghosts) {
    Write-MuxLog 'no ghosts - COM assignment is already unambiguous'
    exit 0
}

$devcon = Find-Devcon
if (-not $devcon) {
    Write-MuxLog 'FATAL: devcon.exe not found (pnputil on 1809 cannot remove devices)'
    exit 3
}
Write-MuxLog "devcon: $devcon"

if ($WhatIfOnly) {
    Write-MuxLog ("WhatIf: would remove {0} ghost(s): {1}" -f $ghosts.Count, (($ghosts | ForEach-Object { $_.Serial }) -join ', '))
    exit 0
}

$freed = @()
foreach ($g in $ghosts) {
    Write-MuxLog ("removing ghost {0} (was {1})" -f $g.Serial, $g.PortName)
    try {
        $p = Start-Process -FilePath $devcon -ArgumentList @('remove', "@$($g.InstanceId)") `
            -PassThru -Wait -WindowStyle Hidden -ErrorAction Stop
        Write-MuxLog ("  devcon exit={0}" -f $p.ExitCode)
        if ($g.PortName -match '^COM(\d+)$') { $freed += [int]$Matches[1] }
    }
    catch {
        Write-MuxLog ("  devcon failed: {0}" -f $_.Exception.Message)
    }
}

# Removing the node normally releases its COM Name Arbiter bit. Clear anything
# left behind, but never a number a live port is actually using.
$liveComs = @(Get-LiveComPorts)
Write-MuxLog ("live COM ports: {0}" -f ($liveComs -join ', '))
foreach ($n in ($freed | Sort-Object -Unique)) {
    if (("COM$n") -in $liveComs) {
        Write-MuxLog "  COM$n is in use by a live port - leaving reserved"
        continue
    }
    if ($n -in $PreserveComPorts) {
        Write-MuxLog "  COM$n is a documented GoldClub port - leaving reserved"
        continue
    }
    if (Clear-ComReservation -Number $n) { Write-MuxLog "  freed COM$n reservation" }
}

Write-MuxLog ("reserved after cleanup: {0}" -f ((Get-ReservedComPorts) -join ', '))
Write-MuxLog '--- end ---'
exit 0
