"""Live cabinet push: recipe diff + write + optional stack restart."""

from __future__ import annotations

from pathlib import Path

from config_scanner.jurisdiction import find_jurisdiction
from config_scanner.live_push import (
    DEFAULT_REMOTE_LIVE_TARGET,
    LIVE_FIELD_TOOLTIP_CHANGED,
    LIVE_FIELD_TOOLTIP_MATCH,
    commit_live_push,
    THIS_PC_GOLDCLUB,
    THIS_PC_MISSING_STATUS,
    default_live_cabinet_target,
    initial_live_cabinet_target,
    load_error_dialog_text,
    merge_live_target_history,
    this_pc_live_target,
    goldclub_stack_kind,
    live_field_file_hover,
    live_field_highlight_state,
    live_field_matches,
    live_field_tooltip,
    live_field_validation_errors,
    live_push_catalog,
    locale_defaults_for_currency,
    looks_like_goldclub_root,
    overlay_jurisdiction_recipe,
    prepare_live_goldclub,
    recipe_change_lines,
    recipe_from_market_id,
)
from config_scanner.slot_setup import (
    _unc_parent_is_host_only,
    load_recipe_from_goldclub,
    recipe_from_jurisdiction_profile,
)
from tests.test_slot_setup import _fake_goldclub


def test_recipe_change_lines_lists_only_diffs() -> None:
    before_prof = find_jurisdiction("puerto_rico")
    after_prof = find_jurisdiction("trinidad_ttd")
    assert before_prof is not None and after_prof is not None
    before = recipe_from_jurisdiction_profile(before_prof)
    after = recipe_from_jurisdiction_profile(after_prof)
    lines = recipe_change_lines(before, after)
    assert lines
    assert any("Currency" in line and "TTD" in line for line in lines)
    after.jurisdiction.magic_wheel_money_limit = 10000
    after.play_limits.jackpot_counters = 4
    limit_lines = recipe_change_lines(before, after)
    assert any("Magic wheel limit" in line and "10000" in line for line in limit_lines)
    assert any("Jackpot counters" in line and "4" in line for line in limit_lines)
    assert recipe_change_lines(before, before) == []


def test_overlay_keeps_live_dallas_and_sas_address(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    live.sas.address = 9
    live.sas.bonusing_controler = False
    live.door_switches.enabled = False
    live.ticket_protocol = "TRANSACT"
    preset_prof = find_jurisdiction("trinidad_ttd")
    assert preset_prof is not None
    preset = recipe_from_jurisdiction_profile(preset_prof)
    merged = overlay_jurisdiction_recipe(live, preset)
    assert merged.dallas.code == live.dallas.code
    assert merged.jurisdiction.currency_name == "TTD"
    assert merged.jurisdiction.currency_symbol
    assert merged.keyboard == live.keyboard
    assert merged.sas.address == 9
    assert merged.sas.bonusing_controler is False
    assert merged.door_switches.enabled is False
    assert merged.ticket_protocol == "TRANSACT"
    assert merged.jurisdiction.magic_wheel_money_limit == 5000
    assert merged.play_limits.jackpot_receipt_layout == "jackpotreceipt0"
    assert merged.denomination_list == live.denomination_list


def test_catalog_has_ready_currencies_and_locale_defaults() -> None:
    catalog = live_push_catalog()
    assert catalog["markets"][0] == "PuertoRico"
    assert "USD" in catalog["currencies"]
    from config_scanner.live_push import (
        CURRENCY_LABELS,
        market_combo_label,
        ordered_live_markets,
    )

    assert "Puerto Rico" in CURRENCY_LABELS["USD"]
    assert market_combo_label("PuertoRico").startswith("PuertoRico")
    assert "Puerto Rico" in market_combo_label("PuertoRico")
    assert ordered_live_markets(("Poland", "Jamaica", "PuertoRico"))[0] == "PuertoRico"
    assert ordered_live_markets(
        ("Poland", "Jamaica", "PuertoRico"),
        accepted=frozenset({"PuertoRico"}),
    ) == ("PuertoRico",)
    usd = locale_defaults_for_currency("USD")
    assert usd is not None
    assert usd.market == "PuertoRico"
    assert "TTD" in catalog["currencies"]
    assert "PEN" in catalog["currencies"]
    assert "en-TT" in catalog["cultures"]
    assert "English" in catalog["languages"]
    assert "TrinidadTobago" in catalog["markets"]
    assert "TT" in catalog["markets"]
    defaults = locale_defaults_for_currency("TTD")
    assert defaults is not None
    assert defaults.culture == "en-TT"
    assert defaults.language == "English"
    assert defaults.denoms
    pen = locale_defaults_for_currency("PEN")
    assert pen is not None
    assert pen.symbol == "S/"
    from config_scanner.live_push import locale_defaults_for_market

    poland = locale_defaults_for_market("Poland")
    assert poland is not None
    assert poland.currency == "PLN"
    assert poland.culture == "pl-PL"
    assert poland.language == "Polish"
    colombia = locale_defaults_for_market("Colombia")
    assert colombia is not None
    assert colombia.currency == "COP"
    trinidad = locale_defaults_for_market("TrinidadTobago")
    assert trinidad is not None
    assert trinidad.currency == "TTD"
    preset = recipe_from_market_id("trinidad_ttd")
    assert preset is not None
    assert preset.jurisdiction.currency_name == "TTD"
    assert preset.jurisdiction.magic_wheel_money_limit == 5000
    assert preset.play_limits.jackpot_receipt_layout == "jackpotreceipt0"
    assert preset.play_limits.cashout_button_mode == "Ticket"
    assert 5000 in [
        int(x) for x in live_push_catalog()["magic_wheel_limits"]
    ]


def test_default_live_target_prefers_local_goldclub(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    chosen = default_live_cabinet_target(
        local_candidates=(str(gold),),
        remote=r"\\10.0.0.111\slot",
    )
    assert str(chosen).replace("\\", "/").rstrip("/") == str(gold).replace("\\", "/").rstrip("/")


def test_initial_live_cabinet_target_saved_wins_over_local() -> None:
    assert (
        initial_live_cabinet_target(
            saved=r"\\10.0.0.90\c$\Goldclub",
            local=r"C:\Goldclub",
        )
        == r"\\10.0.0.90\c$\Goldclub"
    )


def test_initial_live_cabinet_target_uses_local_then_empty() -> None:
    assert initial_live_cabinet_target(saved="  ", local="G:") == "G:"
    assert initial_live_cabinet_target(saved="", local=None) == ""
    assert initial_live_cabinet_target() == ""


def test_merge_live_target_history_newest_first_deduped() -> None:
    merged = merge_live_target_history(
        r"\\10.0.0.98\c$\Goldclub",
        [
            r"\\10.0.0.90\c$\Goldclub",
            r"//10.0.0.98/c$/Goldclub",
            r"C:\Goldclub",
            "",
        ],
        limit=3,
    )
    assert merged == [
        r"\\10.0.0.98\c$\Goldclub",
        r"\\10.0.0.90\c$\Goldclub",
        r"C:\Goldclub",
    ]
    assert merge_live_target_history("", ["  ", r"C:\Goldclub"]) == [r"C:\Goldclub"]


def test_default_live_target_empty_when_no_local(tmp_path: Path) -> None:
    missing = tmp_path / "no-goldclub"
    chosen = default_live_cabinet_target(
        local_candidates=(str(missing),),
        remote="",
    )
    assert chosen == ""


def test_live_targets_for_typed_ip() -> None:
    from config_scanner.live_push import live_targets_for_ip, resolve_live_target_from_user

    assert live_targets_for_ip("10.0.0.98")[0] == r"\\10.0.0.98\c$\Goldclub"
    assert r"\\10.0.0.98\slot" in live_targets_for_ip("10.0.0.98")
    assert live_targets_for_ip(r"\\10.0.0.98\slot") == (r"\\10.0.0.98\slot",)
    assert resolve_live_target_from_user("10.0.0.76", probe=False) == (
        r"\\10.0.0.76\c$\Goldclub"
    )
    assert live_targets_for_ip("") == ()
    assert live_targets_for_ip("not-an-ip") == ()


def test_this_pc_live_target_none_when_not_a_cabinet(tmp_path: Path) -> None:
    missing = tmp_path / "no-goldclub"
    assert this_pc_live_target(local_candidates=(str(missing),)) is None
    assert "Goldclub" in THIS_PC_MISSING_STATUS
    assert THIS_PC_GOLDCLUB == r"C:\Goldclub"


def test_this_pc_live_target_finds_local_goldclub(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    assert Path(this_pc_live_target(local_candidates=(str(gold),))) == gold


def test_local_live_candidates_sweep_image_drives_after_c() -> None:
    from config_scanner.live_push import _LOCAL_LIVE_CANDIDATES, _local_candidate_path

    cands = [c.casefold() for c in _LOCAL_LIVE_CANDIDATES]
    assert cands[0] == "g:"
    assert cands.index(r"c:\goldclub") < cands.index(r"d:\goldclub")
    for drive in ("d:", "e:", "f:", "h:"):
        assert drive in cands
        assert rf"{drive}\goldclub" in cands
    assert not any(c.startswith("\\\\") for c in cands), "local sweep must stay local"
    assert _local_candidate_path("G:") == "G:\\"
    assert _local_candidate_path("d") == "d:\\"
    assert _local_candidate_path(r"C:\Goldclub") == r"C:\Goldclub"
    assert _local_candidate_path("/tmp/gold") == "/tmp/gold"


def test_default_111_and_this_pc_resolve_local_root_first(tmp_path: Path) -> None:
    from config_scanner.live_push import (
        is_default_remote_live_target,
        resolve_live_load_target,
    )

    gold = _fake_goldclub(tmp_path)
    cands = (str(tmp_path / "missing"), str(gold))

    assert is_default_remote_live_target(r"\\10.0.0.111\slot")
    assert is_default_remote_live_target(r"//10.0.0.111/slot/")
    assert not is_default_remote_live_target(r"\\10.0.0.90\c$\Goldclub")

    target, note = resolve_live_load_target(
        DEFAULT_REMOTE_LIVE_TARGET, prefer_local=True, local_candidates=cands
    )
    assert Path(target) == gold
    assert "10.0.0.111" in note and str(gold) in note

    target, note = resolve_live_load_target(
        THIS_PC_GOLDCLUB, prefer_local=True, local_candidates=cands
    )
    assert Path(target) == gold and note

    # Explicit cabinet paths are never swapped.
    explicit = r"\\10.0.0.90\c$\Goldclub"
    assert resolve_live_load_target(explicit, prefer_local=True, local_candidates=cands) == (
        explicit,
        "",
    )
    # Without a local tree the default stays .111.
    assert resolve_live_load_target(
        DEFAULT_REMOTE_LIVE_TARGET,
        prefer_local=True,
        local_candidates=(str(tmp_path / "missing"),),
    ) == (DEFAULT_REMOTE_LIVE_TARGET, "")
    assert resolve_live_load_target(
        DEFAULT_REMOTE_LIVE_TARGET, prefer_local=False, local_candidates=cands
    ) == (DEFAULT_REMOTE_LIVE_TARGET, "")


def test_load_live_cabinet_prefer_local_swaps_default(tmp_path: Path, monkeypatch) -> None:
    from config_scanner import live_push
    from config_scanner.live_push import load_live_cabinet

    gold = _fake_goldclub(tmp_path)
    monkeypatch.setattr(live_push, "_LOCAL_LIVE_CANDIDATES", (str(gold),))
    outcome = load_live_cabinet(DEFAULT_REMOTE_LIVE_TARGET, prefer_local=True)
    assert outcome.error == ""
    assert outcome.root == gold
    assert outcome.recipe is not None


def test_missing_local_path_explains_instead_of_cmdkey(tmp_path: Path) -> None:
    root, err = prepare_live_goldclub(str(tmp_path / "Goldclub"))
    assert root is None
    assert "on this PC" in err
    assert "slot\\themes" in err
    assert "Browse" in err
    assert "cmdkey" not in err


def test_load_error_dialog_text_never_blank() -> None:
    assert load_error_dialog_text("") == "Cannot load cabinet."
    assert load_error_dialog_text("   \n") == "Cannot load cabinet."
    assert load_error_dialog_text(None) == "Cannot load cabinet."
    assert load_error_dialog_text("Folder exists but is not a Goldclub root") == (
        "Folder exists but is not a Goldclub root"
    )


def test_live_field_matches_bill_protocol(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    live.bill_protocol = "JCM"
    same = type(live).from_dict(live.to_dict())
    matches = live_field_matches(live, same)
    assert matches["Bill protocol"] is True
    changed = type(live).from_dict(live.to_dict())
    changed.bill_protocol = "MEI"
    assert live_field_matches(live, changed)["Bill protocol"] is False
    assert live_field_matches(live, changed)["Currency"] is True
    live.ticket_protocol = "JCM"
    same.ticket_protocol = "JCM"
    assert live_field_matches(live, same)["Ticket printer"] is True
    changed.ticket_protocol = "TRANSACT"
    assert live_field_matches(live, changed)["Ticket printer"] is False


def test_live_field_highlight_state_and_tooltips() -> None:
    assert (
        live_field_highlight_state(
            matches_live=True, editable=True, cabinet_loaded=True
        )
        == "match"
    )
    assert (
        live_field_highlight_state(
            matches_live=False, editable=True, cabinet_loaded=True
        )
        == "changed"
    )
    assert (
        live_field_highlight_state(
            matches_live=False, editable=True, cabinet_loaded=False
        )
        == "editable"
    )
    assert (
        live_field_highlight_state(
            matches_live=False, editable=False, cabinet_loaded=True
        )
        == "none"
    )
    assert live_field_tooltip("match") == LIVE_FIELD_TOOLTIP_MATCH
    assert live_field_tooltip("changed") == LIVE_FIELD_TOOLTIP_CHANGED
    tip = live_field_tooltip(
        "changed", help_text="Currency name written to mgconfig."
    )
    assert "Currency name" in tip
    assert "Orange" in tip
    assert "\n\n" in tip
    assert "orange" in LIVE_FIELD_TOOLTIP_CHANGED.casefold()
    assert "green" in LIVE_FIELD_TOOLTIP_MATCH.casefold()
    assert (
        live_field_highlight_state(
            matches_live=True,
            editable=True,
            cabinet_loaded=True,
            invalid_reason="bad",
        )
        == "invalid"
    )
    assert "red" in live_field_tooltip("invalid", detail="Denom blocked").casefold()
    corrupt_tip = live_field_tooltip(
        "invalid",
        detail="UTF-8 cent",
        invalid_kind="corrupt",
    )
    assert "corrupt" in corrupt_tip.casefold()
    assert "?" in corrupt_tip
    with_files = live_field_tooltip(
        "changed",
        file_note="Cabinet files:\n• slot/themes/Link2WinFeature/Link2WinBonusMath.json",
    )
    assert "Link2WinBonusMath.json" in with_files


def test_hover_lists_live_link2win_when_denom_not_on_cabinet(tmp_path: Path) -> None:
    from config_scanner.denom_compat import find_staged_leaf_for_denom
    import shutil

    gold = _fake_goldclub(tmp_path)
    leaf = find_staged_leaf_for_denom(
        5, currency="TTD", market="TrinidadTobago", screens="3"
    )
    assert leaf is not None
    dest = gold / "slot/themes/Link2WinFeature"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        leaf / "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        dest / "Link2WinBonusMath.json",
    )
    note = live_field_file_hover("Denoms (cents)", gold, [10])
    assert "Link2WinBonusMath.json" in note
    assert "10c" in note or "does not include" in note
    assert "5c" in note
    assert live_field_file_hover("Denoms (cents)", gold, [5]) == ""


def test_live_option_help_covers_core_fields() -> None:
    from config_scanner.live_push import LIVE_OPTION_HELP

    required = {
        "Currency",
        "Denoms (cents)",
        "SAS enabled",
        "Bill protocol",
        "Bill notes",
        "Dallas key",
        "Display layout",
        "Credit limit",
        "Offline ticket",
        "Cabinet door auto unlock",
    }
    assert required <= set(LIVE_OPTION_HELP)
    assert all(LIVE_OPTION_HELP[k].strip() for k in required)


def test_display_text_anomalies_flags_cent_and_question() -> None:
    from config_scanner.live_push import display_text_anomalies

    assert display_text_anomalies("c") == ()
    assert display_text_anomalies("{0}c") == ()
    assert display_text_anomalies("$") == ()
    assert display_text_anomalies("5") == ()
    # Lab .76 (GameStar 3.0 Debug) runs <CurrencyBaseSymbol>¢< and paints
    # ``1¢`` on DENOM: a clean cent / euro glyph is NOT corruption.
    assert display_text_anomalies("¢") == ()
    assert display_text_anomalies("{0}¢") == ()
    assert display_text_anomalies("€") == ()
    q_hits = display_text_anomalies("5?¢")
    assert any("?" in h for h in q_hits)
    assert not any("cent" in h.casefold() for h in q_hits)
    assert display_text_anomalies("\ufffd") == ("Unicode replacement character",)
    # UTF-8 bytes re-read as cp1252 (the real ``?¢`` / ``Â¢`` on-screen garbage).
    moji = display_text_anomalies("Â¢")
    assert any("mojibake" in h for h in moji)
    assert not any("non-ASCII" in h for h in moji)
    assert any("mojibake" in h for h in display_text_anomalies("{0}â‚¬"))
    assert any("&cent;" in h for h in display_text_anomalies("{0}&cent;"))
    assert any("control" in h for h in display_text_anomalies("5\x01"))


def _puerto_rico_76_pair():
    """Live recipe shaped like lab .76 plus a form that only types ``1``."""
    from config_scanner.slot_setup import SlotSetupRecipe

    live = SlotSetupRecipe()
    live.denomination_list = [1, 2, 5, 10, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000]
    live.credit_rate_values = list(live.denomination_list)
    live.play_limits.show_denom_selector = False
    live.play_limits.magic_wheel_bet = 40
    live.play_limits.magic_wheel_average = 100
    live.jurisdiction.currency_name = "USD"
    live.jurisdiction.currency_symbol = "$"
    live.jurisdiction.tag = "PuertoRico"
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.denomination_list = [1]
    form.credit_rate_values = [1]
    return live, form


def test_denoms_effectively_equal_selector_off() -> None:
    from config_scanner.live_push import (
        denoms_effectively_equal,
        live_push_ramclear_reasons,
        normalize_effective_denoms,
    )

    live, form = _puerto_rico_76_pair()
    assert denoms_effectively_equal(live, form) is True
    assert live_field_matches(live, form)["Denoms (cents)"] is True
    assert "denomination list" not in live_push_ramclear_reasons(live, form)

    # Restating the live denom keeps the cabinet's own catalog on Apply.
    normalized = normalize_effective_denoms(live, form)
    assert normalized.denomination_list == live.denomination_list
    assert normalized.credit_rate_values == live.credit_rate_values

    # A different playable denom is a real change.
    live2, other = _puerto_rico_76_pair()
    other.denomination_list = [5]
    other.credit_rate_values = [5]
    assert denoms_effectively_equal(live2, other) is False
    assert live_field_matches(live2, other)["Denoms (cents)"] is False
    assert "denomination list" in live_push_ramclear_reasons(live2, other)
    assert normalize_effective_denoms(live2, other).denomination_list == [5]

    # Selector on: every listed denom plays, so ``1`` alone IS a change.
    live3, sel = _puerto_rico_76_pair()
    live3.play_limits.show_denom_selector = True
    sel.play_limits.show_denom_selector = True
    assert denoms_effectively_equal(live3, sel) is False

    # Empty form list never counts as equal to a populated live list.
    live4, empty = _puerto_rico_76_pair()
    empty.denomination_list = []
    assert denoms_effectively_equal(live4, empty) is False


def test_validate_denom_configuration_uses_playable_denoms(tmp_path: Path) -> None:
    from config_scanner.denom_compat import validate_denom_configuration

    gold = _fake_goldclub(tmp_path)
    live, form = _puerto_rico_76_pair()
    result = validate_denom_configuration(live, form, gold)
    assert result.denom_changed is False
    live2, other = _puerto_rico_76_pair()
    other.denomination_list = [5]
    other.credit_rate_values = [5]
    assert validate_denom_configuration(live2, other, gold).denom_changed is True


def test_split_live_proven_errors_demotes_baseline_only_when_unchanged() -> None:
    from config_scanner.live_push import split_live_proven_errors

    baseline = [
        "Denom 1c is not allowed for USD (allowed: 5, 10, 25).",
        "Live Link2Win math on the cabinet does not include 1c.",
    ]
    errors = list(baseline) + ["Bet multiplier 7 is not a preset."]
    # Nothing changed: baseline errors are advisory, the new one blocks.
    matches = {"Denoms (cents)": True, "Bet multipliers": False}
    blocking, advisory = split_live_proven_errors(
        errors, baseline=baseline, matches=matches
    )
    assert blocking == ["Bet multiplier 7 is not a preset."]
    assert advisory == baseline
    # Same message but the Denoms field was edited: stays red.
    blocking2, advisory2 = split_live_proven_errors(
        errors, baseline=baseline, matches={"Denoms (cents)": False}
    )
    assert blocking2 == errors
    assert advisory2 == []
    # Baseline message not attached to any field -> advisory.
    blocking3, advisory3 = split_live_proven_errors(
        ["odd rule"], baseline=["odd rule"], matches={}
    )
    assert blocking3 == [] and advisory3 == ["odd rule"]


def test_validate_live_push_blocking_uses_cabinet_baseline(
    tmp_path: Path, monkeypatch
) -> None:
    import config_scanner.live_push as lp

    gold = _fake_goldclub(tmp_path)
    live, form = _puerto_rico_76_pair()

    def fake_validate(live_r, proposed, root):
        if proposed.denomination_list[0] == 250:
            return ["Denom 250c is not allowed for USD (allowed: 1, 5)."]
        return ["Live Link2Win math on the cabinet does not include 1c."]

    monkeypatch.setattr(lp, "validate_live_push_recipe", fake_validate)
    blocking, advisory = lp.validate_live_push_blocking(live, form, gold)
    assert blocking == []
    assert advisory == ["Live Link2Win math on the cabinet does not include 1c."]
    assert lp.live_field_validation_errors(blocking) == {}

    bad = type(form).from_dict(form.to_dict())
    bad.denomination_list = [250]
    bad.credit_rate_values = [250]
    blocking2, advisory2 = lp.validate_live_push_blocking(live, bad, gold)
    assert blocking2 == ["Denom 250c is not allowed for USD (allowed: 1, 5)."]
    assert advisory2 == []
    assert "Denoms (cents)" in lp.live_field_validation_errors(blocking2)

    # Cached baseline is honoured (no re-validation of the live recipe).
    blocking3, advisory3 = lp.validate_live_push_blocking(
        live, form, gold, baseline=[]
    )
    assert blocking3 == ["Live Link2Win math on the cabinet does not include 1c."]
    assert advisory3 == []


def test_split_display_corruption_live_scan_is_advisory() -> None:
    from config_scanner.live_push import split_display_corruption

    live_scan = {"Denoms (cents)": "jurisdiction_config.xml: literal '?'"}
    form_scan = {"Currency symbol": "literal '?'", "Denoms (cents)": "literal '?'"}
    red, advisory = split_display_corruption(
        live_scan,
        form_scan,
        matches={"Currency symbol": False, "Denoms (cents)": True},
    )
    assert red == {"Currency symbol": "literal '?'"}
    assert advisory["Denoms (cents)"].startswith("jurisdiction_config.xml")
    assert "Currency symbol" not in advisory


def test_live_field_highlight_advisory_state_and_tooltip() -> None:
    from config_scanner.live_push import LIVE_FIELD_TOOLTIP_ADVISORY

    assert (
        live_field_highlight_state(
            matches_live=True,
            editable=True,
            cabinet_loaded=True,
            advisory_reason="Live Link2Win math does not include 1c.",
        )
        == "advisory"
    )
    # Blocking always wins over advisory.
    assert (
        live_field_highlight_state(
            matches_live=True,
            editable=True,
            cabinet_loaded=True,
            invalid_reason="bad",
            advisory_reason="doubt",
        )
        == "invalid"
    )
    tip = live_field_tooltip("advisory", detail="Live Link2Win math does not include 1c.")
    assert tip.startswith(LIVE_FIELD_TOOLTIP_ADVISORY)
    assert "amber" in tip.casefold()
    assert "not blocking" in tip.casefold()
    assert "Link2Win" in tip


def test_live_display_corruption_errors_paints_denoms(tmp_path: Path) -> None:
    from config_scanner.live_push import (
        LIVE_FIELD_CONFIG_RELS,
        live_display_corruption_errors,
        recipe_display_corruption_errors,
        resolve_live_field_config_files,
    )
    from config_scanner.slot_setup import SlotSetupRecipe

    gold = _fake_goldclub(tmp_path)
    assert live_display_corruption_errors(gold) == {}
    jur = gold / "slot" / "themes" / "jurisdiction_config.xml"
    text = jur.read_text(encoding="utf-8")
    text = text.replace(
        "<CurrencySymbol>$</CurrencySymbol>",
        "<CurrencySymbol>$</CurrencySymbol>\n"
        "    <CurrencyBaseSymbol>\u00a2</CurrencyBaseSymbol>\n"
        "    <CurrencyBaseFormat>{0}\u00a2</CurrencyBaseFormat>",
    )
    jur.write_text(text, encoding="utf-8")
    # Clean UTF-8 cent in a utf-8 XML: lab .76 runs exactly this and shows 1¢.
    assert live_display_corruption_errors(gold) == {}

    # Real garbage (literal '?' from an ANSI re-save) is still found, and a
    # cent-tag finding paints DENOM only — never the ``$`` symbol field.
    jur.write_text(
        text.replace("{0}\u00a2", "{0}?\u00a2"), encoding="utf-8"
    )
    errs = live_display_corruption_errors(gold)
    assert "Denoms (cents)" in errs
    assert "Currency symbol" not in errs
    assert "?" in errs["Denoms (cents)"]

    recipe = SlotSetupRecipe()
    recipe.jurisdiction.currency_symbol = "5?"
    form_errs = recipe_display_corruption_errors(recipe)
    assert form_errs["Currency symbol"]
    assert form_errs["Denoms (cents)"]

    assert "Denoms (cents)" in LIVE_FIELD_CONFIG_RELS
    assert "Credit limit" in LIVE_FIELD_CONFIG_RELS
    paths = resolve_live_field_config_files(gold, "Denoms (cents)")
    names = {p.name.casefold() for p in paths}
    assert "mgconfig.xml" in names
    assert "jurisdiction_config.xml" in names
    sas_paths = resolve_live_field_config_files(gold, "SAS address")
    # Fake goldclub may omit Aurum ClientsSet; function must not raise.
    assert isinstance(sas_paths, list)


def test_live_display_corruption_ignores_denom_in_currency_flag(tmp_path: Path) -> None:
    """DisplayDenomInCurrency=true with ASCII 'c' is valid (game shows 5c)."""
    from config_scanner.live_push import live_display_corruption_errors

    gold = _fake_goldclub(tmp_path)
    jur = gold / "slot" / "themes" / "jurisdiction_config.xml"
    text = jur.read_text(encoding="utf-8")
    text = text.replace(
        "</CurrencyDisplaySettings>",
        "    <CurrencyBaseSymbol>c</CurrencyBaseSymbol>\n"
        "    <CurrencyBaseFormat>{0}c</CurrencyBaseFormat>\n"
        "  </CurrencyDisplaySettings>\n"
        "  <DenominationDisplay>\n"
        "    <SingleDenomination>5</SingleDenomination>\n"
        "    <DisplayDenomWithCurrencySymbol>true</DisplayDenomWithCurrencySymbol>\n"
        "    <DisplayDenomInCurrency>true</DisplayDenomInCurrency>\n"
        "  </DenominationDisplay>",
    )
    jur.write_text(text, encoding="utf-8")
    assert live_display_corruption_errors(gold) == {}


def test_live_push_panel_wires_corrupt_and_notepad() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "_install_field_file_menus" in src
    assert "Open" in src and "Notepad" in src
    assert "recipe_display_corruption_errors" in src
    assert "open_with_notepad" in src
    assert "invalid_kind" in src
    # Live-proven baseline: advisory (amber) path is wired, Apply uses blocking only.
    assert "validate_live_push_blocking" in src
    assert "live_baseline_validation_errors" in src
    assert "split_display_corruption" in src
    assert "live_advisory_field_stylesheet" in src
    assert 'state == "advisory"' in src
    assert "normalize_effective_denoms" in src
    assert "validate_live_push_recipe(" not in src


def test_open_with_notepad_rejects_missing(tmp_path: Path) -> None:
    from gui.notepad_pp import open_with_notepad

    ok, msg = open_with_notepad(tmp_path / "missing.xml")
    assert ok is False
    assert "not found" in msg.casefold() or "supported" in msg.casefold()
    empty_ok, empty_msg = open_with_notepad("")
    assert empty_ok is False
    assert empty_msg


def test_live_push_chrome_has_tooltips() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "self._restart.setToolTip(" in src
    assert "self._backup.setToolTip(" in src
    assert "self._backup.setChecked(False)" in src
    assert "self._restore_backup" in src
    assert "_restore_backup_clicked" in src
    assert "self._full_pack.setToolTip(" in src
    assert "self._commit.setToolTip(" in src
    assert "LIVE_OPTION_HELP.get" in src
    assert "delta" in src.casefold() or "differ from the cabinet" in src
    assert "_install_label_click_tips" in src
    assert "mouse_release_shows_tip" in src
    assert r"\\host\slot  or  C:\Goldclub" in src
    assert '("10.0.0.90"' not in src
    assert '("10.0.0.98"' not in src
    assert '("10.0.0.111"' not in src
    assert "initial_live_cabinet_target" in src
    # Remembering goes through the helper shared with Snapshots, so both
    # screens open on the cabinet used last on either of them.
    assert "remember_shared_cabinet_target(" in src
    assert "def sync_cabinet_from_settings" in src
    assert "discover_active_lab_fleet" in src
    assert "_start_fleet_scan" in src


def test_home_and_wizard_tooltips() -> None:
    home = (
        Path(__file__).resolve().parents[1] / "gui" / "simple_home.py"
    ).read_text(encoding="utf-8")
    wiz = (
        Path(__file__).resolve().parents[1] / "gui" / "jurisdiction_wizard.py"
    ).read_text(encoding="utf-8")
    assert "create_btn.setToolTip" in home
    assert "restore_btn.setToolTip" in home
    assert "push_btn.setToolTip" in home
    assert "_juris_combo.setToolTip" in wiz
    assert "_pack_combo.setToolTip" in wiz
    assert "export_btn.setToolTip" in wiz


def test_live_field_validation_errors_map_denoms_and_magic_wheel() -> None:
    errors = [
        "Magic wheel must match the new denom (5c bet, 25c average).",
        "Bet multipliers do not match any approved bet setup for this market.",
        "Live Link2WinBonusMath.json on the cabinet does not include 10c.",
    ]
    mapped = live_field_validation_errors(errors)
    assert "Denoms (cents)" in mapped
    assert "Magic wheel bet" in mapped
    assert "Bet multipliers" in mapped
    math_only = live_field_validation_errors(
        ["Live Link2WinBonusMath.json on the cabinet does not include 10c."]
    )
    assert "10c" in math_only["Denoms (cents)"]


def test_goldclub_root_helpers(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    assert looks_like_goldclub_root(gold)
    assert goldclub_stack_kind(gold) == "slot"
    root, err = prepare_live_goldclub(str(gold))
    assert err == ""
    assert root == gold
    missing, missing_err = prepare_live_goldclub("")
    assert missing is None
    assert "Enter" in missing_err
    assert _unc_parent_is_host_only(Path(r"\\10.0.0.111"))
    assert not _unc_parent_is_host_only(Path(r"\\10.0.0.111\slot"))
    assert not _unc_parent_is_host_only(gold / "slot")


def test_prepare_live_goldclub_retries_1326_then_explains(monkeypatch) -> None:
    from config_scanner.live_push import prepare_live_goldclub

    monkeypatch.setattr(
        "config_scanner.live_push.cabinet_host_reachable",
        lambda *_a, **_k: (True, ""),
    )
    dropped: list[str] = []
    monkeypatch.setattr(
        "network.lab_access.drop_lab_smb_sessions", dropped.append
    )
    monkeypatch.setattr("config_scanner.live_push._ensure_lab_smb", lambda _h: None)
    n = {"n": 0}

    def boom(_target: str):
        n["n"] += 1
        exc = OSError(1326, r"The user name or password is incorrect: '\\10.0.0.111\slot\'")
        exc.winerror = 1326
        raise exc

    monkeypatch.setattr("config_scanner.live_push.goldclub_root_from_target", boom)
    root, err = prepare_live_goldclub(r"\\10.0.0.111\slot")
    assert root is None
    assert dropped == ["10.0.0.111"]
    assert n["n"] == 2
    assert r"10.0.0.111\test" in err
    assert "workgroup" in err.casefold()


def test_ensure_lab_smb_runs_for_unknown_lab_lan(monkeypatch) -> None:
    from config_scanner import live_push

    seen: list[str] = []
    monkeypatch.setattr(
        "network.lab_access.ensure_lab_smb_credential",
        lambda ip: seen.append(ip) or True,
    )
    live_push._ensure_lab_smb("10.0.0.76")
    assert seen == ["10.0.0.76"]
    seen.clear()
    live_push._ensure_lab_smb("8.8.8.8")
    assert seen == []


def test_commit_writes_without_stack(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.jurisdiction.currency_name = "TTD"
    recipe.hardware_currency_name = "TTD"
    recipe.sas.address = 7

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "unknown")
    monkeypatch.setattr("config_scanner.live_push.plan_stack_restart", lambda _t: None)
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        work_parent=tmp_path / "work",
    )
    assert not result.errors
    assert result.written
    assert result.stack_killed is False
    assert result.stack_started is False
    hw = (gold / "slot" / "themes" / "HardwareConfig.xml").read_text(encoding="utf-8")
    assert "TTD" in hw


def test_commit_kills_then_writes_then_starts(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.sas.address = 4
    order: list[str] = []

    class _Plan:
        mode = "local"
        host = None
        kill_ps1 = "kill"
        run_ps1 = "run"

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "roulette")
    monkeypatch.setattr(
        "config_scanner.live_push.plan_stack_restart", lambda _t: _Plan()
    )

    def _kill(_plan):
        order.append("kill")
        return True, "killed"

    def _start(_plan, **kwargs):
        order.append("start")
        return True, "started"

    monkeypatch.setattr("config_scanner.live_push.run_stack_kill", _kill)
    monkeypatch.setattr("config_scanner.live_push.run_stack_start", _start)

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        work_parent=tmp_path / "work",
    )
    assert result.ok
    assert order == ["kill", "start"]
    assert result.stack_killed is True
    assert result.stack_started is True
    assert result.written


def test_commit_pack_error_does_not_stop_game(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.sas.address = 4
    order: list[str] = []

    class _Plan:
        mode = "local"
        host = None
        kill_ps1 = "kill"
        run_ps1 = "run"

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "roulette")
    monkeypatch.setattr(
        "config_scanner.live_push.plan_stack_restart", lambda _t: _Plan()
    )
    monkeypatch.setattr(
        "config_scanner.live_push.build_config_pack",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("no matching Bet/Denom math file")),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_stack_kill",
        lambda _p: order.append("kill") or (True, "killed"),
    )
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        work_parent=tmp_path / "work",
    )
    assert result.errors
    assert "Bet/Denom" in result.errors[0]
    assert order == []
    assert result.stack_killed is False
    assert not result.written


def test_commit_kill_failure_is_an_error(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.sas.address = 9

    class _Plan:
        mode = "local"
        host = None
        kill_ps1 = "kill"
        run_ps1 = "run"

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "roulette")
    monkeypatch.setattr("config_scanner.live_push.plan_stack_restart", lambda _t: _Plan())
    monkeypatch.setattr(
        "config_scanner.live_push.run_stack_kill", lambda _p: (False, "elevate missing")
    )
    result = commit_live_push(recipe, gold, restart_stack=True, work_parent=tmp_path / "work")
    assert result.errors
    assert "elevate missing" in result.errors[0]
    assert not result.written


def test_commit_delta_inactivity_only_writes_mgconfig(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    assert recipe.mg_identity.inactivity_seconds_to_game_selector != 30
    recipe.mg_identity.inactivity_seconds_to_game_selector = 30

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "unknown")
    monkeypatch.setattr("config_scanner.live_push.plan_stack_restart", lambda _t: None)
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        work_parent=tmp_path / "work",
        backup=True,
    )
    assert result.ok
    assert result.sections == ("mgconfig",)
    assert len(result.written) == 1
    assert "mgconfig.xml" in result.written[0].replace("\\", "/").casefold()
    assert result.backup_dir
    assert Path(result.backup_dir).is_dir()
    mg = (gold / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8")
    assert "InactivitySecondsToGameSelector>30<" in mg.replace(" ", "")


def test_commit_skips_backup_by_default(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.mg_identity.inactivity_seconds_to_game_selector = 30

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "unknown")
    monkeypatch.setattr("config_scanner.live_push.plan_stack_restart", lambda _t: None)
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        work_parent=tmp_path / "work",
    )
    assert result.ok
    assert result.written
    assert not result.backup_dir


def test_commit_no_change_aborts_without_write(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    result = commit_live_push(recipe, gold, restart_stack=False, work_parent=tmp_path / "work")
    assert result.errors
    assert "Nothing changed" in result.errors[0]
    assert not result.written


def test_commit_full_pack_writes_without_delta(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "unknown")
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        work_parent=tmp_path / "work",
        full_pack=True,
        backup=False,
    )
    assert result.ok
    assert result.written
    assert result.sections == ()


def test_slot_start_script_falls_back_to_start_process() -> None:
    from config_scanner.live_push import _slot_start_script

    script = _slot_start_script((r"G:\Bootstrap.exe",))
    assert "Start-ScheduledTask" in script
    assert "Start-Process" in script
    assert "Live Push started BiOS2 menu instead of OneHand" in script
    assert "OneHand did not start after Bootstrap" in script


def test_game_start_exe_candidates_for_c_dollar_slot() -> None:
    from config_scanner.live_push import game_start_exe_candidates

    found = game_start_exe_candidates(
        r"\\10.0.0.98\c$\Goldclub\slot",
        dest=r"\\10.0.0.98\c$\Goldclub\slot",
    )
    assert r"C:\Goldclub\slot\game-start.exe" in found
    assert r"G:\slot\game-start.exe" in found
    gold_root = game_start_exe_candidates(
        r"\\10.0.0.98\c$\Goldclub",
        dest=r"\\10.0.0.98\c$\Goldclub",
    )
    assert r"C:\Goldclub\slot\game-start.exe" in gold_root


def test_slot_start_script_release_uses_game_start_not_onehand() -> None:
    from config_scanner.live_push import _slot_start_script

    script = _slot_start_script(
        (r"C:\Goldclub\slot\game-start.exe",),
        launcher="game-start",
    )
    assert r"C:\Goldclub\slot\game-start.exe" in script
    assert "game-start.exe not found" in script
    assert "OneHand did not start after game-start" in script
    assert "OneHand did not start after Bootstrap" not in script
    assert "Bootstrap.exe did not start" not in script
    assert "Get-Process -Name Bootstrap" not in script
    assert "-FilePath OneHand.exe" not in script
    assert "-Execute OneHand.exe" not in script


def test_slot_start_launcher_release_vs_debug(monkeypatch, tmp_path: Path) -> None:
    from config_scanner.build_version import OneHandBuildInfo
    from config_scanner.live_push import slot_start_launcher

    gold = tmp_path / "Goldclub"
    gold.mkdir()
    monkeypatch.setattr(
        "config_scanner.live_push.detect_onehand_build",
        lambda _r: OneHandBuildInfo(version="2.0.1", configuration="Release"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.goldclub_root_from_target",
        lambda _p: gold,
    )
    assert slot_start_launcher(str(gold)) == "game-start"
    monkeypatch.setattr(
        "config_scanner.live_push.detect_onehand_build",
        lambda _r: OneHandBuildInfo(version="2.0.1", configuration="Debug"),
    )
    assert slot_start_launcher(str(gold)) == "bootstrap"
    monkeypatch.setattr(
        "config_scanner.live_push.detect_onehand_build",
        lambda _r: None,
    )
    assert slot_start_launcher(str(gold)) == "bootstrap"
    monkeypatch.setattr(
        "config_scanner.live_push.detect_onehand_build",
        lambda _r: (_ for _ in ()).throw(OSError("smb down")),
    )
    assert slot_start_launcher(str(gold)) == "bootstrap"


def test_watchdog_release_starts_game_start() -> None:
    from config_scanner.live_push import _slot_bootstrap_watchdog_script

    wd = _slot_bootstrap_watchdog_script(
        (r"G:\slot\game-start.exe",),
        launcher="game-start",
    )
    assert r"G:\slot\game-start.exe" in wd
    assert "OneHand,game-start" in wd
    assert "Bootstrap,OneHand" not in wd


def test_live_push_changed_sections_maps_labels() -> None:
    from config_scanner.live_push import live_push_changed_sections

    before_prof = find_jurisdiction("puerto_rico")
    after_prof = find_jurisdiction("trinidad_ttd")
    assert before_prof is not None and after_prof is not None
    live = recipe_from_jurisdiction_profile(before_prof)
    form = recipe_from_jurisdiction_profile(after_prof)
    sections = live_push_changed_sections(live, form)
    assert "mgconfig" in sections
    assert "jurisdiction" in sections
    assert "hardware" in sections
    assert "aurum" in sections


def test_sas_channel_and_switch_snapshot_sections() -> None:
    from config_scanner.live_push import (
        LIVE_OPTION_HELP,
        live_push_changed_sections,
        recipe_snapshot_rows,
    )
    from config_scanner.slot_setup import SlotSetupRecipe

    live = SlotSetupRecipe()
    form = SlotSetupRecipe()
    form.sas.validation_controler = False
    form.door_switches.enabled = False
    rows = dict(recipe_snapshot_rows(form))
    assert rows["Validation controler"] == "off"
    assert rows["Enable switches"] == "off"
    sections = live_push_changed_sections(live, form)
    assert "sas" in sections
    assert "aurum" in sections
    assert "hardware" in sections
    assert "Validation controler" in LIVE_OPTION_HELP
    assert "Enable switches" in LIVE_OPTION_HELP
    assert "Cabinet door auto unlock" in LIVE_OPTION_HELP
    assert "Stacker auto-unlock" in LIVE_OPTION_HELP
    form.door_switches.set_auto_unlock("cabinet_door", True)
    rows = dict(recipe_snapshot_rows(form))
    assert rows["Cabinet door auto unlock"] == "on"
    assert rows["Logic door auto unlock"] == "off"
    assert rows["Stacker auto-unlock"] == "on"


def test_bill_notes_snapshot_and_hardware_section() -> None:
    from config_scanner.live_push import (
        live_field_matches,
        live_push_changed_sections,
        recipe_snapshot_rows,
    )
    from config_scanner.slot_setup import BillToken, SlotSetupRecipe

    live = SlotSetupRecipe(
        bill_tokens=[
            BillToken(code="97", value=100, can_accept=True),
            BillToken(code="102", value=10000, can_accept=True),
        ]
    )
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.bill_tokens[1].can_accept = False
    rows = dict(recipe_snapshot_rows(form))
    assert "102=10000:off" in rows["Bill notes"]
    assert live_field_matches(live, form)["Bill notes"] is False
    assert live_field_matches(live, live)["Bill notes"] is True
    assert live_push_changed_sections(live, form) == frozenset({"hardware"})


def test_live_push_ramclear_reasons_currency_and_denoms() -> None:
    from config_scanner.live_push import live_push_ramclear_reasons
    from config_scanner.slot_setup import SlotSetupRecipe

    live = SlotSetupRecipe()
    live.jurisdiction.currency_name = "TTD"
    live.hardware_currency_name = "TTD"
    live.denomination_list = [2, 5, 10]
    live.play_limits.bet_multipliers = [1, 2, 5]

    form = SlotSetupRecipe()
    form.jurisdiction.currency_name = "USD"
    form.hardware_currency_name = "USD"
    form.denomination_list = [1, 2, 5]
    form.play_limits.bet_multipliers = [1, 2, 10]

    reasons = live_push_ramclear_reasons(live, form)
    assert any("currency" in r.casefold() for r in reasons)
    assert any("denomination" in r.casefold() for r in reasons)
    assert any("bet" in r.casefold() for r in reasons)


def test_live_push_ramclear_reasons_empty_aurum() -> None:
    from config_scanner.live_push import live_push_ramclear_reasons
    from config_scanner.slot_setup import SlotSetupRecipe

    live = SlotSetupRecipe()
    live.jurisdiction.currency_name = "USD"
    form = SlotSetupRecipe()
    form.jurisdiction.currency_name = "USD"
    reasons = live_push_ramclear_reasons(live, form, aurum_currency="")
    assert any("aurum" in r.casefold() and "missing" in r.casefold() for r in reasons)


def test_pick_onehand_allowed_market_prefers_stable() -> None:
    from config_scanner.slot_setup import pick_onehand_allowed_market

    assert (
        pick_onehand_allowed_market(
            {"Jamaica", "PuertoRico", "Colombia"}, preferred="Jamaica"
        )
        == "Jamaica"
    )
    assert (
        pick_onehand_allowed_market(
            {"Colombia", "PuertoRico"}, preferred="Jamaica"
        )
        == "PuertoRico"
    )
    assert pick_onehand_allowed_market({"ZZZ", "AAA"}, preferred="Nope") == "AAA"


def test_patch_aurum_currency_syncs_code_and_id(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        AurumIdentitySettings,
        patch_aurum_setup_placeholders,
        read_aurum_currency_code,
    )

    src = tmp_path / "AurumSetup.xml"
    src.write_text(
        '<?xml version="1.0"?>\n'
        "<AurumSetupData>\n"
        "  <CurrencyTable><CurrencyCode>TTD</CurrencyCode></CurrencyTable>\n"
        "  <ProcessorConfig><CurrencyId>TTD</CurrencyId></ProcessorConfig>\n"
        "  <NetworkHostName>GST22377</NetworkHostName>\n"
        "</AurumSetupData>\n",
        encoding="utf-8",
    )
    dest = tmp_path / "out.xml"
    patch_aurum_setup_placeholders(
        src,
        dest,
        AurumIdentitySettings(network_hostname_template="GST22377"),
        currency_code="USD",
    )
    text = dest.read_text(encoding="utf-8")
    assert "<CurrencyCode>USD</CurrencyCode>" in text
    assert "<CurrencyId>USD</CurrencyId>" in text
    assert read_aurum_currency_code(tmp_path) == ""  # not at goldclub layout
    # Place under Services/aurum/config for the reader helper
    laid = tmp_path / "gc" / "Services" / "aurum" / "config"
    laid.mkdir(parents=True)
    (laid / "AurumSetup.xml").write_text(text, encoding="utf-8")
    assert read_aurum_currency_code(tmp_path / "gc") == "USD"


def test_patch_aurum_creates_missing_currency_leaves(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        AurumIdentitySettings,
        patch_aurum_setup_placeholders,
    )

    src = tmp_path / "AurumSetup.xml"
    src.write_text(
        '<?xml version="1.0"?>\n'
        "<AurumSetupData>\n"
        "  <NetworkHostName>GST22377</NetworkHostName>\n"
        "</AurumSetupData>\n",
        encoding="utf-8",
    )
    dest = tmp_path / "out.xml"
    patch_aurum_setup_placeholders(
        src,
        dest,
        AurumIdentitySettings(),
        currency_code="USD",
    )
    text = dest.read_text(encoding="utf-8")
    assert "<CurrencyCode>USD</CurrencyCode>" in text
    assert "<CurrencyId>USD</CurrencyId>" in text


def test_commit_currency_change_runs_ramclear(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    # Fake goldclub ships USD; push TTD so currency delta + ramclear fire.
    recipe.jurisdiction.currency_name = "TTD"
    recipe.hardware_currency_name = "TTD"
    order: list[str] = []

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_kill",
        lambda *_a, **_k: (order.append("kill") or True, "stopped"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_ramclear",
        lambda *_a, **_k: (order.append("ramclear") or True, "ramclear ok"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.restart_slot_hwsubsys",
        lambda *_a, **_k: (order.append("hwsubsys") or True, "HWSubsys Running"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_start",
        lambda *_a, **_k: (order.append("start") or True, "bootstrap"),
    )

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        scan_target=str(gold),
        work_parent=tmp_path / "work",
        backup=False,
    )
    assert result.ok, result.errors
    assert result.ramclear_ran
    assert order == ["kill", "ramclear", "hwsubsys", "kill", "start"]


def test_commit_ramclear_forces_restart_when_unchecked(
    tmp_path: Path, monkeypatch
) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.jurisdiction.currency_name = "TTD"
    recipe.hardware_currency_name = "TTD"
    order: list[str] = []

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_kill",
        lambda *_a, **_k: (order.append("kill") or True, "stopped"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_ramclear",
        lambda *_a, **_k: (order.append("ramclear") or True, "ramclear ok"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.restart_slot_hwsubsys",
        lambda *_a, **_k: (order.append("hwsubsys") or True, "HWSubsys Running"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_start",
        lambda *_a, **_k: (order.append("start") or True, "bootstrap"),
    )

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        scan_target=str(gold),
        work_parent=tmp_path / "work2",
        backup=False,
    )
    assert result.ok, result.errors
    assert result.ramclear_ran
    assert result.stack_started
    assert order == ["kill", "ramclear", "hwsubsys", "kill", "start"]


def test_commit_slot_uses_bootstrap_not_ruleta(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.sas.address = 3
    order: list[str] = []

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")

    def _kill(_target):
        order.append("slot-kill")
        return True, "stopped"

    def _start(_target, dest=None):
        order.append("slot-start")
        return True, "bootstrap"

    monkeypatch.setattr("config_scanner.live_push.run_slot_stack_kill", _kill)
    monkeypatch.setattr("config_scanner.live_push.run_slot_stack_start", _start)
    monkeypatch.setattr(
        "config_scanner.live_push.restart_slot_hwsubsys",
        lambda *_a, **_k: (order.append("hwsubsys") or True, "hw ok"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_stack_kill",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("roulette kill")),
    )

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        scan_target=str(gold),
        work_parent=tmp_path / "work",
    )
    assert result.ok
    assert order == ["slot-kill", "hwsubsys", "slot-kill", "slot-start"]
    assert result.stack_killed is True
    assert result.stack_started is True
    assert result.written


def test_commit_pushes_missing_licences_from_licenses_dir(
    tmp_path: Path, monkeypatch
) -> None:
    gold = _fake_goldclub(tmp_path)
    (gold / "Licenses").mkdir()
    xml_name = "Licence12-12262688_447_24234.xml"
    (gold / "Licenses" / xml_name).write_text(
        "<Licence><SerialNumber>20664</SerialNumber></Licence>",
        encoding="utf-8",
    )
    recipe = load_recipe_from_goldclub(gold, label="live")
    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "unknown")
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        work_parent=tmp_path / "work",
        push_licences=True,
        backup=False,
    )
    assert result.ok
    assert "licence" in result.sections
    assert f"slot/{xml_name}" in result.written
    assert (gold / "slot" / xml_name).is_file()


def test_commit_skips_licence_push_when_onehand_already_has_xml(
    tmp_path: Path,
) -> None:
    gold = _fake_goldclub(tmp_path)
    (gold / "slot" / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence/>", encoding="utf-8"
    )
    (gold / "slot" / "licence.dll").write_bytes(b"x")
    recipe = load_recipe_from_goldclub(gold, label="live")
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        work_parent=tmp_path / "work",
        push_licences=True,
        backup=False,
    )
    assert result.errors
    assert "Nothing changed" in result.errors[0]
    assert not result.written


def test_restart_slot_hwsubsys_script_uses_goldclub_service_name() -> None:
    import inspect

    from config_scanner import live_push as lp

    src = inspect.getsource(lp.restart_slot_hwsubsys)
    assert "GoldClub Hardware Subsystem" in src
    assert "Get-Service -Name 'HWSubsys'" not in src
    assert "exit 1" in src
    assert "Start-Sleep -Seconds 12" in src
    assert "Start-SlotGameWatch" in lp._SLOT_KILL_SCRIPT
    assert "Start-SlotGameWatch.ps1" in lp._SLOT_KILL_SCRIPT
    assert "Stop-SlotWatchers" in lp._SLOT_KILL_SCRIPT
    assert "ParentProcessId" in lp._SLOT_KILL_SCRIPT
    assert "STILL:Bootstrap" in lp._SLOT_KILL_SCRIPT
    assert "Stop-Named @('Bootstrap')" in lp._SLOT_KILL_SCRIPT
    assert "taskkill /F /T" in lp._SLOT_KILL_SCRIPT
    assert "taskkill /F /T /IM" not in lp._SLOT_KILL_SCRIPT
    assert "ConfigScanner" in lp._SLOT_KILL_SCRIPT
    assert "Test-TreeHasProtected" in lp._SLOT_KILL_SCRIPT
    assert "Test-Protected" in lp._SLOT_KILL_SCRIPT
    assert "MethodName Terminate" in lp._SLOT_KILL_SCRIPT
    assert "pid=" in lp._SLOT_KILL_SCRIPT
    assert "return $false" not in lp._SLOT_KILL_SCRIPT
    src_hw = inspect.getsource(lp.restart_slot_hwsubsys)
    assert "hardware subsystem not installed" in src_hw
    wd = lp._slot_bootstrap_watchdog_script((r"G:\Bootstrap.exe",))
    assert lp._SLOT_WATCHDOG_MARKER in wd
    assert "ConfigScanner" in wd
    assert r"G:\Bootstrap.exe" in wd
    src_local = inspect.getsource(lp._run_local_powershell)
    assert "-EncodedCommand" in src_local
    assert '"-Command"' not in src_local


def test_lp_log_writes_only_livepush_file(tmp_path: Path, monkeypatch, caplog) -> None:
    import logging

    from config_scanner import live_push as lp

    log = tmp_path / "LivePush.log"
    monkeypatch.setattr(lp, "live_push_log_path", lambda: log)
    with caplog.at_level(logging.DEBUG):
        lp._lp_log("hello unique live-push line")
    text = log.read_text(encoding="utf-8")
    assert "hello unique live-push line" in text
    assert "T" in text.split(" ", 1)[0]
    assert "hello unique live-push line" not in caplog.text


def test_commit_slot_kill_failure_restarts_game(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.play_limits.show_all_lines = not bool(recipe.play_limits.show_all_lines)
    starts: list[str] = []

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_kill",
        lambda *_a, **_k: (False, "exit 1"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_start",
        lambda *_a, **_k: (starts.append("start") or True, "bootstrap"),
    )

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        scan_target=str(gold),
        work_parent=tmp_path / "work",
        backup=False,
    )
    assert result.errors
    assert "were not written" in result.errors[0]
    assert not result.written
    assert starts == ["start"]
    assert result.stack_started is True
    assert "Game was started again" in result.errors[0]


def test_patch_aurum_rewrites_messenger_uri(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        AurumIdentitySettings,
        patch_aurum_setup_placeholders,
    )

    src = tmp_path / "AurumSetup.xml"
    src.write_text(
        '<?xml version="1.0"?>\n'
        "<AurumSetup>\n"
        "  <NetworkHostName>GST20664</NetworkHostName>\n"
        "  <ServiceURI>net.tcp://GST20664:50011/aurum</ServiceURI>\n"
        "  <MessengerURI>net.tcp://GST20664:50010/msg</MessengerURI>\n"
        "</AurumSetup>\n",
        encoding="utf-8",
    )
    dest = tmp_path / "out.xml"
    patch_aurum_setup_placeholders(
        src,
        dest,
        AurumIdentitySettings(network_hostname_template="GST22377"),
    )
    text = dest.read_text(encoding="utf-8")
    assert "<NetworkHostName>GST22377</NetworkHostName>" in text
    assert "net.tcp://GST22377:50011/aurum" in text
    assert "net.tcp://GST22377:50010/msg" in text
    assert "GST20664" not in text


def test_apply_aurum_hostname_for_overlay_cabinet(monkeypatch) -> None:
    from config_scanner.live_push import apply_aurum_hostname_for_live_push
    from config_scanner.slot_setup import AurumIdentitySettings, SlotSetupRecipe

    recipe = SlotSetupRecipe(
        aurum_identity=AurumIdentitySettings(network_hostname_template="GST20664"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.resolve_cabinet_windows_hostname",
        lambda _t: "GST22377",
    )
    fixed = apply_aurum_hostname_for_live_push(recipe, r"\\10.0.0.111\slot")
    assert fixed.aurum_identity.network_hostname_template == "GST22377"


def test_commit_currency_change_keeps_windows_hostname(
    tmp_path: Path, monkeypatch
) -> None:
    gold = _fake_goldclub(tmp_path)
    aurum = gold / "Services" / "aurum" / "config" / "AurumSetup.xml"
    aurum.write_text(
        '<?xml version="1.0"?>\n'
        "<AurumSetup>\n"
        "  <CurrencyTable><CurrencyCode>USD</CurrencyCode></CurrencyTable>\n"
        "  <ProcessorConfig><CurrencyId>USD</CurrencyId></ProcessorConfig>\n"
        "  <NetworkHostName>GST20664</NetworkHostName>\n"
        "  <ServiceURI>net.tcp://GST20664:50011/aurum</ServiceURI>\n"
        "  <MessengerURI>net.tcp://GST20664:50010/msg</MessengerURI>\n"
        "</AurumSetup>\n",
        encoding="utf-8",
    )
    recipe = load_recipe_from_goldclub(gold, label="live")
    assert recipe.aurum_identity.network_hostname_template == "GST20664"
    recipe.jurisdiction.currency_name = "TTD"
    recipe.hardware_currency_name = "TTD"

    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")
    monkeypatch.setattr(
        "config_scanner.live_push.resolve_cabinet_windows_hostname",
        lambda _t: "GST22377",
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_kill",
        lambda *_a, **_k: (True, "stopped"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_ramclear",
        lambda *_a, **_k: (True, "ramclear ok"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.restart_slot_hwsubsys",
        lambda *_a, **_k: (True, "HWSubsys Running"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_start",
        lambda *_a, **_k: (True, "bootstrap"),
    )

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=True,
        work_parent=tmp_path / "work",
    )
    assert result.ok, result.errors
    text = aurum.read_text(encoding="utf-8")
    assert "GST22377" in text
    assert "GST20664" not in text
    assert "<CurrencyCode>TTD</CurrencyCode>" in text


def test_commit_writes_leftover_single_denomination(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    mg = gold / "slot" / "themes" / "mgconfig.xml"
    mg.write_text(
        mg.read_text(encoding="utf-8").replace("<int>5</int>", "<int>10</int>"),
        encoding="utf-8",
    )
    recipe = load_recipe_from_goldclub(gold, label="live")
    assert recipe.denomination_list == [10]
    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_kill",
        lambda *_a, **_k: (True, "stopped"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.restart_slot_hwsubsys",
        lambda *_a, **_k: (True, "hw ok"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_start",
        lambda *_a, **_k: (True, "bootstrap"),
    )
    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        scan_target=str(gold),
        work_parent=tmp_path / "work-single",
        backup=False,
    )
    assert result.ok, result.errors
    assert "jurisdiction" in result.sections
    jur = (gold / "slot" / "themes" / "jurisdiction_config.xml").read_text(
        encoding="utf-8"
    )
    assert "<SingleDenomination>10</SingleDenomination>" in jur


def test_strip_powershell_clixml_progress() -> None:
    from config_scanner.live_push import _strip_powershell_noise

    blob = "OK\n#< CLIXML\n<Objs Version=\"1.1.0.1\"></Objs>"
    assert _strip_powershell_noise(blob) == "OK"


def test_commit_sas_only_heals_overlay_hostname_without_rewriting_setup(
    tmp_path: Path, monkeypatch
) -> None:
    gold = _fake_goldclub(tmp_path)
    aurum = gold / "Services" / "aurum" / "config" / "AurumSetup.xml"
    aurum.write_text(
        '<?xml version="1.0"?>\n'
        "<AurumSetup>\n"
        "  <CurrencyTable><CurrencyCode>USD</CurrencyCode></CurrencyTable>\n"
        "  <ProcessorConfig><CurrencyId>USD</CurrencyId></ProcessorConfig>\n"
        "  <Network>\n"
        "    <NetworkHostName>GST20664</NetworkHostName>\n"
        "    <ServiceURI>net.tcp://GST20664:50011/aurum</ServiceURI>\n"
        "    <MessengerURI>net.tcp://GST20664:50010/msg</MessengerURI>\n"
        "  </Network>\n"
        '  <EGM id="GCC_ST_20664_01" CabinetSerialNumber="20664" />\n'
        "</AurumSetup>\n",
        encoding="utf-8",
    )
    recipe = load_recipe_from_goldclub(gold, label="live")
    recipe.sas.address = 9

    monkeypatch.setattr(
        "config_scanner.live_push.resolve_cabinet_windows_hostname",
        lambda _t: "GST22377",
    )
    monkeypatch.setattr("config_scanner.live_push.goldclub_stack_kind", lambda _r: "slot")
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_kill",
        lambda *_a, **_k: (True, "stopped"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.run_slot_stack_start",
        lambda *_a, **_k: (True, "bootstrap"),
    )

    result = commit_live_push(
        recipe,
        gold,
        restart_stack=False,
        scan_target=str(gold),
        work_parent=tmp_path / "work-sas-host",
        backup=False,
    )
    assert result.ok, result.errors
    written = {w.replace("\\", "/").casefold() for w in result.written}
    assert not any(name.endswith("aurumsetup.xml") for name in written)
    assert any("clientsset.xml" in name for name in written)
    text = aurum.read_text(encoding="utf-8")
    assert "<NetworkHostName>GST22377</NetworkHostName>" in text
    assert "net.tcp://GST22377:50011/aurum" in text
    assert "GST20664" not in text
    assert 'id="GCC_ST_20664_01"' in text
    assert (gold / "Services" / "aurum" / "config" / "AurumSetup.xml.bak-host-GST20664").is_file()



def test_cabinet_ip_prefill_selects_last_octet() -> None:
    from config_scanner.live_push import DEFAULT_CABINET_IP, cabinet_ip_prefill

    assert DEFAULT_CABINET_IP == "10.0.0.111"
    text, start, length = cabinet_ip_prefill()
    assert text == "10.0.0.111"
    assert text[start : start + length] == "111"
    text, start, length = cabinet_ip_prefill("10.0.0.9")
    assert (text[start : start + length], start) == ("9", 7)
    assert cabinet_ip_prefill("") == ("", 0, 0)
    assert cabinet_ip_prefill("host")[2] == 0
