#!/usr/bin/env python3
"""Orchestrate BiOS2 QR login on lab cabinet 10.0.0.111."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECODE = REPO / "config_scanner" / "bios_qr_decode.py"
CABINET_IP = "10.0.0.111"


def run_ps(script: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=CABINET_IP)
    parser.add_argument("--role", default="Service")
    parser.add_argument("--pin", help="Override PIN if S3 fetch unavailable")
    args = parser.parse_args()

    ip = args.ip
    lab = REPO / "LabAccess.ps1"
    deploy = (
        f"Copy-Item -Force '{REPO / 'cabinet_tools/shared/Invoke-BiOSQrLogin.ps1'}' "
        f"'\\\\{ip}\\c$\\Platform\\Security\\Invoke-BiOSQrLogin.ps1'; "
        f". '{lab}'; "
        f"Invoke-LabWinRmCommand -ComputerName {ip} -ScriptBlock {{ "
        f"schtasks /Create /TN GoldClub-BiOSQrLogin /TR "
        f"\"powershell.exe -NoProfile -Sta -ExecutionPolicy Bypass -File C:\\Platform\\Security\\Invoke-BiOSQrLogin.ps1 -Role {args.role}\" "
        f"/SC ONCE /ST 23:59 /RU goldclub /IT /F | Out-Null; "
        f"schtasks /Run /TN GoldClub-BiOSQrLogin | Out-Null "
        f"}}"
    )
    r = run_ps(deploy)
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        return r.returncode

    time.sleep(18)
    fetch_log = run_ps(
        f". '{lab}'; Invoke-LabWinRmCommand -ComputerName {ip} -ScriptBlock {{ "
        f"Get-Content C:\\Platform\\Security\\bios-auto-login.log -EA SilentlyContinue; "
        f"Test-Path G:\\bios\\License\\Session.lic "
        f"}}"
    )
    print(fetch_log.stdout)
    if "SUCCESS" in fetch_log.stdout:
        return 0

    if args.pin:
        send = run_ps(
            f". '{lab}'; Invoke-LabWinRmCommand -ComputerName {ip} -ScriptBlock {{ "
            f"$pin='{args.pin}'; "
            f"Add-Type -AssemblyName System.Windows.Forms; "
            f"$b=Get-Process BiOS2|Select -First 1; "
            f"Add-Type 'using System.Runtime.InteropServices; public class F {{ [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(System.IntPtr h); }}'; "
            f"[F]::SetForegroundWindow($b.MainWindowHandle)|Out-Null; Start-Sleep -Milliseconds 500; "
            f"foreach($c in $pin.ToCharArray()){{ [SendKeys]::SendWait($c); Start-Sleep -m 100 }}; "
            f"[SendKeys]::SendWait('{{ENTER}}'); "
            f"Start-Sleep 4; Test-Path G:\\bios\\License\\Session.lic "
            f"}}"
        )
        print(send.stdout)
        return 0 if "True" in send.stdout else 1

    # decode QR from crop for operator
    pull = run_ps(
        f"Copy-Item -Force '\\\\{ip}\\c$\\Platform\\Security\\bios-qr-crop.png' "
        f"'{REPO / 'cabinet_tools/shared/bios-qr-crop.png'}' -EA SilentlyContinue"
    )
    crop = REPO / "cabinet_tools/shared/bios-qr-crop.png"
    if crop.is_file():
        dec = subprocess.run(
            [sys.executable, str(DECODE), str(crop)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        print(dec.stdout)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
