#Requires -Version 5.1
param(
    [string]$LoginPin = '449166',
    [string]$LogPath = 'C:\Platform\Security\bios-auto-login.log'
)
function L([string]$m) { Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'HH:mm:ss.fff')] $m" -Encoding ASCII }
Remove-Item $LogPath -Force -EA SilentlyContinue
L "START pin=$LoginPin BM_CLICK"
Add-Type @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public class BiOSUi {
  public const uint BM_CLICK = 0x00F5;
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumWindowsProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int c);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder sb, int c);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  public static IntPtr Root = IntPtr.Zero;
  public static uint Pid;
  public static Dictionary<string, IntPtr> Buttons = new Dictionary<string, IntPtr>();
  public static bool FindRoot(IntPtr h, IntPtr l) {
    uint pid; GetWindowThreadProcessId(h, out pid);
    if (pid != Pid || !IsWindowVisible(h)) return true;
    var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
    if (sb.ToString() == "Access control") { Root = h; return false; }
    return true;
  }
  public static bool CollectBtn(IntPtr h, IntPtr l) {
    if (!IsWindowVisible(h)) return true;
    var sb = new StringBuilder(64); GetWindowText(h, sb, 64);
    var t = sb.ToString().Trim();
    if (t.Length > 0) Buttons[t] = h;
    return true;
  }
  public static void ClickBtn(string label) {
    IntPtr h; if (!Buttons.TryGetValue(label, out h)) return;
    SendMessage(h, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
    System.Threading.Thread.Sleep(300);
  }
}
'@
$bios = Get-Process BiOS2 -ErrorAction Stop | Select-Object -First 1
[BiOSUi]::Pid = [uint32]$bios.Id
[BiOSUi]::Root = [IntPtr]::Zero
[BiOSUi]::EnumWindows([BiOSUi+EnumWindowsProc]::CreateDelegate([BiOSUi+EnumWindowsProc], [type]'BiOSUi', 'FindRoot'), [IntPtr]::Zero)
if ([BiOSUi]::Root -eq [IntPtr]::Zero) { L 'no Access control root'; exit 1 }
[void][BiOSUi]::SetForegroundWindow([BiOSUi]::Root)
Start-Sleep -Milliseconds 500
[BiOSUi]::Buttons.Clear()
[BiOSUi]::EnumChildWindows([BiOSUi]::Root, [BiOSUi+EnumWindowsProc]::CreateDelegate([BiOSUi+EnumWindowsProc], [type]'BiOSUi', 'CollectBtn'), [IntPtr]::Zero)
L "buttons=$([BiOSUi]::Buttons.Count)"
foreach ($k in ([BiOSUi]::Buttons.Keys | Sort-Object)) { L "  btn [$k]" }
if ([BiOSUi]::Buttons.ContainsKey('CLEAR')) {
    L 'BM_CLICK CLEAR'
    [BiOSUi]::ClickBtn('CLEAR')
    Start-Sleep -Milliseconds 400
}
foreach ($ch in $LoginPin.ToCharArray()) {
    $label = [string]$ch
    if ([BiOSUi]::Buttons.ContainsKey($label)) {
        L "BM_CLICK $label"
        [BiOSUi]::ClickBtn($label)
    } else {
        L "missing btn $label"
    }
}
foreach ($enter in @('ENTER', 'Enter', 'OK')) {
    if ([BiOSUi]::Buttons.ContainsKey($enter)) {
        L "BM_CLICK $enter"
        [BiOSUi]::ClickBtn($enter)
        break
    }
}
Start-Sleep -Seconds 6
if (Test-Path 'G:\bios\License\Session.lic') {
    L 'SUCCESS'
    exit 0
}
L 'FAILED'
exit 1
