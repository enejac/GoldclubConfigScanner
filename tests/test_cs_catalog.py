"""Tests for Country Selector catalog import / apply / wizard packing."""

from __future__ import annotations

import json
from pathlib import Path

from config_scanner.b2u_pack import build_country_b2u_folder, pack_country_update
from config_scanner.cs_catalog import (
    apply_country_leaf,
    discover_leaves,
    filter_leaves,
    is_cs_forbidden_rel,
    load_install_json,
    resolve_country_selector_tool,
    stage_country_pack,
    substitutions_from_machine_number,
)


_INSTALL_JSON = """\
{
	"Readme" : "Test Trinidad 1c OL + SAS 2Screens",
	"Delete" : [
		{
			"Path":"c:/Goldclub/slot/var/",
		}
	],
	"Copy": [
		{
			"From": "slot",
			"To": "c:/Goldclub/Slot/",
		},
		{
			"From": "Services",
			"To": "c:/Goldclub/Services/",
		}
	],
	"Data":[
		{
			"Path" :
			[
				"c:/Goldclub/Services/Aurum/config/AurumSetup.xml",
				"c:/Goldclub/Slot/themes/mgconfig.xml",
			],
			"Variables" : [
				{
					"Title" : "Please, write machine name. Just numbers.",
					"Pattern" : "!!MachineName!!"
				}
			]
		}
	]
}
"""


def _make_cs_fixture(tmp_path: Path) -> Path:
    tool = tmp_path / "CountrySelectorTool"
    leaf = (
        tool
        / "data"
        / "Trinidad 92-94"
        / "Gamestar 2 Screens"
        / "Gamestar OL + SAS"
    )
    leaf.mkdir(parents=True)
    (leaf / "install.json").write_text(_INSTALL_JSON, encoding="utf-8")

    slot = leaf / "slot" / "themes"
    slot.mkdir(parents=True)
    (slot / "mgconfig.xml").write_text(
        "<Multigamer><MachineID>GST!!MachineName!!</MachineID></Multigamer>",
        encoding="utf-8",
    )
    (slot / "HardwareConfig.xml").write_text(
        "<Hardware><CurrencyName>USD</CurrencyName></Hardware>",
        encoding="utf-8",
    )
    # Forbidden serialport map — must be skipped on apply
    sp = (
        leaf
        / "slot"
        / "themes"
        / "system"
        / "hardware"
        / "serialport"
    )
    # Use path that matches forbidden regex: system/hardware/serialport/layout.json
    # under Goldclub-relative copy from slot/
    bad = leaf / "bios" / "system" / "hardware" / "serialport"
    bad.mkdir(parents=True)
    (bad / "layout.json").write_text('{"bad":true}', encoding="utf-8")
    # Also put under slot tree relative path that becomes system/... when? 
    # install copies whole folders; forbidden check is on rel within each Copy From.
    # For bios copy we'd need bios in Copy — add it.
    install = load_install_json(leaf / "install.json")
    # Rewrite install to also copy bios
    data = dict(install.raw)
    data["Copy"] = list(data["Copy"]) + [{"From": "bios", "To": "c:/Goldclub/bios/"}]
    (leaf / "install.json").write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    svc = leaf / "Services" / "Aurum" / "config"
    svc.mkdir(parents=True)
    (svc / "AurumSetup.xml").write_text(
        "<Aurum><NetworkHostName>GST!!MachineName!!</NetworkHostName></Aurum>",
        encoding="utf-8",
    )

    # Second leaf for axis filtering
    leaf2 = (
        tool
        / "data"
        / "Trinidad 92-94"
        / "Gamestar 2 Screens"
        / "Gamestar SAS"
    )
    leaf2.mkdir(parents=True)
    (leaf2 / "install.json").write_text(
        _INSTALL_JSON.replace("OL + SAS", "SAS only"),
        encoding="utf-8",
    )
    (leaf2 / "slot" / "themes").mkdir(parents=True)
    (leaf2 / "slot" / "themes" / "mgconfig.xml").write_text(
        "<Multigamer><MachineID>GST!!MachineName!!</MachineID></Multigamer>",
        encoding="utf-8",
    )
    return tool


def test_load_install_json_tolerates_trailing_commas(tmp_path: Path) -> None:
    path = tmp_path / "install.json"
    path.write_text(_INSTALL_JSON, encoding="utf-8")
    recipe = load_install_json(path)
    assert "Trinidad" in recipe.readme
    assert any("slot/var" in p for p in recipe.delete_paths)
    assert recipe.copy_ops
    assert recipe.variables[0].pattern == "!!MachineName!!"


def test_discover_and_filter_leaves(tmp_path: Path) -> None:
    tool = _make_cs_fixture(tmp_path)
    leaves = discover_leaves(tool)
    assert len(leaves) == 2
    sas_only = filter_leaves(
        leaves,
        country="Trinidad 92-94",
        screens="Gamestar 2 Screens",
        mode="Gamestar SAS",
    )
    assert len(sas_only) == 1
    assert "SAS only" in sas_only[0].readme or sas_only[0].mode == "Gamestar SAS"


def test_resolve_from_package_root(tmp_path: Path) -> None:
    tool = _make_cs_fixture(tmp_path)
    package = tmp_path / "CS-Gamestar-TRI-TEST"
    nested = package / "Content" / "tmp" / "CountrySelectorTool"
    nested.parent.mkdir(parents=True)
    # move tool into nested location
    tool.rename(nested)
    resolved = resolve_country_selector_tool(package)
    assert (resolved / "data").is_dir()
    assert len(discover_leaves(package)) == 2


def test_apply_country_leaf_copies_and_substitutes(tmp_path: Path) -> None:
    tool = _make_cs_fixture(tmp_path)
    leaf = filter_leaves(
        discover_leaves(tool),
        mode="Gamestar OL + SAS",
    )[0]
    gold = tmp_path / "Goldclub"
    (gold / "slot" / "var").mkdir(parents=True)
    (gold / "slot" / "var" / "junk.txt").write_text("x", encoding="utf-8")

    recipe = load_install_json(leaf.path / "install.json")
    subs = substitutions_from_machine_number(recipe, "20664")
    result = apply_country_leaf(leaf, gold, substitutions=subs)

    assert not result.errors
    assert (gold / "slot" / "themes" / "mgconfig.xml").is_file()
    mg = (gold / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8")
    assert "GST20664" in mg
    assert "!!MachineName!!" not in mg
    aurum = (gold / "Services" / "Aurum" / "config" / "AurumSetup.xml").read_text(
        encoding="utf-8"
    )
    assert "GST20664" in aurum
    assert not (gold / "slot" / "var").exists()
    # Forbidden serialport layout must not be written
    assert not (
        gold / "bios" / "system" / "hardware" / "serialport" / "layout.json"
    ).exists()
    assert any("forbidden" in s for s in result.skipped)


def test_is_cs_forbidden_rel() -> None:
    assert is_cs_forbidden_rel("system/hardware/serialport/layout.json")
    assert is_cs_forbidden_rel("bios/system/hardware/serialport/locations.json")
    assert not is_cs_forbidden_rel("slot/themes/mgconfig.xml")


def test_build_country_b2u_folder(tmp_path: Path) -> None:
    tool = _make_cs_fixture(tmp_path)
    exe = tmp_path / "ConfigScanner.exe"
    exe.write_bytes(b"MZ country")
    package = build_country_b2u_folder(
        tmp_path / "out", tool, exe_path=exe, package_name="CS_Test"
    )
    assert (package / "package.xml").is_file()
    init = (package / "Content" / "init.cmd").read_text(encoding="ascii")
    assert "--country-pack" in init
    assert (
        package / "Content" / "tmp" / "CountrySelectorTool" / "data"
    ).is_dir()
    assert (package / "Content" / "tmp" / "ConfigScanner.exe").read_bytes().startswith(
        b"MZ"
    )


def test_pack_country_update_without_encrypt(tmp_path: Path, monkeypatch) -> None:
    crypt = tmp_path / "CRYPT_TOOLS"
    crypt.mkdir()
    (crypt / "Encryptor.exe").write_bytes(b"MZ")
    (crypt / "ReadMe.txt").write_text("Encryptor.exe => JSON\n", encoding="utf-8")
    monkeypatch.setenv("GCS_CRYPT_TOOLS", str(crypt))
    tool = _make_cs_fixture(tmp_path)
    exe = tmp_path / "ConfigScanner.exe"
    exe.write_bytes(b"MZ")
    staged = stage_country_pack(tool, tmp_path / "stage")
    result = pack_country_update(
        tmp_path / "dist",
        staged,
        exe_path=exe,
        package_name="Country_X",
        encrypt=False,
    )
    assert result.b2u_path is None
    assert (result.package_dir / "Content" / "tmp" / "CountrySelectorTool" / "data").is_dir()
