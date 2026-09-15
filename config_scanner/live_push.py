"""Live cabinet push: write the safe Slot Setup recipe, then restack.

Does not rewrite serialport layout/locations or Windows boot.
Licences are never overwritten; missing licence XML / licence.dll may be
copied next to OneHand when the operator enables that Live Push section.
Slot cabinets: stop OneHand/Bootstrap, write, then start game-start
(Release) or Bootstrap (Debug / unknown). Roulette: Kill-All then
Run-FullStack. No EGM reboot either way.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config_scanner.bill_tokens_view import format_bill_notes_snapshot
from config_scanner.build_version import OneHandBuildInfo, detect_onehand_build
from config_scanner.language_flags import COUNTRY_FLAG_LABEL, flags_snapshot
from config_scanner.denom_compat import (
    apply_magic_wheel_for_denom,
    denom_combo_choices,
    denomination_lists_equal,
    inspect_link2win_math,
    live_cabinet_math_gap,
    playable_denoms_from_recipe,
    prefetch_link2win_math,
    validate_live_push_recipe,
    validate_live_push_warnings,
)
from config_scanner.jurisdiction import load_jurisdictions
from config_scanner.read_cache import run_in_scope, scoped_read_cache
from config_scanner.slot_licence import (
    LiveLicenceStatus,
    inspect_live_licences,
    push_missing_licences,
)
from config_scanner.slot_setup import (
    AurumIdentitySettings,
    SlotSetupRecipe,
    apply_config_pack,
    build_config_pack,
    STANDARD_DOOR_SWITCH_NAMES,
    door_switch_auto_unlock_label,
    goldclub_root_from_target,
    leftover_jurisdiction_single_denomination,
    load_recipe_from_goldclub,
    cabinet_has_magic_wheel_gamepack,
    iter_magicwheel_setting_rels,
    markets_accepted_by_onehand,
    read_sas_settings,
    math_settings_rels,
    merge_play_limits,
    missing_display_mode_assets,
    normalize_mei_bill_tokens_for_currency,
    read_display_mode,
    read_ticket_printer_active,
    CabinetLanguages,
    read_cabinet_languages,
    recipe_from_jurisdiction_profile,
    sas_channel_flags_differ,
    LIMIT_SETUP_FIELDS,
    SAS_CHANNEL_FIELDS,
    _resolve_goldclub_rel,
)
from config_scanner.stack_restart import (
    plan_stack_restart,
    remote_winrm_ready,
    run_stack_kill,
    run_stack_start,
    running_on_egm,
    stack_stop_unreachable,
    unc_host_from_target,
    winrm_skip_detail,
)

ProgressFn = Callable[[str], None]

# ISO codes used on GameStar cabinets, then other common gaming currencies.
CURRENCY_LABELS: dict[str, str] = {
    "TTD": "Trinidad & Tobago",
    "JMD": "Jamaica",
    "USD": "Puerto Rico / Panama",
    "COP": "Colombia",
    "GYD": "Guyana",
    "MXN": "Mexico",
    "PEN": "Peru",
    "PLN": "Poland",
    "EUR": "Euro",
    "GBP": "Pound sterling",
    "CAD": "Canadian dollar",
    "ARS": "Argentina",
    "BRL": "Brazil",
    "CLP": "Chile",
    "UYU": "Uruguay",
    "PYG": "Paraguay",
    "BOB": "Bolivia",
    "PAB": "Panama balboa",
    "CRC": "Costa Rica",
    "GTQ": "Guatemala",
    "HNL": "Honduras",
    "NIO": "Nicaragua",
    "DOP": "Dominican Republic",
    "HTG": "Haiti",
    "BBD": "Barbados",
    "XCD": "East Caribbean",
    "VES": "Venezuela",
    "AUD": "Australia",
    "NZD": "New Zealand",
    "ZAR": "South Africa",
    "CHF": "Switzerland",
    "CNY": "China",
    "JPY": "Japan",
    "INR": "India",
    "PHP": "Philippines",
    "AED": "UAE dirham",
}

# TargetMarket combo: enum token → human label (Puerto Rico is not a currency).
MARKET_LABELS: dict[str, str] = {
    "PuertoRico": "Puerto Rico",
    "TrinidadTobago": "Trinidad & Tobago",
    "Trinidad&Tobago": "Trinidad & Tobago",
    "TT": "Trinidad Tag (writes PuertoRico on 2.0.1 TRI)",
    "Panama": "Panama",
    "Jamaica": "Jamaica",
    "Colombia": "Colombia",
    "Guyana": "Guyana",
    "Mexico": "Mexico",
    "Peru": "Peru",
    "Poland": "Poland",
}


def market_combo_label(code: str) -> str:
    token = (code or "").strip()
    if not token:
        return ""
    pretty = MARKET_LABELS.get(token, token)
    if pretty == token:
        return token
    return f"{token}  —  {pretty}"


def ordered_live_markets(
    catalog_markets: tuple[str, ...] | None = None,
    *,
    accepted: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """PuertoRico first; when OneHand reports an enum, only those tokens."""
    raw = list(catalog_markets or ())
    if not raw:
        raw = list(live_push_catalog()["markets"])
    head = ["PuertoRico"]
    if accepted:
        head = [name for name in ("PuertoRico", *sorted(accepted)) if name in accepted]
        raw = [name for name in raw if name in accepted]
    out: list[str] = []
    for name in (*head, *raw):
        if name and name not in out:
            out.append(name)
    return tuple(out)


CURRENCY_SYMBOLS: dict[str, str] = {
    "TTD": "$",
    "JMD": "$",
    "USD": "$",
    "COP": "$",
    "GYD": "$",
    "MXN": "$",
    "PEN": "S/",
    "PLN": "zl",
    "EUR": "EUR",
    "GBP": "GBP",
    "CAD": "$",
    "ARS": "$",
    "BRL": "R$",
    "CLP": "$",
    "UYU": "$",
    "PYG": "G",
    "BOB": "Bs",
    "PAB": "B/",
    "CRC": "C",
    "DOP": "$",
    "BBD": "$",
    "XCD": "$",
    "AUD": "$",
    "NZD": "$",
    "ZAR": "R",
    "CHF": "CHF",
    "CNY": "CNY",
    "JPY": "JPY",
    "INR": "INR",
    "PHP": "PHP",
    "AED": "AED",
}

LANGUAGE_CHOICES: tuple[str, ...] = (
    "English",
    "Spanish",
    "Polish",
    "Portuguese",
    "French",
)

CULTURE_CHOICES: tuple[str, ...] = (
    "en-TT",
    "en-JM",
    "en-US",
    "en-GY",
    "en-GB",
    "en-CA",
    "es-PR",
    "es-PA",
    "es-CO",
    "es-MX",
    "es-PE",
    "es-AR",
    "es-CL",
    "es-UY",
    "es-DO",
    "pl-PL",
    "pt-BR",
    "fr-FR",
)

DENOM_PRESETS: tuple[str, ...] = (
    "1",
    "2",
    "5",
    "10",
    "25",
    "50",
    "100",
    "200",
    "250",
    "500",
    "1000",
    "2000",
    "2500",
    "5000",
    "1, 5, 10",
    "2, 5, 10",
    "1, 2, 5",
    "5, 10, 25",
    "1, 2, 5, 10",
    "100, 200, 500",
    "500, 1000, 5000",
)

INACTIVITY_CHOICES: tuple[tuple[int, str], ...] = (
    (-1, "leave as-is"),
    (0, "0 — stay in game"),
    (30, "30 seconds"),
    (60, "60 seconds"),
    (120, "2 minutes"),
    (180, "3 minutes"),
    (300, "5 minutes"),
)

DALLAS_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "keep cabinet key"),
    ("01D68A721B000019", "GST22377 iButton"),
)

_DALLAS_CODE_RE = re.compile(r"Dallas code received:\s*([0-9A-Fa-f]+)", re.I)
_DALLAS_LINE_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2})?)"
    r".*?Dallas code received:\s*(?P<code>[0-9A-Fa-f]+)",
    re.I,
)
_IGT_PLACEHOLDER_RE = re.compile(r"^0100000000000282$|^IGT", re.I)

# Poll hot (today's) logs only; full scan is fallback.
DALLAS_WAIT_POLL_SEC = 0.75
DALLAS_WAIT_TIMEOUT_SEC = 15.0
DALLAS_TAIL_BYTES = 250_000
DALLAS_HOT_TAIL_BYTES = 65_536
# Newest logs per Dallas folder (SlotLog dailies no longer crowd out BiOS2).
DALLAS_LOGS_PER_FOLDER = 3
_DALLAS_PINNED_REL: tuple[str, ...] = (
    "var/log/BiOS2/BiOS2.log",
    "slot/var/log/BiOS2/BiOS2.log",
)


@dataclass(frozen=True)
class DallasReadResult:
    code: str | None
    source: str = ""
    via: str = ""  # "onehand" | "hardware" | ""
    diagnostics: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.code)


def _dallas_via_from_path(path: Path) -> str:
    name = path.as_posix().casefold()
    if "slotlog" in name or "/onehand" in name or "\\onehand" in name:
        return "onehand"
    return "hardware"


def _dallas_log_dirs(root: Path) -> list[Path]:
    """Log folders that can see Dallas with OneHand or bottom HW only."""
    bases = (root / "var" / "log", root / "slot" / "var" / "log")
    dirs: list[Path] = []
    seen: set[str] = set()
    for base in bases:
        try:
            if not base.is_dir():
                continue
        except OSError:
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            children = []
        named = {
            "SlotLog",
            "OneHand MultiHardware EVENTS",
            "BiOS2 MultiHardware EVENTS",
            "HardwareSetup MultiHardware EVENTS",
            "HwSetup MultiHardware EVENTS",
            "BiOS2",
            "HardwareSetup",
            "HwSetup",
        }
        for child in children:
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            low = child.name.casefold()
            if child.name in named or "multihardware" in low or low == "slotlog":
                key = str(child).casefold()
                if key not in seen:
                    seen.add(key)
                    dirs.append(child)
        # Explicit SlotLog even if empty listing failed partially
        for rel in ("SlotLog",):
            folder = base / rel
            key = str(folder).casefold()
            if key in seen:
                continue
            try:
                if folder.is_dir():
                    seen.add(key)
                    dirs.append(folder)
            except OSError:
                continue
    return dirs


def _log_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dallas_log_files(root: Path) -> list[Path]:
    """Collect Dallas log tails: pinned BiOS2.log plus newest files per folder."""
    picked: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path).casefold()
        if key in seen:
            return
        try:
            if not path.is_file():
                return
        except OSError:
            return
        seen.add(key)
        picked.append(path)

    for rel in _DALLAS_PINNED_REL:
        _add(root.joinpath(*rel.split("/")))

    for folder in _dallas_log_dirs(root):
        try:
            folder_logs = sorted(
                (p for p in folder.glob("*.log") if p.is_file()),
                key=_log_mtime,
                reverse=True,
            )
        except OSError:
            continue
        for path in folder_logs[:DALLAS_LOGS_PER_FOLDER]:
            _add(path)

    for name in ("SlotLog.txt", "slotlog.txt"):
        for parent in (root / "slot" / "var" / "log", root / "var" / "log"):
            _add(parent / name)
    return picked


def _dallas_today_log_name() -> str:
    return datetime.now().strftime("%Y-%m-%d") + ".log"


def _dallas_hot_log_files(root: Path) -> list[Path]:
    """Today's logs + BiOS2.log — small set for instant SMB polls."""
    today = _dallas_today_log_name()
    picked: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path).casefold()
        if key in seen:
            return
        try:
            if not path.is_file():
                return
        except OSError:
            return
        seen.add(key)
        picked.append(path)

    for rel in _DALLAS_PINNED_REL:
        _add(root.joinpath(*rel.split("/")))

    for folder in _dallas_log_dirs(root):
        _add(folder / today)
        try:
            folder_logs = sorted(
                (p for p in folder.glob("*.log") if p.is_file()),
                key=_log_mtime,
                reverse=True,
            )
        except OSError:
            continue
        if folder_logs:
            _add(folder_logs[0])

    for name in ("SlotLog.txt", "slotlog.txt"):
        for parent in (root / "slot" / "var" / "log", root / "var" / "log"):
            _add(parent / name)
    return picked


def _newest_dallas_in_file(path: Path) -> tuple[datetime | None, str] | None:
    hits = _parse_dallas_hits(_read_log_tail(path))
    if not hits:
        return None
    return hits[-1]


def dallas_read_diagnostics(goldclub: Path | str) -> str:
    """Summarize Dallas log folders for operator feedback when read fails."""
    root = goldclub_root_from_target(goldclub)
    folders = _dallas_log_dirs(root)
    if not folders:
        return "No Dallas log folders under var/log (SlotLog, BiOS2 MultiHardware, …)."
    lines: list[str] = ["Scanned Dallas log folders:"]
    for folder in folders:
        label = folder.name
        try:
            logs = sorted(
                (p for p in folder.glob("*.log") if p.is_file()),
                key=_log_mtime,
                reverse=True,
            )[:DALLAS_LOGS_PER_FOLDER]
        except OSError:
            lines.append(f"  {label}: unreadable")
            continue
        pinned = folder / "BiOS2.log"
        if pinned not in logs:
            try:
                if pinned.is_file():
                    logs = [pinned, *logs]
            except OSError:
                pass
        best: tuple[datetime | None, str, str] | None = None
        for path in logs:
            hit = _newest_dallas_in_file(path)
            if hit is None:
                continue
            ts, code = hit
            if best is None or (
                ts is not None
                and (best[0] is None or ts > best[0])
            ):
                best = (ts, code, path.name)
        if best is None:
            lines.append(f"  {label}: no Dallas code received line")
        else:
            ts, code, fname = best
            when = ts.isoformat(sep=" ", timespec="seconds") if ts else "no timestamp"
            lines.append(f"  {label}: {code} @ {when} ({fname})")
    return "\n".join(lines)


def _parse_dallas_hits(text: str) -> list[tuple[datetime | None, str]]:
    hits: list[tuple[datetime | None, str]] = []
    for match in _DALLAS_LINE_RE.finditer(text):
        code = match.group("code").strip().upper()
        if not code or _IGT_PLACEHOLDER_RE.match(code):
            continue
        ts_raw = match.group("ts")
        parsed: datetime | None = None
        try:
            parsed = datetime.fromisoformat(ts_raw.replace(" ", "T", 1))
        except ValueError:
            parsed = None
        hits.append((parsed, code))
    if hits:
        return hits
    # Fallback when lines lack a parseable timestamp
    for code in _DALLAS_CODE_RE.findall(text):
        code = code.strip().upper()
        if not code or _IGT_PLACEHOLDER_RE.match(code):
            continue
        hits.append((None, code))
    return hits


def _read_log_tail(path: Path, *, max_bytes: int = DALLAS_TAIL_BYTES) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > max_bytes:
        raw = raw[-max_bytes:]
    return raw.decode("utf-8", errors="replace")


def _pick_best_dallas_hit(
    root: Path,
    paths: list[Path],
    *,
    not_before: datetime | None,
    ignore_not_before: bool,
    via_filter: str | None,
    tail_bytes: int,
) -> DallasReadResult:
    best: tuple[datetime | None, float, str, Path] | None = None
    time_cutoff = None if ignore_not_before else not_before
    for path in paths:
        path_via = _dallas_via_from_path(path)
        if via_filter is not None and path_via != via_filter:
            continue
        text = _read_log_tail(path, max_bytes=tail_bytes)
        if not text:
            continue
        mtime = _log_mtime(path)
        for ts, code in _parse_dallas_hits(text):
            if time_cutoff is not None and ts is not None:
                try:
                    if ts.tzinfo is not None and time_cutoff.tzinfo is None:
                        cmp_before = time_cutoff.replace(tzinfo=ts.tzinfo)
                    elif ts.tzinfo is None and time_cutoff.tzinfo is not None:
                        cmp_before = time_cutoff.replace(tzinfo=None)
                    else:
                        cmp_before = time_cutoff
                    if ts < cmp_before:
                        continue
                except TypeError:
                    pass
            elif time_cutoff is not None and ts is None:
                if mtime + 1.0 < time_cutoff.timestamp():
                    continue
            if best is None:
                best = (ts, mtime, code, path)
                continue
            b_ts, b_mtime, _, _ = best
            if ts is not None and b_ts is not None:
                try:
                    newer = ts > b_ts
                except TypeError:
                    newer = mtime >= b_mtime
                if newer:
                    best = (ts, mtime, code, path)
            elif ts is not None and b_ts is None:
                best = (ts, mtime, code, path)
            elif ts is None and b_ts is None and mtime >= b_mtime:
                best = (ts, mtime, code, path)
    if best is None:
        return DallasReadResult(None)
    _, _, code, path = best
    try:
        source = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        source = path.name
    return DallasReadResult(code=code, source=source, via=_dallas_via_from_path(path))


def read_latest_dallas_from_hardware(
    goldclub: Path | str,
    *,
    not_before: datetime | None = None,
    via_filter: str | None = None,
    ignore_not_before: bool = False,
    hot_only: bool = False,
    diagnostics: bool = True,
) -> DallasReadResult:
    """Newest physical Dallas/iButton code from OneHand or bottom HW logs.

    Sources (same ``Dallas code received:`` line):
    - SlotLog / OneHand MultiHardware EVENTS — game running
    - BiOS2 / HardwareSetup MultiHardware EVENTS — bottom HW only

    Ignores the shipped IGTKeyAudit placeholder. Optional ``not_before`` keeps
    only inserts at/after that time (for wait-for-key). ``hot_only`` scans
    today's logs + BiOS2.log only (fast SMB path for Read key).
    """
    root = goldclub_root_from_target(goldclub)
    paths = _dallas_hot_log_files(root) if hot_only else _dallas_log_files(root)
    tail = DALLAS_HOT_TAIL_BYTES if hot_only else DALLAS_TAIL_BYTES
    result = _pick_best_dallas_hit(
        root,
        paths,
        not_before=not_before,
        ignore_not_before=ignore_not_before,
        via_filter=via_filter,
        tail_bytes=tail,
    )
    if not result.ok and via_filter is None and diagnostics:
        return DallasReadResult(None, diagnostics=dallas_read_diagnostics(root))
    return result


def wait_for_dallas_from_hardware(
    goldclub: Path | str,
    *,
    timeout_sec: float = DALLAS_WAIT_TIMEOUT_SEC,
    poll_sec: float = DALLAS_WAIT_POLL_SEC,
    progress: ProgressFn | None = None,
) -> DallasReadResult:
    """Poll today's logs for a Dallas insert, then fall back to full scan.

    Does not spin the UI thread — callers should run this on a worker.
    """
    import time

    started = datetime.now().astimezone()
    not_before = datetime.fromtimestamp(started.timestamp() - 5.0, tz=started.tzinfo)

    def _hot(
        *,
        ignore_time: bool = False,
        time_filter: datetime | None = not_before,
    ) -> DallasReadResult:
        return read_latest_dallas_from_hardware(
            goldclub,
            not_before=time_filter,
            ignore_not_before=ignore_time,
            hot_only=True,
            diagnostics=False,
        )

    # 1) Fresh insert since click (today's logs only — fast).
    fresh = _hot(time_filter=not_before)
    if fresh.ok:
        return fresh

    # 2) Key already inserted before Read key — newest line on today's logs.
    recent = _hot(ignore_time=True)
    if recent.ok:
        return recent

    if progress is not None:
        progress("Waiting for Dallas iButton (watching today's logs)…")

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while time.monotonic() < deadline:
        time.sleep(max(0.25, float(poll_sec)))
        hit = _hot(time_filter=not_before)
        if hit.ok:
            return hit
        remaining = int(max(0.0, deadline - time.monotonic()))
        if progress is not None:
            progress(f"Waiting for Dallas iButton… {remaining}s left")

    # 3) Full log scan (older dated files, BiOS2.log history).
    last = read_latest_dallas_from_hardware(goldclub, ignore_not_before=True)
    if last.ok:
        return last
    return DallasReadResult(
        None,
        diagnostics=dallas_read_diagnostics(goldclub),
    )


BET_MULTIPLIER_PRESETS: tuple[str, ...] = (
    "1, 2, 3, 4, 5, 8, 10, 12, 15",
    "1, 2, 3, 4, 5",
    "4, 8, 12",
    "1, 2, 5, 10",
    "1, 5, 10, 20",
)

CURRENCY_SYMBOL_CHOICES: tuple[str, ...] = (
    "$",
    "S/",
    "zl",
    "R$",
    "EUR",
    "GBP",
    "R",
    "Bs",
    "B/",
    "G",
)

MAGIC_WHEEL_LIMITS: tuple[int, ...] = (
    500,
    1000,
    2000,
    2500,
    5000,
    10000,
    25000,
    50000,
    100000,
)
MAGIC_WHEEL_BETS: tuple[int, ...] = (
    1,
    2,
    5,
    10,
    25,
    50,
    100,
    200,
    250,
    500,
    1000,
    2000,
    2500,
    5000,
)
MAGIC_WHEEL_SPINS: tuple[int, ...] = (10000, 25000, 50000, 100000)
MAGIC_WHEEL_AVERAGES: tuple[int, ...] = (
    5,
    10,
    25,
    50,
    100,
    125,
    250,
    500,
    1000,
    1250,
    2000,
    2500,
    5000,
    10000,
    12500,
    25000,
)
JACKPOT_COUNTERS: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
JACKPOT_LAYOUTS: tuple[str, ...] = ("jackpotreceipt0", "jackpotreceipt1")
CELEBRATION_LIMITS: tuple[str, ...] = ("LockAndHandpay", "Handpay", "Ticket")
CASHOUT_MODES: tuple[str, ...] = ("Ticket", "Handpay", "Cashless")
DEFAULT_BETS: tuple[str, ...] = ("Minimum", "Maximum", "Last")

# Start Aurum if Live Push / a filtered goldclub token left it down.
# game-start.exe does not start the service. LockGameWhenNoComms is inert
# until Aurum reloads SASsetupData. Same snippet on WinRM and local EGM.
_ENSURE_AURUM_PS = textwrap.dedent(
    r"""
    function Ensure-GoldClubAurumRunning {
        $svc = Get-Service -Name 'GoldClub.Aurum.Services' -ErrorAction SilentlyContinue
        if (-not $svc) { return }
        if ($svc.Status -eq 'Running') { return }
        Start-Service -Name $svc.Name -ErrorAction SilentlyContinue
        $deadline = (Get-Date).AddSeconds(20)
        do {
            $svc.Refresh()
            if ($svc.Status -eq 'Running') { return }
            Start-Sleep -Milliseconds 400
        } while ((Get-Date) -lt $deadline)
        cmd /c 'schtasks /Run /TN "GoldClub-Ensure-HwStack" /I' 2>$null | Out-Null
        $deadline = (Get-Date).AddSeconds(40)
        do {
            $svc = Get-Service -Name 'GoldClub.Aurum.Services' -ErrorAction SilentlyContinue
            if ($svc -and $svc.Status -eq 'Running') { return }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)
    }
    Ensure-GoldClubAurumRunning
    """
).strip()


def _slot_kill_aurum_block(*, stop_aurum: bool) -> str:
    if stop_aurum:
        return textwrap.dedent(
            """
            # Stop Aurum so it cannot rewrite SASsetupData (LockGameWhenNoComms)
            # from in-memory state while Live Push is writing the file.
            $aurum = Get-Service -Name 'GoldClub.Aurum.Services' -ErrorAction SilentlyContinue
            if ($aurum) { Stop-Service -Name $aurum.Name -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 2
            """
        ).strip()
    return textwrap.dedent(
        """
        # Pre-start kill: leave Aurum Running so LockGameWhenNoComms stays live.
        # game-start.exe does not start GoldClub.Aurum.Services.
        """
    ).strip()


def _slot_kill_script(*, stop_aurum: bool = True) -> str:
    return _SLOT_KILL_SCRIPT_TEMPLATE.replace(
        "__AURUM_BLOCK__",
        _slot_kill_aurum_block(stop_aurum=stop_aurum),
    )


_SLOT_KILL_SCRIPT_TEMPLATE = textwrap.dedent(
    """
    $ErrorActionPreference = 'SilentlyContinue'
    # Start-SlotGameWatch.exe is a stub: it launches powershell.exe -File
    # Start-SlotGameWatch.ps1. Killing only the exe leaves the watcher
    # restarting OneHand (STILL:game-start,OneHand) and, if Bootstrap is
    # still alive, 'Unexpected game stop' / 'Unable to open the BiOS' reboot.
    # Stop-Process alone often fails under a UAC-filtered goldclub token;
    # taskkill /F /T matches Kill-All.ps1 and actually ends Bootstrap.
    # Never /T a tree that contains ConfigScanner / this PowerShell: operators
    # often launch the exe from Bootstrap or game-start, and /T then kills
    # Apply before write+start (black cabinet).
    $script:ToolNames = @(
        'ConfigScanner','LogInvestigator','python','pythonw',
        'powershell','pwsh','cmd','conhost'
    )
    function Get-ParentPid([int]$ProcessId) {
        $cim = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ProcessId) -ErrorAction SilentlyContinue
        if ($cim) { return [int]$cim.ParentProcessId }
        return 0
    }
    function Get-NameOfPid([int]$ProcessId) {
        $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($p) { return [string]$p.Name }
        return ''
    }
    function Test-IsToolName([string]$Name) {
        $n = $Name -replace '\\.exe$',''
        foreach ($t in $script:ToolNames) { if ($n -ieq $t) { return $true } }
        return
    }
    function Get-ProtectedIds {
        $set = @{}
        function Add-Id([int]$Id) { if ($Id -gt 4) { $set[$Id] = $true } }
        Add-Id ([int]$PID)
        $cur = [int]$PID
        for ($i = 0; $i -lt 16; $i++) {
            $pp = Get-ParentPid $cur
            if ($pp -le 4) { break }
            if (-not (Test-IsToolName (Get-NameOfPid $pp))) { break }
            Add-Id $pp
            $cur = $pp
        }
        Get-Process -Name ConfigScanner,LogInvestigator -ErrorAction SilentlyContinue |
            ForEach-Object { Add-Id ([int]$_.Id) }
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match '^(python|pythonw)\\.exe$' -and
                [string]$_.CommandLine -match '(?i)gui_app|config_scanner|ConfigScanner'
            } |
            ForEach-Object { Add-Id ([int]$_.ProcessId) }
        $added = $true
        while ($added) {
            $added = $false
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
                $id = [int]$_.ProcessId
                $pp = [int]$_.ParentProcessId
                if ($set.ContainsKey($pp) -and -not $set.ContainsKey($id)) {
                    $set[$id] = $true
                    $added = $true
                }
            }
        }
        return $set
    }
    $script:Protected = Get-ProtectedIds
    function Test-Protected([int]$ProcessId) {
        return [bool]$script:Protected.ContainsKey($ProcessId)
    }
    function Test-TreeHasProtected([int]$ProcessId) {
        if (Test-Protected $ProcessId) { return $true }
        $queue = New-Object System.Collections.Generic.Queue[int]
        $queue.Enqueue($ProcessId)
        $seen = @{$ProcessId = $true}
        while ($queue.Count -gt 0) {
            $id = $queue.Dequeue()
            $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $id) -ErrorAction SilentlyContinue)
            foreach ($k in $kids) {
                $cid = [int]$k.ProcessId
                if ($seen.ContainsKey($cid)) { continue }
                $seen[$cid] = $true
                if (Test-Protected $cid) { return $true }
                $queue.Enqueue($cid)
            }
        }
        return
    }
    function Stop-OnePid([int]$ProcessId) {
        if ($ProcessId -le 4) { return }
        if (Test-Protected $ProcessId) { return }
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
        if (Test-TreeHasProtected $ProcessId) {
            $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $ProcessId) -ErrorAction SilentlyContinue)
            foreach ($k in $kids) { Stop-OnePid ([int]$k.ProcessId) }
            if (Test-Protected $ProcessId) { return }
            & cmd.exe /c ("taskkill /F /PID {0} 1>nul 2>nul" -f $ProcessId) | Out-Null
        } else {
            & cmd.exe /c ("taskkill /F /T /PID {0} 1>nul 2>nul" -f $ProcessId) | Out-Null
        }
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            try {
                $cim = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ProcessId) -ErrorAction SilentlyContinue
                if ($cim) { Invoke-CimMethod -InputObject $cim -MethodName Terminate | Out-Null }
            } catch {}
        }
    }
    function Stop-SlotWatchers {
        $watchIds = @(
            Get-Process -Name Start-SlotGameWatch -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty Id
        )
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -match '^(powershell|pwsh)\\.exe$' -and (
                    ([string]$_.CommandLine -match 'Start-SlotGameWatch\\.ps1') -or
                    ($watchIds.Count -gt 0 -and ($watchIds -contains $_.ParentProcessId))
                )
            } |
            ForEach-Object { Stop-OnePid ([int]$_.ProcessId) }
    }
    function Stop-Named([string[]]$Names) {
        foreach ($n in $Names) {
            Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
                Stop-OnePid ([int]$_.Id)
            }
        }
    }
    # Bootstrap FIRST, and wait until it is gone, before touching GameBinRun.
    Stop-Named @('Bootstrap')
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt 15) {
        if (-not (Get-Process -Name Bootstrap -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
        Stop-Named @('Bootstrap')
    }
    if (Get-Process -Name Bootstrap -ErrorAction SilentlyContinue) {
        $pids = @(Get-Process -Name Bootstrap -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Id)
        Write-Output ('STILL:Bootstrap pid=' + ($pids -join ','))
        exit 2
    }
    Stop-SlotWatchers
    Stop-Named @('Start-SlotGameWatch','BiOS2','OneHand','game-start')
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt 20) {
        Stop-SlotWatchers
        Stop-Named @('Start-SlotGameWatch','BiOS2','OneHand','game-start')
        $p = Get-Process -Name Start-SlotGameWatch,BiOS2,OneHand,game-start -ErrorAction SilentlyContinue
        if (-not $p) { break }
        Start-Sleep -Milliseconds 400
    }
    __AURUM_BLOCK__
    Stop-SlotWatchers
    $names = @('Bootstrap','Start-SlotGameWatch','BiOS2','OneHand','game-start')
    Stop-Named $names
    Start-Sleep -Seconds 1
    $left = @(Get-Process -Name $names -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Name -Unique)
    $watchers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^(powershell|pwsh)\\.exe$' -and
            [string]$_.CommandLine -match 'Start-SlotGameWatch\\.ps1'
        })
    if ($watchers.Count -gt 0) { $left += 'Start-SlotGameWatch.ps1' }
    if ($left.Count -gt 0) {
        Write-Output ('STILL:' + ($left -join ','))
        exit 2
    }
    Write-Output 'OK'
    exit 0
    """
).strip()

_SLOT_KILL_SCRIPT = _slot_kill_script(stop_aurum=True)


@dataclass(frozen=True)
class LivePushResult:
    written: tuple[str, ...]
    skipped: tuple[str, ...]
    errors: tuple[str, ...]
    stack_killed: bool
    stack_started: bool
    stack_detail: str
    backup_dir: str = ""
    sections: tuple[str, ...] = ()
    ramclear_ran: bool = False
    ramclear_detail: str = ""
    sas_lock_note: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


LIVE_PUSH_APPLY_SLOTLOG_HINT = (
    "SlotLog review runs after the game starts (invalid market, denoms, SAS lock). "
    "Or click Check SlotLog."
)


def format_live_push_apply_status(result: LivePushResult) -> str:
    """One-line Apply outcome for the Live Push status area (no dialog)."""
    bits = [f"Wrote {len(result.written)} file(s)."]
    if result.sections:
        bits.append(f"Sections: {', '.join(result.sections)}.")
    if result.backup_dir:
        bits.append(f"Backup: {result.backup_dir}")
    if result.skipped:
        bits.append(f"Skipped {len(result.skipped)}.")
    if result.stack_killed:
        bits.append("Game was stopped.")
    if result.ramclear_ran:
        bits.append("RAM clear ran.")
    elif result.ramclear_detail:
        bits.append(result.ramclear_detail.splitlines()[0][:120])
    if result.stack_started:
        bits.append("Game started.")
    elif result.stack_detail:
        last = result.stack_detail.splitlines()[-1]
        if last != (result.sas_lock_note or "") and stack_detail_worth_showing(
            last, result.errors
        ):
            bits.append(last)
    if result.sas_lock_note:
        bits.append(result.sas_lock_note)
    return " ".join(bits)


@dataclass(frozen=True)
class LocaleDefaults:
    currency: str
    culture: str
    language: str
    market: str
    denoms: tuple[int, ...]
    symbol: str
    profile_id: str


def currency_symbol_for(code: str) -> str:
    return CURRENCY_SYMBOLS.get((code or "").strip().upper(), "")


def _unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = (item or "").strip()
        if not key:
            continue
        fold = key.casefold()
        if fold in seen:
            continue
        seen.add(fold)
        out.append(key)
    return tuple(out)


def live_push_log_path() -> Path:
    """Always-on live-push trace (writes, kill/start, UNC reachability)."""
    try:
        from app_paths import app_writable_dir

        return app_writable_dir() / "LivePush.log"
    except Exception:  # noqa: BLE001
        return Path("LivePush.log")


def _lp_log(message: str) -> None:
    """Append one timestamped line to LivePush.log (not the CG process log)."""
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    try:
        path = live_push_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def bootstrap_exe_candidates(
    scan_target: str, dest: Path | str | None = None
) -> tuple[str, ...]:
    """Cabinet-local Bootstrap.exe paths (not this PC's leftover C:\\Goldclub)."""
    found = [
        r"G:\Bootstrap.exe",
        r"C:\goldclub\Bootstrap.exe",
        r"C:\Goldclub\Bootstrap.exe",
    ]
    text = str(dest or scan_target or "").replace("/", "\\")
    host = unc_host_from_target(scan_target) or unc_host_from_target(text)
    if host and text:
        marker = rf"\\{host}\c$".casefold()
        low = text.casefold()
        if low.startswith(marker):
            rest = text[len(rf"\\{host}\c$") :].lstrip("\\")
            if rest:
                found.insert(0, rf"C:\{rest}\Bootstrap.exe")
        elif low.rstrip("\\").endswith("\\slot"):
            found.insert(0, r"C:\goldclub\Bootstrap.exe")
    return _unique(found)


def game_start_exe_candidates(
    scan_target: str, dest: Path | str | None = None
) -> tuple[str, ...]:
    """Cabinet-local slot\\game-start.exe paths (Release OneHand launcher)."""
    found = [
        r"G:\slot\game-start.exe",
        r"C:\goldclub\slot\game-start.exe",
        r"C:\Goldclub\slot\game-start.exe",
    ]
    text = str(dest or scan_target or "").replace("/", "\\")
    host = unc_host_from_target(scan_target) or unc_host_from_target(text)
    if host and text:
        marker = rf"\\{host}\c$".casefold()
        low = text.casefold()
        if low.startswith(marker):
            rest = text[len(rf"\\{host}\c$") :].lstrip("\\")
            rest_norm = rest.rstrip("\\")
            if rest_norm:
                if rest_norm.casefold() == "slot" or rest_norm.casefold().endswith(
                    "\\slot"
                ):
                    found.insert(0, rf"C:\{rest_norm}\game-start.exe")
                else:
                    found.insert(0, rf"C:\{rest_norm}\slot\game-start.exe")
        elif low.rstrip("\\").endswith("\\slot"):
            found.insert(0, r"C:\goldclub\slot\game-start.exe")
    return _unique(found)


def slot_start_launcher(
    scan_target: str, dest: Path | str | None = None
) -> str:
    """``game-start`` for Release OneHand, ``bootstrap`` for Debug."""
    raw = dest or scan_target
    try:
        root = goldclub_root_from_target(raw)
    except (OSError, TypeError, ValueError):
        root = Path(str(raw or ""))
    try:
        info = detect_onehand_build(root)
    except (OSError, TypeError, ValueError):
        info = None
    cfg = ((info.configuration if info else "") or "").strip().casefold()
    if cfg == "release":
        return "game-start"
    # Debug, Unknown, or detect failed — Bootstrap (do not assume Release).
    return "bootstrap"


def slot_start_candidates(
    scan_target: str,
    dest: Path | str | None = None,
    *,
    launcher: str | None = None,
) -> tuple[str, ...]:
    kind = (launcher or slot_start_launcher(scan_target, dest)).strip().casefold()
    if kind == "game-start":
        return game_start_exe_candidates(scan_target, dest)
    return bootstrap_exe_candidates(scan_target, dest)


def _slot_start_script(
    candidates: tuple[str, ...],
    *,
    launcher: str = "bootstrap",
) -> str:
    quoted = ", ".join("'" + c.replace("'", "''") + "'" for c in candidates)
    tried = "; ".join(candidates)
    kind = (launcher or "bootstrap").strip().casefold()
    if kind == "game-start":
        missing = f"game-start.exe not found. Tried: {tried}"
        start_fail = "Could not start game-start.exe"
        after_start = """
        Start-Sleep -Seconds 5
        $deadline = (Get-Date).AddSeconds(60)
        $oh = $null
        do {
            $oh = Get-Process -Name OneHand -ErrorAction SilentlyContinue
            if ($oh) { break }
            Start-Sleep -Seconds 1
        } while ((Get-Date) -lt $deadline)
        if (-not $oh) {
            if (Get-Process -Name BiOS2 -ErrorAction SilentlyContinue) {
                throw 'Live Push started BiOS2 menu instead of OneHand'
            }
            throw 'OneHand did not start after game-start'
        }
        """
    else:
        missing = f"Bootstrap.exe not found. Tried: {tried}"
        start_fail = "Could not start Bootstrap.exe"
        after_start = """
        Start-Sleep -Seconds 5
        if (-not (Get-Process -Name Bootstrap -ErrorAction SilentlyContinue)) {
            throw 'Bootstrap.exe did not start'
        }
        $deadline = (Get-Date).AddSeconds(45)
        $oh = $null
        do {
            $oh = Get-Process -Name OneHand -ErrorAction SilentlyContinue
            if ($oh) { break }
            Start-Sleep -Seconds 1
        } while ((Get-Date) -lt $deadline)
        if (-not $oh) {
            if (Get-Process -Name BiOS2 -ErrorAction SilentlyContinue) {
                throw 'Live Push started BiOS2 menu instead of OneHand'
            }
            throw 'OneHand did not start after Bootstrap'
        }
        """
    head = _ENSURE_AURUM_PS + "\n" + textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $exe = $null
        foreach ($c in @({quoted})) {{
            if (Test-Path -LiteralPath $c) {{ $exe = $c; break }}
        }}
        if (-not $exe) {{ throw '{missing}' }}
        $dir = Split-Path -Parent $exe
        $started = $false
        try {{
            $user = 'goldclub'
            $cs = Get-CimInstance Win32_ComputerSystem
            if ($cs.UserName) {{ $user = [string]$cs.UserName }}
            $task = 'GoldClub-LivePush-Start'
            Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
            $action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $dir
            $prin = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
            $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
            Register-ScheduledTask -TaskName $task -Action $action -Principal $prin -Settings $set -Force | Out-Null
            Start-ScheduledTask -TaskName $task
            $started = $true
        }} catch {{
            Start-Process -FilePath $exe -WorkingDirectory $dir
            $started = $true
        }}
        if (-not $started) {{ throw '{start_fail}' }}
        """
    ).strip()
    tail = textwrap.dedent(after_start).strip()
    return head + "\n" + tail + '\n        "OK $exe"'


_SLOT_WATCHDOG_MARKER = "GoldClub-LivePush-Watchdog"


def _slot_bootstrap_watchdog_script(
    candidates: tuple[str, ...],
    *,
    launcher: str = "bootstrap",
) -> str:
    """Detached starter: if Apply dies after kill, still launch the game."""
    quoted = ", ".join("'" + c.replace("'", "''") + "'" for c in candidates)
    kind = (launcher or "bootstrap").strip().casefold()
    if kind == "game-start":
        game_names = "OneHand,game-start"
    else:
        game_names = "Bootstrap,OneHand"
    return textwrap.dedent(
        f"""
        # {_SLOT_WATCHDOG_MARKER}
        $ErrorActionPreference = 'SilentlyContinue'
        $deadline = (Get-Date).AddMinutes(10)
        while ((Get-Date) -lt $deadline) {{
            $game = Get-Process -Name {game_names} -ErrorAction SilentlyContinue
            if ($game) {{ exit 0 }}
            $tool = @(Get-Process -Name ConfigScanner,LogInvestigator -ErrorAction SilentlyContinue)
            $py = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{
                $_.Name -match '^(python|pythonw)\\.exe$' -and
                [string]$_.CommandLine -match '(?i)gui_app|config_scanner|ConfigScanner'
            }})
            if ($tool.Count -gt 0 -or $py.Count -gt 0) {{ Start-Sleep -Seconds 5; continue }}
            Start-Sleep -Seconds 8
            $game = Get-Process -Name {game_names} -ErrorAction SilentlyContinue
            if ($game) {{ exit 0 }}
            $exe = $null
            foreach ($c in @({quoted})) {{
                if (Test-Path -LiteralPath $c) {{ $exe = $c; break }}
            }}
            if (-not $exe) {{ exit 1 }}
            __ENSURE_AURUM__
            $dir = Split-Path -Parent $exe
            try {{
                $user = 'goldclub'
                $cs = Get-CimInstance Win32_ComputerSystem
                if ($cs.UserName) {{ $user = [string]$cs.UserName }}
                $task = 'GoldClub-LivePush-Start'
                Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
                $action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $dir
                $prin = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
                $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
                Register-ScheduledTask -TaskName $task -Action $action -Principal $prin -Settings $set -Force | Out-Null
                Start-ScheduledTask -TaskName $task
            }} catch {{
                Start-Process -FilePath $exe -WorkingDirectory $dir
            }}
            exit 0
        }}
        exit 0
        """
    ).strip().replace("__ENSURE_AURUM__", _ENSURE_AURUM_PS)


def _arm_slot_bootstrap_watchdog(
    scan_target: str, dest: Path | str | None = None
) -> None:
    """Fire-and-forget Bootstrap start if ConfigScanner is killed mid-Apply."""
    if os.name != "nt":
        return
    if not _slot_target_is_local(scan_target) or not running_on_egm():
        return
    launcher = slot_start_launcher(scan_target, dest)
    script = _slot_bootstrap_watchdog_script(
        slot_start_candidates(scan_target, dest, launcher=launcher),
        launcher=launcher,
    )
    path = Path(tempfile.gettempdir()) / "GoldClub-LivePush-Watchdog.ps1"
    try:
        path.write_text(script + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        _lp_log(f"watchdog write failed: {exc}")
        return
    no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    creation = no_window
    creation |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    creation |= 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    try:
        probe = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -match 'GoldClub-LivePush-Watchdog' } | "
                "Select-Object -First 1 -ExpandProperty ProcessId",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            creationflags=no_window,
        )
        if (probe.stdout or "").strip().isdigit():
            return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
            close_fds=True,
        )
        _lp_log(f"armed {_SLOT_WATCHDOG_MARKER}")
    except OSError as exc:
        _lp_log(f"watchdog arm failed: {exc}")


# Snapshot labels -> build_config_pack sections (delta apply).
_LABEL_SECTIONS: dict[str, frozenset[str]] = {
    "SAS enabled": frozenset({"sas"}),
    "SAS address": frozenset({"sas"}),
    "Funds transfer": frozenset({"sas"}),
    "AFT": frozenset({"sas"}),
    "Lock when no SAS": frozenset({"sas"}),
    "Validation controler": frozenset({"sas", "aurum"}),
    "Cashless controler": frozenset({"sas", "aurum"}),
    "Handpay controler": frozenset({"sas", "aurum"}),
    "Bonusing controler": frozenset({"sas", "aurum"}),
    "Note acceptor controler": frozenset({"sas", "aurum"}),
    "Enable switches": frozenset({"hardware"}),
    "Bill protocol": frozenset({"bill"}),
    "Bill notes": frozenset({"hardware"}),
    "Ticket printer": frozenset({"ticket"}),
    "Offline ticket": frozenset({"hardware", "oticket"}),
    "Ticket redeem": frozenset({"hardware"}),
    "Ticket currency ISO": frozenset({"hardware"}),
    "Dallas key": frozenset({"hardware"}),
    "Button deck": frozenset({"hw_drivers"}),
    "Currency": frozenset({"mgconfig", "jurisdiction", "hardware", "aurum"}),
    "Currency symbol": frozenset({"mgconfig", "jurisdiction"}),
    "Culture": frozenset({"mgconfig", "jurisdiction"}),
    "Language": frozenset({"mgconfig", "jurisdiction"}),
    COUNTRY_FLAG_LABEL: frozenset({"jurisdiction"}),
    "Market": frozenset({"mgconfig", "jurisdiction"}),
    "Denoms (cents)": frozenset(
        {"mgconfig", "jurisdiction", "link2win", "magicwheel", "math"}
    ),
    "Bet multipliers": frozenset({"math"}),
    "Magic wheel limit": frozenset({"magicwheel", "jurisdiction"}),
    "Magic wheel bet": frozenset({"magicwheel", "jurisdiction"}),
    "Magic wheel enabled": frozenset({"magicwheel", "jurisdiction"}),
    "Magic wheel max spins": frozenset({"magicwheel", "jurisdiction"}),
    "Magic wheel average": frozenset({"magicwheel", "jurisdiction"}),
    "Jackpot counters": frozenset({"mgconfig"}),
    "Jackpot receipt": frozenset({"hardware"}),
    "Jackpot celebration": frozenset({"mgconfig"}),
    "Cashout button": frozenset({"mgconfig"}),
    "Default bet": frozenset({"mgconfig"}),
    "Show denom selector": frozenset({"mgconfig"}),
    "Inactivity to selector": frozenset({"mgconfig"}),
    "Show all lines": frozenset({"mgconfig"}),
    "Display layout": frozenset({"mgconfig"}),
}
for _spec in LIMIT_SETUP_FIELDS:
    _LABEL_SECTIONS[_spec.label] = frozenset({"mgconfig"})
_LABEL_SECTIONS["Stacker auto-unlock"] = frozenset({"hardware"})
for _name in STANDARD_DOOR_SWITCH_NAMES:
    _LABEL_SECTIONS[door_switch_auto_unlock_label(_name)] = frozenset({"hardware"})


def live_push_changed_sections(
    live: SlotSetupRecipe, form: SlotSetupRecipe
) -> frozenset[str]:
    """Which ``build_config_pack`` sections must be written for the form delta."""
    old = dict(recipe_snapshot_rows(live))
    new = dict(recipe_snapshot_rows(form))
    sections: set[str] = set()
    for label, old_val in old.items():
        if old_val == new.get(label, "—"):
            continue
        sections.update(_LABEL_SECTIONS.get(label, ()))
    return frozenset(sections)


def live_push_ramclear_reasons(
    live: SlotSetupRecipe,
    form: SlotSetupRecipe,
    *,
    aurum_currency: str | None = None,
) -> tuple[str, ...]:
    """Reasons a slot RAM clear is required after this Live Push delta.

    Currency, denomination list, and bet-step (multiplier) changes leave NVRAM
    / trial state that OneHand rejects until the vendor ramclear task runs.

    When ``aurum_currency`` is provided (including empty string), a mismatch
    against the form jurisdiction currency is also a ramclear reason.
    """
    from config_scanner.denom_compat import denomination_lists_equal

    reasons: list[str] = []
    live_c = (
        live.jurisdiction.currency_name or live.hardware_currency_name or ""
    ).strip().upper()
    form_c = (
        form.jurisdiction.currency_name or form.hardware_currency_name or ""
    ).strip().upper()
    if form_c and live_c and form_c != live_c:
        reasons.append(f"currency {live_c} → {form_c}")
    elif form_c and not live_c:
        reasons.append(f"currency set to {form_c}")

    if aurum_currency is not None and form_c:
        aurum_c = (aurum_currency or "").strip().upper()
        if form_c != aurum_c and not any(
            "currency" in r.casefold() for r in reasons
        ):
            if aurum_c:
                reasons.append(f"Aurum currency {aurum_c} → {form_c}")
            else:
                reasons.append(f"Aurum currency missing → set {form_c}")

    live_denoms = list(live.denomination_list or [])
    form_denoms = [int(x) for x in (form.denomination_list or [])]
    if form_denoms and not denomination_lists_equal(form_denoms, live_denoms):
        reasons.append("denomination list")

    form_mults = list(form.play_limits.bet_multipliers or [])
    if not form_mults and form.math:
        form_mults = list(form.math[0].bet_multipliers or [])
    live_mults = list(live.play_limits.bet_multipliers or [])
    if not live_mults and live.math:
        live_mults = list(live.math[0].bet_multipliers or [])
    if form_mults and list(form_mults) != list(live_mults):
        reasons.append("bet multipliers / bet steps")

    return tuple(reasons)


LIVE_PUSH_RESTART_REQUIRED_TITLE = "Full stack restart required"
LIVE_PUSH_RAMCLEAR_RESTART_TITLE = "RAM clear and restart required"
LIVE_PUSH_WRITE_AND_RESTART = "Write and restart"

# Only writes that will not appear (or will NRE) until restack / ramclear.
# SAS address, lock-when-no-comms, and channel checkboxes are ordinary
# deltas — they use the normal Apply confirm, not this warning.
_SAS_RESTART_LABELS = frozenset({"SAS enabled", "AFT", "Funds transfer"})
_CURRENCY_RESTART_LABELS = frozenset(
    {"Currency", "Currency symbol", "Denoms (cents)", "Bet multipliers"}
)
_LANGUAGE_RESTART_LABELS = frozenset(
    {"Language", COUNTRY_FLAG_LABEL, "Culture"}
)
_DISPLAY_RESTART_LABELS = frozenset({"Display layout", "Button deck"})
_BILL_TICKET_RESTART_LABELS = frozenset(
    {"Bill protocol", "Ticket printer"}
)


def live_push_ramclear_notice(reasons: Sequence[str]) -> str:
    """Operator line when a slot RAM clear will run. Empty if none."""
    if not reasons:
        return ""
    return (
        "A RAM clear will run after write (required for: "
        + ", ".join(reasons)
        + "). That resets meters."
    )


def live_push_restart_reason_for_label(label: str) -> str | None:
    """Group name if this snapshot label needs the restart warning, else None."""
    if label in _CURRENCY_RESTART_LABELS:
        return "currency, denoms, or bet steps"
    if label in _LANGUAGE_RESTART_LABELS:
        return "language or country flag"
    if label == "Market":
        return "market"
    if label in _DISPLAY_RESTART_LABELS:
        return "display layout or button deck"
    if label in _SAS_RESTART_LABELS:
        return "SAS enable / AFT"
    if label in _BILL_TICKET_RESTART_LABELS:
        return "bill or ticket protocol"
    return None


def live_push_restart_required_reasons(
    live: SlotSetupRecipe,
    form: SlotSetupRecipe,
    *,
    full_pack: bool = False,
    push_licences: bool = False,
    goldclub: Path | None = None,
) -> tuple[str, ...]:
    """Why Apply must restart — empty for ordinary deltas such as SAS lock.

    Currency / denoms / bets, language, market, display, SAS enable or AFT,
    Link2Win restage, licence copy, and Write full pack. Not lock-when-no-comms,
    SAS address, or channel checkboxes.
    """
    reasons: list[str] = []
    seen: set[str] = set()

    def _add(reason: str | None) -> None:
        if reason and reason not in seen:
            seen.add(reason)
            reasons.append(reason)

    for line in recipe_change_lines(live, form):
        label = line.split(":", 1)[0].strip()
        _add(live_push_restart_reason_for_label(label))
    if goldclub is not None:
        from config_scanner.denom_compat import link2win_restage_change_line

        if link2win_restage_change_line(live, form, Path(goldclub)):
            _add("Link2Win math files")
    if full_pack:
        _add("full config pack rewrite")
    if push_licences:
        _add("licence files")
    return tuple(reasons)


# OneHand already deserialized these into RAM (Collect uses get_CashoutMode).
# SMB overwrite of mgconfig does not call set_CashoutMode; the Service menu
# does. Reloading OneHand (game-start) runs LoadMgConfiguration. Aurum / SAS
# / HWSubsys do not read CashoutButtonMode.
_ONEHAND_RELOAD_LABELS = frozenset({"Cashout button"})


def live_push_onehand_reload_reasons(
    live: SlotSetupRecipe,
    form: SlotSetupRecipe,
) -> tuple[str, ...]:
    """Snapshot labels that need an OneHand reload (not a full stack bounce)."""
    reasons: list[str] = []
    seen: set[str] = set()
    for line in recipe_change_lines(live, form):
        label = line.split(":", 1)[0].strip()
        if label in _ONEHAND_RELOAD_LABELS and label not in seen:
            seen.add(label)
            reasons.append(label)
    return tuple(reasons)


def live_push_apply_mode(
    *,
    kind: str,
    restart_stack: bool,
    restart_reasons: Sequence[str] = (),
    ramclear_reasons: Sequence[str] = (),
    onehand_reload_reasons: Sequence[str] = (),
) -> str:
    """How Apply restacks: ``fullstack``, ``onehand``, or ``write``.

    Cashout-only is ``onehand`` even when the Restart checkbox is on — that
    field is not lock-now / Aurum, and fullstack would bounce SAS for nothing.
    """
    slot = (kind or "").strip().casefold() == "slot"
    if slot and ramclear_reasons:
        return "fullstack"
    if slot and restart_reasons and restart_stack:
        return "fullstack"
    if slot and onehand_reload_reasons and not restart_reasons:
        return "onehand"
    if restart_stack:
        return "fullstack"
    return "write"


def live_push_restart_required_text(
    *,
    kind: str,
    change_lines: Sequence[str],
    ramclear_reasons: Sequence[str] = (),
    full_pack: bool = False,
    backup: bool = False,
    push_licences: bool = False,
) -> str:
    """Plain-language body for the restart-required Apply dialog."""
    parts: list[str] = [
        "The game is still running, so it will keep the old settings.",
    ]
    ramclear_line = live_push_ramclear_notice(ramclear_reasons)
    if ramclear_line:
        parts.append(ramclear_line)
    parts.append("A full stack restart is required before the new settings appear.")
    if change_lines:
        parts.append("What will be written:\n• " + "\n• ".join(change_lines))
    elif full_pack:
        parts.append("The full Live Push config pack will be rewritten.")
    if full_pack and change_lines:
        parts.append("Full pack: all Live Push config files will be rewritten.")
    if backup:
        parts.append("A backup of those live files is taken first.")
    if push_licences:
        parts.append(
            "Missing licence XML / licence.dll will be copied next to "
            "OneHand (existing licence files are not overwritten)."
        )
    if kind == "slot":
        parts.append(
            "Write and restart will stop the game, write the files, then "
            "start it again. Windows will not reboot."
        )
    else:
        parts.append(
            "Write and restart will stop the game, write the files, then "
            "start the stack again. Windows will not reboot."
        )
    return "\n\n".join(parts)


def run_slot_ramclear(scan_target: str) -> tuple[bool, str]:
    """Run the vendor slot ramclear maintenance task (game must already be stopped)."""
    from config_scanner.cabinet_repairs import (
        RepairError,
        _repair_ramclear,
        build_context,
    )

    if not _slot_target_is_local(scan_target):
        host = unc_host_from_target(scan_target) or ""
        if not remote_winrm_ready(host):
            return False, winrm_skip_detail(host)

    try:
        ctx = build_context(scan_target, "slot")
        outcome = _repair_ramclear(ctx)
    except RepairError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"RAM clear failed: {exc}"
    detail = outcome.detail
    if outcome.notes:
        detail = f"{detail} ({'; '.join(outcome.notes[-3:])})"
    return bool(outcome.ok), detail


def restart_slot_hwsubsys(scan_target: str) -> tuple[bool, str]:
    """Ensure GoldClub hardware services are up before Bootstrap/OneHand.

    The Windows service is named ``GoldClub Hardware Subsystem`` (binary
    ``HWSubsys\\hwsubsys.exe``). Looking for a service named ``HWSubsys`` always
    misses and used to return success — OneHand then dies with
    ``Hardware subsystem connection timeout``.
    """
    script = textwrap.dedent(
        r"""
        $ErrorActionPreference = 'SilentlyContinue'
        $names = @(
            'GoldClub.Logging.LogDaemon',
            'GoldClub Serial Communication Gateway',
            'GoldClub Serial Communication Gateway SAS',
            'GoldClub Hardware Subsystem',
            'GoldClub.Aurum.Services'
        )
        $notes = New-Object System.Collections.Generic.List[string]
        foreach ($name in $names) {
            $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
            if (-not $svc) {
                $svc = Get-Service -DisplayName $name -ErrorAction SilentlyContinue
            }
            if (-not $svc) {
                $notes.Add("$name missing")
                continue
            }
            # Aurum and HWSubsys must reload config (SAS lock, currency). Always bounce.
            if ($name -eq 'GoldClub Hardware Subsystem' -or $name -eq 'GoldClub.Aurum.Services') {
                Restart-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
            } elseif ($svc.Status -ne 'Running') {
                Start-Service -Name $svc.Name -ErrorAction SilentlyContinue
            }
            $svc = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
            $st = if ($svc) { [string]$svc.Status } else { 'gone' }
            $notes.Add("$name $st")
        }
        $deadline = (Get-Date).AddSeconds(20)
        $hw = $null
        do {
            $hw = Get-Service -Name 'GoldClub Hardware Subsystem' -ErrorAction SilentlyContinue
            if (-not $hw) {
                $hw = Get-Service -DisplayName 'GoldClub Hardware Subsystem' -ErrorAction SilentlyContinue
            }
            if ($hw -and $hw.Status -eq 'Running') { break }
            Start-Sleep -Milliseconds 400
            if ($hw) { $hw.Refresh() }
        } while ((Get-Date) -lt $deadline)
        $au = Get-Service -Name 'GoldClub.Aurum.Services' -ErrorAction SilentlyContinue
        if ($au) {
            $auDeadline = (Get-Date).AddSeconds(20)
            do {
                if ($au.Status -eq 'Running') { break }
                Start-Service -Name $au.Name -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 400
                $au.Refresh()
            } while ((Get-Date) -lt $auDeadline)
            $notes.Add("GoldClub.Aurum.Services wait=$([string]$au.Status)")
        }
        if ($hw -and $hw.Status -eq 'Running') {
            Start-Sleep -Seconds 12
        }
        $blob = ($notes -join '; ')
        if ($hw) { $blob = $blob + '; wait=' + [string]$hw.Status }
        if ($au -and $au.Status -ne 'Running') {
            Write-Output ($blob + '; Aurum not Running')
            exit 1
        }
        if (-not $hw) {
            Write-Output ($blob + '; hardware subsystem not installed')
            exit 0
        }
        if ($hw.Status -eq 'Running') {
            Write-Output $blob
            exit 0
        }
        Write-Output ($blob + '; hardware subsystem not Running')
        exit 1
        """
    ).strip()
    local = _slot_target_is_local(scan_target)
    try:
        if local:
            return _run_local_powershell(script, timeout=150)
        host = unc_host_from_target(scan_target) or ""
        if not remote_winrm_ready(host):
            return False, winrm_skip_detail(host)
        from automation.remote_exec import winrm_run_inline
        from network.lab_access import require_lab_fleet_ip

        ip = require_lab_fleet_ip(host)
        _ensure_lab_smb(ip)
        result = winrm_run_inline(ip=ip, script=script, timeout=180)
    except Exception as exc:  # noqa: BLE001
        return False, f"HWSubsys restart failed: {exc}"
    blob = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode == 0:
        return True, blob or "GoldClub Hardware Subsystem Running"
    return False, blob or f"HWSubsys restart exit {result.returncode}"


_SAS_LOCK_PROBE_SCRIPT = textwrap.dedent(
    r"""
    $ErrorActionPreference = 'SilentlyContinue'
    $au = Get-Service -Name 'GoldClub.Aurum.Services' -ErrorAction SilentlyContinue
    $aurum = if ($au -and $au.Status -eq 'Running') { '1' } else { '0' }
    $hits = @()
    try {
        $hits = @(Get-NetTCPConnection -LocalPort 31100 -State Listen,Established -ErrorAction SilentlyContinue)
    } catch {}
    if (-not $hits) {
        try {
            $hits = @(netstat -ano | Select-String -Pattern ':31100\s')
        } catch {}
    }
    $port = if ($hits -and $hits.Count -gt 0) { '1' } else { '0' }
    Write-Output ("AURUM={0} PORT31100={1}" -f $aurum, $port)
    exit 0
    """
).strip()

_SAS_LOCK_PROBE_RE = re.compile(
    r"AURUM=(?P<aurum>[01])\s+PORT31100=(?P<port>[01])",
    re.I,
)


def format_sas_lock_probe_line(
    *,
    lock_on: bool,
    port_31100_up: bool | None,
    aurum_running: bool | None = None,
) -> str:
    """One operator line: lock flag vs SAS 31100. Empty when the flag is off."""
    if not lock_on:
        return ""
    if port_31100_up is True:
        return (
            "Lock when no SAS is on; SAS 31100 is up so the game stays unlocked"
        )
    if port_31100_up is False:
        extra = ""
        if aurum_running is False:
            extra = " (Aurum is not Running)"
        return (
            "Lock when no SAS is on; 31100 is down — expect NO SAS COMMUNICATIONS"
            + extra
        )
    return "Lock when no SAS is on; could not check SAS 31100"


def parse_sas_lock_probe_blob(blob: str) -> tuple[bool | None, bool | None]:
    """Parse AURUM=/PORT31100= from the probe script. Unknowns stay None."""
    match = _SAS_LOCK_PROBE_RE.search(blob or "")
    if match is None:
        return None, None
    return match.group("aurum") == "1", match.group("port") == "1"


def probe_sas_lock_comms(scan_target: str) -> tuple[bool | None, bool | None]:
    """Aurum Running and TCP 31100 listen/established. None if unknown.

    Unit tests skip the live cabinet probe (PYTEST_CURRENT_TEST) so Apply
    tests stay offline. Monkeypatch this function when a test needs fakes.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None, None
    local = _slot_target_is_local(scan_target)
    try:
        if local:
            ok, blob = _run_local_powershell(_SAS_LOCK_PROBE_SCRIPT, timeout=30)
        else:
            host = unc_host_from_target(scan_target) or ""
            if not remote_winrm_ready(host):
                _lp_log(f"sas lock probe skip: {winrm_skip_detail(host)}")
                return None, None
            from automation.remote_exec import winrm_run_inline
            from network.lab_access import require_lab_fleet_ip

            ip = require_lab_fleet_ip(host)
            _ensure_lab_smb(ip)
            result = winrm_run_inline(
                ip=ip, script=_SAS_LOCK_PROBE_SCRIPT, timeout=45
            )
            blob = ((result.stdout or "") + (result.stderr or "")).strip()
            ok = result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        _lp_log(f"sas lock probe failed: {exc}")
        return None, None
    if not ok and not blob:
        return None, None
    return parse_sas_lock_probe_blob(blob)


def probe_sas_lock_state(scan_target: str, dest: Path | str) -> str:
    """Disk LockGameWhenNoComms plus cabinet 31100 → one Apply-complete line."""
    try:
        gold = goldclub_root_from_target(dest)
        lock_on = bool(read_sas_settings(gold).lock_game_when_no_comms)
    except Exception as exc:  # noqa: BLE001
        _lp_log(f"sas lock probe disk read failed: {exc}")
        return ""
    if not lock_on:
        return ""
    aurum, port = probe_sas_lock_comms(scan_target)
    return format_sas_lock_probe_line(
        lock_on=True,
        port_31100_up=port,
        aurum_running=aurum,
    )


def backup_live_push_files(
    dest_goldclub: Path | str,
    relative_paths: Sequence[str],
    *,
    backup_root: Path | None = None,
) -> Path | None:
    """Copy live files that will be overwritten into a timestamped backup folder."""
    from config_scanner.paths import tool_root

    dest = goldclub_root_from_target(dest_goldclub)
    paths = [p for p in relative_paths if p]
    if not paths:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path(backup_root) if backup_root is not None else (
        tool_root() / "live_push_backups"
    )
    bak = root / stamp
    copied = 0
    for rel in paths:
        norm = rel.replace("\\", "/").lstrip("/")
        src = dest / norm
        try:
            if not src.is_file():
                continue
            target = bak / norm
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied += 1
        except OSError as exc:
            raise OSError(f"Could not backup {norm}: {exc}") from exc
    if copied == 0:
        return None
    return bak


def restore_live_push_backup(
    dest_goldclub: Path | str,
    backup_dir: Path,
) -> list[str]:
    """Copy a Live Push backup folder back onto the live Goldclub root."""
    from network.lab_access import safe_join_under

    dest = goldclub_root_from_target(dest_goldclub)
    root = Path(backup_dir)
    errors: list[str] = []
    if not root.is_dir():
        return [f"backup folder missing: {root}"]
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            target = safe_join_under(dest, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        except (OSError, ValueError) as exc:
            errors.append(f"{rel}: {exc}")
    return errors


def _short_fail(detail: str) -> str:
    text = (detail or "").strip()
    if not text:
        return "unknown error"
    if "game-start.exe not found" in text:
        return "game-start.exe did not start on the cabinet."
    if "Bootstrap.exe not found" in text:
        return "Bootstrap.exe did not start on the cabinet."
    return text.splitlines()[0][:240]


def live_push_catalog() -> dict[str, tuple[str, ...]]:
    """Ready-to-select values for the live-push form."""
    currencies = list(CURRENCY_LABELS)
    cultures = list(CULTURE_CHOICES)
    languages = list(LANGUAGE_CHOICES)
    markets: list[str] = []
    denoms = list(DENOM_PRESETS)
    for prof in load_jurisdictions():
        if prof.currency:
            currencies.append(prof.currency.upper())
        if prof.culture:
            cultures.append(prof.culture)
        if prof.language:
            languages.append(prof.language)
        if prof.target_market:
            markets.append(prof.target_market)
        if prof.country:
            markets.append(prof.country)
        if prof.allowed_denoms:
            denoms.append(", ".join(str(d) for d in prof.allowed_denoms))
    markets.extend(
        [
            "PuertoRico",
            "TT",
            "TrinidadTobago",
            "Trinidad&Tobago",
            "Panama",
            "Jamaica",
            "Colombia",
            "Guyana",
            "Mexico",
            "Peru",
            "Poland",
        ]
    )
    return {
        "currencies": _unique(currencies),
        "cultures": _unique(cultures),
        "languages": _unique(languages),
        "markets": ordered_live_markets(_unique(markets)),
        "denoms": _unique(denoms),
        "bet_multipliers": BET_MULTIPLIER_PRESETS,
        "symbols": CURRENCY_SYMBOL_CHOICES,
        "magic_wheel_limits": tuple(str(v) for v in MAGIC_WHEEL_LIMITS),
        "jackpot_layouts": JACKPOT_LAYOUTS,
        "celebration_limits": CELEBRATION_LIMITS,
        "cashout_modes": CASHOUT_MODES,
        "default_bets": DEFAULT_BETS,
    }


def locale_defaults_for_currency(code: str) -> LocaleDefaults | None:
    """Best market defaults for an ISO currency (prefer OL+SAS profiles)."""
    want = (code or "").strip().upper()
    if not want:
        return None
    chosen = None
    for prof in load_jurisdictions():
        if (prof.currency or "").strip().upper() != want:
            continue
        chosen = prof
        if "sas_only" not in (prof.id or "").casefold():
            break
    if chosen is None:
        return None
    symbol = (
        str((chosen.expected or {}).get("locale.currency_short_symbol") or "")
        or str((chosen.expected or {}).get("locale.jur_currency_symbol") or "")
        or currency_symbol_for(want)
    )
    return LocaleDefaults(
        currency=want,
        culture=chosen.culture,
        language=chosen.language,
        market=chosen.target_market,
        denoms=tuple(int(d) for d in (chosen.allowed_denoms or ())),
        symbol=symbol,
        profile_id=chosen.id,
    )


def _norm_market_key(value: str) -> str:
    return (
        (value or "")
        .casefold()
        .replace(" ", "")
        .replace("&", "")
        .replace("_", "")
        .replace("-", "")
    )


def locale_defaults_for_market(market: str) -> LocaleDefaults | None:
    """UI preset for a Target market selection (currency / culture / language / symbol).

    Picking Poland fills PLN + pl-PL + Polish, Colombia fills COP, etc. The
    operator can still change any field afterward.
    """
    raw = (market or "").strip()
    if not raw:
        return None
    want = _norm_market_key(raw)
    exact = None
    fuzzy = None
    for prof in load_jurisdictions():
        candidates = {
            _norm_market_key(prof.target_market or ""),
            _norm_market_key(prof.country or ""),
            _norm_market_key(prof.id or ""),
        }
        candidates.discard("")
        if want in candidates:
            exact = prof
            break
        if any(want in c or c in want for c in candidates):
            if fuzzy is None:
                fuzzy = prof
    chosen = exact or fuzzy
    if chosen is None:
        return None
    currency = (chosen.currency or "").strip().upper()
    symbol = (
        str((chosen.expected or {}).get("locale.currency_short_symbol") or "")
        or str((chosen.expected or {}).get("locale.jur_currency_symbol") or "")
        or currency_symbol_for(currency)
    )
    return LocaleDefaults(
        currency=currency,
        culture=(chosen.culture or "").strip(),
        language=(chosen.language or "").strip(),
        market=(chosen.target_market or raw).strip(),
        denoms=tuple(int(d) for d in (chosen.allowed_denoms or ())),
        symbol=symbol,
        profile_id=chosen.id or "",
    )


def cabinet_host_reachable(target: str, *, timeout_sec: float = 2.0) -> tuple[bool, str]:
    """Fast TCP check so a dead UNC share never touches the Windows redirector."""
    host = unc_host_from_target(target)
    if not host:
        return True, ""
    try:
        from network.lab_access import probe_tcp_port
    except Exception:  # noqa: BLE001
        return True, ""
    if probe_tcp_port(host, 445, timeout_sec=timeout_sec):
        return True, ""
    if probe_tcp_port(host, 139, timeout_sec=min(1.0, timeout_sec)):
        return True, ""
    return False, (
        f"{host} is not reachable (SMB port 445 did not answer). "
        "The cabinet is off or this PC is not on the lab network."
    )


def _local_live_candidates() -> tuple[str, ...]:
    """Local Goldclub roots: cabinet volume first, then the same image drives
    the Config Scanner tab sweeps for a slot repo (no full alphabet sweep).

    Order: unlocked ``G:`` (BitLocker game volume), ``C:\\Goldclub`` and its
    ``slot`` child, then ``D:``..``H:`` USB/image roots and their ``Goldclub``
    folders. Bare drive roots are probed with a short timeout so a locked or
    sleeping volume never blocks the UI. Lab UNCs are never listed here —
    the operator types an IP only when no local tree exists.
    """
    out: list[str] = [r"G:", r"C:\Goldclub", r"C:\goldclub", r"C:\Goldclub\slot"]
    for drive in ("D:", "E:", "F:", "H:"):
        out.append(drive)
        out.append(rf"{drive}\Goldclub")
        out.append(rf"{drive}\Goldclub\slot")
    return tuple(out)


_LOCAL_LIVE_CANDIDATES: tuple[str, ...] = _local_live_candidates()
DEFAULT_REMOTE_LIVE_TARGET = r"\\10.0.0.111\slot"
THIS_PC_GOLDCLUB = r"C:\Goldclub"
THIS_PC_MISSING_STATUS = (
    "This PC has no Goldclub tree (G:, C:\\Goldclub, D:-H: Goldclub). "
    "Type a cabinet IP or Browse."
)
_IPV4_HOST_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def _exists_quick(path: Path, *, timeout_sec: float = 0.3) -> bool:
    """``Path.exists`` that gives up quickly (locked BitLocker volumes hang otherwise)."""
    import threading

    box: dict[str, bool] = {"ok": False}

    def _worker() -> None:
        try:
            box["ok"] = bool(path.exists())
        except OSError:
            box["ok"] = False

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout_sec)
    if thread.is_alive():
        return False
    return box["ok"]


def _is_bare_drive(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]:?", text))


def _local_candidate_path(raw: str) -> str:
    """``G:`` -> ``G:\\`` so Path never treats it as drive-relative to the cwd."""
    text = str(raw).strip()
    if _is_bare_drive(text):
        return text.rstrip(":") + ":\\"
    return text


def _local_goldclub_ready(raw: str) -> bool:
    """True when the path looks like a usable unlocked Goldclub tree."""
    try:
        text = str(raw).replace("/", "\\").rstrip("\\")
        # Locked BitLocker / sleeping removable drives can hang Path.exists for
        # minutes — bail fast on bare drive roots.
        if _is_bare_drive(text) and not _exists_quick(
            Path(_local_candidate_path(text)), timeout_sec=0.25
        ):
            return False
        root = goldclub_root_from_target(_local_candidate_path(raw))
        if not looks_like_goldclub_root(root):
            return False
        if text.upper() in {"G:", "G"}:
            return _exists_quick(root / "Bootstrap.exe", timeout_sec=0.25) or (
                _exists_quick(Path(r"G:\Bootstrap.exe"), timeout_sec=0.25)
            )
        return True
    except (OSError, TimeoutError, ValueError):
        return False


def this_pc_live_target(
    *,
    local_candidates: tuple[str, ...] | None = None,
) -> str | None:
    """Local Goldclub if this machine is a cabinet, else ``None``.

    Does not fall back to a lab UNC share — type or recall a cabinet path instead.
    """
    from config_scanner.build_version import prefer_local_scan_target

    for raw in local_candidates if local_candidates is not None else _LOCAL_LIVE_CANDIDATES:
        if not _local_goldclub_ready(raw):
            continue
        try:
            root = goldclub_root_from_target(_local_candidate_path(raw))
        except (OSError, TimeoutError, ValueError):
            continue
        if looks_like_goldclub_root(root):
            return prefer_local_scan_target(str(root))
    return None


def detect_local_live_cabinet(
    *,
    local_candidates: tuple[str, ...] | None = None,
) -> str:
    """Local Goldclub path, or empty when this PC has no tree."""
    return this_pc_live_target(local_candidates=local_candidates) or ""


def is_default_remote_live_target(raw: str) -> bool:
    """True when *raw* is the shipped ``\\\\10.0.0.111\\slot`` default (any case/slashes)."""
    norm = (raw or "").strip().replace("/", "\\").rstrip("\\").casefold()
    return norm == DEFAULT_REMOTE_LIVE_TARGET.casefold()


def resolve_live_load_target(
    raw: str,
    *,
    prefer_local: bool,
    local_candidates: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    """Target to actually load, plus a note when it was swapped for a local root.

    The shipped default stays ``\\\\10.0.0.111\\slot``. With *prefer_local*,
    that default (and the ``This PC`` path) is first resolved against local
    Goldclub roots so a cabinet running the exe reads its own tree, never
    another EGM's share. Explicit cabinet paths are returned unchanged.
    """
    text = (raw or "").strip()
    if not prefer_local or not text:
        return text, ""
    is_this_pc = text.replace("/", "\\").rstrip("\\").casefold() == (
        THIS_PC_GOLDCLUB.casefold()
    )
    if not (is_default_remote_live_target(text) or is_this_pc):
        return text, ""
    local = this_pc_live_target(local_candidates=local_candidates)
    if not local or local.casefold().rstrip("\\") == text.casefold().rstrip("\\"):
        return text, ""
    return local, f"Local Goldclub found at {local}; using it instead of {text}."


def initial_live_cabinet_target(
    *,
    saved: str | None = None,
    local: str | None = None,
) -> str:
    """Path for the Live Push cabinet field on launch.

    A remembered UNC wins so a workstation does not auto-scan This PC.
    Else the local Goldclub tree when this machine is a cabinet.
    Else empty — never a hardcoded lab IP.
    """
    text = (saved or "").strip()
    if text:
        return text
    local_text = (local or "").strip()
    if local_text:
        return local_text
    return ""


DEFAULT_CABINET_IP = "10.0.0.111"


def cabinet_ip_prefill(default_ip: str = DEFAULT_CABINET_IP) -> tuple[str, int, int]:
    """Text to pre-fill the Cabinet field with when nothing else is known, plus
    the (start, length) of its last octet so the caller can select it.

    The operator then only types the last digits (``111`` -> ``98``) instead
    of the whole address. Lab EGMs all sit on ``10.0.0.x``.
    """
    text = (default_ip or "").strip()
    if not text or "." not in text:
        return text, len(text), 0
    start = text.rfind(".") + 1
    return text, start, len(text) - start


def is_scratch_cabinet_target(target: str) -> bool:
    """True for a throwaway path (``%TEMP%``, pytest tmpdir) — never a cabinet.

    Keeps a stray write out of the Cabinet field and drops one that is
    already stored.
    """
    text = str(target or "").strip().replace("/", "\\")
    if not text:
        return False
    key = text.rstrip("\\").casefold()
    if "pytest-of-" in key:
        return True
    for scratch in (tempfile.gettempdir(), os.environ.get("TEMP", "")):
        base = str(scratch or "").strip().replace("/", "\\").rstrip("\\").casefold()
        if base and (key == base or key.startswith(base + "\\")):
            return True
    return False


def merge_live_target_history(
    newest: str,
    recent: list[str] | tuple[str, ...] | None = None,
    *,
    limit: int = 8,
) -> list[str]:
    """Newest first, de-duped (slash/case-insensitive), capped. Empty newest is skipped."""
    cap = max(1, int(limit))
    out: list[str] = []
    seen: set[str] = set()
    for raw in (newest, *(recent or ())):
        text = strip_cabinet_combo_label(str(raw or "").strip())
        if not text:
            continue
        key = text.replace("/", "\\").rstrip("\\").casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= cap:
            break
    return out


_CABINET_LABEL_SERIAL_RE = re.compile(
    r"^(?P<path>.*?)\s+\((?P<serial>[A-Za-z][A-Za-z0-9_-]{1,31})\)$"
)


def strip_cabinet_combo_label(raw: str) -> str:
    """Drop a trailing `` (GST20661)`` so Load still gets a real path."""
    text = (raw or "").strip().strip('"')
    match = _CABINET_LABEL_SERIAL_RE.fullmatch(text)
    if match:
        return match.group("path").strip()
    return text


def cabinet_cache_key(raw: str) -> str:
    """Stable key for the serial cache: lab IP when present, else normalized path."""
    text = strip_cabinet_combo_label(raw)
    if not text:
        return ""
    try:
        from network.lab_access import lab_lan_ip_from_text

        ip = lab_lan_ip_from_text(text)
    except Exception:  # noqa: BLE001
        ip = None
    if ip:
        return ip
    return text.replace("/", "\\").rstrip("\\").casefold()


def format_cabinet_combo_label(path: str, serial: str | None = None) -> str:
    """Dropdown text: ``10.0.0.76 (GST20661)`` or the path alone when unknown."""
    text = strip_cabinet_combo_label(path)
    sn = (serial or "").strip().upper()
    if not text:
        return ""
    if not sn:
        return text
    if f"({sn})" in text:
        return text
    return f"{text} ({sn})"


def remember_cabinet_serial_for_target(
    target: str, *, serial: str | None = None
) -> str:
    """Cache MachineName for *target*. Reads the cabinet only when *serial* is empty."""
    from config_manager import SettingsManager
    from config_scanner.build_version import read_machine_serial_from_target

    text = strip_cabinet_combo_label(target)
    sn = (serial or "").strip().upper()
    if not sn and text:
        sn = (read_machine_serial_from_target(text) or "").strip().upper()
    if not text or not sn:
        return ""
    return SettingsManager.remember_cabinet_serial(text, sn)


def live_targets_for_ip(raw: str) -> tuple[str, ...]:
    """UNC Goldclub roots for a typed cabinet IP or pasted share."""
    from config_scanner.build_version import normalize_scan_target

    text = strip_cabinet_combo_label((raw or "").strip().strip('"'))
    if not text:
        return ()
    if text.startswith("\\\\"):
        return (normalize_scan_target(text),)
    first, sep, rest = text.partition("\\")
    if _IPV4_HOST_RE.fullmatch(first) and sep and rest.strip():
        return (normalize_scan_target(rf"\\{first}\{rest.strip()}"),)
    host = first.strip()
    if not _IPV4_HOST_RE.fullmatch(host):
        return ()
    return (
        rf"\\{host}\c$\Goldclub",
        rf"\\{host}\slot",
        rf"\\{host}\c$\Goldclub\slot",
    )


def cabinet_hint_needs_resolve(raw: str) -> bool:
    """True for a bare IP (or incomplete share) that Load would expand.

    A typed ``10.0.0.76`` is not a Goldclub root; Snapshots must expand it to
    ``\\\\10.0.0.76\\c$\\Goldclub`` without waiting for the Load button.
    A path that already is one of the candidate roots does not need another try.
    """
    text = (raw or "").strip().strip('"')
    if not text:
        return False
    candidates = live_targets_for_ip(text)
    if not candidates:
        return False
    key = text.replace("/", "\\").rstrip("\\").casefold()
    return all(
        c.replace("/", "\\").rstrip("\\").casefold() != key for c in candidates
    )


def resolve_live_target_from_user(
    raw: str,
    *,
    probe: bool = True,
) -> str:
    """Local path, pasted UNC, or first reachable share for a typed IP."""
    text = strip_cabinet_combo_label((raw or "").strip().strip('"'))
    if not text:
        return ""
    if not text.startswith("\\\\") and not _IPV4_HOST_RE.fullmatch(text.split("\\", 1)[0]):
        return text
    candidates = live_targets_for_ip(text)
    if not candidates:
        return text
    if not probe:
        return candidates[0]
    for cand in candidates:
        try:
            if _exists_quick(Path(cand), timeout_sec=1.2) and _local_goldclub_ready(cand):
                return cand
        except (OSError, TimeoutError, ValueError):
            continue
    return candidates[0]


def default_live_cabinet_target(
    *,
    local_candidates: tuple[str, ...] | None = None,
    remote: str = "",
) -> str:
    """Pick a local Goldclub tree. Empty when none — do not guess a lab IP.

    ``prefer_local_scan_target`` still folds a loopback admin share back to a
    drive letter when this PC *is* the host. Pass *remote* only when the
    caller already has an operator-typed share. Live Push uses
    :func:`initial_live_cabinet_target` so a remembered UNC wins over This PC.
    """
    from config_scanner.build_version import prefer_local_scan_target

    local = this_pc_live_target(local_candidates=local_candidates)
    if local:
        return local
    text = (remote or "").strip()
    return prefer_local_scan_target(text) if text else ""


def load_error_dialog_text(error: str | None) -> str:
    """Body for the Load warning. Never return blank (empty QMessageBox)."""
    text = str(error or "").strip()
    return text or "Cannot load cabinet."


def denoms_effectively_equal(live: SlotSetupRecipe, form: SlotSetupRecipe) -> bool:
    """True when the form plays the same denoms the cabinet plays now.

    With ``ShowDenominationSelector=false`` OneHand plays only the first entry
    of mgconfig ``DenominationList``; the rest is the CS catalog. Typing ``1``
    on a cabinet that lists ``1, 2, 5, ... 5000`` and plays 1c is therefore not
    a change. Both lists empty, or the raw lists equal, is also equal.
    """
    live_list = [int(x) for x in (live.denomination_list or [])]
    form_list = [int(x) for x in (form.denomination_list or [])]
    if denomination_lists_equal(live_list, form_list):
        return True
    if not live_list or not form_list:
        return False
    return denomination_lists_equal(
        playable_denoms_from_recipe(form), playable_denoms_from_recipe(live)
    )


def normalize_effective_denoms(
    live: SlotSetupRecipe, form: SlotSetupRecipe
) -> SlotSetupRecipe:
    """Keep the cabinet's own denom catalog when the form only restates the live denom.

    Returns *form* unchanged when denoms differ. Otherwise copies the live
    ``DenominationList`` / ``CreditRateValues`` onto *form* so Apply does not
    shrink a working catalog to a single value and nothing is marked changed.
    """
    if not denoms_effectively_equal(live, form):
        return form
    live_list = [int(x) for x in (live.denomination_list or [])]
    form_list = [int(x) for x in (form.denomination_list or [])]
    if denomination_lists_equal(live_list, form_list):
        return form
    form.denomination_list = list(live_list)
    form.credit_rate_values = list(live.credit_rate_values or live_list)
    return form


def live_field_matches(live: SlotSetupRecipe, form: SlotSetupRecipe) -> dict[str, bool]:
    """True for each snapshot label whose form value still equals the cabinet.

    ``Denoms (cents)`` compares what the game plays, not the raw catalog text.
    """
    old = dict(recipe_snapshot_rows(live))
    new = dict(recipe_snapshot_rows(form))
    out = {label: old.get(label) == new.get(label) for label in old}
    if "Denoms (cents)" in out and not out["Denoms (cents)"]:
        out["Denoms (cents)"] = denoms_effectively_equal(live, form)
    return out


LIVE_FIELD_TOOLTIP_ADVISORY = (
    "Amber: a scanner rule disagrees with the running cabinet, which already "
    "has this value and the game is up. Not blocking -- nothing is written for "
    "this field unless you change it."
)
LIVE_FIELD_TOOLTIP_MATCH = (
    "Green: matches the live cabinet. No change will be written for this field."
)
LIVE_FIELD_TOOLTIP_CHANGED = (
    "Orange: editable in Live Push and your value differs from the live cabinet. "
    "Apply writes only the files for changed fields (unless Write full pack is on)."
)
LIVE_FIELD_TOOLTIP_EDITABLE = (
    "Orange: you can change this field in Live Push after the cabinet is loaded."
)

# What each Live Push control does (shown on hover, above the green/orange/red status).
LIVE_OPTION_HELP: dict[str, str] = {
    "Currency": (
        "Currency name written to mgconfig, jurisdiction, HardwareConfig, and "
        "AurumSetup (CurrencyCode / CurrencyId). All four must match or OneHand "
        "raises 'Jurisdiction currency … and Aurum selected currency … do not "
        "match'. Changing currency always triggers a RAM clear after write."
    ),
    "Currency symbol": (
        "Display symbol for amounts on the game UI (e.g. $, TT$)."
    ),
    "Culture": (
        "Windows culture / locale for number and date formatting "
        "(e.g. en-TT, en-JM)."
    ),
    "Language": (
        "Initial game language. On 2.0.1+ images this is the first entry of "
        "jurisdiction_config <Languages> and the list offers only the "
        "translations installed in slot\\languages on this cabinet; older "
        "images use mgconfig <Language>. This is not the picture on the "
        f"console button — use {COUNTRY_FLAG_LABEL} for that."
    ),
    COUNTRY_FLAG_LABEL: (
        "Picture on the console language button (jurisdiction_config "
        "Languages / TexturePath). Filenames are language tokens "
        "(flag_spanish.png or .dds) and often do not match the country in "
        "the bitmap — Puerto Rico packs commonly wire Spanish to a PR flag. "
        "Pick by the thumbnail. First language in the list is still the "
        "Language row (the default), not this picture."
    ),
    "Market": (
        "Target market / jurisdiction tag (mgconfig TargetMarket). Choosing a "
        "known market (Poland → PLN, Colombia → COP, TrinidadTobago → TTD, …) "
        "prefills currency, culture, language, and symbol as a UI preset — "
        "you can still change any field afterward."
    ),
    "Denoms (cents)": (
        "Playable denominations in cents (single or comma-separated). "
        "Written to mgconfig DenominationList and jurisdiction_config "
        "SingleDenomination (the on-screen DENOM). Choices go from 1c "
        "through 5000c. Live Push blocks a denom unless the live cabinet "
        "Link2WinBonusMath.json already contains that denom (red if it does not)."
    ),
    "Bet multipliers": (
        "Bet multiplier list offered to the player. Must match an approved bet "
        "setup for the selected denoms / market."
    ),
    "Magic wheel limit": (
        "Maximum money the magic wheel can award. Written to "
        "jurisdiction_config MagicWheelPackSettings/MoneyLimit and, when "
        "present, magicwheel_Config.xml — not mgconfig."
    ),
    "Magic wheel bet": (
        "Magic-wheel entry bet in cents. Newer gamepacks store this in "
        "jurisdiction_config MagicWheelPackSettings; older images use "
        "magicwheel_Config.xml. Must match the active denom pack."
    ),
    "Magic wheel enabled": (
        "Turns the magic-wheel feature on or off in jurisdiction_config "
        "MagicWheelPackSettings and/or magicwheel_Config.xml — not mgconfig."
    ),
    "Magic wheel max spins": (
        "Maximum spins allowed in a magic-wheel session "
        "(jurisdiction_config / magicwheel_Config.xml)."
    ),
    "Magic wheel average": (
        "Expected average win for magic-wheel math. Written with the other "
        "wheel knobs (not mgconfig). Must match the denom pack."
    ),
    "Jackpot counters": "How many progressive / jackpot counters the UI shows.",
    "Jackpot receipt": "Jackpot receipt / ticket layout style.",
    "Jackpot celebration": "Celebration screen limit / style after a jackpot.",
    "Cashout button": (
        "Writes mgconfig TransferParameters/CashoutButtonMode: Ticket, "
        "Handpay, or Cashless. Not a restart-required field: Apply reloads "
        "OneHand (game-start) so Collect uses the new mode, and leaves "
        "Aurum / SAS / hardware up. Cashless is WAT-to-host (Collect "
        "trigger with MODE:Cashless) and needs AFT/WAT — without a host, "
        "OneHand falls back to handpay."
    ),
    "Default bet": "Default bet selection when a game opens.",
    "Show denom selector": (
        "Show the on-screen denomination picker in the game UI."
    ),
    "Inactivity to selector": (
        "Seconds of idle time before returning to the game selector "
        "(0 disables the timeout)."
    ),
    "Show all lines": "Show all paylines on the game UI when enabled.",
    "SAS enabled": (
        "Enable the SAS host link (Aurum SASControler). Off = no SAS messaging."
    ),
    "SAS address": "SAS poll address for this EGM (typically 1–127).",
    "Funds transfer": (
        "Cashless funds-transfer method: AFT, EFT, or NONE."
    ),
    "AFT": "Enable AFT (Advanced Funds Transfer) when funds transfer is AFT.",
    "Lock when no SAS": (
        "Writes SASsetupData LockGameWhenNoComms. The game locks only if "
        "that SAS gateway/TCP drops (Aurum SASControler1 → CommCtrlSAS "
        "localhost:31100 / COM11 — the 31 Aug COM11-ghost case). A healthy "
        "31100 path stays unlocked. This is not lock now and not "
        "'no casino host on the LAN'."
    ),
    "Validation controler": (
        "SAS channel functionality: this host owns ticket validation "
        "(AurumSetup voucher OwnerHostId → SASControler1)."
    ),
    "Cashless controler": (
        "SAS channel functionality: this host owns cashless / WAT "
        "(AurumSetup WAT OwnerHostId → SASControler1)."
    ),
    "Handpay controler": (
        "SAS channel functionality: this host owns handpay "
        "(AurumSetup handpay OwnerHostId → SASControler1)."
    ),
    "Bonusing controler": (
        "SAS channel functionality: this host owns bonus devices "
        "(AurumSetup bonus OwnerHostId → SASControler1)."
    ),
    "Note acceptor controler": (
        "SAS channel functionality: this host owns the note acceptor "
        "(AurumSetup noteAcceptor OwnerHostId → SASControler1)."
    ),
    "Enable switches": (
        "HardwareConfig SwitchesSettings/Enabled — OneHand door-switch "
        "master. Switch Config Intelligent also keeps a separate encrypted "
        "bios/etc/application/game/switches.xml that Live Push does not write."
    ),
    "Stacker auto-unlock": (
        "BillSettings/StackerInstalledAutoUnlock — auto-unlock when the "
        "stacker is seated. Live 10.0.0.111 default is on."
    ),
    "Bill protocol": (
        "Bill acceptor protocol in Quixant / hardware config "
        "(e.g. MEI, JCM)."
    ),
    "Bill notes": (
        "HardwareConfig TokenMapping rows: acceptor code → credit value. "
        "Accept on/off is CanAccept — the note stays in the table so OneHand "
        "can still look it up; off means that bill is rejected. Apply writes "
        "slot/themes/HardwareConfig.xml."
    ),
    "Ticket printer": (
        "Ticket printer protocol (FutureLogic TITO, JCM, etc.). "
        "Separate from Offline ticket mode."
    ),
    "Offline ticket": (
        "HardwareConfig OfflineEnabled — standalone ticket mode without a SAS host. "
        "TITO can still print/redeem with offline off when Redeem is on."
    ),
    "Ticket redeem": "Allow ticket redemption (cashless / TITO redeem).",
    "Ticket currency ISO": (
        "Print / validate ticket amounts using ISO currency codes."
    ),
    "Credit limit": "Maximum player credit allowed on the machine.",
    "Jackpot limit": "Maximum jackpot award before handpay / limit rules apply.",
    "Max hopper payout limit": "Maximum amount paid from the hopper automatically.",
    "Handpay in limit": "Threshold for handpay-in / attendant credit.",
    "Bill limit": "Maximum bill denomination / bill credit accepted.",
    "Ticket payout limit": "Maximum ticket payout printed automatically.",
    "Handpay limit": "Threshold above which wins require handpay.",
    "Display layout": (
        "Switch mgconfig paths between 2-screen (dual top) and 3-screen "
        "(vertical stack). Requires theme assets for the target mode."
    ),
    "Dallas key": (
        "Service Dallas / iButton key ID stored in HardwareConfig Permissions. "
        "Use Read key to capture the physical key from BiOS hardware logs."
    ),
    "Button deck": "Hardware button-deck / driver profile for this cabinet.",
}


# Files each Live Push row opens on right-click (first existing path wins as
# the primary file; extras appear as extra menu items).
_CLIENTS_SET_REL = "Services/aurum/config/SASControler1/ClientsSet.xml"
_SAS_SETUP_REL = "Services/aurum/config/SASControler1/SASsetupData.xml"
_AURUM_SETUP_REL = "Services/aurum/config/AurumSetup.xml"
_QUIXANT_REL = "slot/hwdrivers/QuixantHardware.xml"
_HARDWARE_CONFIG_REL = "slot/themes/HardwareConfig.xml"
_MGCONFIG_REL = "slot/themes/mgconfig.xml"
_JURISDICTION_REL = "slot/themes/jurisdiction_config.xml"
_KEYBOARD_REL = "slot/hwdrivers/Keyboard.xml"

LIVE_FIELD_CONFIG_RELS: dict[str, tuple[str, ...]] = {
    "SAS enabled": (_CLIENTS_SET_REL,),
    "SAS address": (_CLIENTS_SET_REL,),
    "AFT": (_CLIENTS_SET_REL,),
    "Funds transfer": (_SAS_SETUP_REL,),
    "Lock when no SAS": (_SAS_SETUP_REL,),
    "Validation controler": (_AURUM_SETUP_REL,),
    "Cashless controler": (_AURUM_SETUP_REL,),
    "Handpay controler": (_AURUM_SETUP_REL,),
    "Bonusing controler": (_AURUM_SETUP_REL,),
    "Note acceptor controler": (_AURUM_SETUP_REL,),
    "Enable switches": (_HARDWARE_CONFIG_REL,),
    "Bill protocol": (_QUIXANT_REL,),
    "Bill notes": (_HARDWARE_CONFIG_REL,),
    "Ticket printer": (_QUIXANT_REL, _HARDWARE_CONFIG_REL),
    "Offline ticket": (_HARDWARE_CONFIG_REL,),
    "Ticket redeem": (_HARDWARE_CONFIG_REL,),
    "Ticket currency ISO": (_HARDWARE_CONFIG_REL,),
    "Display layout": (_MGCONFIG_REL,),
    "Dallas key": (_HARDWARE_CONFIG_REL,),
    "Button deck": (_KEYBOARD_REL,),
    "Currency": (_MGCONFIG_REL, _JURISDICTION_REL, _HARDWARE_CONFIG_REL),
    "Currency symbol": (_JURISDICTION_REL, _MGCONFIG_REL),
    "Culture": (_JURISDICTION_REL,),
    "Language": (_JURISDICTION_REL, _MGCONFIG_REL),
    COUNTRY_FLAG_LABEL: (_JURISDICTION_REL,),
    "Market": (_MGCONFIG_REL, _JURISDICTION_REL),
    "Denoms (cents)": (
        _MGCONFIG_REL,
        _JURISDICTION_REL,
        "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        "slot/themes/Link2WinFeature/Link2WinBonusMath_Config2.json",
    ),
    "Bet multipliers": ("slot/themes/*/MathSettings.xml",),
    "Magic wheel limit": (
        _JURISDICTION_REL,
        "slot/themes/magicwheel_Config.xml",
        "slot/themes/magicwheel.xml",
        "slot/themes/magicwheel_3Screens.xml",
    ),
    "Magic wheel bet": (
        _JURISDICTION_REL,
        "slot/themes/magicwheel_Config.xml",
        "slot/themes/magicwheel.xml",
        "slot/themes/magicwheel_3Screens.xml",
    ),
    "Magic wheel enabled": (
        _JURISDICTION_REL,
        "slot/themes/magicwheel_Config.xml",
        "slot/themes/magicwheel.xml",
        "slot/themes/magicwheel_3Screens.xml",
    ),
    "Magic wheel max spins": (
        _JURISDICTION_REL,
        "slot/themes/magicwheel_Config.xml",
        "slot/themes/magicwheel.xml",
        "slot/themes/magicwheel_3Screens.xml",
    ),
    "Magic wheel average": (
        _JURISDICTION_REL,
        "slot/themes/magicwheel_Config.xml",
        "slot/themes/magicwheel.xml",
        "slot/themes/magicwheel_3Screens.xml",
    ),
    "Jackpot counters": (_MGCONFIG_REL,),
    "Jackpot receipt": (_MGCONFIG_REL, _HARDWARE_CONFIG_REL),
    "Jackpot celebration": (_MGCONFIG_REL,),
    "Cashout button": (_MGCONFIG_REL,),
    "Default bet": (_MGCONFIG_REL,),
    "Show denom selector": (_MGCONFIG_REL,),
    "Inactivity to selector": (_MGCONFIG_REL,),
    "Show all lines": (_MGCONFIG_REL,),
}
for _spec in LIMIT_SETUP_FIELDS:
    LIVE_FIELD_CONFIG_RELS.setdefault(_spec.label, (_MGCONFIG_REL,))
LIVE_FIELD_CONFIG_RELS.setdefault("Stacker auto-unlock", (_HARDWARE_CONFIG_REL,))
LIVE_OPTION_HELP.setdefault(
    "Stacker auto-unlock",
    "BillSettings/StackerInstalledAutoUnlock — auto-unlock when the stacker is seated.",
)
for _name in STANDARD_DOOR_SWITCH_NAMES:
    _unlock_label = door_switch_auto_unlock_label(_name)
    LIVE_FIELD_CONFIG_RELS.setdefault(_unlock_label, (_HARDWARE_CONFIG_REL,))
    LIVE_OPTION_HELP.setdefault(
        _unlock_label,
        (
            "HardwareConfig SwitchSettings AutoUnlock for this door. "
            "When on, OneHand unlocks after the door closes. Live 10.0.0.111 "
            "default is off. Switch Config Intelligent writes a separate "
            "encrypted bios/.../game/switches.xml that is not edited here."
        ),
    )
FIELD_HELP = LIVE_OPTION_HELP

# Tags OneHand paints on the game DENOM / credit labels. UTF-8 cent or a
# leftover '?' here is what shows as ``5?¢`` on cabinet.
_DISPLAY_TEXT_TAGS: dict[str, tuple[str, ...]] = {
    "CurrencyBaseSymbol": ("Denoms (cents)", "Currency symbol"),
    "CurrencyBaseFormat": ("Denoms (cents)", "Currency symbol"),
    "CurrencyShortSymbol": ("Currency symbol",),
    "CurrencyShortFormat": ("Currency", "Denoms (cents)"),
    "CurrencyLongFormat": ("Currency", "Denoms (cents)"),
    "CurrencyFormat": ("Currency", "Denoms (cents)"),
    "CurrencySymbol": ("Currency symbol",),
    "CurrencyName": ("Currency",),
}

_DISPLAY_SCAN_RELS: tuple[str, ...] = (
    _JURISDICTION_REL,
    _MGCONFIG_REL,
    _HARDWARE_CONFIG_REL,
)

_DISPLAY_TAG_PATTERN = re.compile(
    r"<(?:[\w.-]+:)?("
    + "|".join(re.escape(tag) for tag in _DISPLAY_TEXT_TAGS)
    + r")(?:\s[^>]*)?>([^<]*)</",
    re.IGNORECASE,
)


def display_text_anomalies(text: str) -> tuple[str, ...]:
    """Reasons a live XML / form string will render as garbage on OneHand."""
    raw = text if text is not None else ""
    if raw == "":
        return ()
    reasons: list[str] = []
    if "\ufffd" in raw:
        reasons.append("Unicode replacement character")
    if "\u00a2" in raw or "¢" in raw:
        reasons.append("UTF-8 cent sign (shows as ?¢ on DENOM)")
    if "?" in raw:
        reasons.append("literal '?'")
    low = raw.casefold()
    if "&cent;" in low or "&#162;" in low or "&#xa2;" in low:
        reasons.append("HTML cent entity (shows as ?¢ on DENOM)")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in raw):
        reasons.append("control character")
    extras = [
        ch
        for ch in raw
        if ord(ch) > 127 and ch not in ("\u00a2", "¢", "\ufffd")
    ]
    if extras:
        shown = "".join(dict.fromkeys(extras))[:6]
        reasons.append(f"non-ASCII {shown!r} (OneHand reads ANSI)")
    return tuple(reasons)


def recipe_display_corruption_errors(
    recipe: SlotSetupRecipe | None,
) -> dict[str, str]:
    """Flag form values that would themselves paint as '?' on the game."""
    if recipe is None:
        return {}
    out: dict[str, str] = {}
    symbol = recipe.jurisdiction.currency_symbol or ""
    hits = display_text_anomalies(symbol)
    if hits:
        reason = (
            f"Corrupt currency symbol {symbol!r} ({'; '.join(hits)})."
        )
        out["Currency symbol"] = reason
        out["Denoms (cents)"] = reason
    name = recipe.jurisdiction.currency_name or recipe.hardware_currency_name or ""
    name_hits = display_text_anomalies(name)
    if name_hits:
        out.setdefault(
            "Currency",
            f"Corrupt currency name {name!r} ({'; '.join(name_hits)}).",
        )
    return out


def live_display_corruption_errors(goldclub: Path | str) -> dict[str, str]:
    """Scan live theme XML for symbols OneHand will show as '?' on DENOM."""
    out: dict[str, str] = {}
    root = Path(goldclub)
    for rel in _DISPLAY_SCAN_RELS:
        path = _resolve_goldclub_rel(root, rel)
        if path is None:
            continue
        try:
            if not path.is_file():
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        for match in _DISPLAY_TAG_PATTERN.finditer(text):
            tag_raw = match.group(1)
            canon = next(
                (tag for tag in _DISPLAY_TEXT_TAGS if tag.casefold() == tag_raw.casefold()),
                tag_raw,
            )
            value = match.group(2)
            anomalies = display_text_anomalies(value)
            if not anomalies:
                continue
            reason = (
                f"Corrupt display text in {path.name} <{canon}>: {value!r} "
                f"({'; '.join(anomalies)}). OneHand reads this as ANSI, so the "
                f"game DENOM label can show a '?' next to the amount."
            )
            for label in _DISPLAY_TEXT_TAGS.get(canon, ()):
                out.setdefault(label, reason)
    return out


_FIELD_LABEL_ALIASES: dict[str, str] = {
    "Money limit": "Magic wheel limit",
    "Wheel bet": "Magic wheel bet",
    "Max spins": "Magic wheel max spins",
    "Money average": "Magic wheel average",
    "Symbol": "Currency symbol",
    "Target market": "Market",
    "Inactivity": "Inactivity to selector",
}

_MAGIC_WHEEL_LABELS: frozenset[str] = frozenset(
    {
        "Magic wheel limit",
        "Magic wheel bet",
        "Magic wheel enabled",
        "Magic wheel max spins",
        "Magic wheel average",
    }
)


def canonicalize_live_field_label(label: str) -> str:
    """Map form captions (Money limit) to snapshot / right-click keys."""
    text = (label or "").strip()
    return _FIELD_LABEL_ALIASES.get(text, text)


def _live_field_rels_for(goldclub: Path, label: str) -> list[str]:
    canon = canonicalize_live_field_label(label)
    if canon in _MAGIC_WHEEL_LABELS:
        try:
            discovered = iter_magicwheel_setting_rels(goldclub)
        except (OSError, ValueError):
            discovered = []
        if discovered:
            return list(discovered)
    if canon == "Bet multipliers":
        try:
            math_rels = math_settings_rels(goldclub)
        except (OSError, ValueError):
            math_rels = []
        if math_rels:
            return math_rels
    return list(LIVE_FIELD_CONFIG_RELS.get(canon, ()))


def resolve_live_field_config_files(
    goldclub: Path | str, label: str
) -> list[Path]:
    """Existing config files for one Live Push setting row (cabinet order)."""
    found: list[Path] = []
    seen: set[str] = set()
    root = Path(goldclub)
    for rel in _live_field_rels_for(root, label):
        pattern = str(rel).replace("\\", "/").lstrip("/")
        try:
            matches = (
                list(root.glob(pattern))
                if "*" in pattern
                else [_resolve_goldclub_rel(root, pattern)]
            )
        except (OSError, ValueError):
            continue
        for path in matches:
            if path is None:
                continue
            try:
                if not path.is_file():
                    continue
                key = str(path).casefold()
                if key in seen:
                    continue
                seen.add(key)
                found.append(path)
            except OSError:
                continue
    return found


def live_field_validation_errors(errors: list[str]) -> dict[str, str]:
    """Map snapshot labels to the first validation error that blocks apply."""
    out: dict[str, str] = {}
    for err in errors:
        low = err.casefold()
        labels: list[str] = []
        if "magic wheel" in low:
            labels.extend(
                ["Magic wheel bet", "Magic wheel average", "Denoms (cents)"]
            )
        elif "bet multiplier" in low:
            labels.append("Bet multipliers")
        elif "target market" in low:
            labels.extend(["Market", "Currency"])
        elif any(
            token in low
            for token in (
                "link2win",
                "bonusmath",
                "country pack",
                "single denomination",
                "does not include",
                "not allowed for",
                "denom ",
            )
        ):
            labels.append("Denoms (cents)")
        for label in labels:
            out.setdefault(label, err)
    return out


def live_baseline_validation_errors(
    live: SlotSetupRecipe, goldclub: Path | str
) -> list[str]:
    """Validation errors the *running* cabinet raises against itself.

    ``validate(live, live)`` cannot describe a broken push -- nothing is
    proposed. Anything it returns is a scanner rule that disagrees with a
    cabinet whose game is up, so those messages are advisory, never red.
    """
    try:
        return list(validate_live_push_recipe(live, live, Path(goldclub)))
    except Exception as exc:  # noqa: BLE001
        _lp_log(f"live baseline validation failed: {exc}")
        return []


def split_live_proven_errors(
    errors: Sequence[str],
    *,
    baseline: Sequence[str],
    matches: dict[str, bool],
) -> tuple[list[str], list[str]]:
    """Split validation errors into ``(blocking, advisory)``.

    An error is advisory when the running cabinet already triggers the same
    message *and* every form field it maps to still equals the cabinet. The
    operator is not proposing anything the game has not already proven. A
    message the live cabinet does not raise, or one attached to a field the
    operator changed, stays blocking (red).
    """
    base = set(baseline)
    blocking: list[str] = []
    advisory: list[str] = []
    for err in errors:
        if err in base:
            labels = list(live_field_validation_errors([err]).keys())
            if not labels or all(matches.get(label, True) for label in labels):
                advisory.append(err)
                continue
        blocking.append(err)
    return blocking, advisory


def validate_live_push_blocking(
    live: SlotSetupRecipe,
    proposed: SlotSetupRecipe,
    goldclub: Path | str,
    *,
    baseline: Sequence[str] | None = None,
) -> tuple[list[str], list[str]]:
    """``(blocking, advisory)`` for a Live Push proposal.

    Blocking errors stop Apply and paint red. Advisory ones are rules the
    cabinet already lives with (see :func:`live_baseline_validation_errors`).
    Pass a cached *baseline* to skip re-validating the live recipe.
    """
    root = Path(goldclub)
    errors = list(validate_live_push_recipe(live, proposed, root))
    if not errors:
        return [], []
    base = (
        list(baseline)
        if baseline is not None
        else live_baseline_validation_errors(live, root)
    )
    if not base:
        return errors, []
    return split_live_proven_errors(
        errors, baseline=base, matches=live_field_matches(live, proposed)
    )


def split_display_corruption(
    live_scan: dict[str, str],
    form_scan: dict[str, str],
    *,
    matches: dict[str, bool],
) -> tuple[dict[str, str], dict[str, str]]:
    """``(red, advisory)`` for display-text findings.

    The live-file scan describes the cabinet as it runs today, so it is
    always advisory. A form value is red only when the operator changed that
    field; an unchanged form value merely restates the cabinet.
    """
    red: dict[str, str] = {}
    advisory: dict[str, str] = dict(live_scan)
    for label, reason in form_scan.items():
        if matches.get(label, False):
            advisory.setdefault(label, reason)
        else:
            red[label] = reason
    return red, advisory


def collect_live_invalid_field_labels(
    live: SlotSetupRecipe,
    form: SlotSetupRecipe,
    *,
    validation_errors: list[str],
    display_corruption: dict[str, str] | None = None,
    log_field_errors: dict[str, str] | None = None,
) -> frozenset[str]:
    """Snapshot labels painted red (validation, corrupt display, or SlotLog)."""
    from config_scanner.slotlog_review import field_highlight_error

    matches = live_field_matches(live, form)
    invalid = live_field_validation_errors(validation_errors)
    corrupt = display_corruption or {}
    log_errs = log_field_errors or {}
    blocked: set[str] = set()
    for label, _old in recipe_snapshot_rows(live):
        reason = field_highlight_error(
            matches_live=bool(matches.get(label)),
            validation_error=invalid.get(label, "") or corrupt.get(label, ""),
            log_error=log_errs.get(label, ""),
        )
        if reason:
            blocked.add(label)
    return frozenset(blocked)


def _revert_live_push_label(
    out: SlotSetupRecipe, live: SlotSetupRecipe, label: str
) -> None:
    """Copy one snapshot label from *live* onto *out* (orange-only apply skip)."""
    if label == "SAS enabled":
        out.sas.enabled = live.sas.enabled
    elif label == "SAS address":
        out.sas.address = live.sas.address
    elif label == "AFT":
        out.sas.aft_enabled = live.sas.aft_enabled
    elif label == "Funds transfer":
        out.sas.funds_transfer_type = live.sas.funds_transfer_type
    elif label == "Lock when no SAS":
        out.sas.lock_game_when_no_comms = live.sas.lock_game_when_no_comms
    elif label == "Enable switches":
        out.door_switches.enabled = live.door_switches.enabled
    elif label == "Stacker auto-unlock":
        out.door_switches.stacker_installed_auto_unlock = (
            live.door_switches.stacker_installed_auto_unlock
        )
    elif label == "Bill protocol":
        out.bill_protocol = live.bill_protocol
    elif label == "Bill notes":
        out.bill_tokens = list(live.bill_tokens or [])
    elif label == "Ticket printer":
        out.ticket_protocol = live.ticket_protocol
    elif label == "Currency":
        out.jurisdiction.currency_name = live.jurisdiction.currency_name
        out.hardware_currency_name = live.hardware_currency_name
    elif label == "Currency symbol":
        out.jurisdiction.currency_symbol = live.jurisdiction.currency_symbol
    elif label == "Culture":
        out.jurisdiction.culture_name = live.jurisdiction.culture_name
    elif label == "Language":
        out.mg_identity.language = live.mg_identity.language
    elif label == COUNTRY_FLAG_LABEL:
        out.jurisdiction.language_flags = list(live.jurisdiction.language_flags)
    elif label == "Market":
        out.jurisdiction.tag = live.jurisdiction.tag
    elif label == "Denoms (cents)":
        out.denomination_list = list(live.denomination_list or [])
        out.credit_rate_values = list(
            live.credit_rate_values or live.denomination_list or []
        )
    elif label == "Bet multipliers":
        live_mults = list(live.play_limits.bet_multipliers or [])
        if not live_mults and live.math:
            live_mults = list(live.math[0].bet_multipliers or [])
        out.play_limits.bet_multipliers = list(live_mults)
        if out.math and live.math:
            out.math[0].bet_multipliers = list(live.math[0].bet_multipliers or [])
    elif label == "Default bet":
        out.play_limits.default_bet = live.play_limits.default_bet
    elif label == "Show denom selector":
        out.play_limits.show_denom_selector = live.play_limits.show_denom_selector
    elif label == "Magic wheel limit":
        out.jurisdiction.magic_wheel_money_limit = (
            live.jurisdiction.magic_wheel_money_limit
        )
    elif label == "Magic wheel bet":
        out.play_limits.magic_wheel_bet = live.play_limits.magic_wheel_bet
    elif label == "Magic wheel enabled":
        out.play_limits.magic_wheel_enabled = live.play_limits.magic_wheel_enabled
    elif label == "Magic wheel max spins":
        out.play_limits.magic_wheel_max_spins = live.play_limits.magic_wheel_max_spins
    elif label == "Magic wheel average":
        out.play_limits.magic_wheel_average = live.play_limits.magic_wheel_average
    elif label == "Jackpot counters":
        out.play_limits.jackpot_counters = live.play_limits.jackpot_counters
    elif label == "Jackpot receipt":
        out.play_limits.jackpot_receipt_layout = live.play_limits.jackpot_receipt_layout
    elif label == "Jackpot celebration":
        out.play_limits.celebration_limit = live.play_limits.celebration_limit
    elif label == "Cashout button":
        out.play_limits.cashout_button_mode = live.play_limits.cashout_button_mode
    elif label == "Show all lines":
        out.play_limits.show_all_lines = live.play_limits.show_all_lines
    elif label == "Offline ticket":
        out.offline_enabled = live.offline_enabled
        out.include_oticket = live.include_oticket
    elif label == "Ticket redeem":
        out.play_limits.ticket_redeem_enabled = live.play_limits.ticket_redeem_enabled
    elif label == "Ticket currency ISO":
        out.play_limits.ticket_use_currency_iso = live.play_limits.ticket_use_currency_iso
    elif label == "Dallas key":
        out.dallas = live.dallas
    elif label == "Inactivity to selector":
        out.mg_identity.inactivity_seconds_to_game_selector = (
            live.mg_identity.inactivity_seconds_to_game_selector
        )
    elif label == "Display layout":
        out.display_mode = live.display_mode
    elif label == "Button deck":
        out.hw_driver_profile = live.hw_driver_profile
        out.keyboard = dict(live.keyboard or {})
    else:
        for field, channel_label, _cls in SAS_CHANNEL_FIELDS:
            if channel_label == label:
                setattr(out.sas, field, getattr(live.sas, field, True))
                return
        for name in STANDARD_DOOR_SWITCH_NAMES:
            if door_switch_auto_unlock_label(name) == label:
                out.door_switches.set_auto_unlock(name, live.door_switches.auto_unlock_for(name))
                return
        for spec in LIMIT_SETUP_FIELDS:
            if spec.label == label:
                out.limit_setup.set_value(
                    spec.key, live.limit_setup.value_for(spec.key)
                )
                return


def recipe_for_orange_only_apply(
    live: SlotSetupRecipe,
    form: SlotSetupRecipe,
    skip_labels: frozenset[str],
) -> SlotSetupRecipe:
    """Return *form* with red snapshot labels reverted to the live cabinet."""
    if not skip_labels:
        return SlotSetupRecipe.from_dict(form.to_dict())
    out = SlotSetupRecipe.from_dict(form.to_dict())
    matches = live_field_matches(live, form)
    for label in skip_labels:
        if matches.get(label, True):
            continue
        _revert_live_push_label(out, live, label)
    return out


def live_field_highlight_state(
    *,
    matches_live: bool,
    editable: bool,
    cabinet_loaded: bool,
    invalid_reason: str = "",
    advisory_reason: str = "",
) -> str:
    """Return ``match``, ``changed``, ``editable``, ``invalid``, ``advisory`` or ``none``."""
    if invalid_reason:
        return "invalid"
    if advisory_reason:
        return "advisory"
    if not editable:
        return "none"
    if matches_live:
        return "match"
    if cabinet_loaded:
        return "changed"
    return "editable"


def live_field_tooltip(
    state: str,
    *,
    detail: str = "",
    help_text: str = "",
    invalid_kind: str = "",
    file_note: str = "",
) -> str:
    """Hover text: option help, apply status, then blocking files."""
    parts: list[str] = []
    help_bits = (help_text or "").strip()
    if help_bits:
        parts.append(help_bits)
    if state == "invalid":
        if invalid_kind == "corrupt":
            base = (
                "Red: corrupt display text on the cabinet "
                "(weird '?' / non-ASCII that OneHand shows as garbage)."
            )
        elif invalid_kind == "live_math":
            base = (
                "Red: live Link2Win math on the cabinet does not include "
                "this denom."
            )
        else:
            base = "Red: invalid — this value cannot be applied."
        parts.append(f"{base} {detail}".strip())
    elif state == "advisory":
        parts.append(f"{LIVE_FIELD_TOOLTIP_ADVISORY} {detail}".strip())
    elif state == "match":
        parts.append(LIVE_FIELD_TOOLTIP_MATCH)
    elif state == "changed":
        parts.append(LIVE_FIELD_TOOLTIP_CHANGED)
    elif state == "editable":
        parts.append(LIVE_FIELD_TOOLTIP_EDITABLE)
    note = (file_note or "").strip()
    if note:
        parts.append(note)
    return "\n\n".join(parts)


_MATH_HOVER_LABELS = frozenset(
    {
        "Denoms (cents)",
        "Bet multipliers",
        "Magic wheel bet",
        "Magic wheel average",
    }
)


def live_field_file_hover(
    label: str,
    goldclub: Path | None,
    proposed_denoms: list[int] | None = None,
    *,
    validation_error: str = "",
) -> str:
    """Cabinet-relative files that constrain or block this Live Push field."""
    if goldclub is None:
        return ""
    try:
        root = goldclub_root_from_target(goldclub)
    except (OSError, ValueError):
        return ""
    lines: list[str] = []
    denoms = [int(x) for x in (proposed_denoms or []) if int(x) > 0]
    math_gap = ""
    if label in _MATH_HOVER_LABELS and denoms:
        math_gap = live_cabinet_math_gap(root, denoms, allow_decrypt=False)
        if math_gap:
            from config_scanner.denom_compat import DENOM_COMPANION_RELS

            for rel in DENOM_COMPANION_RELS:
                path = root / rel
                if not path.is_file():
                    continue
                extra = ""
                support = inspect_link2win_math(path, allow_decrypt=False)
                if support is not None and support.denoms:
                    have = ", ".join(f"{d}c" for d in sorted(support.denoms))
                    extra = f" (live math supports {have})"
                elif rel.casefold().endswith("math.json") or "link2win" in rel.casefold():
                    extra = " (live math, encrypted / unknown denom)"
                lines.append(f"{rel}{extra}")
    if validation_error:
        for path in resolve_live_field_config_files(root, label):
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = path.name
            if any(item.startswith(rel) for item in lines):
                continue
            lines.append(rel)
    if not lines and not math_gap and not validation_error:
        return ""
    if not lines and validation_error:
        return ""
    header = "Blocking files:" if validation_error else "Cabinet files:"
    body = "\n".join(f"• {item}" for item in lines)
    if math_gap and not validation_error:
        return (
            f"{header}\n{body}\n{math_gap} "
            "Apply is blocked until the live math includes that denom."
        )
    if math_gap:
        return f"{header}\n{body}\n{math_gap}"
    return f"{header}\n{body}"


def looks_like_goldclub_root(root: Path | str) -> bool:
    path = Path(root)
    try:
        return (path / "slot" / "themes").is_dir() or (
            path / "slot" / "OneHand.exe"
        ).is_file()
    except (OSError, TimeoutError, ValueError):
        return False


def goldclub_stack_kind(root: Path | str) -> str:
    """``slot``, ``roulette``, or ``unknown`` from files on the Goldclub root."""
    path = Path(root)
    try:
        has_onehand = (path / "slot" / "OneHand.exe").is_file() or (
            path / "OneHand.exe"
        ).is_file()
        has_ruleta = (path / "ruleta" / "ruleta.exe").is_file() or (
            path / "ruleta" / "Ruleta.exe"
        ).is_file()
        has_bootstrap = (path / "Bootstrap.exe").is_file()
    except (OSError, TimeoutError, ValueError):
        return "unknown"
    # OneHand wins over leftover Ruleta.exe on converted Slot cabinets.
    if has_onehand:
        return "slot"
    if has_ruleta:
        return "roulette"
    if has_bootstrap:
        return "slot"
    return "unknown"


_SMB_READY_LOCK = threading.Lock()
_SMB_READY_HOSTS: set[str] = set()


def forget_lab_smb_session(host: str) -> None:
    """Drop the 'session already open' memo so the next probe reconnects."""
    with _SMB_READY_LOCK:
        _SMB_READY_HOSTS.discard((host or "").strip().casefold())


def _ensure_lab_smb(host: str) -> None:
    """Silent SMB test/test for any lab-LAN cabinet. Does not use WinRM.

    A successful session is remembered per host for this process so the
    ``cmdkey`` spawn + ``WNetAddConnection2`` handshake runs once, not once
    per probe candidate on every Load. A logon failure clears the memo.
    """
    host = (host or "").strip()
    if not host:
        return
    key = host.casefold()
    with _SMB_READY_LOCK:
        if key in _SMB_READY_HOSTS:
            return
    try:
        from network.lab_access import ensure_lab_smb_credential, is_lab_lan_ip

        if is_lab_lan_ip(host) and ensure_lab_smb_credential(host):
            with _SMB_READY_LOCK:
                _SMB_READY_HOSTS.add(key)
    except Exception:  # noqa: BLE001
        return


def prepare_live_goldclub(target: str) -> tuple[Path | None, str]:
    """Resolve a Goldclub root, mapping lab SMB credentials for UNC cabinets.

    Never probes the Windows redirector until the host answers on SMB, so a
    down cabinet (e.g. 10.0.0.90) cannot hang or crash the GUI.
    """
    raw = (target or "").strip()
    if not raw:
        return None, "Enter a cabinet Goldclub path."
    ok, why = cabinet_host_reachable(raw)
    if not ok:
        _lp_log(f"host unreachable {raw}: {why}")
        return None, why
    host = unc_host_from_target(raw)
    return _probe_live_goldclub(raw, host, retry_auth=True)


def _probe_live_goldclub(
    raw: str, host: str | None, *, retry_auth: bool
) -> tuple[Path | None, str]:
    if host:
        _ensure_lab_smb(host)
    try:
        root = goldclub_root_from_target(raw)
        if looks_like_goldclub_root(root):
            return root, ""
        if host:
            for cand in (
                rf"\\{host}\slot",
                rf"\\{host}\c$\Goldclub",
                rf"\\{host}\c$\goldclub",
            ):
                _ensure_lab_smb(host)
                probed = goldclub_root_from_target(cand)
                if looks_like_goldclub_root(probed):
                    return probed, ""
        exists = root.is_dir()
        if exists:
            return None, (
                f"Folder exists but is not a Goldclub root (need slot\\themes):\n{root}"
            )
        if not host:
            return None, (
                f"No Goldclub tree at {raw} on this PC "
                "(need slot\\themes or slot\\OneHand.exe).\n"
                "Use Browse… to pick the Goldclub folder, or a cabinet button for a lab EGM."
            )
        return None, (
            f"Cannot reach {raw}. Store the lab login (cmdkey) and check the cabinet is on."
        )
    except (OSError, TimeoutError, ValueError) as exc:
        from network.lab_access import (
            drop_lab_smb_sessions,
            format_lab_smb_logon_failure,
            is_smb_logon_failure,
        )

        if host and is_smb_logon_failure(exc) and retry_auth:
            forget_lab_smb_session(host)
            drop_lab_smb_sessions(host)
            return _probe_live_goldclub(raw, host, retry_auth=False)
        if host and is_smb_logon_failure(exc):
            return None, format_lab_smb_logon_failure(host, exc)
        return None, f"Cannot reach {raw} ({exc})."


@dataclass
class LiveLoadOutcome:
    root: Path | None
    recipe: SlotSetupRecipe | None
    error: str
    status: str
    licence: LiveLicenceStatus | None = None
    display_corruption: dict[str, str] = field(default_factory=dict)
    onehand_build: OneHandBuildInfo | None = None
    # TargetMarket tokens compiled into this OneHand.exe (None = unknown /
    # not a slot). Read on the worker so the GUI thread never touches SMB.
    onehand_markets: frozenset[str] | None = None
    ticket_printer_active: bool = False
    # slot\languages catalog + jurisdiction_config <Languages> of this root.
    languages: CabinetLanguages | None = None
    # Dedicated wheel XML / theme folder — not jurisdiction MagicWheelPackSettings.
    has_magic_wheel_gamepack: bool = False
    # True for the early callback (root + recipe + wheel flag) before licences.
    partial: bool = False


# Worker threads for one Load. SMB is latency-bound, so independent reads
# overlap well; more than this just queues on the single SMB session.
LIVE_LOAD_WORKERS = 6


def _load_status_text(root: Path, kind: str, recipe: SlotSetupRecipe) -> str:
    if kind == "slot":
        disp = recipe.display_mode or read_display_mode(root)
        disp_s = f"{disp}-screen" if disp else "unknown"
        return (
            f"Loaded {root} ({disp_s} layout). "
            "Apply will stop OneHand, write, then start Bootstrap."
        )
    if kind == "roulette":
        return f"Loaded {root}. Apply will Kill-All, write, then Run-FullStack."
    return f"Loaded {root}. No game restart plan — Apply will write files only."


def _timed(label: str, timings: dict[str, float], fn: Callable[..., object]):
    """Wrap *fn* so its wall time lands in *timings* under *label*."""

    def _run(*args, **kwargs):
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            timings[label] = time.perf_counter() - started

    return _run


def _format_timings(timings: dict[str, float]) -> str:
    return " ".join(
        f"{name}={secs * 1000:.0f}ms"
        for name, secs in sorted(timings.items(), key=lambda kv: -kv[1])
    )


def load_live_cabinet(
    target: str,
    *,
    prefer_local: bool = False,
    on_partial: Callable[[LiveLoadOutcome], None] | None = None,
) -> LiveLoadOutcome:
    """Load a cabinet recipe. Never raises — dead shares return an error string.

    With *prefer_local*, the shipped ``\\\\10.0.0.111\\slot`` default and the
    ``This PC`` path are first resolved against local Goldclub roots.

    Once the Goldclub root is known, the independent reads (recipe, licences,
    OneHand build, market tokens, printer flag, math prefetch, display-text
    scan) run concurrently on a small pool and share one read cache, so a
    file or the 9.5 MB ``OneHand.exe`` crosses the SMB link once. *on_partial*
    (if given) fires as soon as the recipe alone is ready with a
    ``partial=True`` outcome so the form can paint while the rest finishes.
    """
    timings: dict[str, float] = {}
    total_started = time.perf_counter()
    try:
        target, swapped = resolve_live_load_target(target, prefer_local=prefer_local)
        if swapped:
            _lp_log(swapped)
        root, err = _timed("connect", timings, prepare_live_goldclub)(target)
        if root is None:
            return LiveLoadOutcome(None, None, err, "")
        kind = _timed("kind", timings, goldclub_stack_kind)(root)

        def _quiet(label: str, fn: Callable[..., object], default: object):
            def _run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    _lp_log(f"{label} failed: {exc}")
                    return default

            return _timed(label, timings, _run)

        with scoped_read_cache() as scope, ThreadPoolExecutor(
            max_workers=LIVE_LOAD_WORKERS, thread_name_prefix="live-load"
        ) as pool:

            def submit(fn: Callable[..., object], *args: object, **kwargs: object):
                return pool.submit(run_in_scope(fn, *args, **kwargs))

            f_recipe = submit(
                _timed("recipe", timings, load_recipe_from_goldclub),
                root,
                label="live",
            )
            f_licence = submit(_timed("licence", timings, inspect_live_licences), root)
            f_onehand = submit(
                _quiet("OneHand build detect", detect_onehand_build, None), root
            )
            f_markets = submit(
                _quiet("OneHand market scan", markets_accepted_by_onehand, None), root
            )
            f_printer = submit(
                _quiet("ticket printer flag", read_ticket_printer_active, False), root
            )
            f_langs = submit(
                _quiet("cabinet languages", read_cabinet_languages, None), root
            )
            f_mw = submit(
                _quiet(
                    "magic wheel pack", cabinet_has_magic_wheel_gamepack, False
                ),
                root,
            )
            f_corrupt = submit(
                _quiet("display corruption scan", live_display_corruption_errors, {}),
                root,
            )
            f_math = None
            if kind == "slot":
                f_math = submit(_quiet("math prefetch", prefetch_link2win_math, None), root)

            recipe = f_recipe.result()
            has_mw = bool(f_mw.result())
            status = _load_status_text(root, kind, recipe)
            if on_partial is not None:
                try:
                    on_partial(
                        LiveLoadOutcome(
                            root,
                            recipe,
                            "",
                            status,
                            has_magic_wheel_gamepack=has_mw,
                            partial=True,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    _lp_log(f"partial-load callback failed: {exc}")

            licence = f_licence.result()
            onehand = f_onehand.result()
            markets = f_markets.result()
            printer_on = bool(f_printer.result())
            languages = f_langs.result()
            corrupt = f_corrupt.result() or {}
            if f_math is not None:
                f_math.result()

        timings["total"] = time.perf_counter() - total_started
        _lp_log(
            f"load {root}: {_format_timings(timings)} "
            f"(cache hits={scope.hits} misses={scope.misses})"
        )
        return LiveLoadOutcome(
            root,
            recipe,
            "",
            status,
            licence,
            display_corruption=dict(corrupt),
            onehand_build=onehand,
            onehand_markets=markets,
            ticket_printer_active=printer_on,
            languages=languages,
            has_magic_wheel_gamepack=has_mw,
        )
    except Exception as exc:  # noqa: BLE001
        return LiveLoadOutcome(
            None,
            None,
            f"Cannot load cabinet: {exc}",
            "",
        )


def _run_local_powershell(script: str, *, timeout: int) -> tuple[bool, str]:
    """Run a script via -EncodedCommand so $vars are not eaten by -Command."""
    wrapped = "$ProgressPreference = 'SilentlyContinue'\n" + script
    encoded = base64.b64encode(wrapped.encode("utf-16-le")).decode("ascii")
    run_kw: dict = {
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": timeout,
    }
    if os.name == "nt":
        run_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            **run_kw,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, str(exc)
    blob = _strip_powershell_noise(
        ((result.stdout or "") + (result.stderr or "")).strip()
    )
    if result.returncode == 0:
        return True, blob or "OK"
    detail = f"exit {result.returncode}"
    if blob:
        detail = f"{detail} {blob[:800]}"
    return False, detail


def resolve_cabinet_windows_hostname(scan_target: str) -> str | None:
    """Windows hostname Aurum LoadSetup matches ([Environment]::MachineName).

    Overlay cabinets (e.g. GST22377 with mgconfig MachineID GST20664) must use
    this name in AurumSetup host tokens, not the overlay identity.
    """
    target = (scan_target or "").strip()
    if not target:
        return (os.environ.get("COMPUTERNAME") or "").strip() or None
    try:
        from config_scanner.cabinet_repairs import (
            RepairError,
            _MACHINE_NAME_PROBE,
            build_context,
            run_probe,
        )

        ctx = build_context(target, "slot")
        values = run_probe(ctx, _MACHINE_NAME_PROBE, timeout=30)
        name = (values.get("MACHINE") or "").strip()
        if name:
            return name
    except Exception as exc:  # noqa: BLE001
        _lp_log(f"resolve hostname probe failed for {target!r}: {exc}")
    if _slot_target_is_local(target):
        return (os.environ.get("COMPUTERNAME") or "").strip() or None
    return None


def apply_aurum_hostname_for_live_push(
    recipe: SlotSetupRecipe,
    scan_target: str,
) -> SlotSetupRecipe:
    """Ensure AurumSetup host tokens target the cabinet Windows hostname."""
    machine = resolve_cabinet_windows_hostname(scan_target)
    if not machine:
        return recipe
    template = (recipe.aurum_identity.network_hostname_template or "").strip()
    if template.casefold() == machine.casefold():
        return recipe
    _lp_log(
        f"aurum host: recipe template {template!r} -> Windows hostname {machine!r}"
    )
    updated = SlotSetupRecipe.from_dict(recipe.to_dict())
    updated.aurum_identity = AurumIdentitySettings(
        network_hostname_template=machine,
    )
    return updated


def live_push_will_write_aurum_setup(
    dest: Path,
    recipe: SlotSetupRecipe,
    sections: frozenset[str] | None,
) -> bool:
    """True when this commit will stage AurumSetup.xml (hostname / currency / channels)."""
    if sections is None or "aurum" in sections:
        return True
    return "sas" in sections and sas_channel_flags_differ(dest, recipe.sas)


def ensure_aurum_setup_windows_hostname(dest: Path, scan_target: str) -> None:
    """Patch live AurumSetup host tokens in place before Aurum reloads the file."""
    machine = resolve_cabinet_windows_hostname(scan_target)
    if not machine:
        _lp_log("aurum host ensure skipped: no Windows hostname")
        return
    from config_scanner.cabinet_repairs import (
        find_aurum_setup_xml,
        rewrite_aurum_host_tokens,
    )

    setup = find_aurum_setup_xml(dest)
    if setup is None:
        return
    changed, detail = rewrite_aurum_host_tokens(setup, machine, backup=True)
    _lp_log(f"aurum host ensure changed={changed} {detail}")


_CLIXML_MARK = "#< CLIXML"


def _strip_powershell_noise(blob: str) -> str:
    """Drop CLIXML progress records PowerShell writes to stderr."""
    text = blob or ""
    if _CLIXML_MARK in text:
        text = text.split(_CLIXML_MARK, 1)[0]
    return text.strip()


def _slot_target_is_local(scan_target: str) -> bool:
    """True when the scan target is this PC (local stop/start, not WinRM)."""
    from config_scanner.stack_restart import scan_target_is_local_machine

    return scan_target_is_local_machine(scan_target)


_WINRM_UNREACHABLE_MARKERS = (
    "servernottrusted",
    "trustedhosts",
    "psremotingtransportexception",
    "winrm client cannot process the request",
    "cannot connect to the destination",
    "winrm inline timed out",
    "winrm script timed out",
    "access is denied",
    "logon failure",
    "the user name or password is incorrect",
)


def slot_stop_unreachable(detail: str) -> bool:
    """True when the stop never reached the cabinet (WinRM trust / transport / logon).

    Retrying, or trying to *start* the game over the same channel, cannot
    work — but the SMB write path is independent, so settings can still go.
    Covers both Live Push transport markers and the restore-side
    ``stack_stop_unreachable`` set (5985 closed / OperationTimeout).
    """
    low = (detail or "").casefold()
    if any(marker in low for marker in _WINRM_UNREACHABLE_MARKERS):
        return True
    return stack_stop_unreachable(detail)


def _states_winrm_is_down(text: str) -> bool:
    low = " ".join(str(text or "").split()).casefold()
    if "winrm" not in low:
        return False
    return any(
        marker in low
        for marker in (
            "not reachable",
            "not listening",
            "not answering",
            "did not answer",
        )
    )


def stack_detail_worth_showing(detail_line: str, errors: Sequence[str]) -> bool:
    """False when the error text already tells the operator the same thing.

    The summary line and the error paragraph are built separately, so a dead
    WinRM channel used to be spelled out in both.
    """
    line = " ".join(str(detail_line or "").split())
    if not line:
        return False
    joined = " ".join(" ".join(str(e or "").split()) for e in errors or ())
    if not joined:
        return True
    if line.casefold() in joined.casefold():
        return False
    return not (_states_winrm_is_down(line) and _states_winrm_is_down(joined))


def winrm_listener_dead(detail: str) -> bool:
    """True only for 'nothing is listening on 5985' — not trust or logon.

    Those two have their own fix, so their wording must survive; this one is
    the case where the stop error, the aside and the hint all said 'no WinRM'.
    """
    low = (detail or "").casefold()
    if "servernottrusted" in low or "trustedhosts" in low:
        return False
    if (
        "access is denied" in low
        or "logon failure" in low
        or "user name or password is incorrect" in low
    ):
        return False
    return (
        "cannot connect to the destination" in low
        or "timed out" in low
        or "winrmoperationtimeout" in low
        or "winrm cannot complete the operation" in low
        or "winrm is not reachable" in low
        or "no listener" in low
    )


def winrm_failure_hint(detail: str, host: str) -> str:
    """One-line operator fix for the common WinRM-from-this-PC failures."""
    low = (detail or "").casefold()
    who = host or "the cabinet"
    if "servernottrusted" in low or "trustedhosts" in low:
        return (
            f"This PC's WinRM client does not trust {who}. Run once as "
            "Administrator: .\\Initialize-LabAccess.ps1 (or: Start-Service WinRM; "
            f"Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value '{who}' "
            "-Concatenate -Force)."
        )
    if (
        "access is denied" in low
        or "logon failure" in low
        or "user name or password is incorrect" in low
    ):
        return (
            f"WinRM logon to {who} was refused. Check the lab credential for "
            f"that cabinet (cmdkey /add:{who})."
        )
    if (
        "cannot connect to the destination" in low
        or "timed out" in low
        or "winrmoperationtimeout" in low
        or "winrm cannot complete the operation" in low
        or "winrm is not reachable" in low
        or "no listener" in low
    ):
        return (
            f"WinRM (TCP 5985) on {who} did not answer. Enable-PSRemoting on the "
            "cabinet, or restart the game there by hand."
        )
    return ""


def run_slot_stack_kill(
    scan_target: str, *, stop_aurum: bool = True
) -> tuple[bool, str]:
    """Stop OneHand / Bootstrap so slot XML can be written.

    ``stop_aurum`` is True for the pre-write kill so Aurum cannot rewrite
    SASsetupData. False for the pre-start kill: Aurum already reloaded the
    file, and game-start does not bring the service back.
    """
    import time

    script = _slot_kill_script(stop_aurum=stop_aurum)
    local = _slot_target_is_local(scan_target)
    _lp_log(
        f"slot kill local={local} stop_aurum={stop_aurum} target={scan_target!r}"
    )
    if local:
        _arm_slot_bootstrap_watchdog(scan_target)
    host = "" if local else (unc_host_from_target(scan_target) or "")
    if host and not remote_winrm_ready(host):
        detail = f"Slot stop failed: {winrm_skip_detail(host)}"
        _lp_log(detail)
        return False, detail
    last_detail = ""
    for attempt in range(1, 4):
        if local:
            ok, detail = _run_local_powershell(script, timeout=90)
        else:
            try:
                from automation.remote_exec import winrm_run_inline
                from network.lab_access import require_lab_fleet_ip

                ip = require_lab_fleet_ip(host)
                _ensure_lab_smb(ip)
                result = winrm_run_inline(
                    ip=ip, script=script, timeout=120
                )
            except Exception as exc:  # noqa: BLE001
                _lp_log(f"slot kill remote exception {exc}")
                return False, f"Slot stop failed: {exc}"
            blob = ((result.stdout or "") + (result.stderr or "")).strip()
            ok = result.returncode == 0 and "STILL:" not in blob.upper()
            detail = blob or f"exit {result.returncode}"
        last_detail = detail
        _lp_log(f"slot kill attempt={attempt} ok={ok} {detail[:400]}")
        if ok:
            return True, detail if detail else "OK"
        if not local and slot_stop_unreachable(detail):
            _lp_log("slot kill: WinRM never reached the cabinet, not retrying")
            break
        if attempt < 3:
            time.sleep(2)
    return False, f"Slot stop failed: {last_detail}"


def run_slot_stack_start(
    scan_target: str, dest: Path | str | None = None
) -> tuple[bool, str]:
    """Start the slot game in the console session on the target cabinet.

    Release OneHand: ``slot\\game-start.exe`` (never OneHand.exe directly).
    Debug OneHand: ``Bootstrap.exe`` (unchanged).
    """
    launcher = slot_start_launcher(scan_target, dest)
    candidates = slot_start_candidates(scan_target, dest, launcher=launcher)
    script = _slot_start_script(candidates, launcher=launcher)
    local = _slot_target_is_local(scan_target)
    _lp_log(
        f"slot start local={local} launcher={launcher} target={scan_target!r} "
        f"dest={dest!r} candidates={candidates}"
    )
    noun = "game-start" if launcher == "game-start" else "Bootstrap"
    if local:
        ok, detail = _run_local_powershell(script, timeout=150)
        _lp_log(f"slot start local result ok={ok} {detail}")
        return ok, detail if ok else f"Slot start failed: {detail}"
    host = unc_host_from_target(scan_target) or ""
    if not remote_winrm_ready(host):
        detail = winrm_skip_detail(host)
        _lp_log(f"slot start skipped: {detail}")
        return False, f"Slot start failed: {detail}"
    try:
        from automation.remote_exec import winrm_run_inline
        from network.lab_access import require_lab_fleet_ip

        ip = require_lab_fleet_ip(host)
        _ensure_lab_smb(ip)
        result = winrm_run_inline(ip=ip, script=script, timeout=180)
    except Exception as exc:  # noqa: BLE001
        _lp_log(f"slot start remote exception {exc}")
        return False, f"Slot start failed: {exc}"
    blob = ((result.stdout or "") + (result.stderr or "")).strip()
    _lp_log(f"slot start remote host={host} exit={result.returncode} {blob[:800]}")
    if result.returncode == 0:
        return True, blob or f"{noun} started on {host}"
    return False, blob or f"Slot start failed on {host} (exit {result.returncode})"


def _fmt_list(values: list[int] | None) -> str:
    if not values:
        return "—"
    return ", ".join(str(v) for v in values)


def _offline_label(value: bool | None) -> str:
    if value is None:
        return "—"
    return "on" if value else "off"


def _fmt_opt(value: object) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def recipe_snapshot_rows(recipe: SlotSetupRecipe) -> tuple[tuple[str, str], ...]:
    """Operator-facing (label, value) pairs for the live-push form."""
    pl = recipe.play_limits
    return (
        ("SAS enabled", "on" if recipe.sas.enabled else "off"),
        ("SAS address", str(recipe.sas.address)),
        ("AFT", "on" if recipe.sas.aft_enabled else "off"),
        ("Funds transfer", recipe.sas.funds_transfer_type or "—"),
        ("Lock when no SAS", "on" if recipe.sas.lock_game_when_no_comms else "off"),
        *(
            (
                label,
                "on" if bool(getattr(recipe.sas, field, True)) else "off",
            )
            for field, label, _cls in SAS_CHANNEL_FIELDS
        ),
        ("Enable switches", "on" if recipe.door_switches.enabled else "off"),
        (
            "Stacker auto-unlock",
            "on" if recipe.door_switches.stacker_installed_auto_unlock else "off",
        ),
        *(
            (
                door_switch_auto_unlock_label(name),
                "on" if recipe.door_switches.auto_unlock_for(name) else "off",
            )
            for name in STANDARD_DOOR_SWITCH_NAMES
        ),
        ("Bill protocol", recipe.bill_protocol or "—"),
        ("Bill notes", format_bill_notes_snapshot(recipe.bill_tokens)),
        ("Ticket printer", recipe.ticket_protocol or "—"),
        ("Currency", recipe.jurisdiction.currency_name or recipe.hardware_currency_name or "—"),
        ("Currency symbol", recipe.jurisdiction.currency_symbol or "—"),
        ("Culture", recipe.jurisdiction.culture_name or "—"),
        ("Language", recipe.mg_identity.language or "—"),
        (COUNTRY_FLAG_LABEL, flags_snapshot(recipe.jurisdiction.language_flags)),
        ("Market", recipe.jurisdiction.tag or "—"),
        ("Denoms (cents)", _fmt_list(recipe.denomination_list)),
        ("Bet multipliers", _fmt_list(pl.bet_multipliers or (
            recipe.math[0].bet_multipliers if recipe.math else []
        ))),
        ("Default bet", _fmt_opt(pl.default_bet)),
        ("Show denom selector", _fmt_opt(pl.show_denom_selector)),
        ("Magic wheel limit", _fmt_opt(recipe.jurisdiction.magic_wheel_money_limit)),
        ("Magic wheel bet", _fmt_opt(pl.magic_wheel_bet)),
        ("Magic wheel enabled", _fmt_opt(pl.magic_wheel_enabled)),
        ("Magic wheel max spins", _fmt_opt(pl.magic_wheel_max_spins)),
        ("Magic wheel average", _fmt_opt(pl.magic_wheel_average)),
        ("Jackpot counters", _fmt_opt(pl.jackpot_counters)),
        ("Jackpot receipt", _fmt_opt(pl.jackpot_receipt_layout)),
        ("Jackpot celebration", _fmt_opt(pl.celebration_limit)),
        ("Cashout button", _fmt_opt(pl.cashout_button_mode)),
        ("Show all lines", _fmt_opt(pl.show_all_lines)),
        ("Offline ticket", _offline_label(recipe.offline_enabled)),
        ("Ticket redeem", _fmt_opt(pl.ticket_redeem_enabled)),
        ("Ticket currency ISO", _fmt_opt(pl.ticket_use_currency_iso)),
        ("Dallas key", recipe.dallas.code or "—"),
        (
            "Inactivity to selector",
            (
                "—"
                if recipe.mg_identity.inactivity_seconds_to_game_selector is None
                else str(recipe.mg_identity.inactivity_seconds_to_game_selector)
            ),
        ),
        (
            "Display layout",
            f"{recipe.display_mode} screens" if recipe.display_mode else "—",
        ),
        ("Button deck", recipe.hw_driver_profile or "—"),
        *(
            (spec.label, str(recipe.limit_setup.value_for(spec.key) or 0))
            for spec in LIMIT_SETUP_FIELDS
        ),
    )


def recipe_change_lines(before: SlotSetupRecipe, after: SlotSetupRecipe) -> list[str]:
    """Human lines for values that will change on commit."""
    old = dict(recipe_snapshot_rows(before))
    new = dict(recipe_snapshot_rows(after))
    lines: list[str] = []
    for label, old_val in old.items():
        new_val = new.get(label, "—")
        if old_val != new_val:
            lines.append(f"{label}: {old_val} → {new_val}")
    return lines


def overlay_jurisdiction_recipe(
    live: SlotSetupRecipe, preset: SlotSetupRecipe
) -> SlotSetupRecipe:
    """Apply market preset fields onto a live machine recipe (keep Dallas / SAS address)."""
    out = SlotSetupRecipe.from_dict(live.to_dict())
    preset_copy = SlotSetupRecipe.from_dict(preset.to_dict())
    out.label = preset_copy.label or live.label
    live_addr = live.sas.address
    out.sas = preset_copy.sas
    out.sas.address = live_addr
    for field, _label, _cls in SAS_CHANNEL_FIELDS:
        setattr(out.sas, field, getattr(live.sas, field, True))
    out.door_switches = live.door_switches
    live_mw = live.jurisdiction.magic_wheel_money_limit
    live_flags = list(live.jurisdiction.language_flags)
    out.jurisdiction = preset_copy.jurisdiction
    if out.jurisdiction.magic_wheel_money_limit is None:
        out.jurisdiction.magic_wheel_money_limit = live_mw
    if not out.jurisdiction.language_flags:
        out.jurisdiction.language_flags = live_flags
    if not out.jurisdiction.currency_symbol:
        out.jurisdiction.currency_symbol = currency_symbol_for(
            out.jurisdiction.currency_name
        )
    live_template = live.mg_identity.machine_id_template
    live_inact = live.mg_identity.inactivity_seconds_to_game_selector
    out.mg_identity = preset_copy.mg_identity
    out.mg_identity.machine_id_template = live_template
    if out.mg_identity.inactivity_seconds_to_game_selector is None:
        out.mg_identity.inactivity_seconds_to_game_selector = live_inact
    if preset_copy.hardware_currency_name:
        out.hardware_currency_name = preset_copy.hardware_currency_name
    if preset_copy.offline_enabled is not None:
        out.offline_enabled = preset_copy.offline_enabled
        out.include_oticket = bool(preset_copy.offline_enabled)
    if preset_copy.bill_tokens and not live.bill_tokens:
        out.bill_tokens = list(preset_copy.bill_tokens)
    if preset_copy.bill_protocol:
        out.bill_protocol = preset_copy.bill_protocol
    if preset_copy.ticket_protocol:
        out.ticket_protocol = preset_copy.ticket_protocol
    # Keep the cabinet's active denomination list — presets carry allowed_denoms
    # for validation/choices, not a wholesale mgconfig replacement.
    out.play_limits = merge_play_limits(live.play_limits, preset_copy.play_limits)
    out.dallas = live.dallas
    out.keyboard = dict(live.keyboard)
    out.aurum_identity = live.aurum_identity
    return out


def recipe_from_market_id(jurisdiction_id: str) -> SlotSetupRecipe | None:
    profiles = {p.id: p for p in load_jurisdictions()}
    prof = profiles.get(str(jurisdiction_id or "").strip())
    if prof is None:
        return None
    return recipe_from_jurisdiction_profile(prof)


def _emit(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)


def commit_live_push(
    recipe: SlotSetupRecipe,
    dest_goldclub: Path | str,
    *,
    restart_stack: bool = True,
    scan_target: str | None = None,
    work_parent: Path | None = None,
    progress: ProgressFn | None = None,
    backup: bool = False,
    full_pack: bool = False,
    push_licences: bool = False,
    licence_source: str | Path | None = None,
) -> LivePushResult:
    """Stop the game (if planned), write recipe files, start the game again.

    By default only sections that differ from the live cabinet are written
    (delta apply). Pass ``full_pack=True`` for the legacy full rewrite.
    When ``backup`` is true, overwritten live files are copied under
    ``live_push_backups/<timestamp>/`` beside the tool. Backup is off by
    default (opt-in from the Live Push checkbox).
    """
    from config_scanner.slot_setup import load_recipe as load_pack_recipe

    currency = (recipe.jurisdiction.currency_name or recipe.hardware_currency_name or "").strip()
    if recipe.bill_protocol.upper() == "MEI" and recipe.bill_tokens:
        fixed = normalize_mei_bill_tokens_for_currency(recipe.bill_tokens, currency)
        if fixed != recipe.bill_tokens:
            _lp_log(
                "commit: normalized MEI bill tokens for "
                f"{currency or 'unknown currency'} (97-102 TTD layout)"
            )
            recipe = SlotSetupRecipe.from_dict(recipe.to_dict())
            recipe.bill_tokens = fixed
    log_path = live_push_log_path()
    plan_src = scan_target or str(dest_goldclub)
    _lp_log(
        f"commit begin dest={dest_goldclub!s} target={plan_src!r} "
        f"bill={recipe.bill_protocol} ticket={recipe.ticket_protocol} "
        f"currency={recipe.jurisdiction.currency_name} "
        f"aft={recipe.sas.aft_enabled} restart={restart_stack} "
        f"backup={backup} full_pack={full_pack} push_licences={push_licences}"
    )
    prepared, prepare_err = prepare_live_goldclub(str(dest_goldclub))
    dest = prepared if prepared is not None else goldclub_root_from_target(dest_goldclub)
    if not looks_like_goldclub_root(dest):
        msg = prepare_err or f"Goldclub root not found: {dest}"
        _lp_log(f"commit abort: {msg}")
        return LivePushResult(
            (),
            (),
            (msg,),
            False,
            False,
            "",
        )

    live_recipe = load_recipe_from_goldclub(dest, label="live")
    config_errors = validate_live_push_recipe(live_recipe, recipe, dest)
    if config_errors:
        msg = config_errors[0]
        _lp_log(f"commit abort: {msg}")
        return LivePushResult((), (), (msg,), False, False, msg)

    form_currency = (
        recipe.jurisdiction.currency_name or recipe.hardware_currency_name or ""
    ).strip().upper()
    try:
        from config_scanner.slot_setup import read_aurum_currency_code

        aurum_currency = read_aurum_currency_code(dest)
    except (OSError, ValueError):
        aurum_currency = ""
    # Empty / missing Aurum CurrencyCode counts as a mismatch — OneHand NRE if
    # jurisdiction has a code and Aurum does not (or they differ).
    aurum_currency_mismatch = bool(
        form_currency and form_currency != (aurum_currency or "").strip().upper()
    )
    ramclear_reasons = live_push_ramclear_reasons(
        live_recipe, recipe, aurum_currency=aurum_currency
    )
    if ramclear_reasons:
        _lp_log(f"commit will ramclear: {', '.join(ramclear_reasons)}")

    sections: frozenset[str] | None = None
    want_licences = False
    if push_licences:
        dest_lic = inspect_live_licences(dest)
        want_licences = bool(dest_lic.needs_push)
        if not want_licences:
            _lp_log("commit: licence push skipped — files already next to OneHand")
    if not full_pack:
        sections = live_push_changed_sections(live_recipe, recipe)
        if want_licences:
            sections = frozenset(set(sections) | {"licence"})
        if aurum_currency_mismatch:
            sections = frozenset(
                set(sections) | {"aurum", "mgconfig", "jurisdiction", "hardware"}
            )
        leftover_single = leftover_jurisdiction_single_denomination(
            dest, list(recipe.denomination_list or live_recipe.denomination_list)
        )
        if leftover_single is not None:
            _lp_log(
                "commit leftover SingleDenomination="
                f"{leftover_single} (mgconfig "
                f"{(recipe.denomination_list or live_recipe.denomination_list)[:1]})"
            )
            sections = frozenset(set(sections) | {"jurisdiction", "mgconfig"})
        from config_scanner.denom_compat import link2win_restage_change_line

        if link2win_restage_change_line(live_recipe, recipe, dest):
            sections = frozenset(
                set(sections) | {"link2win", "magicwheel", "mgconfig"}
            )
        if not sections:
            msg = "Nothing changed on the live cabinet."
            _lp_log(f"commit abort: {msg}")
            return LivePushResult((), (), (msg,), False, False, msg)
        _lp_log(f"commit delta sections={sorted(sections)}")

    kind = goldclub_stack_kind(dest)
    local_slot = _slot_target_is_local(plan_src) if kind == "slot" else False
    _lp_log(f"commit kind={kind} local_slot={local_slot} resolved={dest}")
    if recipe.display_mode in ("2", "3"):
        missing = missing_display_mode_assets(dest, recipe.display_mode)
        if missing:
            msg = (
                f"Cannot switch to {recipe.display_mode}-screen layout: "
                f"missing theme files on cabinet: {', '.join(missing)}"
            )
            _lp_log(f"commit abort: {msg}")
            return LivePushResult((), (), (msg,), False, False, msg)
    # Currency / denom / bet-step deltas need ramclear + Bootstrap even if the
    # operator left "restart game" unchecked. Cashout-only reloads OneHand
    # (LoadMgConfiguration) and leaves Aurum / SAS / HWSubsys running.
    need_slot_ramclear = bool(ramclear_reasons) and kind == "slot"
    restart_reasons = live_push_restart_required_reasons(
        live_recipe,
        recipe,
        full_pack=full_pack,
        push_licences=want_licences,
        goldclub=dest,
    )
    onehand_reload_reasons = live_push_onehand_reload_reasons(live_recipe, recipe)
    apply_mode = live_push_apply_mode(
        kind=kind,
        restart_stack=restart_stack,
        restart_reasons=restart_reasons,
        ramclear_reasons=ramclear_reasons if kind == "slot" else (),
        onehand_reload_reasons=onehand_reload_reasons,
    )
    effective_restart = apply_mode == "fullstack"
    use_slot = bool(effective_restart and kind == "slot")
    use_onehand_reload = apply_mode == "onehand"
    plan = (
        None
        if use_slot or use_onehand_reload
        else (plan_stack_restart(plan_src) if effective_restart else None)
    )
    stack_killed = False
    stack_detail = ""
    if need_slot_ramclear and not restart_stack:
        _lp_log("commit: forcing slot restart because ramclear is required")
    if use_onehand_reload:
        _lp_log(
            "commit: OneHand reload only (Aurum stays up): "
            + ", ".join(onehand_reload_reasons)
        )
    if effective_restart and not use_slot and plan is None:
        stack_detail = (
            "No roulette stack plan on this PC. Settings will still be written."
        )

    parent = Path(work_parent) if work_parent is not None else Path(
        tempfile.mkdtemp(prefix="live_push_")
    )
    pack_dir = parent / "config-pack"
    written: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    backup_dir = ""
    staged_files: list[str] = []
    try:
        _emit(progress, "Building settings pack…")
        if live_push_will_write_aurum_setup(dest, recipe, sections):
            recipe = apply_aurum_hostname_for_live_push(recipe, plan_src)
        build_config_pack(recipe, dest, pack_dir, sections=sections)
        pack_recipe = load_pack_recipe(pack_dir / "recipe.json")
        staged_files = list(pack_recipe.files)
    except (OSError, ValueError, FileNotFoundError) as exc:
        if work_parent is None:
            shutil.rmtree(parent, ignore_errors=True)
        msg = str(exc)
        _lp_log(f"commit abort before stop: {msg}")
        return LivePushResult((), (), (msg,), False, False, msg)

    stop_failed = ""
    slot_stop_failed = ""
    if use_slot:
        _emit(progress, "Stopping the slot game…")
        ok, stack_detail = run_slot_stack_kill(plan_src)
        stack_killed = ok
        if not ok:
            # The SMB write path does not depend on WinRM or on the game being
            # down: OneHand reads these XMLs at start-up. Push the files anyway
            # and tell the operator the game must be restarted on the cabinet.
            slot_stop_failed = stack_detail
            _lp_log(
                "commit: slot stop failed, writing settings anyway: "
                f"{_short_fail(stack_detail)}"
            )
            _emit(progress, "Game stop failed — writing settings anyway…")
    elif plan is not None:
        _emit(progress, "Stopping the game (Kill-All)…")
        ok, stack_detail = run_stack_kill(plan)
        if not ok:
            if stack_stop_unreachable(stack_detail):
                stop_failed = stack_detail
                _lp_log(
                    "commit: Kill-All unreachable, writing settings anyway: "
                    f"{stack_detail[:400]}"
                )
                _emit(progress, "Game stop failed — writing settings anyway…")
            else:
                if work_parent is None:
                    shutil.rmtree(parent, ignore_errors=True)
                return LivePushResult(
                    (),
                    (),
                    (stack_detail or "Kill-All failed",),
                    False,
                    False,
                    stack_detail,
                )
        else:
            stack_killed = True

    try:
        if backup and staged_files:
            _emit(progress, "Backing up live files…")
            bak = backup_live_push_files(dest, staged_files)
            if bak is not None:
                backup_dir = str(bak)
                _lp_log(f"backup {backup_dir}")
        _emit(progress, "Writing settings…")
        applied = apply_config_pack(pack_dir, dest)
        written = applied.written
        skipped = applied.skipped
        errors = applied.errors
        if errors and backup_dir:
            rb = restore_live_push_backup(dest, Path(backup_dir))
            if rb:
                errors = errors + tuple(f"backup restore: {item}" for item in rb)
            else:
                errors = errors + ("Reverted live files from backup.",)
        _lp_log(
            f"write done files={len(written)} skipped={len(skipped)} "
            f"errors={errors} sections={sorted(sections) if sections else 'full'}"
        )
    except (OSError, ValueError, FileNotFoundError) as exc:
        errors = (str(exc),)
        if backup_dir:
            rb = restore_live_push_backup(dest, Path(backup_dir))
            if not rb:
                errors = errors + ("Reverted live files from backup.",)
    finally:
        if work_parent is None:
            shutil.rmtree(parent, ignore_errors=True)

    if kind == "slot" and written:
        try:
            ensure_aurum_setup_windows_hostname(dest, plan_src)
        except Exception as exc:  # noqa: BLE001
            _lp_log(f"aurum host ensure failed: {exc}")

    if want_licences:
        _emit(progress, "Copying missing licence files…")
        src = Path(licence_source) if licence_source else None
        lw, ls, le = push_missing_licences(dest, source=src)
        written = tuple(written) + lw
        skipped = tuple(skipped) + ls
        errors = tuple(errors) + le
        _lp_log(f"licence push written={lw} skipped={ls} errors={le}")
        if sections is not None and "licence" not in sections:
            sections = frozenset(set(sections) | {"licence"})

    if (
        stop_failed
        and written
        and not errors
        and stack_stop_unreachable(stop_failed)
    ):
        host = unc_host_from_target(plan_src) or "the cabinet"
        game = "OneHand" if use_slot else "the GoldClub stack"
        errors = (
            f"Settings written ({len(written)} file(s)), but the game could not "
            f"be stopped/restarted from this PC — WinRM is not listening on "
            f"{host}. Restart {game} there for them to take effect "
            f"(log: {log_path}).",
        )
        _lp_log(
            "commit: skip restart after unreachable stop: "
            f"{stop_failed[:200]}"
        )

    stack_started = False
    ramclear_ran = False
    ramclear_detail = ""
    start_noun = (
        "game-start"
        if (use_slot or use_onehand_reload)
        and slot_start_launcher(plan_src, dest) == "game-start"
        else "Bootstrap"
    )
    # A stop that *reached* the cabinet but left the game up falls through to
    # the normal post-write flow (hwsubsys -> stop again -> start). A dead WinRM
    # channel, or a pending RAM clear with the game still up, cannot.
    if (
        use_slot
        and slot_stop_failed
        and not errors
        and (slot_stop_unreachable(slot_stop_failed) or ramclear_reasons)
    ):
        host = unc_host_from_target(plan_src) or "the cabinet"
        why = _short_fail(slot_stop_failed)
        need_rc = (
            " RAM clear is still required ("
            + ", ".join(ramclear_reasons)
            + ") — run begin-ramclear on the cabinet."
            if ramclear_reasons
            else ""
        )
        if not written:
            head = f"Nothing was written and the game could not be stopped: {why}"
            hint = winrm_failure_hint(slot_stop_failed, host)
        elif winrm_listener_dead(slot_stop_failed):
            # State the dead channel once. The raw stop error, the "not
            # listening" aside and the generic hint all said the same thing.
            head = (
                f"Settings written ({len(written)} file(s)), but WinRM (TCP 5985) "
                f"is not answering on {host}, so the game could not be restarted "
                f"from here. Restart OneHand on the cabinet for them to take "
                f"effect.{need_rc}"
            )
            hint = (
                "Run Enable-PSRemoting on the cabinet to let Config Scanner "
                "restart it for you next time."
            )
        else:
            head = (
                f"Settings written ({len(written)} file(s)), but the game could not "
                f"be stopped/restarted from this PC — restart OneHand on {host} for "
                f"them to take effect. {why}{need_rc}"
            )
            hint = winrm_failure_hint(slot_stop_failed, host)
        errors = (f"{head} {hint} (log: {log_path})".strip(),)
        _lp_log(f"commit: slot stop failed outcome: {errors[0][:400]}")
    if (
        use_slot
        and ramclear_reasons
        and written
        and not errors
    ):
        _emit(
            progress,
            "Running RAM clear (" + ", ".join(ramclear_reasons) + ")…",
        )
        ok_rc, ramclear_detail = run_slot_ramclear(plan_src)
        ramclear_ran = ok_rc
        stack_detail = f"{stack_detail}\n{ramclear_detail}".strip()
        _lp_log(f"ramclear ok={ok_rc} {ramclear_detail[:400]}")
        if not ok_rc:
            errors = (
                "Settings written, but RAM clear failed — "
                f"{start_noun} was not started: {_short_fail(ramclear_detail)} "
                f"(log: {log_path})",
            )

    if use_slot and effective_restart and not errors:
        _emit(progress, "Starting GoldClub hardware services…")
        ok_hw, hw_detail = restart_slot_hwsubsys(plan_src)
        stack_detail = f"{stack_detail}\n{hw_detail}".strip()
        _lp_log(f"hwsubsys ok={ok_hw} {hw_detail[:400]}")
        if not ok_hw:
            errors = (
                "Settings written, but GoldClub Hardware Subsystem is not "
                f"Running — {start_noun} was not started: {_short_fail(hw_detail)} "
                f"(log: {log_path})",
            )

    if use_slot and effective_restart and not errors:
        _emit(progress, f"Ensuring game is stopped before {start_noun}…")
        ok_stop, stop_detail = run_slot_stack_kill(plan_src, stop_aurum=False)
        stack_detail = f"{stack_detail}\n{stop_detail}".strip()
        _lp_log(f"pre-start kill ok={ok_stop} stop_aurum=False {stop_detail[:400]}")
        if not ok_stop:
            errors = (
                "Settings written, but OneHand/Bootstrap was still running — "
                f"{start_noun} was not started: {_short_fail(stop_detail)} "
                f"(log: {log_path})",
            )

    if use_slot and effective_restart and not errors:
        _emit(progress, f"Starting {start_noun} on the cabinet…")
        ok, start_detail = run_slot_stack_start(plan_src, dest=dest)
        stack_started = ok
        stack_detail = f"{stack_detail}\n{start_detail}".strip()
        if not ok and not errors:
            errors = (
                f"Settings written, but the game did not start: {_short_fail(start_detail)} "
                f"(log: {log_path})",
            )
    elif stack_killed and plan is not None and not errors:
        _emit(progress, "Starting the game (Run-FullStack)…")
        ok, start_detail = run_stack_start(plan, scan_target=plan_src)
        stack_started = ok
        stack_detail = f"{stack_detail}\n{start_detail}".strip()
        if not ok and not errors:
            errors = (
                f"Settings written, but stack did not start: {_short_fail(start_detail)} "
                f"(log: {log_path})",
            )
    elif use_onehand_reload and written and not errors:
        _emit(progress, "Reloading OneHand (Aurum stays up)…")
        ok_stop, stop_detail = run_slot_stack_kill(plan_src, stop_aurum=False)
        stack_killed = ok_stop
        stack_detail = f"{stack_detail}\n{stop_detail}".strip()
        _lp_log(
            f"onehand reload kill ok={ok_stop} stop_aurum=False {stop_detail[:400]}"
        )
        if not ok_stop:
            host = unc_host_from_target(plan_src) or "the cabinet"
            hint = winrm_failure_hint(stop_detail, host)
            errors = (
                (
                    f"Settings written ({len(written)} file(s)), but OneHand "
                    f"could not be reloaded on {host} — "
                    f"{_short_fail(stop_detail)} {hint} (log: {log_path})"
                ).strip(),
            )
        else:
            _emit(progress, f"Starting {start_noun} on the cabinet…")
            ok, start_detail = run_slot_stack_start(plan_src, dest=dest)
            stack_started = ok
            stack_detail = f"{stack_detail}\n{start_detail}".strip()
            if ok:
                stack_detail = (
                    f"{stack_detail}\nOneHand reloaded (Aurum left running)."
                ).strip()
            elif not errors:
                errors = (
                    f"Settings written, but the game did not start: "
                    f"{_short_fail(start_detail)} (log: {log_path})",
                )

    sas_lock_note = ""
    wrote_sas = sections is None or "sas" in sections
    if (
        kind == "slot"
        and written
        and (wrote_sas or bool(recipe.sas.lock_game_when_no_comms))
    ):
        try:
            sas_lock_note = probe_sas_lock_state(plan_src, dest)
        except Exception as exc:  # noqa: BLE001
            _lp_log(f"sas lock probe skipped: {exc}")
            sas_lock_note = ""
        if sas_lock_note:
            stack_detail = f"{stack_detail}\n{sas_lock_note}".strip()
            _lp_log(f"sas lock probe {sas_lock_note}")

    _lp_log(
        f"commit end killed={stack_killed} started={stack_started} "
        f"ramclear={ramclear_ran} written={len(written)} errors={errors}"
    )
    return LivePushResult(
        written,
        skipped,
        errors,
        stack_killed,
        stack_started,
        stack_detail,
        backup_dir=backup_dir,
        sections=tuple(sorted(sections)) if sections is not None else (),
        ramclear_ran=ramclear_ran,
        ramclear_detail=ramclear_detail,
        sas_lock_note=sas_lock_note,
    )
