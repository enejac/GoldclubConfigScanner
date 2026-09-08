"""Tests for BiOS2-style ConfigScanner update folder packing."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock

from config_scanner.b2u_pack import (
    build_egm_b2u_folder,
    build_tool_b2u_folder,
    encrypt_b2u,
    pack_egm_update,
    pack_tool_update,
)
from config_scanner.slot_setup import SlotSetupRecipe, save_recipe


def _fake_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "ConfigScanner.exe"
    exe.write_bytes(b"MZ fake-scanner")
    return exe


def test_launched_from_tool_b2u_detects_frozen_layout(
    tmp_path: Path, monkeypatch
) -> None:
    content = tmp_path / "Content"
    tmp_dir = content / "tmp"
    tmp_dir.mkdir(parents=True)
    exe = tmp_dir / "ConfigScanner.exe"
    exe.write_bytes(b"MZ")
    (content / "init.cmd").write_text("@echo off\n", encoding="ascii")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    from config_scanner.b2u_pack import launched_from_tool_b2u

    assert launched_from_tool_b2u() is True


def test_launched_from_tool_b2u_false_for_dev(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    from config_scanner.b2u_pack import launched_from_tool_b2u

    assert launched_from_tool_b2u() is False


def test_build_tool_b2u_folder(tmp_path: Path) -> None:
    exe = _fake_exe(tmp_path)
    package = build_tool_b2u_folder(tmp_path / "out", exe_path=exe)
    assert (package / "package.xml").is_file()
    assert (package / "Meta" / "package.xml").is_file()
    init = (package / "Content" / "init.cmd").read_text(encoding="ascii")
    assert "ConfigScanner.exe" in init
    assert "--snapshots" in init
    assert "--apply-pack" not in init
    staged = package / "Content" / "tmp" / "ConfigScanner.exe"
    assert staged.read_bytes().startswith(b"MZ")


def test_build_egm_b2u_folder(tmp_path: Path) -> None:
    exe = _fake_exe(tmp_path)
    pack = tmp_path / "config-pack"
    pack.mkdir()
    save_recipe(SlotSetupRecipe(label="field", bill_protocol="MEI"), pack / "recipe.json")
    (pack / "slot" / "hwdrivers").mkdir(parents=True)
    (pack / "slot" / "hwdrivers" / "Keyboard.xml").write_text("<config/>", encoding="utf-8")

    package = build_egm_b2u_folder(
        tmp_path / "out", pack, exe_path=exe, package_name="ConfigScanner_EGM_Test"
    )
    assert (package / "Content" / "tmp" / "ConfigScanner.exe").is_file()
    assert (package / "Content" / "tmp" / "config-pack" / "recipe.json").is_file()
    assert (
        package / "Content" / "tmp" / "config-pack" / "slot" / "hwdrivers" / "Keyboard.xml"
    ).is_file()
    init = (package / "Content" / "init.cmd").read_text(encoding="ascii")
    assert "--apply-pack" in init
    assert "config-pack" in init


def test_pack_tool_update_skips_encrypt_without_generator(
    tmp_path: Path, monkeypatch
) -> None:
    exe = _fake_exe(tmp_path)
    monkeypatch.setattr(
        "config_scanner.b2u_pack.default_package_generator", lambda: None
    )
    result = pack_tool_update(tmp_path / "dist", exe_path=exe, encrypt=True)
    assert result.b2u_path is None
    assert result.package_dir.is_dir()
    assert "skipped" in result.note.casefold() or "missing" in result.note.casefold()


def test_pack_egm_update_without_encrypt(tmp_path: Path) -> None:
    exe = _fake_exe(tmp_path)
    pack = tmp_path / "config-pack"
    pack.mkdir()
    save_recipe(SlotSetupRecipe(label="x"), pack / "recipe.json")
    result = pack_egm_update(
        tmp_path / "dist", pack, exe_path=exe, package_name="EGM_X", encrypt=False
    )
    assert result.b2u_path is None
    assert (result.package_dir / "Content" / "tmp" / "config-pack" / "recipe.json").is_file()


def test_encrypt_b2u_moves_file_from_generator_output_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """PackageGenerator writes into a directory; we flatten to the target file."""
    package = tmp_path / "ConfigScanner_Tool"
    package.mkdir()
    (package / "package.xml").write_text("<package/>", encoding="utf-8")
    fake_gen = tmp_path / "BiOS2_PackageGenerator.exe"
    fake_gen.write_bytes(b"MZ")

    def fake_run(cmd, capture_output=True, text=True, check=False, **kwargs):  # noqa: ANN001
        out = Path(cmd[cmd.index("--outputPath") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "ConfigScanner_Tool.b2u").write_bytes(b"encrypted-b2u")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("config_scanner.b2u_pack.subprocess.run", fake_run)
    (fake_gen.parent / "log4net.dll").write_bytes(b"x")
    (fake_gen.parent / "ICSharpCode.SharpZipLib.dll").write_bytes(b"x")
    dest = tmp_path / "out" / "ConfigScanner_Tool.b2u"
    result = encrypt_b2u(package, dest, generator=fake_gen)
    assert result == dest
    assert dest.is_file()
    assert dest.read_bytes() == b"encrypted-b2u"
    assert not (tmp_path / "out" / ".b2u_stage_ConfigScanner_Tool").exists()
