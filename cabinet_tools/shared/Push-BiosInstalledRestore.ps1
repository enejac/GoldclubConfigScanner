#Requires -Version 5.1
<#
.SYNOPSIS
  Push bios Installed restore to a live cabinet over SMB (slot share).

.EXAMPLE
  .\Push-BiosInstalledRestore.ps1 -ComputerName 10.0.0.111
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ComputerName,
    [string]$ShareSource = '\\10.0.0.249\WinSystems_SLOT\_Verzije\BIOS2\Quixant\BIOS2 v1.0.9\Installed',
    [string]$CredentialUser = '10.0.0.111\test',
    [string]$CredentialPassword = 'test'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$restorePs1 = Join-Path $repoRoot 'shared\Restore-BiosInstalled.ps1'

cmdkey /add:$ComputerName /user:$CredentialUser /pass:$CredentialPassword | Out-Null

$slot = "\\$ComputerName\slot"
if (-not (Test-Path -LiteralPath $slot)) {
    throw "Cannot reach $slot - is the cabinet on the network?"
}

$remoteStage = Join-Path $slot '..\tmp\bios_Installed_restore'
# slot maps to C:\goldclub; tmp is C:\tmp on cabinet - use c$ for staging
$remoteStage = "\\$ComputerName\c$\tmp\bios_Installed_restore"
$remoteRestore = "\\$ComputerName\c$\Platform\Security\Restore-BiosInstalled.ps1"
$remoteOo = "\\$ComputerName\c$\Platform\Security\OO_Security.ps1"

Write-Host "Staging Installed -> $remoteStage"
if (Test-Path -LiteralPath $remoteStage) {
    Remove-Item -LiteralPath $remoteStage -Recurse -Force
}
Copy-Item -LiteralPath $ShareSource -Destination $remoteStage -Recurse -Force
$count = (Get-ChildItem -LiteralPath $remoteStage -Filter '*.b2p').Count
Write-Host "Staged $count b2p files"

Copy-Item -LiteralPath $restorePs1 -Destination $remoteRestore -Force
Write-Host "Copied Restore-BiosInstalled.ps1"

# Run restore in session 1 via schtasks (game is up = user session exists)
$cred = New-Object pscredential($CredentialUser, (ConvertTo-SecureString $CredentialPassword -AsPlainText -Force))
Invoke-Command -ComputerName $ComputerName -Credential $cred -Authentication Negotiate -ScriptBlock {
    & 'C:\Platform\Security\Restore-BiosInstalled.ps1'
    $n = if (Test-Path 'G:\bios\Installed') {
        (Get-ChildItem 'G:\bios\Installed' -Filter '*.b2p' -EA SilentlyContinue).Count
    } else { 0 }
    [pscustomobject]@{ Hostname = $env:COMPUTERNAME; InstalledB2p = $n }
}

Write-Host 'Done. Reboot or restart BiOS2 shell if apps still missing.'
