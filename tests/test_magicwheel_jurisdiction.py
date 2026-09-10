"""Newer-build magic wheel lives in jurisdiction_config, not mgconfig."""

from __future__ import annotations

from pathlib import Path

from config_scanner.live_push import (
    LIVE_FIELD_CONFIG_RELS,
    LIVE_OPTION_HELP,
    canonicalize_live_field_label,
    live_push_changed_sections,
    resolve_live_field_config_files,
)
from config_scanner.profiles import get_profile
from config_scanner.slot_setup import (
    PlayLimitsSettings,
    SlotSetupRecipe,
    build_config_pack,
    iter_magicwheel_setting_rels,
    load_recipe_from_goldclub,
    read_play_limits,
    theme_rel_from_mgconfig_path,
)
from tests.test_slot_setup import _fake_goldclub, _write


def test_theme_rel_from_mgconfig_path_prefixes_slot() -> None:
    assert theme_rel_from_mgconfig_path(r"themes\magicwheel.xml") == (
        "slot/themes/magicwheel.xml"
    )
    assert theme_rel_from_mgconfig_path("slot/themes/magicwheel_3Screens.xml") == (
        "slot/themes/magicwheel_3Screens.xml"
    )


def test_form_captions_alias_to_magic_wheel_labels() -> None:
    assert canonicalize_live_field_label("Money limit") == "Magic wheel limit"
    assert canonicalize_live_field_label("Wheel bet") == "Magic wheel bet"
    assert canonicalize_live_field_label("Magic wheel bet") == "Magic wheel bet"


def test_right_click_magic_wheel_opens_jurisdiction_not_mgconfig(
    tmp_path: Path,
) -> None:
    gold = _fake_goldclub(tmp_path)
    for label in (
        "Magic wheel limit",
        "Magic wheel bet",
        "Magic wheel enabled",
        "Wheel bet",
        "Money limit",
    ):
        names = {p.name.casefold() for p in resolve_live_field_config_files(gold, label)}
        assert "jurisdiction_config.xml" in names, label
        assert "magicwheel_config.xml" in names, label
        assert "mgconfig.xml" not in names, label
    assert "mgconfig.xml" not in {
        Path(rel).name.casefold() for rel in LIVE_FIELD_CONFIG_RELS["Magic wheel bet"]
    }
    assert "mgconfig" not in LIVE_OPTION_HELP["Magic wheel enabled"].casefold() or (
        "not mgconfig" in LIVE_OPTION_HELP["Magic wheel enabled"]
    )


def test_right_click_bet_multipliers_opens_mathsettings(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    names = {p.name.casefold() for p in resolve_live_field_config_files(gold, "Bet multipliers")}
    assert "mathsettings.xml" in names
    assert "mgconfig.xml" not in names


def test_read_play_limits_from_jurisdiction_pack_when_no_config(
    tmp_path: Path,
) -> None:
    gold = _fake_goldclub(tmp_path)
    (gold / "slot" / "themes" / "magicwheel_Config.xml").unlink()
    _write(
        gold / "slot" / "themes" / "jurisdiction_config.xml",
        """<?xml version="1.0"?>
<JurisdictionSettings>
  <Tag>TrinidadTobago</Tag>
  <MagicWheelPackSettings>
    <MoneyLimit>25000</MoneyLimit>
    <Enabled>true</Enabled>
    <Bet>10</Bet>
    <MaxWheelSpins>8000</MaxWheelSpins>
    <MoneyWheelAverage>50</MoneyWheelAverage>
  </MagicWheelPackSettings>
</JurisdictionSettings>
""",
    )
    recipe = load_recipe_from_goldclub(gold, label="pack-only")
    assert recipe.jurisdiction.magic_wheel_money_limit == 25000
    assert recipe.play_limits.magic_wheel_bet == 10
    assert recipe.play_limits.magic_wheel_enabled is True
    assert recipe.play_limits.magic_wheel_max_spins == 8000
    assert recipe.play_limits.magic_wheel_average == 50
    rels = iter_magicwheel_setting_rels(gold)
    assert "slot/themes/jurisdiction_config.xml" in rels
    assert "slot/themes/magicwheel_Config.xml" not in rels
    names = {p.name.casefold() for p in resolve_live_field_config_files(gold, "Magic wheel bet")}
    assert names == {"jurisdiction_config.xml"}


def test_jurisdiction_pack_overrides_stale_magicwheel_config(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "slot" / "themes" / "jurisdiction_config.xml",
        """<?xml version="1.0"?>
<JurisdictionSettings>
  <Tag>TrinidadTobago</Tag>
  <MagicWheelPackSettings>
    <MoneyLimit>5000</MoneyLimit>
    <Bet>25</Bet>
    <MoneyWheelAverage>125</MoneyWheelAverage>
  </MagicWheelPackSettings>
</JurisdictionSettings>
""",
    )
    limits = read_play_limits(gold)
    assert limits.magic_wheel_bet == 25
    assert limits.magic_wheel_average == 125
    assert limits.magic_wheel_enabled is True
    assert limits.magic_wheel_max_spins == 50000


def test_pack_writes_jurisdiction_wheel_when_config_missing(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    (gold / "slot" / "themes" / "magicwheel_Config.xml").unlink()
    _write(
        gold / "slot" / "themes" / "jurisdiction_config.xml",
        """<?xml version="1.0"?>
<JurisdictionSettings>
  <Tag>PuertoRico</Tag>
  <MagicWheelPackSettings>
    <MoneyLimit>500</MoneyLimit>
    <Bet>5</Bet>
    <Enabled>true</Enabled>
    <MoneyWheelAverage>25</MoneyWheelAverage>
  </MagicWheelPackSettings>
</JurisdictionSettings>
""",
    )
    recipe = load_recipe_from_goldclub(gold, label="newer")
    recipe.jurisdiction.magic_wheel_money_limit = 10000
    recipe.play_limits = PlayLimitsSettings(
        magic_wheel_enabled=True,
        magic_wheel_bet=10,
        magic_wheel_average=50,
    )
    pack = tmp_path / "mw-pack"
    built = build_config_pack(recipe, gold, pack)
    assert "slot/themes/jurisdiction_config.xml" in built.files
    assert "slot/themes/magicwheel_Config.xml" not in built.files
    jur = (pack / "slot" / "themes" / "jurisdiction_config.xml").read_text(
        encoding="utf-8"
    )
    assert "<MoneyLimit>10000</MoneyLimit>" in jur
    assert "<Bet>10</Bet>" in jur
    assert "<MoneyWheelAverage>50</MoneyWheelAverage>" in jur
    assert "<Enabled>true</Enabled>" in jur


def test_legacy_pack_does_not_invent_jurisdiction_bet_tags(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="legacy")
    recipe.jurisdiction.magic_wheel_money_limit = 5000
    recipe.play_limits = PlayLimitsSettings(magic_wheel_bet=10, magic_wheel_average=50)
    pack = tmp_path / "legacy-pack"
    build_config_pack(recipe, gold, pack)
    jur = (pack / "slot" / "themes" / "jurisdiction_config.xml").read_text(
        encoding="utf-8"
    )
    assert "<MoneyLimit>5000</MoneyLimit>" in jur
    assert "<Bet>10</Bet>" not in jur
    mw = (pack / "slot" / "themes" / "magicwheel_Config.xml").read_text(encoding="utf-8")
    assert "<Bet>10</Bet>" in mw
    assert "<MoneyWheelAverage>50</MoneyWheelAverage>" in mw


def test_magic_wheel_bet_change_includes_jurisdiction_section() -> None:
    live = SlotSetupRecipe()
    live.play_limits.magic_wheel_bet = 5
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.play_limits.magic_wheel_bet = 10
    sections = live_push_changed_sections(live, form)
    assert "magicwheel" in sections
    assert "jurisdiction" in sections


def test_slot_profiles_do_not_hardcode_lab_ips() -> None:
    slot = get_profile("slot_lab_90")
    roulette = get_profile("roulette_usb")
    for profile in (slot, roulette):
        assert not any("10.0.0." in item for item in profile.discover_targets)
        assert "10.0.0." not in profile.default_target
    panel = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert '("10.0.0.90"' not in panel
    assert '("10.0.0.98"' not in panel
    assert "This PC" not in panel
    assert "Use a cabinet IP instead" in panel
    assert "_begin_detect" in panel
    assert "canonicalize_live_field_label" in panel
