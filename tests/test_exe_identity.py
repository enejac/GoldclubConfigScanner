"""Shipped Windows exe must be named ConfigScanner, not a leftover download name."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_info_original_filename_is_configscanner() -> None:
    text = (ROOT / "file_version_info.txt").read_text(encoding="utf-8")
    assert 'StringStruct("OriginalFilename", "ConfigScanner.exe")' in text
    assert 'StringStruct("ProductName", "Config Scanner")' in text
    assert 'StringStruct("InternalName", "ConfigScanner")' in text
    assert "CursorUserSetup" not in text
    assert "Launch-Config" not in text


def test_spec_embeds_version_info_and_name() -> None:
    text = (ROOT / "ConfigScanner.spec").read_text(encoding="utf-8")
    assert 'name="ConfigScanner"' in text
    assert 'version="file_version_info.txt"' in text


def test_gitignore_allows_downloads_configscanner_exe() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert "/ConfigScanner.exe" in lines
    assert "ConfigScanner.exe" not in lines
    assert "downloads/ConfigScanner.exe" not in lines


def test_shipped_download_exe_is_named_configscanner() -> None:
    exes = sorted(p.name for p in (ROOT / "downloads").glob("*.exe"))
    assert exes == ["ConfigScanner.exe"], exes
