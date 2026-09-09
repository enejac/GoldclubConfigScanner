"""Tests for bill token compare helpers."""

from __future__ import annotations

from config_scanner.bill_tokens_view import (
    apply_bill_token_accept,
    bill_tokens_all_match,
    bill_tokens_compare_rows,
    bill_tokens_warning_lines,
    format_bill_notes_snapshot,
    resolve_target_bill_tokens,
    summarize_bill_tokens,
)
from config_scanner.slot_setup import BillToken, TTD_MEI_BILL_TOKENS


def test_summarize_empty() -> None:
    assert summarize_bill_tokens([]) == "(none)"


def test_compare_rows_marks_missing_and_mismatch() -> None:
    live = [
        BillToken(code="97", value=100),
        BillToken(code="99", value=500),
    ]
    target = list(TTD_MEI_BILL_TOKENS)
    rows = bill_tokens_compare_rows(live, target)
    by_code = {r.code: r for r in rows}
    assert by_code["97"].matches is True
    assert by_code["98"].live_value is None
    assert by_code["98"].target_value == 500
    assert by_code["99"].matches is False
    assert bill_tokens_all_match(live, target) is False


def test_compare_rows_all_match_ttd() -> None:
    live = list(TTD_MEI_BILL_TOKENS)
    target = list(TTD_MEI_BILL_TOKENS)
    assert bill_tokens_all_match(live, target) is True
    assert all(r.matches for r in bill_tokens_compare_rows(live, target))


def test_warning_lines_flag_missing_98() -> None:
    live = [
        BillToken(code="97", value=100),
        BillToken(code="99", value=500),
    ]
    warnings = bill_tokens_warning_lines(live, list(TTD_MEI_BILL_TOKENS))
    assert any("bill code 98" in w for w in warnings)
    assert any("Live missing codes" in w for w in warnings)


def test_resolve_target_uses_ttd_currency_when_no_preset() -> None:
    tokens, label = resolve_target_bill_tokens(currency_name="TTD")
    assert [t.code for t in tokens] == [t.code for t in TTD_MEI_BILL_TOKENS]
    assert label == "TTD default"


def test_resolve_target_prefers_preset_over_currency() -> None:
    preset = [BillToken(code="97", value=1)]
    tokens, label = resolve_target_bill_tokens(
        preset_tokens=preset,
        preset_label="Trinidad & Tobago (TTD)",
        currency_name="TTD",
    )
    assert tokens == preset
    assert "Trinidad" in label


def test_apply_bill_token_accept_keeps_value_and_code() -> None:
    tokens = list(TTD_MEI_BILL_TOKENS)
    out = apply_bill_token_accept(tokens, {"102": False, "97": True})
    by_code = {t.code: t for t in out}
    assert by_code["102"].can_accept is False
    assert by_code["102"].value == 10000
    assert by_code["97"].can_accept is True
    assert by_code["98"].can_accept is True


def test_format_bill_notes_snapshot_includes_accept_flag() -> None:
    tokens = [
        BillToken(code="97", value=100, can_accept=True),
        BillToken(code="102", value=10000, can_accept=False),
    ]
    text = format_bill_notes_snapshot(tokens)
    assert "97=100:on" in text
    assert "102=10000:off" in text
    assert format_bill_notes_snapshot([]) == "—"
