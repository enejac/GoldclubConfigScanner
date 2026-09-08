"""HWDrivers ST3 / Rhapsody / Sublime button-deck packs."""

from __future__ import annotations

from pathlib import Path

from config_scanner.hw_drivers import (
    detect_hw_driver_profile,
    find_hw_driver_profile,
    list_hw_driver_profiles,
    stage_hw_driver_profile,
)
from config_scanner.slot_setup import (
    SlotSetupRecipe,
    build_config_pack,
    load_recipe_from_goldclub,
    read_keyboard_map,
)
from tests.test_slot_setup import _fake_goldclub


def test_list_profiles_includes_st3() -> None:
    ids = {p.id for p in list_hw_driver_profiles()}
    assert "ST3" in ids
    assert "Rhapsody" in ids
    assert "Sublime_Axiomtek" in ids


def test_st3_keyboard_maps_spin_271() -> None:
    prof = find_hw_driver_profile("ST3")
    assert prof is not None
    text = prof.keyboard_path().read_text(encoding="utf-8")
    assert 'name="271">Spin' in text
    assert 'name="270">MaxBet' in text


def test_detect_and_stage_st3(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    pack = tmp_path / "pack"
    pack.mkdir()
    written = stage_hw_driver_profile("ST3", pack)
    assert "slot/hwdrivers/Keyboard.xml" in written
    assert "slot/hwdrivers/Lights.xml" in written
    dest = gold / "slot" / "hwdrivers"
    for rel in written:
        (dest / Path(rel).name).write_bytes((pack / rel).read_bytes())
    assert detect_hw_driver_profile(gold) == "ST3"
    kb = read_keyboard_map(gold)
    assert kb.get("271") == "Spin"
    assert kb.get("270") == "MaxBet"
    assert kb.get("264") == "BetOne"


def test_build_config_pack_includes_hw_deck(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="t")
    recipe.hw_driver_profile = "ST3"
    pack = tmp_path / "out"
    built = build_config_pack(recipe, gold, pack)
    assert "slot/hwdrivers/Keyboard.xml" in built.files
    assert "slot/hwdrivers/Lights.xml" in built.files
    kb = (pack / "slot/hwdrivers/Keyboard.xml").read_text(encoding="utf-8")
    assert 'name="271">Spin' in kb
