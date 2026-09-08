using System;
using System.Diagnostics;
using System.IO;

internal static class Program
{
    private static int Main()
    {
        string dir = Path.GetDirectoryName(Process.GetCurrentProcess().MainModule.FileName);
        string ps1 = Path.Combine(dir, "Start-SlotGameWatch.ps1");
        if (!File.Exists(ps1))
        {
            string fallback = Path.Combine(dir, "game-start.exe");
            if (!File.Exists(fallback))
            {
                return 1;
            }
            Process p = Process.Start(new ProcessStartInfo
            {
                FileName = fallback,
                WorkingDirectory = dir,
                UseShellExecute = false
            });
            if (p == null)
            {
                return 1;
            }
            p.WaitForExit();
            return p.ExitCode;
        }

        Process watch = Process.Start(new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + ps1 + "\"",
            UseShellExecute = false,
            CreateNoWindow = true
        });
        if (watch == null)
        {
            return 1;
        }
        watch.WaitForExit();
        return watch.ExitCode;
    }
}
