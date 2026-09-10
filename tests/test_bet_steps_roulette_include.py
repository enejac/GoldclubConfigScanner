"""Bet-step catalog vs game packs, and RouletteGame snapshot include-check."""

from __future__ import annotations

from pathlib import Path

from config_scanner.cs_coverage import profile_covers_rel, snapshot_include_check
from config_scanner.denom_compat import (
    allowed_bet_profiles_for,
    bet_multiplier_preset_labels,
    validate_denom_configuration,
)
from config_scanner.jurisdiction import load_jurisdictions
from config_scanner.live_push import BET_MULTIPLIER_PRESETS, live_push_catalog
from config_scanner.profiles import get_profile
from config_scanner.scanner import collect_scan_files
from config_scanner.slot_setup import (
    PlayLimitsSettings,
    SlotSetupRecipe,
    _math_theme_names,
    build_config_pack,
    load_recipe_from_goldclub,
    receives_live_push_bet_steps,
)
from tests.test_slot_setup import _fake_goldclub, _write


_APPROVED_BETS = (1, 2, 3, 4, 5, 8, 10, 12, 15)

_ROULETTE_ON_SLOT_RELS = (
    "slot/themes/RouletteGame/MathSettings.xml",
    "slot/themes/RouletteGame/RouletteGameMath.json",
    "slot/themes/RouletteGame/sub/ExtraMath.json",
    "slot/themes/RouletteGame/ProgressiveSetup.xml",
)

_LEFTOVER_RULETA_RELS = (
    "ruleta/Ruleta.exe",
    "ruleta/persistent/RouletteActivate.dat",
)


def _parse_preset(label: str) -> tuple[int, ...]:
    return tuple(int(x.strip()) for x in label.split(",") if x.strip())


def test_every_jurisdiction_shares_the_approved_bet_steps() -> None:
    profiles = allowed_bet_profiles_for()
    assert profiles == [_APPROVED_BETS]
    for prof in load_jurisdictions():
        assert tuple(prof.allowed_bet_multipliers) == _APPROVED_BETS, prof.id


def test_live_push_catalog_bets_match_market_not_invalid_presets() -> None:
    labels = bet_multiplier_preset_labels()
    catalog = live_push_catalog()["bet_multipliers"]
    assert labels == catalog == BET_MULTIPLIER_PRESETS
    parsed = [_parse_preset(item) for item in catalog]
    allowed = allowed_bet_profiles_for()
    assert parsed
    assert all(item in allowed for item in parsed)
    invalid = {
        (1, 2, 3, 4, 5),
        (4, 8, 12),
        (1, 2, 5, 10),
        (1, 5, 10, 20),
    }
    assert invalid.isdisjoint(parsed)


def test_receives_live_push_bet_steps_skips_unsupported_themes() -> None:
    assert receives_live_push_bet_steps("BigSafari_HnW")
    assert receives_live_push_bet_steps("PR2_Foo")
    assert not receives_live_push_bet_steps("RouletteGame")
    assert not receives_live_push_bet_steps("roulettegame")
    assert not receives_live_push_bet_steps("Link2WinFeature")
    assert not receives_live_push_bet_steps("data")
    assert not receives_live_push_bet_steps("_RouletteGame_disabled")
    assert not receives_live_push_bet_steps("")


def test_build_config_pack_does_not_write_roulettegame_bet_steps(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    roulette = gold / "slot" / "themes" / "RouletteGame" / "MathSettings.xml"
    _write(
        roulette,
        """<?xml version="1.0"?>
<MathSettings>
  <DenomConfig>
    <DenomConfigSettings>
      <BetMultipliers>
        <int>1</int>
        <int>5</int>
      </BetMultipliers>
    </DenomConfigSettings>
  </DenomConfig>
</MathSettings>
""",
    )
    recipe = load_recipe_from_goldclub(gold, label="bets")
    recipe.play_limits = PlayLimitsSettings(bet_multipliers=list(_APPROVED_BETS))
    pack = tmp_path / "bet-pack"
    built = build_config_pack(recipe, gold, pack)
    safari = pack / "slot" / "themes" / "BigSafari_HnW" / "MathSettings.xml"
    assert safari.is_file()
    text = safari.read_text(encoding="utf-8")
    for value in _APPROVED_BETS:
        assert f"<int>{value}</int>" in text
    assert "RouletteGame" not in " ".join(built.files)
    assert not (pack / "slot" / "themes" / "RouletteGame" / "MathSettings.xml").exists()
    assert _math_theme_names(gold) == ["BigSafari_HnW"]


def test_leaving_live_bets_unchanged_skips_market_check(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    live.jurisdiction.currency_name = "TTD"
    live.play_limits.bet_multipliers = [4, 8, 12]
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    result = validate_denom_configuration(live, proposed, gold)
    assert result.ok


def test_slot_snapshot_includes_roulettegame_not_leftover_ruleta(tmp_path: Path) -> None:
    profile = get_profile("slot_lab_90")
    game = tmp_path / "slot" / "themes" / "RouletteGame"
    game.mkdir(parents=True)
    (game / "MathSettings.xml").write_text("<math/>", encoding="utf-8")
    (game / "RouletteGameMath.json").write_bytes(b"\x00math")
    (game / "ProgressiveSetup.xml").write_text("<prog/>", encoding="utf-8")
    (game / "game.xml").write_text("<g/>", encoding="utf-8")
    (game / "sub").mkdir()
    (game / "sub" / "ExtraMath.json").write_bytes(b"\x01math")
    leftover = tmp_path / "ruleta"
    leftover.mkdir()
    (leftover / "Ruleta.exe").write_bytes(b"MZ-ruleta")
    persist = leftover / "persistent"
    persist.mkdir()
    (persist / "RouletteActivate.dat").write_bytes(b"\x00" * 16)
    (tmp_path / "slot" / "OneHand.exe").write_bytes(b"MZ")

    files = collect_scan_files(
        tmp_path,
        list(profile.scan_roots),
        profile.include_patterns,
        extra_file_globs=profile.extra_file_globs,
    )
    rels = {path.relative_to(tmp_path).as_posix() for path in files}
    rels_cf = {rel.casefold() for rel in rels}
    for rel in _ROULETTE_ON_SLOT_RELS:
        assert rel.casefold() in rels_cf, rel
    assert "slot/themes/roulettegame/game.xml" not in rels_cf
    assert "ruleta/ruleta.exe" not in rels_cf
    assert "ruleta/persistent/rouletteactivate.dat" not in rels_cf

    include = snapshot_include_check(
        (*_ROULETTE_ON_SLOT_RELS, *_LEFTOVER_RULETA_RELS, "slot/themes/RouletteGame/game.xml")
    )
    for rel in _ROULETTE_ON_SLOT_RELS:
        assert include[rel] is True, rel
        assert profile_covers_rel(profile, rel)
    for rel in _LEFTOVER_RULETA_RELS:
        assert include[rel] is False, rel
        assert not profile_covers_rel(profile, rel)
    assert include["slot/themes/RouletteGame/game.xml"] is False


def test_slot_profile_discovers_cabinet_98() -> None:
    slot = get_profile("slot_lab_90")
    roulette = get_profile("roulette_usb")
    assert r"\\10.0.0.98\slot" in slot.discover_targets
    assert r"\\10.0.0.98\c$\Goldclub" in slot.discover_targets
    assert r"\\10.0.0.98\slot" in roulette.discover_targets
