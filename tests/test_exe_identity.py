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
    assert "_collect_pyside6_qt_plugins" in text
    assert "qwindows.dll" in text


def test_gitignore_allows_downloads_configscanner_exe() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert "/ConfigScanner.exe" in lines
    assert "ConfigScanner.exe" not in lines
    assert "downloads/ConfigScanner.exe" not in lines


def test_shipped_download_exe_is_named_configscanner() -> None:
    exe = ROOT / "downloads" / "ConfigScanner.exe"
    exes = sorted(p.name for p in (ROOT / "downloads").glob("*.exe"))
    assert exes == ["ConfigScanner.exe"], exes
    data = exe.read_bytes()
    assert "ConfigScanner.exe".encode("utf-16-le") in data
    assert "OriginalFilename".encode("utf-16-le") in data
    assert b"CursorUserSetup" not in data
    assert "CursorUserSetup".encode("utf-16-le") not in data


def test_shipped_exe_embeds_qt_windows_platform_plugin() -> None:
    """Wine builds used to omit qwindows.dll → Qt fails on a real Windows box."""
    data = (ROOT / "downloads" / "ConfigScanner.exe").read_bytes()
    assert b"qwindows.dll" in data
    assert b"qwindows" in data
