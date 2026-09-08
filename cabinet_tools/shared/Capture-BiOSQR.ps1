#Requires -Version 5.1
<#
  Capture BiOS2 login QR from session-1 desktop and decode payload.
  Output: C:\Platform\Security\bios-qr.txt and bios-qr.png
#>
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$outPng = 'C:\Platform\Security\bios-qr.png'
$outTxt = 'C:\Platform\Security\bios-qr.txt'
$log = 'C:\Platform\Security\bios-qr-capture.log'

function Write-Log([string]$m) {
    Add-Content -LiteralPath $log -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $m" -Encoding ASCII
}

try {
    Write-Log 'start capture'
    $proc = Get-Process BiOS2 -ErrorAction Stop | Select-Object -First 1
    Write-Log "BiOS2 pid=$($proc.Id)"

    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

    [void][Win32]::SetForegroundWindow($proc.MainWindowHandle)
    Start-Sleep -Milliseconds 400

    $r = New-Object Win32+RECT
    [void][Win32]::GetWindowRect($proc.MainWindowHandle, [ref]$r)
    $w = $r.Right - $r.Left
    $h = $r.Bottom - $r.Top
    Write-Log "window ${w}x${h} at $($r.Left),$($r.Top)"

    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, [System.Drawing.Size]::new($w, $h))
    $g.Dispose()
    $bmp.Save($outPng, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Log "saved $outPng"
}
catch {
    Write-Log "ERROR $($_.Exception.Message)"
    exit 1
}

exit 0
