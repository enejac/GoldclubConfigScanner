"""Tests for PackageGenerator dependency checks and live CS export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config_scanner.b2u_pack import (
    default_package_generator,
    package_generator_ready,
    run_package_generator,
)
from config_scanner.live_cs_export import (
    OFFICIAL_CS_INIT_CMD,
    build_official_cs_package,
    export_full_country_selector,
    list_live_settings,
    overlay_live_onto_leaf,
    write_settings_report,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_package_generator_ready_requires_deps(tmp_path: Path) -> None:
    bare = tmp_path / "BiOS2_PackageGenerator.exe"
    bare.write_bytes(b"MZ")
    assert package_generator_ready(bare) is False
    (tmp_path / "log4net.dll").write_bytes(b"x")
    assert package_generator_ready(bare) is False
    (tmp_path / "ICSharpCode.SharpZipLib.dll").write_bytes(b"x")
    assert package_generator_ready(bare) is True


def test_default_package_generator_skips_bare_beside_exe(
    tmp_path: Path, monkeypatch
) -> None:
    bare = tmp_path / "BiOS2_PackageGenerator.exe"
    bare.write_bytes(b"MZ")
    good = tmp_path / "good"
    good.mkdir()
    (good / "BiOS2_PackageGenerator.exe").write_bytes(b"MZ")
    (good / "log4net.dll").write_bytes(b"x")
    (good / "ICSharpCode.SharpZipLib.dll").write_bytes(b"x")

    monkeypatch.setattr(
        "config_scanner.b2u_pack._package_generator_candidates",
        lambda: [bare, good / "BiOS2_PackageGenerator.exe"],
    )
    got = default_package_generator()
    assert got == good / "BiOS2_PackageGenerator.exe"


def test_run_package_generator_uses_cwd(tmp_path: Path, monkeypatch) -> None:
    gen = tmp_path / "BiOS2_PackageGenerator.exe"
    gen.write_bytes(b"MZ")
    (tmp_path / "log4net.dll").write_bytes(b"x")
    (tmp_path / "ICSharpCode.SharpZipLib.dll").write_bytes(b"x")
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        seen["cmd"] = cmd
        seen["cwd"] = kwargs.get("cwd")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("config_scanner.b2u_pack.subprocess.run", fake_run)
    proc = run_package_generator(["updateDecrypt", "--nowait"], generator=gen)
    assert proc.returncode == 0
    assert seen["cwd"] == str(tmp_path)
    assert seen["cmd"][0] == str(gen)


def test_overlay_live_onto_leaf(tmp_path: Path) -> None:
    leaf = tmp_path / "leaf"
    live = tmp_path / "goldclub"
    _write(leaf / "install.json", '{"Readme":"t","Delete":[],"Copy":[],"Data":[]}')
    _write(leaf / "slot" / "themes" / "mgconfig.xml", "<Multigamer><old/></Multigamer>")
    _write(
        live / "slot" / "themes" / "mgconfig.xml",
        "<Multigamer><TargetMarket>TT</TargetMarket></Multigamer>",
    )
    written = overlay_live_onto_leaf(leaf, live)
    assert "slot/themes/mgconfig.xml" in written
    assert "TT" in (leaf / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8")


def test_list_and_write_settings_report(tmp_path: Path) -> None:
    live = tmp_path / "goldclub"
    _write(
        live / "slot" / "themes" / "mgconfig.xml",
        "<Multigamer><TargetMarket>Jamaica</TargetMarket></Multigamer>",
    )
    rows = list_live_settings(live)
    assert isinstance(rows, list)
    report = write_settings_report(rows, tmp_path / "settings.json", goldclub=live)
    assert report.is_file()
    assert report.with_suffix(".txt").is_file()


def test_build_official_cs_package(tmp_path: Path, monkeypatch) -> None:
    crypt = tmp_path / "CRYPT_TOOLS"
    crypt.mkdir()
    (crypt / "Encryptor.exe").write_bytes(b"MZ")
    (crypt / "ReadMe.txt").write_text("Encryptor.exe => JSON\n", encoding="utf-8")
    monkeypatch.setenv("GCS_CRYPT_TOOLS", str(crypt))

    tool = tmp_path / "CountrySelectorTool"
    leaf = tool / "data" / "Jamaica" / "2 Screens" / "SAS 10c"
    _write(leaf / "install.json", '{"Readme":"j","Delete":[],"Copy":[],"Data":[]}')
    _write(leaf / "slot" / "themes" / "mgconfig.xml", "<Multigamer/>")
    (tool / "CountrySelector.exe").write_bytes(b"MZ")
    (tool / "Newtonsoft.Json.dll").write_bytes(b"x")

    package = build_official_cs_package(
        tmp_path / "out", tool, package_name="CS-Jamaica-Live"
    )
    assert (package / "package.xml").is_file()
    init = (package / "Content" / "init.cmd").read_text(encoding="ascii")
    assert "CountrySelector.exe" in init
    assert "ConfigScanner" not in init
    assert "begin-RamClearWithSetup" in OFFICIAL_CS_INIT_CMD
    dest_tool = package / "Content" / "tmp" / "CountrySelectorTool"
    assert (dest_tool / "CountrySelector.exe").is_file()
    assert (dest_tool / "CRYPT_TOOLS" / "Encryptor.exe").is_file()
    assert (dest_tool / "CRYPT_TOOLS" / "ReadMe.txt").is_file()


def test_export_full_country_selector_without_encrypt(tmp_path: Path, monkeypatch) -> None:
    crypt = tmp_path / "CRYPT_TOOLS"
    crypt.mkdir()
    (crypt / "Encryptor.exe").write_bytes(b"MZ")
    (crypt / "ReadMe.txt").write_text("Encryptor.exe => JSON\n", encoding="utf-8")
    monkeypatch.setenv("GCS_CRYPT_TOOLS", str(crypt))

    tool = tmp_path / "CountrySelectorTool"
    leaf = tool / "data" / "Jamaica" / "2 Screens" / "SAS 10c"
    _write(leaf / "install.json", '{"Readme":"j","Delete":[],"Copy":[],"Data":[]}')
    _write(leaf / "slot" / "themes" / "mgconfig.xml", "<Multigamer><old/></Multigamer>")
    (tool / "CountrySelector.exe").write_bytes(b"MZ")

    live = tmp_path / "goldclub"
    _write(
        live / "slot" / "themes" / "mgconfig.xml",
        "<Multigamer><TargetMarket>Jamaica</TargetMarket></Multigamer>",
    )

    monkeypatch.setattr(
        "config_scanner.live_cs_export.default_package_generator", lambda: None
    )
    from config_scanner.cs_catalog import discover_leaves

    leaves = discover_leaves(tool)
    assert leaves
    result = export_full_country_selector(
        tmp_path / "export",
        live_goldclub=live,
        country_tool_dir=tool,
        leaf=leaves[0],
        package_name="CS-JAM-Live",
        encrypt=True,
    )
    assert result.b2u_path is None
    assert "skipped" in result.note.casefold() or "missing" in result.note.casefold()
    assert result.settings_report.is_file()
    assert any("mgconfig" in f for f in result.overlay_files)
    mg = (
        result.package_dir
        / "Content"
        / "tmp"
        / "CountrySelectorTool"
        / "data"
        / "Jamaica"
        / "2 Screens"
        / "SAS 10c"
        / "slot"
        / "themes"
        / "mgconfig.xml"
    )
    assert "Jamaica" in mg.read_text(encoding="utf-8")
    assert "CountrySelector.exe" in (
        result.package_dir / "Content" / "init.cmd"
    ).read_text(encoding="ascii")
