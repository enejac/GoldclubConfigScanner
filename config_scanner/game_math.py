"""Per-theme bet steps and RTP helpers for Live Push."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from config_scanner.slot_setup import MathDenomSettings, math_settings_unreadable_reason

GAMES_MATH_LABEL = "Games / math"

_RTP_RE = re.compile(
    r"^return_(?:(?P<prefix>[a-z0-9]+)_)?(?P<whole>\d+)_(?P<frac>\d+)$",
    re.IGNORECASE,
)
_THEME_PREFIX_RE = re.compile(r"^(?:PR\d+|GSC)_", re.IGNORECASE)


def format_return_percent(token: str | None) -> str:
    """``return_94_0`` → ``94.0%``; ``return_frog_92_0`` → ``Frog 92.0%``."""
    raw = (token or "").strip()
    if not raw:
        return "—"
    match = _RTP_RE.match(raw)
    if match is None:
        return raw
    prefix = (match.group("prefix") or "").strip()
    percent = f"{int(match.group('whole'))}.{match.group('frac')}%"
    if prefix:
        return f"{prefix[:1].upper()}{prefix[1:]} {percent}"
    return percent


def theme_display_name(theme: str) -> str:
    """``PR3_RedZone`` → ``RedZone``; other folder names stay as-is."""
    name = (theme or "").strip()
    stripped = _THEME_PREFIX_RE.sub("", name)
    return stripped or name


def format_bet_steps(multipliers: Sequence[int] | None) -> str:
    """Compact bet-step label: ``1, 2, …, 15`` → ``1–15``."""
    values = [int(x) for x in (multipliers or [])]
    if not values:
        return "—"
    if len(values) == 1:
        return str(values[0])
    if len(values) >= 3:
        return f"{values[0]}–{values[-1]}"
    return ", ".join(str(x) for x in values)


def format_game_combo_label(row: MathDenomSettings) -> str:
    """``RedZone — 92.0% · 1–15``."""
    name = theme_display_name(row.theme)
    rtp = format_return_percent(row.return_percent)
    bets = format_bet_steps(row.bet_multipliers)
    return f"{name}  —  {rtp}  ·  {bets}"


def format_game_math_snapshot(rows: Sequence[MathDenomSettings]) -> str:
    """Stable per-theme fingerprint so swaps are not hidden by a mixed summary."""
    parts: list[str] = []
    for row in rows:
        theme = (row.theme or "").strip()
        if not theme or theme == "*":
            continue
        rtp = (row.return_percent or "").strip() or "-"
        bets = ",".join(str(int(x)) for x in (row.bet_multipliers or []))
        parts.append(f"{theme}={rtp}[{bets}]")
    return " | ".join(parts) or "—"


def format_game_math_summary(rows: Sequence[MathDenomSettings]) -> str:
    """Cabinet-wide snapshot: ``mixed · 3 bet maps · 92.0% / 94.0% · 20 games``."""
    usable = [row for row in rows if (row.theme or "").strip() not in {"", "*"}]
    if not usable:
        return "—"
    bet_maps = {tuple(int(x) for x in (row.bet_multipliers or [])) for row in usable}
    rtp_labels: list[str] = []
    seen_rtp: set[str] = set()
    for row in usable:
        token = (row.return_percent or "").strip()
        if not token or token in seen_rtp:
            continue
        seen_rtp.add(token)
        rtp_labels.append(format_return_percent(token))
    parts: list[str] = []
    if len(bet_maps) > 1:
        parts.append(f"mixed · {len(bet_maps)} bet maps")
    elif bet_maps:
        parts.append(format_bet_steps(next(iter(bet_maps))))
    if len(rtp_labels) > 1:
        parts.append(", ".join(rtp_labels))
    elif rtp_labels:
        parts.append(rtp_labels[0])
    parts.append(f"{len(usable)} games")
    return "  ·  ".join(parts)


def clone_math_rows(rows: Iterable[MathDenomSettings]) -> list[MathDenomSettings]:
    return [
        MathDenomSettings(
            theme=row.theme,
            denomination_multiplier=row.denomination_multiplier,
            fixed_bet=row.fixed_bet,
            bet_multipliers=list(row.bet_multipliers or []),
            return_percent=row.return_percent,
            allowed_return_percents=list(row.allowed_return_percents or []),
        )
        for row in rows
    ]


def math_by_theme(
    rows: Sequence[MathDenomSettings],
) -> dict[str, MathDenomSettings]:
    out: dict[str, MathDenomSettings] = {}
    for row in rows:
        theme = (row.theme or "").strip()
        if not theme or theme == "*":
            continue
        out[theme] = row
    return out


def math_bets_equal(
    left: Sequence[int] | None, right: Sequence[int] | None
) -> bool:
    return [int(x) for x in (left or [])] == [int(x) for x in (right or [])]


def game_math_change_lines(
    live_rows: Sequence[MathDenomSettings],
    form_rows: Sequence[MathDenomSettings],
) -> list[str]:
    """``RedZone: 92.0% → 94.0%`` / ``WondersOfIndia: bets 1–10 → 1–8``."""
    live_map = math_by_theme(live_rows)
    lines: list[str] = []
    for row in form_rows:
        live = live_map.get((row.theme or "").strip())
        if live is None:
            continue
        bits: list[str] = []
        if (live.return_percent or "") != (row.return_percent or ""):
            bits.append(
                f"{format_return_percent(live.return_percent)} → "
                f"{format_return_percent(row.return_percent)}"
            )
        if not math_bets_equal(live.bet_multipliers, row.bet_multipliers):
            bits.append(
                f"bets {format_bet_steps(live.bet_multipliers)} → "
                f"{format_bet_steps(row.bet_multipliers)}"
            )
        if bits:
            lines.append(f"{theme_display_name(row.theme)}: {'; '.join(bits)}")
    return lines


def bet_steps_changed(
    live_rows: Sequence[MathDenomSettings],
    form_rows: Sequence[MathDenomSettings],
) -> bool:
    live_map = math_by_theme(live_rows)
    for row in form_rows:
        live = live_map.get((row.theme or "").strip())
        if live is None:
            continue
        if not math_bets_equal(live.bet_multipliers, row.bet_multipliers):
            return True
    return False


def rtp_changed(
    live_rows: Sequence[MathDenomSettings],
    form_rows: Sequence[MathDenomSettings],
) -> bool:
    live_map = math_by_theme(live_rows)
    for row in form_rows:
        live = live_map.get((row.theme or "").strip())
        if live is None:
            continue
        if (live.return_percent or "") != (row.return_percent or ""):
            return True
    return False


def offered_bet_steps(
    row: MathDenomSettings, live_row: MathDenomSettings | None
) -> list[int]:
    """Checkbox values: this theme's live list plus any already on the form row."""
    values: list[int] = []
    seen: set[int] = set()
    for source in (live_row, row):
        if source is None:
            continue
        for raw in source.bet_multipliers or []:
            step = int(raw)
            if step in seen:
                continue
            seen.add(step)
            values.append(step)
    return values


def theme_math_row_dirty(
    live_row: MathDenomSettings | None, row: MathDenomSettings
) -> bool:
    """True when RTP or bet steps differ from live, or the theme was not loaded."""
    if live_row is None:
        return bool(
            (row.theme or "").strip()
            and (row.theme or "").strip() != "*"
            and (
                (row.return_percent or "").strip()
                or list(row.bet_multipliers or [])
            )
        )
    if (live_row.return_percent or "") != (row.return_percent or ""):
        return True
    return not math_bets_equal(live_row.bet_multipliers, row.bet_multipliers)


def theme_rtp_errors(
    live_rows: Sequence[MathDenomSettings],
    form_rows: Sequence[MathDenomSettings],
) -> list[str]:
    """Changed RTP must stay on that theme's loaded AllowedReturnPercents."""
    live_map = math_by_theme(live_rows)
    errors: list[str] = []
    for row in form_rows:
        theme = (row.theme or "").strip()
        if not theme or theme == "*":
            continue
        live = live_map.get(theme)
        new = (row.return_percent or "").strip()
        old = (live.return_percent or "").strip() if live is not None else ""
        if new == old:
            continue
        if live is None:
            continue
        if not new:
            errors.append(f"{theme}: return percent cannot be empty.")
            continue
        choices = allowed_return_choices(live)
        if not choices:
            errors.append(
                f"{theme}: MathSettings.xml has no return percents; "
                "RTP cannot be changed."
            )
            continue
        if new not in choices:
            errors.append(
                f"{theme}: {format_return_percent(new)} is not in "
                "AllowedReturnPercents."
            )
    return errors


def theme_math_write_errors(
    goldclub: Path,
    live_rows: Sequence[MathDenomSettings],
    form_rows: Sequence[MathDenomSettings],
) -> list[str]:
    """Block RTP / bet writes when MathSettings.xml is missing or undecodable."""
    live_map = math_by_theme(live_rows)
    errors = theme_rtp_errors(live_rows, form_rows)
    seen = set(errors)
    for row in form_rows:
        theme = (row.theme or "").strip()
        if not theme or theme == "*":
            continue
        if not theme_math_row_dirty(live_map.get(theme), row):
            continue
        reason = math_settings_unreadable_reason(goldclub, theme)
        if reason and reason not in seen:
            seen.add(reason)
            errors.append(reason)
    return errors


def theme_bet_step_errors(
    live_rows: Sequence[MathDenomSettings],
    form_rows: Sequence[MathDenomSettings],
    *,
    bulk_bets: Sequence[int] | None = None,
) -> list[str]:
    """Changed themes must keep a non-empty subset of that theme's live steps."""
    live_map = math_by_theme(live_rows)
    errors: list[str] = []
    for row in form_rows:
        theme = (row.theme or "").strip()
        live = live_map.get(theme)
        if live is None:
            continue
        new_bets = [int(x) for x in (row.bet_multipliers or [])]
        live_bets = [int(x) for x in (live.bet_multipliers or [])]
        if math_bets_equal(new_bets, live_bets):
            continue
        if not new_bets:
            errors.append(f"{theme}: bet steps cannot be empty.")
            continue
        extra = [x for x in new_bets if x not in set(live_bets)]
        if extra:
            extras = ", ".join(str(x) for x in extra)
            errors.append(
                f"{theme}: bet steps {extras} are not on this game's live list."
            )
    bulk = [int(x) for x in (bulk_bets or [])]
    if not bulk:
        return errors
    for theme, live in live_map.items():
        live_bets = {int(x) for x in (live.bet_multipliers or [])}
        if not live_bets:
            continue
        extra = [x for x in bulk if x not in live_bets]
        if extra:
            extras = ", ".join(str(x) for x in extra)
            errors.append(
                f"{theme}: bet steps {extras} are not on this game's live list."
            )
    return errors


def copy_bet_steps_to_compatible(
    rows: Sequence[MathDenomSettings],
    bets: Sequence[int],
    live_rows: Sequence[MathDenomSettings],
) -> tuple[list[MathDenomSettings], tuple[str, ...]]:
    """Copy *bets* onto themes whose live list already contains every step."""
    want = [int(x) for x in bets]
    live_map = math_by_theme(live_rows)
    skips: list[str] = []
    out: list[MathDenomSettings] = []
    for row in clone_math_rows(rows):
        live = live_map.get(row.theme)
        live_bets = (
            [int(x) for x in live.bet_multipliers]
            if live is not None
            else list(row.bet_multipliers)
        )
        if want and set(want) <= set(live_bets):
            row.bet_multipliers = list(want)
        elif want:
            skips.append(row.theme)
        out.append(row)
    return out, tuple(skips)


def set_return_percent_where_allowed(
    rows: Sequence[MathDenomSettings], token: str
) -> tuple[list[MathDenomSettings], int]:
    """Set RTP on every theme that lists *token* in AllowedReturnPercents."""
    want = (token or "").strip()
    changed = 0
    out: list[MathDenomSettings] = []
    for row in clone_math_rows(rows):
        allowed = list(row.allowed_return_percents or [])
        if want and want in allowed:
            if (row.return_percent or "") != want:
                changed += 1
            row.return_percent = want
        out.append(row)
    return out, changed


def allowed_return_choices(row: MathDenomSettings) -> list[str]:
    """Radio options: allowed list, plus current if the pack omitted it."""
    values: list[str] = []
    seen: set[str] = set()
    for raw in list(row.allowed_return_percents or []) + [
        (row.return_percent or "").strip()
    ]:
        token = (raw or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        values.append(token)
    return values
