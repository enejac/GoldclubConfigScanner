"""Review SlotLog (and related) tails for probable misconfig after a live push.

OneHand writes concrete failures once the game is up — e.g. invalid TargetMarket
('Jamaica' is not a valid value for Market), RAMCLEAR / trial, SAS lock. Live Push
surfaces those so the operator can change a field (denom / market) or restore the
pre-push backup.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_TS_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2})?)"
)
_MARKET_INVALID_RE = re.compile(
    r"Instance validation error:\s*'(?P<value>[^']+)'\s+is not a valid value for Market",
    re.I,
)
_DENOM_INVALID_RE = re.compile(
    r"(?:invalid|unsupported|unknown)\s+denom(?:ination)?[^.\n]{0,80}",
    re.I,
)
_XML_ERROR_RE = re.compile(
    r"error in XML document|XmlException|XmlSerializer",
    re.I,
)


@dataclass(frozen=True)
class SlotLogFinding:
    """One probable misconfig detected in cabinet logs."""

    id: str
    severity: str  # "error" | "warning" | "info"
    title: str
    detail: str
    field_label: str = ""  # Live Push form label when applicable
    fix_hint: str = ""
    log_rel: str = ""
    line: str = ""
    captured_value: str = ""  # e.g. invalid market name


@dataclass
class SlotLogReview:
    findings: list[SlotLogFinding] = field(default_factory=list)
    logs_scanned: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def errors(self) -> list[SlotLogFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[SlotLogFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def has_actionable(self) -> bool:
        return bool(self.errors or self.warnings)


# (id, severity, title, field, fix_hint, compiled pattern or None, plain needles)
_RULES: tuple[tuple[str, str, str, str, str, re.Pattern[str] | None, tuple[str, ...]], ...] = (
    (
        "market_invalid",
        "error",
        "Invalid Target market for this OneHand build",
        "Market",
        "Change Target market to a value this OneHand accepts "
        "(e.g. PuertoRico / TrinidadAndTobago on GameStar 2.0.1), then Apply again. "
        "Or restore the pre-push backup.",
        _MARKET_INVALID_RE,
        (),
    ),
    (
        "ramclear_required",
        "error",
        "RAM clear required (licence / NVRAM)",
        "",
        "Licence or trial state is inconsistent. Run the slot RAM clear maintenance "
        "task (not a Live Push field). Restore backup only if you changed licence files.",
        None,
        ("RAMCLEAR REQUIRED", "ErrorRegistryDataNotFound"),
    ),
    (
        "trial_expired",
        "error",
        "Trial / licence data missing",
        "",
        "Slot trial blob missing — usually fixed by RAM clear after a licence change.",
        None,
        ("Trial expired with trial type",),
    ),
    (
        "currency_mismatch",
        "error",
        "Jurisdiction currency does not match Aurum",
        "Currency",
        "OneHand refused to start: jurisdiction CurrencyName and AurumSetup "
        "CurrencyCode/CurrencyId disagree. Live Push must write both and run a "
        "RAM clear after currency changes. Restore the Live Push backup or "
        "re-Apply with matching currency.",
        None,
        (
            "Jurisdiction currency",
            "Aurum selected currency",
            "do not match",
        ),
    ),
    (
        "aurum_egm_nre",
        "error",
        "Aurum EGM failed to start",
        "SAS enabled",
        "OneHand could not create AurumEGM (wrong AurumSetup host block, not "
        "the SAS address checkbox). Use More → Diagnose & repair cabinet "
        "(AurumSetup host) — do not rewrite serialport maps.",
        None,
        (
            "AurumEGM creation error",
            "AurumEGM..ctor",
            "CONFIG FOR SASControler1 NOT FOUND",
        ),
    ),
    (
        "sas_lock",
        "warning",
        "Game locked: NO SAS COMMUNICATIONS",
        "Lock when no SAS",
        "SAS lock after start. Often clears once CommCtrlSAS opens COM11. "
        "If it stays locked, check MUX/SAS (not Live Push denoms). "
        "You can turn off Lock when no SAS only for lab testing.",
        None,
        ("NO SAS COMMUNICATIONS",),
    ),
    (
        "ticket_comms",
        "warning",
        "Ticket printer communication error",
        "Ticket printer",
        "Printer did not come up cleanly. Check Ticket printer protocol and cabling; "
        "Offline ticket mode is separate from TITO.",
        None,
        ("RECOVER COMUNICATION ERROR", "RECOVER COMMUNICATION ERROR"),
    ),
    (
        "return_percent",
        "info",
        "Theme return percent missing / invalid",
        "",
        "A theme had an empty return percent and OneHand fell back to a default. "
        "Normal on this image (not a Denoms field problem).",
        None,
        ("Return percent '' is not valid", "Return percent \"\" is not valid"),
    ),
    (
        "theme_icon",
        "info",
        "Invalid theme icon index",
        "",
        "InfoScreen logs icon index 0 on almost every boot. Not caused by "
        "2-screen vs 3-screen Display layout.",
        None,
        ("Invalid theme icon index",),
    ),
    (
        "config_changed_discard",
        "info",
        "Game discarded prior run state after config change",
        "",
        "Expected after a Live Push — OneHand discarded queued game state.",
        None,
        ("Configuration has changed since last game run",),
    ),
)


_SAS_CLEAR_NEEDLES = (
    "Lock item removed: OnlineLock",
    "Unlocked by Host.",
    "'Select A Game'",
    "Select A Game",
)
_PRINTER_OK_NEEDLES = (
    "HWCONTROLLER_TicketPrinter - DEVICE INITIALIZED",
    "Initilized correctly the TICKET PRINTER DRIVER",
    "Initialized correctly the TICKET PRINTER DRIVER",
)
_TICKET_FAIL_NEEDLES = (
    "ERROR TICKET PRINTING",
    "Ticket Printer Disconnected.",
    "TicketError_Connected",
    "Device class mismatch: required=ticketprinter",
    "Proxy error: channel_name=tito",
)
_AURUM_OK_NEEDLES = (
    "Aurum EGM messenger created and started",
    "Aurum EGM messenger created",
)


def _parse_line_time(line: str) -> datetime | None:
    match = _TS_RE.match(line.strip())
    if not match:
        return None
    raw = match.group("ts")
    try:
        if "T" in raw:
            # 2026-09-03T10:29:23.359+01:00
            return datetime.fromisoformat(raw)
        # 2026-09-03 10:47:13
        return datetime.fromisoformat(raw.replace(" ", "T")).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _read_tail(path: Path, *, max_bytes: int = 500_000) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    try:
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def _slotlog_candidates(goldclub: Path, *, limit: int = 6) -> list[Path]:
    root = Path(goldclub)
    dirs = [
        root / "var" / "log" / "SlotLog",
        root / "slot" / "var" / "log" / "SlotLog",
        root / "var" / "log" / "OneHand",
        root / "var" / "log" / "GoldClub.Aurum.Services",
        root / "var" / "log" / "GoldClub.Aurum.Services SASControler1",
        root / "var" / "log" / "GameLicenceManager",
    ]
    files: list[Path] = []
    for folder in dirs:
        try:
            if not folder.is_dir():
                continue
            files.extend(p for p in folder.glob("*.log") if p.is_file())
        except OSError:
            continue

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    files.sort(key=_mtime, reverse=True)
    return files[:limit]


def _utc_naive(dt: datetime) -> datetime:
    """Compare cabinet (+01) lines to a UTC or local ``since`` on one clock."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(tzinfo=None)


def _ts_after_since(ts: datetime, since: datetime) -> bool:
    try:
        return _utc_naive(ts) >= _utc_naive(since)
    except TypeError:
        return True


def _line_after_since(line: str, since: datetime | None) -> bool:
    if since is None:
        return True
    ts = _parse_line_time(line)
    if ts is None:
        return True  # caller should inherit the previous dated line instead
    return _ts_after_since(ts, since)


def review_slot_logs(
    goldclub: Path,
    *,
    since: datetime | None = None,
    max_bytes: int = 500_000,
) -> SlotLogReview:
    """Scan recent SlotLog / Aurum tails for known misconfig signatures."""
    goldclub = Path(goldclub)
    review = SlotLogReview()
    candidates = _slotlog_candidates(goldclub)
    if not candidates:
        review.note = "No SlotLog files found under var/log."
        return review

    # Collect lines (path, line) after since
    corpus: list[tuple[Path, str]] = []
    for path in candidates:
        text = _read_tail(path, max_bytes=max_bytes)
        if not text:
            continue
        try:
            rel = path.relative_to(goldclub).as_posix()
        except ValueError:
            rel = path.name
        review.logs_scanned.append(rel)
        # Undated stack frames inherit the last dated line. Orphan frames at
        # the start of a tail (yesterday's AurumEGM..ctor) must not count.
        last_keep = since is None
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line:
                continue
            ts = _parse_line_time(line)
            if ts is not None:
                last_keep = since is None or _ts_after_since(ts, since)
            if not last_keep:
                continue
            corpus.append((path, line))

    seen_ids: set[str] = set()
    sas_locked = False
    sas_cleared = False
    online_lock_seen = False
    ticket_recover = False
    ticket_hard_fail = False
    ticket_ok = False
    aurum_nre = False
    aurum_ok = False

    for path, line in corpus:
        low = line.casefold()
        try:
            rel = path.relative_to(goldclub).as_posix()
        except ValueError:
            rel = path.name

        if "onlinelock" in low:
            online_lock_seen = True
        for needle in _SAS_CLEAR_NEEDLES:
            if needle.casefold() in low:
                sas_cleared = True
        for needle in _PRINTER_OK_NEEDLES:
            if needle.casefold() in low:
                ticket_ok = True
        for needle in _TICKET_FAIL_NEEDLES:
            if needle.casefold() in low:
                ticket_hard_fail = True
        if (
            "hwcontroller_ticketprinter" in low.replace(" ", "")
            and "communication error" in low
            and "recover" not in low
        ):
            ticket_hard_fail = True
        for needle in _AURUM_OK_NEEDLES:
            if needle.casefold() in low:
                aurum_ok = True

        for rule_id, severity, title, field, fix, pattern, needles in _RULES:
            hit = False
            captured = ""
            if pattern is not None:
                m = pattern.search(line)
                if m:
                    hit = True
                    if "value" in m.groupdict():
                        captured = m.group("value")
            for needle in needles:
                if needle.casefold() in low:
                    hit = True
                    break
            if not hit:
                continue
            if rule_id == "sas_lock":
                sas_locked = True
                continue  # decide after full scan
            if rule_id == "ticket_comms":
                ticket_recover = True
                continue  # decide after full scan
            if rule_id == "aurum_egm_nre":
                aurum_nre = True
                continue  # decide after full scan
            if rule_id in seen_ids:
                continue
            seen_ids.add(rule_id)
            detail = line.strip()
            if captured:
                detail = f"Value {captured!r}: {detail}"
            review.findings.append(
                SlotLogFinding(
                    id=rule_id,
                    severity=severity,
                    title=title if not captured else f"{title}: {captured}",
                    detail=detail[:400],
                    field_label=field,
                    fix_hint=fix,
                    log_rel=rel,
                    line=line[:400],
                    captured_value=captured,
                )
            )

        # Denom-ish free-text
        if "denom_invalid" not in seen_ids and _DENOM_INVALID_RE.search(line):
            seen_ids.add("denom_invalid")
            review.findings.append(
                SlotLogFinding(
                    id="denom_invalid",
                    severity="error",
                    title="Denomination rejected in SlotLog",
                    detail=line.strip()[:400],
                    field_label="Denoms (cents)",
                    fix_hint=(
                        "Pick a denomination this market / image supports "
                        "(e.g. 1, 2, 5, 10, 25, 50, 100), then Apply again — "
                        "or restore the pre-push backup."
                    ),
                    log_rel=rel,
                    line=line[:400],
                )
            )

        # Generic XML serializer failure without Market capture
        if (
            "xml_config_error" not in seen_ids
            and "market_invalid" not in seen_ids
            and _XML_ERROR_RE.search(line)
            and "error" in low
        ):
            seen_ids.add("xml_config_error")
            review.findings.append(
                SlotLogFinding(
                    id="xml_config_error",
                    severity="error",
                    title="mgconfig / XML failed to load",
                    detail=line.strip()[:400],
                    field_label="Market",
                    fix_hint=(
                        "OneHand rejected the written XML. Check Target market and "
                        "locale fields, or restore the pre-push backup."
                    ),
                    log_rel=rel,
                    line=line[:400],
                )
            )

    if sas_locked and not sas_cleared and "sas_lock" not in seen_ids:
        review.findings.append(
            SlotLogFinding(
                id="sas_lock",
                severity="warning",
                title="Game locked: NO SAS COMMUNICATIONS",
                detail="SAS lock seen in SlotLog without a later unlock in the scanned tail.",
                field_label="Lock when no SAS",
                fix_hint=(
                    "Wait for SAS poll / MUX on COM11. If it stays locked, use cabinet "
                    "MUX repair — not a denom change."
                ),
                log_rel="var/log/SlotLog",
            )
        )
    elif sas_locked and sas_cleared:
        review.findings.append(
            SlotLogFinding(
                id="sas_lock_cleared",
                severity="info",
                title="SAS lock appeared then cleared",
                detail="NO SAS COMMUNICATIONS was logged, then the game unlocked.",
                field_label="Lock when no SAS",
                fix_hint="No action needed — normal when CommCtrlSAS comes up after Bootstrap.",
            )
        )
    elif not sas_locked and not online_lock_seen:
        lock_on = _live_sas_lock_on_disk(goldclub)
        if lock_on is True:
            review.findings.append(
                SlotLogFinding(
                    id="sas_lock_flag_idle",
                    severity="info",
                    title="Lock when no SAS is on; game did not lock",
                    detail=(
                        "LockGameWhenNoComms is true and SlotLog has no "
                        "NO SAS COMMUNICATIONS / OnlineLock. Unlocked is "
                        "expected while SAS 31100 / CommCtrlSAS is up."
                    ),
                    field_label="Lock when no SAS",
                    fix_hint=(
                        "This is not lock now. The game locks only if the SAS "
                        "gateway (localhost:31100) drops."
                    ),
                )
            )

    if (ticket_recover or ticket_hard_fail) and not ticket_ok:
        detail = (
            "Printer recover lock in SlotLog without a later DEVICE INITIALIZED."
            if ticket_recover and not ticket_hard_fail
            else (
                "Ticket printer failed to initialize (COMMUNICATION ERROR / "
                "TicketError_Connected / HWSubsys tito proxy). Often after "
                "Live Push if OneHand stayed running during restart."
            )
        )
        review.findings.append(
            SlotLogFinding(
                id="ticket_comms",
                severity="warning",
                title="Ticket printer communication error",
                detail=detail,
                field_label="Ticket printer",
                fix_hint=(
                    "Printer did not come up cleanly. Re-apply with restart, or "
                    "reboot the cabinet. JCM Gen5 uses the FutureLogic (JCM) "
                    "driver — protocol is already correct on this image. "
                    "Offline ticket mode is separate from TITO."
                ),
                log_rel="var/log/SlotLog",
            )
        )
    elif ticket_recover and ticket_ok:
        review.findings.append(
            SlotLogFinding(
                id="ticket_comms_cleared",
                severity="info",
                title="Ticket printer recovered after boot handshake",
                detail=(
                    "RECOVER COMUNICATION ERROR is logged on every TITO SafeStart, "
                    "then DEVICE INITIALIZED. Not a Live Push protocol mismatch."
                ),
                field_label="",
                fix_hint="No action needed — printer initialized after the recover lock.",
            )
        )

    if aurum_nre and not aurum_ok:
        review.findings.append(
            SlotLogFinding(
                id="aurum_egm_nre",
                severity="error",
                title="Aurum EGM failed to start",
                detail="AurumEGM..ctor / creation error in SlotLog with no later messenger.",
                field_label="SAS enabled",
                fix_hint=(
                    "OneHand could not create AurumEGM (wrong AurumSetup host "
                    "block). Use More → Diagnose & repair cabinet — do not "
                    "rewrite serialport maps."
                ),
                log_rel="var/log/SlotLog",
            )
        )
    elif aurum_nre and aurum_ok:
        review.findings.append(
            SlotLogFinding(
                id="aurum_egm_cleared",
                severity="info",
                title="Aurum EGM NRE during boot then messenger started",
                detail=(
                    "AurumEGM creation error can appear while services come up. "
                    "A later 'Aurum EGM messenger created and started' means the "
                    "game recovered — not a Live Push SAS failure."
                ),
                field_label="",
                fix_hint="No action needed — wait for Select A Game before re-checking.",
            )
        )

    # Prefer errors first
    order = {"error": 0, "warning": 1, "info": 2}
    review.findings.sort(key=lambda f: (order.get(f.severity, 9), f.id))
    _suppress_resolved_findings(review, goldclub)
    review.findings.sort(key=lambda f: (order.get(f.severity, 9), f.id))
    if not review.findings:
        review.note = (
            f"Scanned {len(review.logs_scanned)} log(s); no known misconfig signatures."
        )
    elif not review.has_actionable:
        idle = next(
            (f for f in review.findings if f.id == "sas_lock_flag_idle"),
            None,
        )
        if idle is not None:
            review.note = (
                "Lock when no SAS is on; SlotLog has no lock — unlocked is "
                "expected while SAS 31100 is up."
            )
        else:
            review.note = (
                f"Scanned {len(review.logs_scanned)} log(s); only boot-noise notes "
                "(empty theme RTP, TITO handshake, icon index) — not Live Push fields."
            )
    return review


def _live_sas_lock_on_disk(goldclub: Path) -> bool | None:
    """True/False from SASsetupData; None when the file is missing or unreadable."""
    try:
        from config_scanner.slot_setup import (
            _SAS_SETUP_REL,
            _resolve_goldclub_rel,
            read_sas_settings,
        )
    except Exception:  # noqa: BLE001
        return None
    path = _resolve_goldclub_rel(goldclub, _SAS_SETUP_REL)
    if path is None or not path.is_file():
        return None
    try:
        return bool(read_sas_settings(goldclub).lock_game_when_no_comms)
    except Exception:  # noqa: BLE001
        return None


def _xml_text(goldclub: Path, rel: str, tag: str) -> str:
    path = Path(goldclub) / rel
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(
        rf"<(?:[\w.]+:)?{re.escape(tag)}>([^<]*)</(?:[\w.]+:)?{re.escape(tag)}>",
        text,
        re.I,
    )
    return (match.group(1) if match else "").strip()


def _suppress_resolved_findings(review: SlotLogReview, goldclub: Path) -> None:
    """Drop or downgrade findings the live files already contradict.

    SlotLog tails keep today's earlier failures (e.g. USD vs TTD at 11:24) long
    after Live Push aligned currency / turned off LockGameWhenNoComms.
    """
    try:
        from config_scanner.slot_setup import read_aurum_currency_code, read_sas_settings
    except Exception:  # noqa: BLE001
        return

    jur = (
        _xml_text(goldclub, "slot/themes/jurisdiction_config.xml", "CurrencyName")
        or _xml_text(goldclub, "slot/themes/mgconfig.xml", "CurrencyName")
        or _xml_text(goldclub, "slot/themes/HardwareConfig.xml", "CurrencyName")
    ).strip().upper()
    try:
        aurum = (read_aurum_currency_code(goldclub) or "").strip().upper()
    except Exception:  # noqa: BLE001
        aurum = ""
    currencies_ok = bool(jur and aurum and jur == aurum)

    try:
        lock_off = not bool(read_sas_settings(goldclub).lock_game_when_no_comms)
    except Exception:  # noqa: BLE001
        lock_off = False

    kept: list[SlotLogFinding] = []
    for finding in review.findings:
        if finding.id == "currency_mismatch" and currencies_ok:
            kept.append(
                SlotLogFinding(
                    id="currency_mismatch_resolved",
                    severity="info",
                    title="Currency mismatch was logged earlier (now fixed on disk)",
                    detail=(
                        f"SlotLog still has an older mismatch line, but live files "
                        f"agree ({jur} / Aurum {aurum}). No Apply needed for currency."
                    ),
                    field_label="",
                    fix_hint="Acknowledge — or Check SlotLog again after the next boot.",
                    log_rel=finding.log_rel,
                    line=finding.line,
                )
            )
            continue
        if finding.id == "sas_lock" and lock_off:
            kept.append(
                SlotLogFinding(
                    id="sas_lock_config_off",
                    severity="info",
                    title="NO SAS lock was logged; Lock when no SAS is off on disk",
                    detail=(
                        "SASsetupData LockGameWhenNoComms is false. If the game still "
                        "locks, Aurum must be restarted so it reloads SAS setup "
                        "(Live Push now restarts Aurum before Bootstrap)."
                    ),
                    field_label="Lock when no SAS",
                    fix_hint="Apply with Restart game, or restart GoldClub.Aurum.Services.",
                    log_rel=finding.log_rel,
                    line=finding.line,
                )
            )
            continue
        kept.append(finding)
    review.findings = kept


def finding_field_errors(findings: list[SlotLogFinding]) -> dict[str, str]:
    """Map Live Push field labels → first error/warning message for red/amber paint."""
    out: dict[str, str] = {}
    for finding in findings:
        if finding.severity not in ("error", "warning"):
            continue
        if not finding.field_label:
            continue
        out.setdefault(
            finding.field_label,
            f"{finding.title}. {finding.fix_hint}".strip(),
        )
    return out


def field_highlight_error(
    *,
    matches_live: bool,
    validation_error: str = "",
    log_error: str = "",
) -> str:
    """Reason to paint a field red.

    Recipe validation always wins. SlotLog must not paint a field red when the
    form already matches the live cabinet (boot-noise leftovers).
    """
    if validation_error:
        return validation_error
    if matches_live:
        return ""
    return (log_error or "").strip()


def restore_live_push_backup(backup_dir: Path, goldclub: Path) -> list[str]:
    """Copy files from a Live Push backup tree back onto the goldclub root."""
    backup_dir = Path(backup_dir)
    goldclub = Path(goldclub)
    if not backup_dir.is_dir():
        raise FileNotFoundError(f"backup not found: {backup_dir}")
    if not goldclub.is_dir():
        raise FileNotFoundError(f"goldclub not found: {goldclub}")
    restored: list[str] = []
    for path in backup_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(backup_dir)
        dest = goldclub / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        restored.append(rel.as_posix())
    return restored


def format_review_summary(review: SlotLogReview) -> str:
    if not review.findings:
        return review.note or "No SlotLog issues found."
    lines: list[str] = []
    for finding in review.findings:
        if finding.severity == "info":
            continue
        mark = "ERROR" if finding.severity == "error" else "WARN"
        lines.append(f"[{mark}] {finding.title}")
        if finding.fix_hint:
            lines.append(f"  → {finding.fix_hint}")
        if finding.field_label:
            lines.append(f"  Field: {finding.field_label}")
    actionable = [f for f in review.findings if f.severity != "info"]
    if not lines:
        return "SlotLog: only informational notes (config change discarded, etc.)."
    return (
        f"SlotLog review: {len(actionable)} issue(s)\n\n" + "\n".join(lines)
    )
