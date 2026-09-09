"""Read-only bill-token compare helpers for Live Push (MEI code → credit value)."""

from __future__ import annotations

from dataclasses import dataclass

from config_scanner.slot_setup import (
    BillToken,
    default_bill_tokens_for_currency,
    mei_bill_token_issues,
)


def _sort_code(code: str) -> tuple[int, str | int]:
    c = (code or "").strip()
    if c.isdigit():
        return (0, int(c))
    return (1, c)


def bill_tokens_by_code(tokens: list[BillToken]) -> dict[str, BillToken]:
    out: dict[str, BillToken] = {}
    for token in tokens:
        code = (token.code or "").strip()
        if code:
            out[code] = token
    return out


@dataclass(frozen=True)
class BillTokenCompareRow:
    code: str
    live_value: int | None
    target_value: int | None

    @property
    def matches(self) -> bool:
        return (
            self.live_value is not None
            and self.target_value is not None
            and self.live_value == self.target_value
        )

    @property
    def live_only(self) -> bool:
        return self.live_value is not None and self.target_value is None

    @property
    def target_only(self) -> bool:
        return self.target_value is not None and self.live_value is None


def bill_tokens_compare_rows(
    live: list[BillToken], target: list[BillToken]
) -> list[BillTokenCompareRow]:
    """Side-by-side rows for every MEI code present on live and/or target."""
    live_map = bill_tokens_by_code(live)
    target_map = bill_tokens_by_code(target)
    codes = sorted(set(live_map) | set(target_map), key=_sort_code)
    rows: list[BillTokenCompareRow] = []
    for code in codes:
        lv = live_map.get(code)
        tv = target_map.get(code)
        rows.append(
            BillTokenCompareRow(
                code=code,
                live_value=None if lv is None else int(lv.value),
                target_value=None if tv is None else int(tv.value),
            )
        )
    return rows


def apply_bill_token_accept(
    tokens: list[BillToken], enabled: dict[str, bool]
) -> list[BillToken]:
    """Copy tokens, setting CanAccept from *enabled* (code → accept)."""
    out: list[BillToken] = []
    for token in tokens:
        code = (token.code or "").strip()
        if code in enabled:
            out.append(
                BillToken(
                    code=token.code,
                    value=token.value,
                    can_accept=bool(enabled[code]),
                    can_return=token.can_return,
                )
            )
        else:
            out.append(token)
    return out


def format_bill_notes_snapshot(tokens: list[BillToken]) -> str:
    """Stable Live Push snapshot for code/value/CanAccept."""
    if not tokens:
        return "—"
    ordered = sorted(tokens, key=lambda t: _sort_code(t.code or ""))
    parts: list[str] = []
    for token in ordered:
        flag = "on" if token.can_accept else "off"
        parts.append(f"{token.code}={token.value}:{flag}")
    return ", ".join(parts)


def summarize_bill_tokens(tokens: list[BillToken]) -> str:
    if not tokens:
        return "(none)"
    ordered = sorted(tokens, key=lambda t: _sort_code(t.code or ""))
    return ", ".join(f"{t.code}\u2192{t.value}" for t in ordered)


def resolve_target_bill_tokens(
    *,
    preset_tokens: list[BillToken] | None = None,
    preset_label: str = "",
    currency_name: str = "",
) -> tuple[list[BillToken], str]:
    """Pick a compare target: jurisdiction profile first, then currency default."""
    if preset_tokens:
        return list(preset_tokens), (preset_label or "jurisdiction profile")
    fallback = default_bill_tokens_for_currency(currency_name)
    if fallback:
        code = (currency_name or "").strip().upper() or "currency"
        return fallback, f"{code} default"
    return [], ""


def bill_tokens_all_match(live: list[BillToken], target: list[BillToken]) -> bool:
    rows = bill_tokens_compare_rows(live, target)
    if not rows:
        return not live and not target
    return all(row.matches for row in rows)


def bill_tokens_warning_lines(
    live: list[BillToken],
    target: list[BillToken],
    *,
    currency_name: str = "",
) -> list[str]:
    """Human warnings for the Live Push bill-token preview."""
    lines: list[str] = []
    for label, tokens in (("Live cabinet", live), ("Target", target)):
        issues = mei_bill_token_issues(tokens)
        for issue in issues:
            lines.append(f"{label}: {issue}")
    if live and target and not bill_tokens_all_match(live, target):
        missing_live = [r.code for r in bill_tokens_compare_rows(live, target) if r.target_only]
        missing_target = [r.code for r in bill_tokens_compare_rows(live, target) if r.live_only]
        mismatched = [
            r.code
            for r in bill_tokens_compare_rows(live, target)
            if r.live_value is not None
            and r.target_value is not None
            and r.live_value != r.target_value
        ]
        if missing_live:
            lines.append(f"Live missing codes: {', '.join(missing_live)}")
        if missing_target:
            lines.append(f"Target missing codes: {', '.join(missing_target)}")
        if mismatched:
            lines.append(f"Value mismatch on codes: {', '.join(mismatched)}")
    if currency_name and not target and live:
        lines.append(
            f"No bill.tokens in the selected jurisdiction profile for {currency_name}; "
            "showing live cabinet only."
        )
    return lines
