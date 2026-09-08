#Requires -Version 5.1
$log = 'C:\Platform\Security\bios-probe2.log'
Remove-Item $log -Force -EA SilentlyContinue
function L($m) { Add-Content $log "[$(Get-Date -Format HH:mm:ss.fff)] $m" -Encoding ASCII }
L '=== processes ==='
Get-Process BiOS2,OneHand,Bootstrap,Godot* -EA SilentlyContinue | ForEach-Object {
    L "$($_.ProcessName) pid=$($_.Id) sess=$($_.SessionId) hwnd=$($_.MainWindowHandle) title=$($_.MainWindowTitle)"
}
Add-Type @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public class EnumWin2 {
  public delegate bool CB(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(CB cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int c);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder sb, int c);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public static List<string> Lines = new List<string>();
  public static bool Handler(IntPtr h, IntPtr l) {
    uint pid; GetWindowThreadProcessId(h, out pid);
    var sb = new StringBuilder(256);
    GetWindowText(h, sb, 256); var t = sb.ToString();
    GetClassName(h, sb, 256); var c = sb.ToString();
    if (IsWindowVisible(h)) { Lines.Add("pid="+pid+" cls="+c+" title="+t+" hwnd="+h); }
    return true;
  }
}
'@
[EnumWin2]::Lines.Clear()
[EnumWin2]::EnumWindows([EnumWin2+CB]::CreateDelegate([EnumWin2+CB], [type]'EnumWin2', 'Handler'), [IntPtr]::Zero)
L '=== visible windows ==='
[EnumWin2]::Lines | ForEach-Object { L $_ }
Set-Location 'G:\BiOS'
foreach ($dll in @('LicenseValidator.dll')) { if (Test-Path $dll) { [void][Reflection.Assembly]::LoadFrom((Resolve-Path $dll).Path) } }
$asm = [Reflection.Assembly]::LoadFrom('G:\BiOS\BiOS2.exe')
$svType = $asm.GetType('BiOS2.Model.SessionValidatorDLL')
L '=== SessionValidatorDLL methods ==='
$svType.GetMethods([Reflection.BindingFlags]'Public,Static,Instance,NonPublic') |
    Where-Object { $_.DeclaringType -eq $svType } |
    ForEach-Object {
        $p = ($_.GetParameters() | ForEach-Object { $_.ParameterType.Name + ' ' + $_.Name }) -join ', '
        L "  $($_.ReturnType.Name) $($_.Name)($p)"
    }
$roleType = $asm.GetType('BiOS2.Model.Role')
L "Role enum: $($roleType.GetEnumNames() -join ',')"
Get-Content $log
