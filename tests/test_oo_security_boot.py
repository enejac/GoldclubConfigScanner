"""Contract tests for GST22377 OO_Security boot sequence."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OO = ROOT / "cabinet_tools" / "shared" / "platform-security" / "OO_Security.ps1"
RETRY = ROOT / "cabinet_tools" / "shared" / "platform-security" / "Unlock-GoldClubRetry.ps1"


def test_oo_security_accepts_working_directory_param() -> None:
    src = OO.read_text(encoding="utf-8")
    assert "param(" in src
    assert "$WorkingDirectory" in src


def test_oo_security_never_probes_c_goldclub() -> None:
    src = OO.read_text(encoding="utf-8")
    # Comments may mention the junction; runtime must not Test-Path / start from it.
    for bad in (
        "Test-Path 'C:\\goldclub",
        'Test-Path "C:\\goldclub',
        "Test-Path C:\\goldclub",
        "Start-Process 'C:\\goldclub",
        'Start-Process "C:\\goldclub',
    ):
        assert bad not in src, bad


def test_oo_security_waits_for_unlocker() -> None:
    src = OO.read_text(encoding="utf-8")
    assert "Invoke-UnlockerDisk -Wait" in src
    assert "Unlock-GoldClubRetry.ps1" in src
    assert "Clear-RemovableLetterG" in src
    assert "Repair-GoldClubDriveLetter" in src
    # Must not define the old helper that stripped Fixed BitLocker G:.
    assert "function Protect-GoldClubLetter" not in src


def test_unlock_retry_helper_exists() -> None:
    src = RETRY.read_text(encoding="utf-8")
    assert "UnlockerDisk.exe" in src
    assert "unlock only" in src
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "onlogon.ps1" not in code
    assert "Start-Process -FilePath 'G:\\Bootstrap.exe'" not in code
