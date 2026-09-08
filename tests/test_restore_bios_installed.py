"""Tests for Restore-BiosInstalled.ps1 logic (staging paths, skip rules)."""

from __future__ import annotations

from pathlib import Path


def test_restore_script_exists() -> None:
    path = Path("cabinet_tools/shared/Restore-BiosInstalled.ps1")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "bios_Installed_restore" in text
    assert "MinB2pCount" in text
    assert "G:\\bios\\Installed" in text


def test_push_script_exists() -> None:
    path = Path("cabinet_tools/shared/Push-BiosInstalledRestore.ps1")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Restore-BiosInstalled.ps1" in text
    assert "bios_Installed_restore" in text
