#Requires -Version 5.1
# Capture QR, set LoginPhrase, test Validate, auto SendKeys on success.
param(
    [string]$Role = 'Service',
    [string]$LogPath = 'C:\Platform\Security\bios-auto-login.log'
)

function L([string]$m) { Add-Content $LogPath "[$(Get-Date -Format HH:mm:ss.fff)] $m" -Encoding ASCII }

try {
    if (Test-Path $LogPath) { Remove-Item $LogPath -Force }
    L 'START'
    Add-Type -AssemblyName System.Windows.Forms,System.Drawing
    Set-Location 'G:\BiOS'
    foreach ($dll in @('GoldClub.Logging.dll','GoldClub.Interfaces.dll','GoldClub.Settings.dll',
        'LicenseValidator.dll','AWSSDK.Core.dll','AWSSDK.S3.dll','Newtonsoft.Json.dll','QRCoder.dll')) {
        if (Test-Path $dll) { [void][Reflection.Assembly]::LoadFrom((Resolve-Path $dll).Path) }
    }
    $asm = [Reflection.Assembly]::LoadFrom('G:\BiOS\BiOS2.exe')
    $acType = $asm.GetType('BiOS2.Utils.AccessControl')
    $ac = $acType.GetMethod('GetInstance').Invoke($null, @())

    # Capture QR region (left half of BiOS2 window)
    $bios = Get-Process BiOS2 -ErrorAction Stop | Select-Object -First 1
    Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32 {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
    [void][W32]::SetForegroundWindow($bios.MainWindowHandle)
    Start-Sleep -Milliseconds 300
    $rect = New-Object W32+RECT
    [void][W32]::GetWindowRect($bios.MainWindowHandle, [ref]$rect)
    $w = $rect.R - $rect.L; $h = $rect.B - $rect.T
    $cropW = [int]($w * 0.45)
    $bmp = New-Object Drawing.Bitmap $cropW, $h
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.L, $rect.T, 0, 0, [Drawing.Size]::new($cropW, $h))
    $g.Dispose()
    $png = 'C:\Platform\Security\bios-qr-crop.png'
    $bmp.Save($png, [Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    L "captured $png ${cropW}x$h"

    # Decode QR via QRCoder BitmapByteQRCode reverse - use QRCodeData from QRCoder reader if available
    $qrAsm = [Reflection.Assembly]::LoadFrom('G:\BiOS\QRCoder.dll')
    $readerType = $qrAsm.GetType('QRCoder.QRCodeReader')
    if ($readerType) {
        L 'QRCodeReader found'
    } else {
        L 'QRCodeReader not in QRCoder.dll - pins must be fetched externally'
    }

    L "CloudKey set=$([bool]$ac.CloudAccessKey) Bucket=$($ac.CloudBucketName) pins=$($ac.Pins.Count)"
    foreach ($kv in $ac.Pins.GetEnumerator()) { L "cached PIN $($kv.Key)=$([string]$kv.Value)" }

    # If BiOS2 already on login screen, sync LoginPhrase from GetLoginUrl decrypt path
    $loginUrl = $acType.GetMethod('GetLoginUrl').Invoke($ac, @())
    L "GetLoginUrl len=$($loginUrl.Length)"

    # Brute: try Validate on cached pins + SendKeys first pin that validates
    $validated = $false
    $usePin = $null
    foreach ($kv in $ac.Pins.GetEnumerator()) {
        $p = ([string]$kv.Value).Trim()
        if ([string]::IsNullOrWhiteSpace($p)) { continue }
        $ok = $acType.GetMethod('Validate').Invoke($ac, @($p))
        L "Validate cached $($kv.Key) pin=$p -> $ok"
        if ($ok -and [string]$kv.Key -eq $Role) { $usePin = $p; $validated = $true; break }
    }

    if (-not $validated) {
        L 'No cached valid PIN - cannot auto login without fresh S3 pin fetch or QR decode'
        exit 2
    }

    L "Using PIN for SendKeys"
    Add-Type @"
using System.Runtime.InteropServices;
public class FG { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h); }
"@
    [void][FG]::SetForegroundWindow($bios.MainWindowHandle)
    Start-Sleep -Milliseconds 400
    foreach ($ch in $usePin.ToCharArray()) {
        [Windows.Forms.SendKeys]::SendWait($ch)
        Start-Sleep -Milliseconds 100
    }
    [Windows.Forms.SendKeys]::SendWait('{ENTER}')
    L 'SendKeys done'
    Start-Sleep -Seconds 4
    if (Test-Path 'G:\bios\License\Session.lic') { L 'SUCCESS Session.lic'; exit 0 }
    L 'No Session.lic yet'
    exit 1
}
catch {
    L "ERR $($_.Exception.Message)"
    exit 1
}
