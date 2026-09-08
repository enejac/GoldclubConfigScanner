#Requires -Version 5.1
<#
.SYNOPSIS
  Restore Goldclub bios\Installed from C:\tmp\bios_Installed_restore staging.

  Safe to run after UnlockerDisk (G: unlocked). Use from OO_Security, onlogon,
  or manually on a live cabinet when BiOS2 apps are missing/corrupt.
#>
[CmdletBinding()]
param(
    [string]$StagingRoot = 'C:\tmp\bios_Installed_restore',
    [string]$DestRoot = 'G:\bios\Installed',
    [int]$MinB2pCount = 10
)

$ErrorActionPreference = 'Continue'

function Write-RestoreLog([string]$Message) {
    $line = "[$(Get-Date -Format o)] $Message"
    try {
        [IO.File]::AppendAllText('C:\Platform\Security\oo-security.log', $line + [Environment]::NewLine)
    } catch {}
    Write-Host $line
}

if (-not (Test-Path -LiteralPath $StagingRoot)) {
    Write-RestoreLog "SKIP no staging at $StagingRoot"
    return 1
}

$staged = @(Get-ChildItem -LiteralPath $StagingRoot -Filter '*.b2p' -ErrorAction SilentlyContinue)
if ($staged.Count -lt $MinB2pCount) {
    Write-RestoreLog "SKIP staging has only $($staged.Count) b2p (need $MinB2pCount)"
    return 2
}

$destParent = Split-Path $DestRoot -Parent
$gReady = $false
try {
    $gd = [IO.DriveInfo]::new('G:\')
    $gReady = [bool]($gd.IsReady -and [IO.File]::Exists('G:\Bootstrap.exe'))
} catch {}
if (-not $gReady) {
    Write-RestoreLog 'SKIP G: GOLDCLUB not unlocked yet'
    return 3
}

$existing = 0
if (Test-Path -LiteralPath $DestRoot) {
    $existing = @(Get-ChildItem -LiteralPath $DestRoot -Filter '*.b2p' -ErrorAction SilentlyContinue).Count
}
if ($existing -ge $MinB2pCount) {
    Write-RestoreLog "OK Installed already has $existing b2p at $DestRoot"
    return 0
}

if (-not (Test-Path -LiteralPath $destParent)) {
    New-Item -ItemType Directory -Path $destParent -Force | Out-Null
}
if (Test-Path -LiteralPath $DestRoot) {
    Remove-Item -LiteralPath $DestRoot -Recurse -Force
}

Copy-Item -LiteralPath $StagingRoot -Destination $DestRoot -Recurse -Force
$new = @(Get-ChildItem -LiteralPath $DestRoot -Filter '*.b2p' -ErrorAction SilentlyContinue).Count
Write-RestoreLog "Restored $new b2p -> $DestRoot (was $existing)"
return 0
