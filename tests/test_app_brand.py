from __future__ import annotations

from datetime import datetime
from pathlib import Path

from config_scanner.app_brand import build_stamp_text, program_title


def test_build_exe_writes_stamp() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "build_exe.ps1"
    ).read_text(encoding="utf-8")
    assert "config_scanner/_build_stamp.py" in src
    assert "%Y-%m-%d %H:%M" in src


def test_program_title_appends_stamp(monkeypatch) -> None:
    import config_scanner.app_brand as brand

    monkeypatch.setattr(brand, "build_stamp_text", lambda: "2026-09-04 11:48")
    assert program_title() == "Config Scanner  2026-09-04 11:48"
    assert program_title("Snapshots") == "Config Scanner — Snapshots  2026-09-04 11:48"
    assert program_title("Restore settings") == (
        "Config Scanner — Restore settings  2026-09-04 11:48"
    )


def test_build_stamp_prefers_baked_value(monkeypatch) -> None:
    import config_scanner.app_brand as brand

    class _Stamp:
        BUILD_STAMP = "2026-09-04 10:39"

    monkeypatch.setattr(brand, "sys", type("S", (), {"frozen": False, "executable": ""})())
    monkeypatch.setitem(__import__("sys").modules, "config_scanner._build_stamp", _Stamp)
    assert brand.build_stamp_text() == "2026-09-04 10:39"


def test_build_stamp_source_is_dev_when_unbaked(monkeypatch) -> None:
    import config_scanner.app_brand as brand

    class _Stamp:
        BUILD_STAMP = ""

    monkeypatch.setattr(brand, "sys", type("S", (), {"frozen": False, "executable": ""})())
    monkeypatch.setitem(__import__("sys").modules, "config_scanner._build_stamp", _Stamp)
    assert brand.build_stamp_text() == "dev"


def test_build_stamp_frozen_uses_exe_mtime(monkeypatch, tmp_path) -> None:
    import config_scanner.app_brand as brand

    class _Stamp:
        BUILD_STAMP = ""

    exe = tmp_path / "ConfigScanner.exe"
    exe.write_bytes(b"x")
    stamp = datetime(2026, 9, 4, 11, 48)
    exe.touch()
    import os

    os.utime(exe, (stamp.timestamp(), stamp.timestamp()))
    monkeypatch.setattr(
        brand,
        "sys",
        type("S", (), {"frozen": True, "executable": str(exe)})(),
    )
    monkeypatch.setitem(__import__("sys").modules, "config_scanner._build_stamp", _Stamp)
    assert brand.build_stamp_text() == "2026-09-04 11:48"
