"""Contract tests for ConfigScanner licence restore + hardware start scripts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "cabinet_tools" / "shared" / "Apply-CsRestore.ps1"
HW = ROOT / "cabinet_tools" / "shared" / "Start-GoldClubHardware.ps1"
DESK = ROOT / "cabinet_tools" / "shared" / "Start-LabDesktop.ps1"


def test_apply_cs_restore_copies_licence_not_serialport() -> None:
    text = APPLY.read_text(encoding="utf-8")
    assert "licence.dll" in text
    assert "Licenses" in text
    assert "01D68A721B000019" in text
    assert "HardwareConfig.xml" in text
    assert "layout.json" not in text
    assert "locations.json" not in text
    assert "DriveInfo" in text
    assert "Bootstrap.exe" in text
    assert "cs_restore.applied" in text
    assert "keep live" in text
    assert "Copy-IfMissing" in text
    assert "SKIP already applied" in text
    assert "will not overwrite accepted licence" in text
    assert "[switch]$Force" in text
    assert "Session.lic" in text
    assert "SKIP bios License.lic" in text
    assert "accept-only bind files" in text


def test_start_hardware_does_not_write_licence() -> None:
    text = HW.read_text(encoding="utf-8")
    assert "GoldClub Hardware Subsystem" in text
    assert "hwsubsys.exe" in text
    assert "GoldClub.Aurum.Services" in text
    assert "CommCtrl" in text
    assert "slot\\licence.dll" not in text
    assert "Licenses" not in text
    assert "layout.json" not in text
    assert "G:\\Services" in text
    assert "G: ready after" in text


def test_start_lab_desktop_share_tv_tc_no_goldclub_probe() -> None:
    text = DESK.read_text(encoding="utf-8")
    assert "net share slot=G:\\" in text
    assert "TeamViewer" in text
    assert "TOTALCMD64" in text
    assert "skip second instance" in text
    assert "[IO.DriveInfo]::GetDrives()" in text
    assert "IsReady" in text
    assert "C:\\goldclub" not in text
    assert "Enable-PSRemoting" not in text
    assert "layout.json" not in text
    assert "licence.dll" not in text
    assert "LanmanServer" in text
    assert "netsh advfirewall" in text
    assert "GoldClub-TeamViewer-Start" in text
    assert "GoldClub-TotalCommander-USB" in text
    assert "Launch-LabUsbTool.ps1" in text
    assert "task already registered" in text
    assert "[switch]$PollForUsb" in text
    assert "MinDelaySeconds" in text
    assert "MinDelaySeconds: waiting" in text
    assert "PollForUsb: scanning up to 90s" in text
    assert "Start-LabDesktop skipped - no lab USB" in text
    assert "_share.bat" in text
