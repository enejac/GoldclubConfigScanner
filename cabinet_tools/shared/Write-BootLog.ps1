#Requires -Version 5.1
<#
.SYNOPSIS
  Shared boot log helper for Platform\Security scripts.
#>
function Write-BootLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    $utf8 = [Text.UTF8Encoding]::new($false)
    foreach ($logPath in @(
            'C:\Platform\Security\oo-security.log',
            'C:\tmp\oo-security.log',
            'C:\tmp\boot-trace.log'
        )) {
        try {
            $dir = Split-Path -Parent $logPath
            if ($dir -and -not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
            }
            [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
        }
        catch {}
    }
    try {
        $gd = [IO.DriveInfo]::new('G:\')
        if ($gd.IsReady) {
            $gLog = 'G:\var\log\oo-security.log'
            $gDir = Split-Path -Parent $gLog
            if (-not (Test-Path -LiteralPath $gDir)) {
                New-Item -ItemType Directory -Path $gDir -Force | Out-Null
            }
            [IO.File]::AppendAllText($gLog, $line + [Environment]::NewLine, $utf8)
        }
    }
    catch {}
}
