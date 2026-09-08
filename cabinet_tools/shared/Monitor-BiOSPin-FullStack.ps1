#Requires -Version 5.1
<#
  Full-stack monitor for BiOS QR/PIN login.
  Logs: C:\Platform\Security\bios-pin-fullstack.log
#>
param(
    [int]$DurationSeconds = 1200,
    [int]$IntervalSeconds = 1
)

$logOut = 'C:\Platform\Security\bios-pin-fullstack.log'
$sessionLog = 'G:\bios\SessionValidator.log'
$sessionLic = 'G:\bios\License\Session.lic'

$watchFiles = [ordered]@{
    $sessionLog = 0L
    'G:\var\log\SlotLog' = 0L
    'G:\var\log\onlogon.log' = 0L
    'G:\var\log\onlogon-lab.log' = 0L
    'G:\services\aurum\var\log\aurum.log' = 0L
    'G:\services\aurum\var\log\GCMessenger.log' = 0L
}

$watchPorts = @(30200, 30800, 31100, 40000, 50010, 50011)
$procNames = @('BiOS2', 'CommCtrl', 'CommCtrlSAS', 'hwsubsys', 'OneHand', 'Bootstrap', 'GoldClub.Aurum.Services')

function Write-Mon([string]$Tag, [string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] [$Tag] $Msg"
    Add-Content -LiteralPath $logOut -Value $line -Encoding ASCII
}

function Get-FileTailDelta {
    param([string]$Path, [ref]$LastSize)
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    try {
        $len = (Get-Item -LiteralPath $Path).Length
    } catch { return @() }
    if ($len -le $LastSize.Value) { return @() }
    $delta = [int]($len - $LastSize.Value)
    $LastSize.Value = $len
    try {
        $fs = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        $fs.Seek($len - $delta, 'Begin') | Out-Null
        $buf = New-Object byte[] $delta
        [void]$fs.Read($buf, 0, $delta)
        $fs.Close()
        $text = [Text.Encoding]::UTF8.GetString($buf) -replace "`r", ''
        return @($text -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    } catch {
        Write-Mon 'ERR' "read $Path : $($_.Exception.Message)"
        return @()
    }
}

function Get-ProcMap {
    $map = @{}
    foreach ($name in $procNames) {
        foreach ($p in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            $map[$p.Id] = $name
        }
    }
    return $map
}

$ErrorActionPreference = 'SilentlyContinue'
try { if (Test-Path -LiteralPath $logOut) { Remove-Item -LiteralPath $logOut -Force } } catch { }

Write-Mon 'READY' '=== FULL-STACK MONITOR ARMED - enter PIN when ready ==='
Write-Mon 'STATE' "Session.lic=$(Test-Path -LiteralPath $sessionLic)"
Write-Mon 'STATE' "BiOS2=$((@(Get-Process BiOS2 -EA SilentlyContinue | ForEach-Object Id)) -join ',')"

foreach ($k in @($watchFiles.Keys)) {
    if (Test-Path -LiteralPath $k) {
        $watchFiles[$k] = (Get-Item -LiteralPath $k).Length
        Write-Mon 'STATE' "$(Split-Path $k -Leaf) size=$($watchFiles[$k])"
    }
}

foreach ($port in $watchPorts) {
    $listen = @(Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue)
    $est = @(Get-NetTCPConnection -LocalPort $port -State Established -EA SilentlyContinue)
    Write-Mon 'PORT' ":$port listen=$($listen.Count) established=$($est.Count) owner=$(
        ($listen + $est | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            $n = (Get-Process -Id $_ -EA SilentlyContinue).ProcessName
            if ($n) { "$n($_)" } else { $_ }
        }) -join ','
    )"
}

$seenNet = @{}
$seenSessionLic = $false
$lastCommSnapshot = ''
$deadline = (Get-Date).AddSeconds($DurationSeconds)

while ((Get-Date) -lt $deadline) {
    foreach ($entry in $watchFiles.GetEnumerator()) {
        $path = [string]$entry.Key
        $sizeRef = [ref][long]$entry.Value
        foreach ($line in @(Get-FileTailDelta -Path $path -LastSize $sizeRef)) {
            $tag = switch -Regex ($path) {
                'SessionValidator' { 'SESSION' }
                'SlotLog' { 'SLOT' }
                'onlogon' { 'ONLOGON' }
                'aurum\.log' { 'AURUM' }
                'GCMessenger' { 'AURUM-SAS' }
                default { 'LOG' }
            }
            Write-Mon $tag "$(Split-Path $path -Leaf): $line"
        }
        $watchFiles[$path] = $sizeRef.Value
    }

    if ((Test-Path -LiteralPath $sessionLic) -and -not $seenSessionLic) {
        $seenSessionLic = $true
        $lic = Get-Item -LiteralPath $sessionLic
        Write-Mon 'SESSION-FILE' "CREATED len=$($lic.Length) mtime=$($lic.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
    }

    $procMap = Get-ProcMap
    foreach ($entry in $procMap.GetEnumerator()) {
        $biosPid = [int]$entry.Key
        $pname = [string]$entry.Value
        foreach ($c in @(Get-NetTCPConnection -OwningProcess $biosPid -EA SilentlyContinue)) {
            if ($c.State -ne 'Established') { continue }
            $key = "$pname|$biosPid|$($c.LocalAddress):$($c.LocalPort)->$($c.RemoteAddress):$($c.RemotePort)"
            if (-not $seenNet.ContainsKey($key)) {
                $seenNet[$key] = $true
                Write-Mon 'NET-PROC' $key
            }
        }
    }

    foreach ($c in @(Get-NetTCPConnection -State Established -EA SilentlyContinue)) {
        if ($c.RemoteAddress -in @('127.0.0.1', '::1', '0.0.0.0', '::')) { continue }
        if ($c.RemotePort -notin @(80, 443, 8080, 8443, 5938)) { continue }
        try { $pn = (Get-Process -Id $c.OwningProcess -EA Stop).ProcessName } catch { continue }
        if ($pn -notin @('BiOS2', 'OneHand', 'Bootstrap', 'GoldClub.Aurum.Services', 'CommCtrl', 'CommCtrlSAS') -and
            $pn -notlike 'GoldClub*') { continue }
        $key = "OUT|$pn|$($c.OwningProcess)|$($c.LocalPort)->$($c.RemoteAddress):$($c.RemotePort)"
        if (-not $seenNet.ContainsKey($key)) {
            $seenNet[$key] = $true
            Write-Mon 'NET-OUT' $key
        }
    }

    $commLines = @()
    foreach ($port in @(30800, 30200, 31100)) {
        foreach ($c in @(Get-NetTCPConnection -LocalPort $port -EA SilentlyContinue | Where-Object { $_.State -eq 'Established' })) {
            $owner = (Get-Process -Id $c.OwningProcess -EA SilentlyContinue).ProcessName
            $commLines += ":$port $owner($($c.OwningProcess)) $($c.LocalAddress):$($c.LocalPort)<->$($c.RemoteAddress):$($c.RemotePort)"
        }
    }
    $commSnap = ($commLines | Sort-Object) -join ' | '
    if ($commSnap -and $commSnap -ne $lastCommSnapshot) {
        $lastCommSnapshot = $commSnap
        Write-Mon 'COMM' $commSnap
    }

    Start-Sleep -Seconds $IntervalSeconds
}

Write-Mon 'END' 'monitor finished'
