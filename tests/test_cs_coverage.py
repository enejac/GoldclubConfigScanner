"""Slot profile covers Country Selector overlay files; CS resolve is resilient."""

from __future__ import annotations

from pathlib import Path

import pytest

from config_scanner.cs_catalog import (
    _normalize_goldclub_path,
    resolve_country_selector_tool,
)
from config_scanner.cs_coverage import (
    applied_goldclub_rels,
    coverage_gaps,
    inventory_leaf_config_files,
    profile_covers_rel,
)
from config_scanner.profiles import get_profile
from config_scanner.scanner import collect_scan_files


def _tt00_leaf() -> Path:
    leaf = Path(
        r"C:\tmp\cs_b2u\CS-Gamestar-TT-00\Content\tmp\CountrySelectorTool"
        r"\data\Trinidad 94\Gamestar2\Gamestar2 3 Screens"
    )
    return leaf


@pytest.fixture
def tt00_leaf() -> Path:
    leaf = _tt00_leaf()
    if not leaf.is_dir():
        pytest.skip("TT-00 decrypt cache not present")
    return leaf


def test_slot_profile_includes_txt_and_services() -> None:
    profile = get_profile("slot_lab_90")
    assert "*.txt" in profile.include_patterns
    assert any(r.path.casefold() == "services" for r in profile.scan_roots)
    assert "slot/Confirmation.txt" in profile.extra_file_globs
    assert "hello.txt" in profile.extra_file_globs


def test_tt00_leaf_inventory(tt00_leaf: Path) -> None:
    files = inventory_leaf_config_files(tt00_leaf)
    names = {p.name for p in files}
    assert "mgconfig.xml" in names
    assert "HardwareConfig.xml" in names
    assert "Keyboard.xml" in names
    assert "Confirmation.txt" in names
    assert "SASsetupData.xml" in names
    assert "AurumSetup.xml" in names
    assert "soundvolume.xml" in names


def test_slot_profile_covers_tt00_leaf(tt00_leaf: Path) -> None:
    profile = get_profile("slot_lab_90")
    gaps = coverage_gaps(profile, tt00_leaf)
    # Allow only non-config noise if any; core CS files must be covered
    critical = [
        "slot/themes/mgconfig.xml",
        "slot/themes/HardwareConfig.xml",
        "slot/hwdrivers/Keyboard.xml",
        "slot/Confirmation.txt",
        "Services/aurum/config/AurumSetup.xml",
        "Services/aurum/config/SASControler1/SASsetupData.xml",
        "Services/aurum/config/SASControler1/ClientsSet.xml",
        "bios/etc/application/system/soundvolume.xml",
        "hello.txt",
    ]
    for rel in critical:
        assert profile_covers_rel(profile, rel), f"profile misses {rel}"
        assert rel not in gaps and not any(
            g.casefold() == rel.casefold() for g in gaps
        ), f"gap list still has {rel}: {gaps}"


def test_collect_scan_files_picks_cs_overlay_layout(tmp_path: Path) -> None:
    profile = get_profile("slot_lab_90")
    # Full Goldclub root layout matching TT-00 apply targets
    (tmp_path / "slot" / "themes" / "PR2_Foo").mkdir(parents=True)
    (tmp_path / "slot" / "hwdrivers").mkdir(parents=True)
    (tmp_path / "Services" / "aurum" / "config" / "SASControler1").mkdir(parents=True)
    (tmp_path / "bios" / "etc" / "application" / "system").mkdir(parents=True)
    (tmp_path / "hello.txt").write_text("machine", encoding="utf-8")
    (tmp_path / "slot" / "Confirmation.txt").write_text("Trinidad 5c", encoding="utf-8")
    (tmp_path / "slot" / "themes" / "mgconfig.xml").write_text("<mg/>", encoding="utf-8")
    (tmp_path / "slot" / "themes" / "HardwareConfig.xml").write_text("<hw/>", encoding="utf-8")
    (tmp_path / "slot" / "hwdrivers" / "Keyboard.xml").write_text("<k/>", encoding="utf-8")
    (tmp_path / "slot" / "themes" / "PR2_Foo" / "MathSettings.xml").write_text(
        "<m/>", encoding="utf-8"
    )
    (
        tmp_path / "Services" / "aurum" / "config" / "SASControler1" / "SASsetupData.xml"
    ).write_text("<sas/>", encoding="utf-8")
    (
        tmp_path / "Services" / "aurum" / "config" / "SASControler1" / "crcfileslist.txt"
    ).write_text("a", encoding="utf-8")
    (
        tmp_path / "bios" / "etc" / "application" / "system" / "soundvolume.xml"
    ).write_text("<vol/>", encoding="utf-8")

    files = collect_scan_files(
        tmp_path, list(profile.scan_roots), profile.include_patterns, profile.extra_file_globs
    )
    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    rels_cf = {r.casefold() for r in rels}
    assert "hello.txt" in rels_cf
    assert "slot/confirmation.txt" in rels_cf
    assert "slot/themes/mgconfig.xml" in rels_cf
    assert "slot/hwdrivers/keyboard.xml" in rels_cf
    assert "slot/themes/pr2_foo/mathsettings.xml" in rels_cf
    assert "services/aurum/config/sascontroler1/sassetupdata.xml" in rels_cf
    assert "services/aurum/config/sascontroler1/crcfileslist.txt" in rels_cf
    assert "bios/etc/application/system/soundvolume.xml" in rels_cf


def test_normalize_prefers_existing_slot_casing(tmp_path: Path) -> None:
    (tmp_path / "slot" / "themes").mkdir(parents=True)
    dest = _normalize_goldclub_path("c:/Goldclub/Slot/themes/mgconfig.xml", tmp_path)
    assert dest.parts[-3].casefold() == "slot"
    assert dest.name == "mgconfig.xml"


def test_resolve_tool_nested_layout(tmp_path: Path) -> None:
    tool = tmp_path / "pkg" / "Content" / "tmp" / "CountrySelectorTool"
    leaf = tool / "data" / "T" / "2" / "SAS"
    leaf.mkdir(parents=True)
    (leaf / "install.json").write_text(
        '{"Readme":"x","Delete":[],"Copy":[],"Data":[]}', encoding="utf-8"
    )
    found = resolve_country_selector_tool(tmp_path / "pkg")
    assert found == tool


def test_applied_rels_lists_slot_and_services(tt00_leaf: Path) -> None:
    rels = {r.casefold() for r in applied_goldclub_rels(tt00_leaf)}
    assert "slot/themes/mgconfig.xml" in rels
    assert "services/aurum/config/aurumsetup.xml" in rels or any(
        "aurumsetup.xml" in r for r in rels
    )
