#Requires -Version 5.1
<#
.SYNOPSIS
  Re-enable Windows USB automount and disabled USB mass-storage devices.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'

function Log([string]$Message) {
    Write-Host $Message
}

Log 'Enabling automount (mountvol /E, diskpart automount enable)'
cmd /c 'mountvol /E' | Out-Null
$dp = Join-Path $env:TEMP 'fix-usb-automount.txt'
[System.IO.File]::WriteAllText($dp, "automount enable`r`nexit`r`n", [System.Text.UTF8Encoding]::new($false))
cmd /c "diskpart /s `"$dp`"" | Out-Null
New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\mountmgr' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\mountmgr' -Name 'NoAutoMount' -Value 0 -Type DWord -ErrorAction SilentlyContinue
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR' -Name 'Start' -Value 3 -Type DWord -ErrorAction SilentlyContinue

Get-Partition -ErrorAction SilentlyContinue |
    Where-Object { $_.Type -eq 'Recovery' -and $_.DriveLetter } |
    ForEach-Object {
        Log ("Removing $($_.DriveLetter): from Recovery partition (must not steal USB letters)")
        try { Set-Partition -DiskNumber $_.DiskNumber -PartitionNumber $_.PartitionNumber -NoDefaultDriveLetter $true } catch {}
        try { Set-Partition -DiskNumber $_.DiskNumber -PartitionNumber $_.PartitionNumber -RemoveDriveLetter } catch {}
    }

Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Status -eq 'Error' -and (
            $_.FriendlyName -match 'Mass Storage|UAS|Flash Drive' -or
            $_.InstanceId -match 'USBSTOR|VID_152D'
        )
    } |
    ForEach-Object {
        Log ("Enabling $($_.FriendlyName)")
        pnputil /enable-device $_.InstanceId 2>&1 | Out-Null
        try { Enable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    }

Log 'USB automount repair done.'
exit 0
