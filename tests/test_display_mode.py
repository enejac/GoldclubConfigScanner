"""GameStar 2-screen vs 3-screen mgconfig path switching."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from config_scanner.live_push import commit_live_push, recipe_change_lines
from config_scanner.slot_setup import (
    SlotSetupRecipe,
    build_config_pack,
    display_mode_infoscreen_height,
    load_recipe_from_goldclub,
    missing_display_mode_assets,
    patch_mgconfig_display_mode,
    patch_mgconfig_locale,
    read_display_mode,
    read_display_mode_paths,
    resolve_target_market_for_mgconfig,
)
from tests.test_slot_setup import _fake_goldclub, _write

_STAGED_2 = (
    Path("config_scanner/assets/embedded_updates/staged/CS-Gamestar-TRI-00_OL+SAS")
    / "CountrySelectorTool/data/Trinidad&Tobago/Gamestar OL+SAS 10c/Gamestar 2 Screens"
    / "slot/themes/mgconfig.xml"
)
_STAGED_3 = (
    Path("config_scanner/assets/embedded_updates/staged/CS-Gamestar-TRI-00_OL+SAS")
    / "CountrySelectorTool/data/Trinidad&Tobago/Gamestar OL+SAS 10c/Gamestar 3 Screens"
    / "slot/themes/mgconfig.xml"
)


def _goldclub_with_mgconfig(tmp_path: Path, mg_src: Path) -> Path:
    root = tmp_path / "Goldclub"
    dest = root / "slot" / "themes" / "mgconfig.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mg_src, dest)
    return root


def _touch_theme_assets(root: Path, mode: str) -> None:
    from config_scanner.slot_setup import _theme_file_from_mgconfig_path, _transform_display_path

    paths = read_display_mode_paths(root)
    for raw in paths.values():
        transformed = _transform_display_path(raw, mode)
        target = _theme_file_from_mgconfig_path(root, transformed)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<stub/>", encoding="utf-8")


@pytest.mark.skipif(not _STAGED_2.is_file(), reason="staged CS pack not present")
def test_staged_cs_packs_detect_2_and_3_screen_modes() -> None:
    root2 = _STAGED_2.parents[2]
    root3 = _STAGED_3.parents[2]
    assert read_display_mode(root2) == "2"
    assert read_display_mode(root3) == "3"


@pytest.mark.skipif(not _STAGED_2.is_file(), reason="staged CS pack not present")
def test_patch_mgconfig_round_trips_2_to_3_to_2(tmp_path: Path) -> None:
    gold = _goldclub_with_mgconfig(tmp_path, _STAGED_2)
    pack = tmp_path / "pack"
    build_config_pack(
        SlotSetupRecipe(display_mode="3"),
        gold,
        pack,
    )
    patched = pack / "slot" / "themes" / "mgconfig.xml"
    assert patched.is_file()
    assert read_display_mode(pack) == "3"
    root3 = _STAGED_3.parents[2]
    live3 = read_display_mode_paths(pack)
    expect3 = read_display_mode_paths(root3)
    assert live3 == expect3

    back_root = tmp_path / "back"
    back_mg = back_root / "slot" / "themes" / "mgconfig.xml"
    back_mg.parent.mkdir(parents=True, exist_ok=True)
    patch_mgconfig_display_mode(patched, back_mg, "2")
    assert read_display_mode(back_root) == "2"


def test_missing_assets_blocks_commit(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <EffectSettingsFile>themes\\shaders\\Effects.xml</EffectSettingsFile>
  <GameSelectorSettingsFile>themes\\\\data\\\\GameStarColors\\\\1080p\\Red\\gameselector_GSC_config.xml</GameSelectorSettingsFile>
  <MagicWheelPath>themes\\\\magicwheel.xml</MagicWheelPath>
</Multigamer>
""",
    )
    recipe = load_recipe_from_goldclub(gold)
    recipe.display_mode = "3"
    assert missing_display_mode_assets(gold, "3")
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        scan_target=str(gold),
    )
    assert result.errors
    assert "missing theme files" in result.errors[0].casefold()


def test_commit_succeeds_when_3_screen_assets_exist(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <EffectSettingsFile>themes\\shaders\\Effects.xml</EffectSettingsFile>
  <GameSelectorSettingsFile>themes\\\\data\\\\GameStarColors\\\\1080p\\Red\\gameselector_GSC_config.xml</GameSelectorSettingsFile>
  <MagicWheelPath>themes\\\\magicwheel.xml</MagicWheelPath>
  <DenominationList><int>5</int></DenominationList>
</Multigamer>
""",
    )
    _touch_theme_assets(gold, "3")
    recipe = load_recipe_from_goldclub(gold)
    assert recipe.display_mode == "2"
    recipe.display_mode = "3"
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        scan_target=str(gold),
    )
    assert not result.errors
    assert read_display_mode(gold) == "3"


def test_recipe_change_lines_includes_display_layout() -> None:
    before = SlotSetupRecipe(display_mode="2")
    after = SlotSetupRecipe(display_mode="3")
    lines = recipe_change_lines(before, after)
    assert any("Display layout" in line and "3 screens" in line for line in lines)


def test_build_config_pack_never_writes_configuredisplays(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "bios" / "etc" / "application" / "configuredisplays" / "config.xml",
        """<?xml version="1.0"?><config><monitors><monitor0><Y>0</Y></monitor0></config>""",
    )
    _write(
        gold / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <EffectSettingsFile>themes\\shaders\\Effects_3Screens.xml</EffectSettingsFile>
  <InfoScreenSharedPath>themes\\data\\GameStarColors\\1080p\\Red\\3_Screens_GSC_Settings.xml</InfoScreenSharedPath>
</Multigamer>
""",
    )
    pack = tmp_path / "pack"
    built = build_config_pack(SlotSetupRecipe(display_mode="2"), gold, pack)
    assert "configuredisplays" not in " ".join(built.files).casefold()
    assert not (pack / "bios" / "etc" / "application" / "configuredisplays").exists()


def test_display_mode_infoscreen_height_from_settings(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    settings = (
        gold
        / "slot"
        / "themes"
        / "data"
        / "GameStarColors"
        / "1080p"
        / "Red"
        / "3_Screens_GSC_Settings.xml"
    )
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        """<?xml version="1.0"?><Root><Width>1920</Width><Height>3240</Height></Root>""",
        encoding="utf-8",
    )
    _write(
        gold / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <InfoScreenSharedPath>themes\\data\\GameStarColors\\1080p\\Red\\3_Screens_GSC_Settings.xml</InfoScreenSharedPath>
</Multigamer>
""",
    )
    assert display_mode_infoscreen_height(gold) == 3240


def test_tt_alias_preserves_existing_puerto_rico() -> None:
    assert (
        resolve_target_market_for_mgconfig("TT", "PuertoRico") == "PuertoRico"
    )
    assert resolve_target_market_for_mgconfig("TT", "TT") == "PuertoRico"
    assert resolve_target_market_for_mgconfig("TT", None) == "PuertoRico"
    assert resolve_target_market_for_mgconfig("TT", "Jamaica") == "PuertoRico"
    assert resolve_target_market_for_mgconfig("SA", "PuertoRico") == "SA"
    assert resolve_target_market_for_mgconfig("South Africa", None) == "SA"


def test_display_only_pack_does_not_write_tt_target_market(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "slot" / "themes" / "jurisdiction_config.xml",
        """<?xml version="1.0"?><JurisdictionSettings><Tag>TT</Tag></JurisdictionSettings>""",
    )
    _write(
        gold / "slot" / "themes" / "mgconfig.xml",
        """<?xml version="1.0"?>
<Multigamer>
  <MarketSpecific><TargetMarket>PuertoRico</TargetMarket></MarketSpecific>
  <EffectSettingsFile>themes\\shaders\\Effects_3Screens.xml</EffectSettingsFile>
  <InfoScreenSharedPath>themes\\data\\x\\3_Screens_GSC_Settings.xml</InfoScreenSharedPath>
  <DenominationList><int>5</int></DenominationList>
</Multigamer>
""",
    )
    pack = tmp_path / "pack"
    build_config_pack(SlotSetupRecipe(display_mode="2"), gold, pack)
    text = (pack / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8")
    assert "<TargetMarket>PuertoRico</TargetMarket>" in text
    assert "<TargetMarket>TT</TargetMarket>" not in text


def test_patch_mgconfig_locale_maps_tt_to_valid_market(tmp_path: Path) -> None:
    src = tmp_path / "src.xml"
    dest = tmp_path / "dest.xml"
    src.write_text(
        """<?xml version="1.0"?>
<Multigamer><MarketSpecific><TargetMarket>TT</TargetMarket></MarketSpecific></Multigamer>""",
        encoding="utf-8",
    )
    from config_scanner.slot_setup import JurisdictionSettings

    patch_mgconfig_locale(
        src,
        dest,
        JurisdictionSettings(tag="TT"),
    )
    assert "<TargetMarket>PuertoRico</TargetMarket>" in dest.read_text(encoding="utf-8")


def test_live_onehand_rejects_jamaica_when_exe_is_tri(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    exe = gold / "slot" / "OneHand.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ\x00PuertoRico\x00TargetMarket\x00")
    mg = gold / "slot" / "themes" / "mgconfig.xml"
    mg.parent.mkdir(parents=True, exist_ok=True)
    mg.write_text(
        """<?xml version="1.0"?>
<Multigamer><MarketSpecific><TargetMarket>PuertoRico</TargetMarket></MarketSpecific>
<DenominationList><int>5</int></DenominationList></Multigamer>""",
        encoding="utf-8",
    )
    from config_scanner.denom_compat import validate_live_push_recipe
    from config_scanner.slot_setup import load_recipe_from_goldclub

    live = load_recipe_from_goldclub(gold, label="live")
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.jurisdiction.tag = "Jamaica"
    proposed.jurisdiction.currency_name = "JMD"
    errors = validate_live_push_recipe(live, proposed, gold)
    assert errors
    assert any("Jamaica" in err and "PuertoRico" in err for err in errors)

    proposed.jurisdiction.tag = "TT"
    proposed.jurisdiction.currency_name = "TTD"
    assert validate_live_push_recipe(live, proposed, gold) == []


def test_live_onehand_allows_jamaica_when_exe_has_it(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    exe = gold / "slot" / "OneHand.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ\x00PuertoRico\x00Jamaica\x00TargetMarket\x00")
    mg = gold / "slot" / "themes" / "mgconfig.xml"
    mg.parent.mkdir(parents=True, exist_ok=True)
    mg.write_text(
        """<?xml version="1.0"?>
<Multigamer><MarketSpecific><TargetMarket>PuertoRico</TargetMarket></MarketSpecific>
<DenominationList><int>5</int></DenominationList></Multigamer>""",
        encoding="utf-8",
    )
    from config_scanner.denom_compat import validate_live_push_recipe
    from config_scanner.slot_setup import load_recipe_from_goldclub

    live = load_recipe_from_goldclub(gold, label="live")
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.jurisdiction.tag = "Jamaica"
    proposed.jurisdiction.currency_name = "JMD"
    assert validate_live_push_recipe(live, proposed, gold) == []
