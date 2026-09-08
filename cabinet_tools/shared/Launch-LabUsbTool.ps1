#Requires -Version 5.1
<#
.SYNOPSIS
  At-logon helper: find lab USB (any letter) and start TeamViewer or Total Commander.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('TeamViewer', 'TotalCommander')]
    [string]$Tool,
    [string]$Arguments
)

$ErrorActionPreference = 'SilentlyContinue'

function Find-LabUsbRoot {
    foreach ($d in [IO.DriveInfo]::GetDrives()) {
        try {
            if (-not $d.IsReady) { continue }
            $root = $d.Name.TrimEnd('\')
            if ($root -in @('C:', 'G:')) { continue }
            if ($d.DriveType -notin @('Removable', 'Fixed')) { continue }
            if ([IO.File]::Exists("$root\Bootstrap.exe")) { continue }
            if ([IO.File]::Exists("$root\slot\OneHand.exe")) { continue }
            if ([IO.File]::Exists("$root\ruleta\Ruleta.exe")) { continue }
            if ([IO.File]::Exists("$root\TeamViewerPortable\TeamViewer.exe")) { return $root }
            if ([IO.File]::Exists("$root\totalcmd\TOTALCMD64.EXE")) { return $root }
            if ([IO.File]::Exists("$root\totalcmd\TOTALCMD.EXE")) { return $root }
        } catch {}
    }
    return $null
}

function Resolve-ToolExe {
    param([string]$UsbRoot)
    $candidates = @()
    if ($Tool -eq 'TeamViewer') {
        $candidates += 'C:\Platform\Tools\TeamViewerPortable\TeamViewer.exe'
        if ($UsbRoot) { $candidates += (Join-Path $UsbRoot 'TeamViewerPortable\TeamViewer.exe') }
        $candidates += 'C:\Users\goldclub\AppData\Local\TeamViewer\TeamViewer.exe'
    } else {
        $candidates += 'C:\Platform\Tools\totalcmd\TOTALCMD64.EXE'
        $candidates += 'C:\Platform\Tools\totalcmd\TOTALCMD.EXE'
        if ($UsbRoot) {
            $candidates += (Join-Path $UsbRoot 'totalcmd\TOTALCMD64.EXE')
            $candidates += (Join-Path $UsbRoot 'totalcmd\TOTALCMD.EXE')
        }
    }
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

$names = if ($Tool -eq 'TeamViewer') { @('TeamViewer') } else { @('TOTALCMD', 'TOTALCMD64') }
if (@(Get-Process -Name $names | Where-Object { $_.SessionId -gt 0 }).Count -gt 0) { exit 0 }

$usb = Find-LabUsbRoot
$exe = Resolve-ToolExe -UsbRoot $usb
if (-not $exe) { exit 1 }

if ($Tool -eq 'TeamViewer') {
    $printer = Join-Path (Split-Path -Parent $exe) 'Printer'
    $off = Join-Path (Split-Path -Parent $exe) 'Printer.disabled'
    if ((Test-Path -LiteralPath $printer) -and -not (Test-Path -LiteralPath $off)) {
        Rename-Item -LiteralPath $printer -NewName 'Printer.disabled' -ErrorAction SilentlyContinue
    }
}

$wd = Split-Path -Parent $exe
if ($Arguments) {
    Start-Process -FilePath $exe -ArgumentList $Arguments -WorkingDirectory $wd
} else {
    Start-Process -FilePath $exe -WorkingDirectory $wd
}
