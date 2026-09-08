#Requires -Version 5.1
param(
    [int]$DurationSeconds = 900,
    [int]$IntervalSeconds = 2
)

$logOut = 'C:\Platform\Security\bios-pin-monitor.log'
$sessionLog = 'G:\bios\SessionValidator.log'
$sessionLic = 'G:\bios\License\Session.lic'

function Write-Mon([string]$Tag, [string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff')] [$Tag] $Msg"
    Add-Content -LiteralPath $logOut -Value $line -Encoding ASCII
}

$ErrorActionPreference = 'SilentlyContinue'
try { if (Test-Path -LiteralPath $logOut) { Remove-Item -LiteralPath $logOut -Force } } catch { }

Write-Mon 'START' "duration=${DurationSeconds}s"
Write-Mon 'STATE' "Session.lic=$(Test-Path -LiteralPath $sessionLic)"
Write-Mon 'STATE' "BiOS2=$((Get-Process BiOS2 -EA SilentlyContinue | ForEach-Object Id) -join ',')"

$lastSessionSize = 0L
if (Test-Path -LiteralPath $sessionLog) {
    $lastSessionSize = (Get-Item -LiteralPath $sessionLog).Length
    Write-Mon 'STATE' "SessionValidator.log size=$lastSessionSize"
}

$seenNet = @{}
$deadline = (Get-Date).AddSeconds($DurationSeconds)

while ((Get-Date) -lt $deadline) {
    try {
        if (Test-Path -LiteralPath $sessionLog) {
            $len = (Get-Item -LiteralPath $sessionLog).Length
            if ($len -gt $lastSessionSize) {
                $stream = [IO.File]::Open($sessionLog, 'Open', 'Read', 'ReadWrite')
                $stream.Seek($lastSessionSize, 'Begin') | Out-Null
                $count = [int]($len - $lastSessionSize)
                $buf = New-Object byte[] $count
                [void]$stream.Read($buf, 0, $count)
                $stream.Close()
                $text = [Text.Encoding]::UTF8.GetString($buf) -replace "`r", ''
                foreach ($line in ($text -split "`n")) {
                    $t = $line.Trim()
                    if ($t) { Write-Mon 'SESSION-LOG' $t }
                }
                $lastSessionSize = $len
            }
        }

        if (Test-Path -LiteralPath $sessionLic) {
            $lic = Get-Item -LiteralPath $sessionLic
            Write-Mon 'SESSION-FILE' "Session.lic len=$($lic.Length) mtime=$($lic.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
        }

        foreach ($biosPid in @(Get-Process BiOS2 -EA SilentlyContinue | ForEach-Object { $_.Id })) {
            foreach ($c in @(Get-NetTCPConnection -OwningProcess $biosPid -EA SilentlyContinue)) {
                if ($c.RemoteAddress -in @('127.0.0.1','0.0.0.0','::','')) { continue }
                $key = "$biosPid|$($c.LocalPort)->$($c.RemoteAddress):$($c.RemotePort)|$($c.State)"
                if (-not $seenNet.ContainsKey($key)) {
                    $seenNet[$key] = $true
                    Write-Mon 'NET-BIOS2' $key
                }
            }
        }

        foreach ($c in @(Get-NetTCPConnection -State Established -EA SilentlyContinue)) {
            if ($c.RemoteAddress -in @('127.0.0.1','0.0.0.0','::')) { continue }
            if ($c.RemotePort -notin @(80,443,8080,8443)) { continue }
            try { $pn = (Get-Process -Id $c.OwningProcess -EA Stop).ProcessName } catch { continue }
            $key = "OUT|$pn|$($c.OwningProcess)|$($c.LocalPort)->$($c.RemoteAddress):$($c.RemotePort)"
            if (-not $seenNet.ContainsKey($key)) {
                $seenNet[$key] = $true
                Write-Mon 'NET-HTTPS' $key
            }
        }
    } catch {
        Write-Mon 'ERR' $_.Exception.Message
    }
    Start-Sleep -Seconds $IntervalSeconds
}

Write-Mon 'END' 'finished'
