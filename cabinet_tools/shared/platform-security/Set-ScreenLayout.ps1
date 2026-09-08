# Arrange the cabinet monitors as a vertical stack with the primary at the bottom.
#
# OneHand renders one tall window (OneHand.exe.config: width=1920, height=1080,
# starty=-2160) that spans every panel above the primary. If Windows instead
# extends the desktop sideways -- its default after the panels re-enumerate --
# the upper two thirds of that window fall outside the desktop and the extra
# panels stay black.
#
# Must run in the INTERACTIVE session (session 1). A WinRM call lands in
# session 0, whose desktop has no physical monitors.
#
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    # Non-primary devices bottom-to-top, e.g. 'DISPLAY2,DISPLAY3' puts DISPLAY2
    # directly above the primary and DISPLAY3 at the top. Defaults to the order
    # Windows enumerates them in.
    [string]$Order,

    [int]$PanelHeight = 1080,

    [switch]$DryRun,

    [string]$OutFile = 'C:\Platform\Security\screen-layout-report.txt'
)

$ErrorActionPreference = 'Stop'
$lines = New-Object System.Collections.Generic.List[string]
function Add-Line { param([string]$Text) $lines.Add($Text); Write-Host $Text }

try {

$sig = @'
using System;
using System.Runtime.InteropServices;

public class ScreenLayout {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    public struct DISPLAY_DEVICE {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]  public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public int StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int   dmFields;
        public int   dmPositionX;
        public int   dmPositionY;
        public int   dmDisplayOrientation;
        public int   dmDisplayFixedOutput;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels;
        public int   dmBitsPerPel;
        public int   dmPelsWidth;
        public int   dmPelsHeight;
        public int   dmDisplayFlags;
        public int   dmDisplayFrequency;
        public int   dmICMMethod;
        public int   dmICMIntent;
        public int   dmMediaType;
        public int   dmDitherType;
        public int   dmReserved1;
        public int   dmReserved2;
        public int   dmPanningWidth;
        public int   dmPanningHeight;
    }

    public const int  ENUM_CURRENT_SETTINGS = -1;
    public const int  DM_POSITION           = 0x00000020;
    public const uint CDS_UPDATEREGISTRY    = 0x00000001;
    public const uint CDS_NORESET           = 0x10000000;
    public const int  DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1;
    public const int  DISPLAY_DEVICE_PRIMARY_DEVICE      = 0x4;

    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern bool EnumDisplayDevices(string dev, uint num, ref DISPLAY_DEVICE dd, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern bool EnumDisplaySettings(string dev, int mode, ref DEVMODE dm);

    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern int ChangeDisplaySettingsEx(string dev, ref DEVMODE dm, IntPtr wnd, uint flags, IntPtr param);

    [DllImport("user32.dll")]
    public static extern int ChangeDisplaySettingsEx(IntPtr dev, IntPtr dm, IntPtr wnd, uint flags, IntPtr param);
}
'@
Add-Type -TypeDefinition $sig

Add-Type -AssemblyName System.Windows.Forms

function Get-AttachedDisplay {
    # EnumDisplayDevices returns nothing for the goldclub shell token on this
    # cabinet, so read the desktop through Screen.AllScreens, which does work
    # there. ChangeDisplaySettingsEx only needs the \\.\DISPLAYn name.
    $result = @()
    foreach ($screen in [System.Windows.Forms.Screen]::AllScreens) {
        $result += [pscustomobject]@{
            Name    = $screen.DeviceName
            Primary = [bool]$screen.Primary
            X       = $screen.Bounds.X
            Y       = $screen.Bounds.Y
            Width   = $screen.Bounds.Width
            Height  = $screen.Bounds.Height
        }
    }
    return $result
}

Add-Line ("Set-ScreenLayout {0} as {1} (session {2})" -f (Get-Date -Format o),
    [Security.Principal.WindowsIdentity]::GetCurrent().Name, (Get-Process -Id $PID).SessionId)

$displays = @(Get-AttachedDisplay)
Add-Line ''
Add-Line 'before:'
foreach ($d in $displays) {
    Add-Line ("  {0,-14} primary={1,-5} {2}x{3} at ({4},{5})" -f $d.Name, $d.Primary, $d.Width, $d.Height, $d.X, $d.Y)
}

$primary = $displays | Where-Object { $_.Primary } | Select-Object -First 1
if (-not $primary) { throw 'no primary display found' }

$others = @($displays | Where-Object { -not $_.Primary })
if ($Order) {
    $wanted = $Order.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $sorted = @()
    foreach ($w in $wanted) {
        $match = $others | Where-Object { $_.Name -like "*$w*" } | Select-Object -First 1
        if (-not $match) { throw "device '$w' is not an attached non-primary display" }
        $sorted += $match
    }
    foreach ($o in $others) {
        if ($sorted -notcontains $o) { $sorted += $o }
    }
    $others = $sorted
}

# Primary anchors the desktop at (0,0); the rest stack upwards in $others order.
$targets = @{ $primary.Name = @(0, 0) }
$y = 0
foreach ($o in $others) {
    $y -= $PanelHeight
    $targets[$o.Name] = @(0, $y)
}

Add-Line ''
Add-Line 'target layout:'
foreach ($d in $displays) {
    $t = $targets[$d.Name]
    $note = if ($d.X -eq $t[0] -and $d.Y -eq $t[1]) { 'unchanged' } else { ("was ({0},{1})" -f $d.X, $d.Y) }
    Add-Line ("  {0,-14} -> ({1},{2})   {3}" -f $d.Name, $t[0], $t[1], $note)
}

if ($DryRun) {
    Add-Line ''
    Add-Line 'DryRun: nothing applied.'
}
else {
    Add-Line ''
    Add-Line 'applying...'
    # Stage every device with CDS_NORESET, then commit once so the desktop is
    # never transiently non-contiguous (Windows rejects that).
    foreach ($d in $displays) {
        $t = $targets[$d.Name]
        $dm = New-Object ScreenLayout+DEVMODE
        $dm.dmSize = [int16][Runtime.InteropServices.Marshal]::SizeOf([type][ScreenLayout+DEVMODE])
        if (-not [ScreenLayout]::EnumDisplaySettings($d.Name, [ScreenLayout]::ENUM_CURRENT_SETTINGS, [ref]$dm)) {
            throw "EnumDisplaySettings failed for $($d.Name)"
        }
        $dm.dmFields = $dm.dmFields -bor [ScreenLayout]::DM_POSITION
        $dm.dmPositionX = $t[0]
        $dm.dmPositionY = $t[1]
        $flags = [ScreenLayout]::CDS_UPDATEREGISTRY -bor [ScreenLayout]::CDS_NORESET
        $rc = [ScreenLayout]::ChangeDisplaySettingsEx($d.Name, [ref]$dm, [IntPtr]::Zero, $flags, [IntPtr]::Zero)
        Add-Line ("  stage {0,-14} rc={1}" -f $d.Name, $rc)
        if ($rc -ne 0) { throw "staging $($d.Name) failed with $rc" }
    }
    $rc = [ScreenLayout]::ChangeDisplaySettingsEx([IntPtr]::Zero, [IntPtr]::Zero, [IntPtr]::Zero, 0, [IntPtr]::Zero)
    Add-Line ("  commit rc={0}  (0 = success)" -f $rc)
    if ($rc -ne 0) { throw "commit failed with $rc" }

    Start-Sleep -Seconds 3
    Add-Line ''
    Add-Line 'after:'
    foreach ($d in (Get-AttachedDisplay)) {
        Add-Line ("  {0,-14} primary={1,-5} {2}x{3} at ({4},{5})" -f $d.Name, $d.Primary, $d.Width, $d.Height, $d.X, $d.Y)
    }
}

}
catch {
    # The report is the only channel back to the operator: a scheduled task in
    # session 1 has nowhere to print, so never leave without writing it.
    Add-Line ''
    Add-Line ("FAILED: {0}" -f $_.Exception.Message)
    Add-Line ("at: {0}" -f $_.InvocationInfo.PositionMessage)
}

$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
[IO.File]::WriteAllText($OutFile, ($lines -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
