"""Registry integrity for setting_spec."""

from __future__ import annotations

from pathlib import Path

from config_scanner.embedded_updates import load_catalog, materialize_country_tool
from config_scanner.setting_spec import SETTING_GROUPS, SETTING_SPECS, all_specs, validate_registry


def test_registry_unique_and_valid() -> None:
    problems = validate_registry()
    assert problems == [], problems
    ids = [s.id for s in all_specs()]
    assert len(ids) == len(set(ids))
    assert len(SETTING_SPECS) >= 120
    groups = {s.group for s in SETTING_SPECS}
    for required in (
        "Jurisdiction",
        "UI",
        "SAS",
        "Ticketing",
        "Hardware",
        "Dallas",
        "Identity",
        "Aurum",
        "Audio",
        "Buttons",
    ):
        assert required in groups
    assert any(s.kind == "ini_scalar" for s in SETTING_SPECS)
    assert any(s.kind == "service_enabled" for s in SETTING_SPECS)
    assert any(s.id == "aurum.conf_skip_service_check" for s in SETTING_SPECS)
    assert {s.group for s in SETTING_SPECS} <= set(SETTING_GROUPS)


def test_cs_delivered_files_exist_in_staged_trinidad() -> None:
    entries = load_catalog()
    tri = next(
        (e for e in entries if e.id == "CS-Gamestar-TRI-00_OL+SAS"),
        None,
    )
    if tri is None or tri.staged_tool_path is None:
        # Fall back to TT-00
        tri = next(e for e in entries if e.id == "CS-Gamestar-TT-00")
    tool = materialize_country_tool(tri)
    # Pick any leaf with install.json
    leaves = sorted(tool.rglob("install.json"))
    assert leaves, "no install.json under staged tree"
    leaf = leaves[0].parent

    for spec in all_specs():
        if not spec.cs_pack_delivers:
            continue
        if spec.per_theme:
            themes = leaf / "slot" / "themes"
            assert themes.is_dir(), f"{spec.id}: themes missing under {leaf}"
            maths = list(themes.glob("*/MathSettings.xml"))
            assert maths, f"{spec.id}: no MathSettings.xml under {leaf}"
            continue
        rel = spec.file_rel.replace("\\", "/")
        path = leaf / Path(rel)
        assert path.is_file(), f"{spec.id}: missing {rel} under {leaf}"


def test_no_serialport_or_licence_specs() -> None:
    for spec in all_specs():
        low = spec.file_rel.casefold()
        assert "layout.json" not in low
        assert "locations.json" not in low
        assert "licence.dll" not in low
