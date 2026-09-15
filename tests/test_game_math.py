"""Per-theme bet steps and RTP helpers."""

from __future__ import annotations

from pathlib import Path

from config_scanner.game_math import (
    GAMES_MATH_LABEL,
    allowed_return_choices,
    bet_steps_changed,
    clone_math_rows,
    copy_bet_steps_to_compatible,
    format_bet_steps,
    format_game_combo_label,
    format_game_math_summary,
    format_return_percent,
    game_math_change_lines,
    offered_bet_steps,
    set_return_percent_where_allowed,
    theme_bet_step_errors,
    theme_display_name,
    theme_math_write_errors,
    theme_rtp_errors,
)
from config_scanner.live_push import (
    live_push_ramclear_reasons,
    live_push_restart_reason_for_label,
    recipe_change_lines,
    recipe_snapshot_rows,
)
from config_scanner.slot_setup import (
    MathDenomSettings,
    SlotSetupRecipe,
    build_config_pack,
    load_recipe_from_goldclub,
    math_settings_unreadable_reason,
    receives_live_push_bet_steps,
)
from config_scanner.denom_compat import (
    validate_denom_configuration,
    validate_live_push_recipe,
)
from tests.test_slot_setup import _fake_goldclub, _write


def _row(
    theme: str,
    *,
    bets: list[int],
    rtp: str,
    allowed: list[str] | None = None,
) -> MathDenomSettings:
    return MathDenomSettings(
        theme=theme,
        bet_multipliers=list(bets),
        return_percent=rtp,
        allowed_return_percents=list(allowed if allowed is not None else [rtp]),
    )


def test_format_return_percent_tokens() -> None:
    assert format_return_percent("return_94_0") == "94.0%"
    assert format_return_percent("return_frog_92_0") == "Frog 92.0%"
    assert format_return_percent("return_97_0") == "97.0%"
    assert format_return_percent("") == "—"


def test_theme_display_and_combo_label() -> None:
    assert theme_display_name("PR3_RedZone") == "RedZone"
    assert theme_display_name("BigSafari_HnW") == "BigSafari_HnW"
    row = _row("PR2_WondersOfIndia", bets=[1, 2, 3, 4, 5, 8, 10], rtp="return_92_0")
    assert format_game_combo_label(row) == "WondersOfIndia  —  92.0%  ·  1–10"
    assert format_bet_steps([4, 8, 12]) == "4–12"


def test_summary_mixed_vs_uniform() -> None:
    red = _row("PR3_RedZone", bets=[1, 2, 3, 4, 5, 8, 10, 12, 15], rtp="return_92_0")
    same = _row("PR2_GoldRushDeluxe", bets=[1, 2, 3, 4, 5, 8, 10, 12, 15], rtp="return_92_0")
    uniform = format_game_math_summary([red, same])
    assert "1–15" in uniform
    assert "92.0%" in uniform
    assert "2 games" in uniform
    wonder = _row("PR2_WondersOfIndia", bets=[1, 2, 3, 4, 5, 8, 10], rtp="return_94_0")
    mixed = format_game_math_summary([red, wonder])
    assert "mixed" in mixed
    assert "2 bet maps" in mixed
    assert "92.0%" in mixed and "94.0%" in mixed


def test_theme_bet_step_errors_subset_and_reject_extra() -> None:
    live = [_row("BigSafari_HnW", bets=[4, 8, 12, 16], rtp="return_94_0")]
    ok = clone_math_rows(live)
    ok[0].bet_multipliers = [4, 8, 12]
    assert theme_bet_step_errors(live, ok) == []
    bad = clone_math_rows(live)
    bad[0].bet_multipliers = [4, 8, 12, 20]
    errors = theme_bet_step_errors(live, bad)
    assert errors
    assert "20" in errors[0]


def test_mixed_live_maps_pass_validation(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "slot" / "themes" / "PR2_WondersOfIndia" / "MathSettings.xml",
        """<?xml version="1.0"?>
<MathSettings>
  <CurrentReturnPercent>return_92_0</CurrentReturnPercent>
  <AllowedReturnPercents>
    <string>return_92_0</string>
    <string>return_94_0</string>
  </AllowedReturnPercents>
  <DenomConfig>
    <DenomConfigSettings>
      <DenominationMultiplier>1</DenominationMultiplier>
      <BetMultipliers>
        <int>1</int><int>2</int><int>3</int><int>4</int>
        <int>5</int><int>8</int><int>10</int>
      </BetMultipliers>
      <ReturnPercent>return_92_0</ReturnPercent>
    </DenomConfigSettings>
  </DenomConfig>
</MathSettings>
""",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    result = validate_denom_configuration(live, proposed, gold)
    assert result.ok
    safari = next(row for row in proposed.math if row.theme == "BigSafari_HnW")
    safari.bet_multipliers = [4, 8]
    result = validate_denom_configuration(live, proposed, gold)
    assert result.ok


def test_apply_rtp_on_one_theme_leaves_other_bets(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write(
        gold / "slot" / "themes" / "PR2_WondersOfIndia" / "MathSettings.xml",
        """<?xml version="1.0"?>
<MathSettings>
  <CurrentReturnPercent>return_92_0</CurrentReturnPercent>
  <AllowedReturnPercents>
    <string>return_92_0</string>
    <string>return_94_0</string>
  </AllowedReturnPercents>
  <DenomConfig>
    <DenomConfigSettings>
      <BetMultipliers>
        <int>1</int><int>2</int><int>10</int>
      </BetMultipliers>
      <ReturnPercent>return_92_0</ReturnPercent>
    </DenomConfigSettings>
  </DenomConfig>
</MathSettings>
""",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.play_limits.bet_multipliers = []
    wonder = next(row for row in form.math if row.theme == "PR2_WondersOfIndia")
    wonder.return_percent = "return_94_0"
    pack = tmp_path / "math-pack"
    build_config_pack(form, gold, pack)
    safari_text = (
        pack / "slot" / "themes" / "BigSafari_HnW" / "MathSettings.xml"
    ).read_text(encoding="utf-8")
    wonder_text = (
        pack / "slot" / "themes" / "PR2_WondersOfIndia" / "MathSettings.xml"
    ).read_text(encoding="utf-8")
    assert "<int>4</int>" in safari_text
    assert "<int>12</int>" in safari_text
    assert "return_94_0" in safari_text
    assert "<int>1</int>" in wonder_text
    assert "<int>10</int>" in wonder_text
    assert "return_94_0" in wonder_text
    assert "<int>4</int>" not in wonder_text


def test_copy_bets_skips_incompatible_and_roulette() -> None:
    live = [
        _row("PR3_RedZone", bets=[1, 2, 3, 4, 5, 8, 10, 12, 15], rtp="return_92_0"),
        _row("BigSafari_HnW", bets=[4, 8, 12, 16], rtp="return_94_0"),
    ]
    form = clone_math_rows(live)
    form[0].bet_multipliers = [1, 2, 5]
    updated, skipped = copy_bet_steps_to_compatible(
        form, [1, 2, 5], live
    )
    assert skipped == ("BigSafari_HnW",)
    assert updated[0].bet_multipliers == [1, 2, 5]
    assert updated[1].bet_multipliers == [4, 8, 12, 16]
    assert receives_live_push_bet_steps("RouletteGame") is False


def test_set_rtp_only_where_allowed() -> None:
    rows = [
        _row(
            "PR3_RedZone",
            bets=[1, 2],
            rtp="return_92_0",
            allowed=["return_92_0", "return_94_0"],
        ),
        _row(
            "Frog",
            bets=[1, 2],
            rtp="return_frog_92_0",
            allowed=["return_frog_92_0", "return_frog_95_0"],
        ),
    ]
    updated, count = set_return_percent_where_allowed(rows, "return_94_0")
    assert count == 1
    assert updated[0].return_percent == "return_94_0"
    assert updated[1].return_percent == "return_frog_92_0"


def test_snapshot_and_change_lines_and_restart() -> None:
    live = SlotSetupRecipe(
        math=[
            _row("PR3_RedZone", bets=[1, 2, 5, 10], rtp="return_92_0"),
            _row("PR2_WondersOfIndia", bets=[1, 2, 5], rtp="return_92_0"),
        ]
    )
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.math[0].return_percent = "return_94_0"
    form.math[1].bet_multipliers = [1, 2]
    rows = dict(recipe_snapshot_rows(form))
    assert GAMES_MATH_LABEL in rows
    assert "PR3_RedZone=return_94_0" in rows[GAMES_MATH_LABEL]
    assert "PR2_WondersOfIndia=return_92_0[1,2]" in rows[GAMES_MATH_LABEL]
    lines = recipe_change_lines(live, form)
    assert any("RedZone" in line and "94.0%" in line for line in lines)
    assert any("WondersOfIndia" in line and "bets" in line for line in lines)
    assert live_push_restart_reason_for_label(GAMES_MATH_LABEL) == "game RTP or bet steps"
    from config_scanner.live_push import live_push_restart_required_reasons

    assert "game RTP or bet steps" in live_push_restart_required_reasons(live, form)
    assert bet_steps_changed(live.math, form.math)
    reasons = live_push_ramclear_reasons(live, form)
    assert any("bet" in r.casefold() for r in reasons)
    rtp_only = SlotSetupRecipe.from_dict(live.to_dict())
    rtp_only.math[0].return_percent = "return_94_0"
    assert live_push_ramclear_reasons(live, rtp_only) == ()
    assert "game RTP or bet steps" in live_push_restart_required_reasons(live, rtp_only)


def test_offered_steps_stay_on_theme_ladder() -> None:
    live = _row("BigSafari_HnW", bets=[4, 8, 12, 16], rtp="return_94_0")
    form = _row("BigSafari_HnW", bets=[4, 8], rtp="return_94_0")
    assert offered_bet_steps(form, live) == [4, 8, 12, 16]
    assert allowed_return_choices(live) == ["return_94_0"]


def test_rtp_blocked_when_mathsettings_missing(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = [_row("GhostTheme", bets=[1, 2], rtp="return_92_0", allowed=["return_92_0", "return_94_0"])]
    form = clone_math_rows(live)
    form[0].return_percent = "return_94_0"
    errors = theme_math_write_errors(gold, live, form)
    assert any("not present" in err and "GhostTheme" in err for err in errors)
    assert math_settings_unreadable_reason(gold, "GhostTheme")
    recipe_live = SlotSetupRecipe(math=live)
    recipe_form = SlotSetupRecipe(math=form)
    assert any(
        "not present" in err
        for err in validate_live_push_recipe(recipe_live, recipe_form, gold)
    )
    try:
        build_config_pack(recipe_form, gold, tmp_path / "missing-math-pack")
    except ValueError as exc:
        assert "not present" in str(exc)
    else:
        raise AssertionError("expected pack to refuse a missing MathSettings.xml")


def test_rtp_blocked_when_mathsettings_undecodable(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    safari = gold / "slot" / "themes" / "BigSafari_HnW" / "MathSettings.xml"
    safari.write_bytes(b"\x00\x01encrypted-math")
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.math[0].return_percent = "return_92_0"
    errors = theme_math_write_errors(gold, live.math, form.math)
    assert any("cannot be decoded" in err for err in errors)
    assert "cannot be decoded" in (math_settings_unreadable_reason(gold, "BigSafari_HnW") or "")
    reloaded = load_recipe_from_goldclub(gold, label="again")
    assert reloaded.math == []


def test_rtp_blocked_when_token_not_allowed_or_empty() -> None:
    live = [_row("PR3_RedZone", bets=[1, 2], rtp="return_92_0", allowed=["return_92_0"])]
    bad = clone_math_rows(live)
    bad[0].return_percent = "return_99_0"
    errors = theme_rtp_errors(live, bad)
    assert errors
    assert "AllowedReturnPercents" in errors[0]
    empty = clone_math_rows(live)
    empty[0].return_percent = ""
    assert any("cannot be empty" in err for err in theme_rtp_errors(live, empty))


def test_rtp_allowed_token_passes_when_file_readable(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.math[0].return_percent = "return_92_0"
    assert theme_math_write_errors(gold, live.math, form.math) == []
    result = validate_denom_configuration(live, form, gold)
    assert result.ok
