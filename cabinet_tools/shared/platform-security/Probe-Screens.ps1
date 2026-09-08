# Read-only display probe. Must run in the INTERACTIVE session (session 1):
# WinRM lands in session 0, which has its own 1024x768 virtual desktop and cannot
# see the game's monitors or window placement.
#
# Writes a plain-text report next to itself so it can be read back over SMB.
#
# Must stay pure ASCII: no BOM, so PowerShell 5.1 reads it as ANSI.

[CmdletBinding()]
param(
    [string]$OutFile = 'C:\Platform\Security\screens-report.txt'
)

$ErrorActionPreference = 'Continue'
$lines = New-Object System.Collections.Generic.List[string]

function Add-Line {
    param([string]$Text)
    $lines.Add($Text)
}

Add-Line ("probe run {0} as {1} in session {2}" -f (Get-Date -Format o),
    [Security.Principal.WindowsIdentity]::GetCurrent().Name,
    (Get-Process -Id $PID).SessionId)
Add-Line ''

Add-Line '=== monitors attached to this desktop ==='
try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    foreach ($s in [System.Windows.Forms.Screen]::AllScreens) {
        Add-Line ("  {0,-16} primary={1,-5} bounds=({2},{3}) {4}x{5}" -f `
                $s.DeviceName, $s.Primary, $s.Bounds.X, $s.Bounds.Y,
            $s.Bounds.Width, $s.Bounds.Height)
    }
    $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
    Add-Line ("  virtual desktop: ({0},{1}) {2}x{3}" -f $vs.X, $vs.Y, $vs.Width, $vs.Height)
}
catch {
    Add-Line ("  FAILED: {0}" -f $_.Exception.Message)
}

Add-Line ''
Add-Line '=== display devices (adapter -> monitor attach state) ==='
$sig = @'
using System;
using System.Runtime.InteropServices;
public class Disp {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    public struct DISPLAY_DEVICE {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]  public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public int StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }
    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern bool EnumDisplayDevices(string dev, uint num, ref DISPLAY_DEVICE dd, uint flags);

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
'@
try {
    Add-Type -TypeDefinition $sig -ErrorAction Stop
}
catch {
    Add-Line ("  Add-Type failed: {0}" -f $_.Exception.Message)
}

if ('Disp' -as [type]) {
    $i = 0
    while ($true) {
        $dd = New-Object Disp+DISPLAY_DEVICE
        $dd.cb = [Runtime.InteropServices.Marshal]::SizeOf($dd)
        if (-not [Disp]::EnumDisplayDevices($null, $i, [ref]$dd, 0)) { break }
        # 0x1 = attached to desktop, 0x4 = primary
        $attached = [bool]($dd.StateFlags -band 0x1)
        $primary = [bool]($dd.StateFlags -band 0x4)
        Add-Line ("  {0,-14} attached={1,-5} primary={2,-5} '{3}'" -f `
                $dd.DeviceName, $attached, $primary, $dd.DeviceString.Trim())

        $mon = New-Object Disp+DISPLAY_DEVICE
        $mon.cb = [Runtime.InteropServices.Marshal]::SizeOf($mon)
        if ([Disp]::EnumDisplayDevices($dd.DeviceName, 0, [ref]$mon, 0)) {
            Add-Line ("                   monitor: '{0}'  id={1}" -f `
                    $mon.DeviceString.Trim(), $mon.DeviceID.Trim())
        }
        $i++
    }
}

Add-Line ''
Add-Line '=== visible top-level windows of the game processes ==='
if ('Disp' -as [type]) {
    $targets = @{}
    foreach ($p in (Get-Process -Name 'OneHand', 'Bootstrap', 'game-start' -ErrorAction SilentlyContinue)) {
        $targets[[uint32]$p.Id] = $p.ProcessName
    }
    $cb = [Disp+EnumProc] {
        param([IntPtr]$h, [IntPtr]$lp)
        $pid2 = [uint32]0
        [void][Disp]::GetWindowThreadProcessId($h, [ref]$pid2)
        if ($targets.ContainsKey($pid2)) {
            $r = New-Object Disp+RECT
            [void][Disp]::GetWindowRect($h, [ref]$r)
            $sb = New-Object System.Text.StringBuilder 256
            [void][Disp]::GetWindowText($h, $sb, $sb.Capacity)
            $vis = [Disp]::IsWindowVisible($h)
            $w = $r.Right - $r.Left
            $ht = $r.Bottom - $r.Top
            if ($w -gt 0 -and $ht -gt 0) {
                Add-Line ("  {0,-12} visible={1,-5} rect=({2},{3})-({4},{5})  {6}x{7}  '{8}'" -f `
                        $targets[$pid2], $vis, $r.Left, $r.Top, $r.Right, $r.Bottom, $w, $ht, $sb.ToString())
            }
        }
        return $true
    }
    [void][Disp]::EnumWindows($cb, [IntPtr]::Zero)
}

$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
[IO.File]::WriteAllText($OutFile, ($lines -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
$lines | ForEach-Object { Write-Host $_ }
