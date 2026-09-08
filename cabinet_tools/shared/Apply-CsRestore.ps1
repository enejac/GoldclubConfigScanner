#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot copy of ConfigScanner-saved Slot licence XML/dll onto GOLDCLUB (G:).

  Never copies bios License.lic / Session.lic - only a successful BiOS accept
  creates Session.lic. Copying staging bind files was wiping accept on reboot.

  Does not touch serialport maps. Use -Force only for a deliberate restage.
#>
[CmdletBinding()]
param(
    [string]$StagingRoot = 'C:\tmp\cs_restore',
    [string]$GoldRoot = 'G:',
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
$sentinel = 'C:\Platform\Security\cs_restore.applied'
$script:NeverCopyBiosBind = @(
    'License.lic',
    'License_BACKUP.lic',
    'Session.lic'
)

function Write-RestoreLog([string]$Message) {
    $line = "[$(Get-Date -Format o)] $Message"
    try {
        [IO.File]::AppendAllText('C:\Platform\Security\oo-security.log', $line + [Environment]::NewLine)
    } catch {}
    Write-Host $line
}

function Test-GoldClubReady {
    try {
        $d = [IO.DriveInfo]::new(($GoldRoot.TrimEnd('\') + '\'))
        return [bool]($d.IsReady -and [IO.File]::Exists(($GoldRoot.TrimEnd('\') + '\Bootstrap.exe')))
    } catch {
        return $false
    }
}

function Copy-IfMissing([string]$Src, [string]$Dst) {
    if (-not (Test-Path -LiteralPath $Src)) { return }
    if (Test-Path -LiteralPath $Dst) {
        Write-RestoreLog "keep live $Dst"
        return
    }
    $dir = Split-Path $Dst -Parent
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Copy-Item -LiteralPath $Src -Destination $Dst -Force
    Write-RestoreLog "copied $Dst"
}

if (-not $Force -and (Test-Path -LiteralPath $sentinel)) {
    Write-RestoreLog 'SKIP already applied - will not overwrite accepted licence'
    return 0
}

if (-not (Test-Path -LiteralPath $StagingRoot)) {
    Write-RestoreLog "SKIP no staging $StagingRoot"
    return 1
}
if (-not (Test-GoldClubReady)) {
    Write-RestoreLog 'SKIP G: GOLDCLUB not ready'
    return 2
}

$gold = $GoldRoot.TrimEnd('\')
$srcLic = Join-Path $StagingRoot 'Licenses'
if (Test-Path -LiteralPath $srcLic) {
    $destLic = Join-Path $gold 'Licenses'
    if (-not (Test-Path -LiteralPath $destLic)) {
        New-Item -ItemType Directory -Path $destLic -Force | Out-Null
    }
    Get-ChildItem -LiteralPath $srcLic -File | ForEach-Object {
        Copy-IfMissing $_.FullName (Join-Path $destLic $_.Name)
    }
}

Copy-IfMissing (Join-Path $StagingRoot 'slot\licence.dll') (Join-Path $gold 'slot\licence.dll')
Get-ChildItem -LiteralPath (Join-Path $StagingRoot 'slot') -Filter 'Licence*.xml' -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-IfMissing $_.FullName (Join-Path $gold ("slot\" + $_.Name))
}

Write-RestoreLog 'SKIP bios License.lic / Session.lic (accept-only bind files)'

$hwSrc = Join-Path $StagingRoot 'slot\themes\HardwareConfig.xml'
$hwDst = Join-Path $gold 'slot\themes\HardwareConfig.xml'
$code = '01D68A721B000019'
if (Test-Path -LiteralPath $hwDst) {
    Write-RestoreLog 'HardwareConfig already on GOLDCLUB - not overwritten'
} else {
    Copy-IfMissing $hwSrc $hwDst
}

if (Test-Path -LiteralPath $hwDst) {
    try {
        $raw = [IO.File]::ReadAllText($hwDst)
        if ($raw -notmatch [regex]::Escape($code)) {
            $block = @"
      <DallasKey>
        <Code>$code</Code>
        <Groups>
          <string>Service</string>
        </Groups>
        <Unlock>true</Unlock>
      </DallasKey>
"@
            $hit = [regex]::Match($raw, '(?s)(<DallasKeySettings>.*?<Permissions>)')
            if ($hit.Success) {
                $updated = $raw.Insert($hit.Index + $hit.Length, "`r`n" + $block)
                $bak = $hwDst + '.bak-dallas'
                if (-not (Test-Path -LiteralPath $bak)) { [IO.File]::Copy($hwDst, $bak, $false) }
                [IO.File]::WriteAllText($hwDst, $updated, [Text.UTF8Encoding]::new($false))
                Write-RestoreLog "Dallas $code inserted into HardwareConfig"
            }
        } else {
            Write-RestoreLog "Dallas $code already present"
        }
    } catch {
        Write-RestoreLog "Dallas patch failed: $($_.Exception.Message)"
    }
}

try {
    [IO.File]::WriteAllText($sentinel, (Get-Date -Format o), [Text.UTF8Encoding]::new($false))
    Write-RestoreLog "wrote $sentinel"
} catch {
    Write-RestoreLog "sentinel write failed: $($_.Exception.Message)"
}

Write-RestoreLog 'Apply-CsRestore done'
return 0
