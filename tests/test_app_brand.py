from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config_scanner.app_brand import program_title
from config_scanner.build_stamp_write import (
    current_build_stamp,
    clear_build_stamp,
    write_build_stamp,
)

_REPO = Path(__file__).resolve().parents[1]


def test_committed_build_stamp_is_empty() -> None:
    text = (_REPO / "config_scanner" / "_build_stamp.py").read_text(encoding="utf-8")
    assert re.search(r"^BUILD_STAMP = [\"'][\"']\s*$", text, re.MULTILINE)
    assert not re.search(r"BUILD_STAMP = ['\"]20\d{2}-", text)


def test_build_exe_writes_stamp_via_now() -> None:
    src = (_REPO / "build_exe.ps1").read_text(encoding="utf-8")
    writer = (_REPO / "config_scanner" / "build_stamp_write.py").read_text(
        encoding="utf-8"
    )
    spec = (_REPO / "ConfigScanner.spec").read_text(encoding="utf-8")
    assert "config_scanner.build_stamp_write" in src
    assert "datetime.now()" in writer
    assert "%Y-%m-%d %H:%M" in writer
    assert "--clear" in src
    assert "write_build_stamp" in spec


def test_current_build_stamp_is_this_minute() -> None:
    allowed = {datetime.now().strftime("%Y-%m-%d %H:%M")}
    stamp = current_build_stamp()
    allowed.add(datetime.now().strftime("%Y-%m-%d %H:%M"))
    assert stamp in allowed


def test_write_build_stamp_uses_exact_given_minute(tmp_path: Path) -> None:
    dest = tmp_path / "_build_stamp.py"
    when = datetime(2026, 9, 10, 14, 51)
    assert write_build_stamp(now=when, dest=dest) == "2026-09-10 14:51"
    text = dest.read_text(encoding="utf-8")
    assert "2026-09-10 14:51" in text
    assert "BUILD_STAMP =" in text
    clear_build_stamp(dest=dest)
    cleared = dest.read_text(encoding="utf-8")
    assert 'BUILD_STAMP = ""' in cleared
    assert "2026-09-10 14:51" not in cleared


def test_program_title_appends_stamp(monkeypatch) -> None:
    import config_scanner.app_brand as brand

    monkeypatch.setattr(brand, "build_stamp_text", lambda: "2026-09-04 11:48")
    assert program_title() == "Config Scanner  2026-09-04 11:48"
    assert program_title("Snapshots") == "Config Scanner — Snapshots  2026-09-04 11:48"
    assert program_title("Restore settings") == (
        "Config Scanner — Restore settings  2026-09-04 11:48"
    )


def test_source_run_ignores_stale_baked_stamp(monkeypatch) -> None:
    import config_scanner.app_brand as brand

    class _Stamp:
        BUILD_STAMP = "2026-09-10 13:30"

    monkeypatch.setattr(brand, "sys", type("S", (), {"frozen": False, "executable": ""})())
    monkeypatch.setitem(__import__("sys").modules, "config_scanner._build_stamp", _Stamp)
    assert brand.build_stamp_text() == "dev"


def test_build_stamp_prefers_baked_value_when_frozen(monkeypatch) -> None:
    import config_scanner.app_brand as brand

    class _Stamp:
        BUILD_STAMP = "2026-09-04 10:39"

    monkeypatch.setattr(brand, "sys", type("S", (), {"frozen": True, "executable": ""})())
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
