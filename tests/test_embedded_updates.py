"""Tests for embedded GameStar country updates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config_scanner.embedded_updates import (
    EmbeddedUpdate,
    load_catalog,
    materialize_country_tool,
    write_catalog,
)


def test_load_catalog_from_assets() -> None:
    entries = load_catalog()
    assert len(entries) >= 1
    ids = {e.id for e in entries}
    assert "CS-Gamestar-TT-00" in ids
    assert "CS-Gamestar-PR-03" in ids
    assert "CS-Gamestar-PR-06" in ids
    assert "CS-Gamestar-PR-06_SAS" in ids
    assert "CS-Gamestar-PANC-01" in ids
    assert "CS-Gamestar-PER-00" in ids
    assert "CS-Gamestar-SA-00" in ids
    assert "CS-Gamestar-TRI-00" in ids


def test_materialize_staged_sa00_and_pr06() -> None:
    entries = load_catalog()
    sa = next(e for e in entries if e.id == "CS-Gamestar-SA-00")
    tool = materialize_country_tool(sa)
    assert (tool / "data" / "South Africa 94").is_dir()
    assert any(tool.rglob("install.json"))
    pr = next(e for e in entries if e.id == "CS-Gamestar-PR-06")
    pr_tool = materialize_country_tool(pr)
    assert (pr_tool / "data" / "PuertoRico 94").is_dir()
    assert any(pr_tool.rglob("install.json"))


def test_embedded_updates_root_prefers_beside_exe_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config_scanner import embedded_updates as mod

    install = tmp_path / "install"
    install.mkdir()
    beside = install / "embedded_updates"
    beside.mkdir()
    (beside / "catalog.json").write_text('{"version":1,"updates":[]}', encoding="utf-8")
    fake_exe = install / "ConfigScanner.exe"
    fake_exe.write_bytes(b"MZ")
    monkeypatch.setattr(mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(mod.sys, "executable", str(fake_exe), raising=False)
    assert mod.embedded_updates_root() == beside


def test_materialize_staged_tt00() -> None:
    entries = load_catalog()
    tt = next(e for e in entries if e.id == "CS-Gamestar-TT-00")
    tool = materialize_country_tool(tt)
    assert (tool / "data").is_dir()
    assert any(tool.rglob("install.json"))


def test_write_catalog_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    entries = [
        EmbeddedUpdate(
            id="test-pkg",
            label="Test",
            country="T",
            gamestar_version="1",
            b2u_file="test.b2u",
            staged_id="test-pkg",
        )
    ]
    write_catalog(entries, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["updates"][0]["id"] == "test-pkg"
