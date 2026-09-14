"""Tests for post-push SlotLog misconfig review."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config_scanner.slotlog_review import (
    field_highlight_error,
    finding_field_errors,
    format_review_summary,
    restore_live_push_backup,
    review_slot_logs,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_review_suppresses_currency_mismatch_when_files_agree(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "2026-09-03.log"
    _write(
        log,
        "2026-09-03T11:24:38.122+01:00 ERROR [SlotMachine] OneHand.AurumEGM - "
        "Jurisdiction currency USD and Aurum selected currency TTD do not match\n",
    )
    _write(
        tmp_path / "slot" / "themes" / "jurisdiction_config.xml",
        "<root><CurrencyName>USD</CurrencyName></root>\n",
    )
    _write(
        tmp_path / "Services" / "aurum" / "config" / "AurumSetup.xml",
        "<AurumSetup><CurrencyTable><CurrencyCode>USD</CurrencyCode></CurrencyTable>"
        "<ProcessorConfig><CurrencyId>USD</CurrencyId></ProcessorConfig></AurumSetup>\n",
    )
    review = review_slot_logs(tmp_path)
    assert not any(f.id == "currency_mismatch" for f in review.findings)
    assert any(f.id == "currency_mismatch_resolved" for f in review.findings)
    assert "Currency" not in finding_field_errors(review.findings)


def test_review_detects_currency_mismatch(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "2026-09-03.log"
    _write(
        log,
        "2026-09-03T12:30:00.000+01:00 ERROR [1] OneHand.AurumEGM - "
        "System.Exception: Jurisdiction currency USD and Aurum selected "
        "currency TTD do not match\n",
    )
    review = review_slot_logs(tmp_path)
    assert any(f.id == "currency_mismatch" for f in review.findings)
    hit = next(f for f in review.findings if f.id == "currency_mismatch")
    assert hit.field_label == "Currency"
    assert hit.severity == "error"


def test_resolve_goldclub_rel_case_insensitive(tmp_path: Path) -> None:
    from config_scanner.slot_setup import _resolve_goldclub_rel, read_sas_settings

    sas_dir = tmp_path / "services" / "aurum" / "config" / "SASControler1"
    sas_dir.mkdir(parents=True)
    (sas_dir / "SASsetupData.xml").write_text(
        '<?xml version="1.0"?>\n'
        "<SASsetupData>"
        "<LockGameWhenNoComms>false</LockGameWhenNoComms>"
        "<FundsTransferType>AFT</FundsTransferType>"
        "</SASsetupData>\n",
        encoding="utf-8",
    )
    hit = _resolve_goldclub_rel(
        tmp_path, "Services/aurum/config/SASControler1/SASsetupData.xml"
    )
    assert hit is not None
    assert hit.is_file()
    assert read_sas_settings(tmp_path).lock_game_when_no_comms is False

    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T12:54:14.640+01:00 INFO NO SAS COMMUNICATIONS!\n",
    )
    _write(
        tmp_path / "Services" / "aurum" / "config" / "SASControler1" / "SASsetupData.xml",
        '<?xml version="1.0"?><SASsetupData>'
        "<LockGameWhenNoComms>false</LockGameWhenNoComms></SASsetupData>\n",
    )
    review = review_slot_logs(tmp_path)
    assert not any(f.id == "sas_lock" and f.severity == "warning" for f in review.findings)
    assert any(f.id == "sas_lock_config_off" for f in review.findings)


def test_review_detects_invalid_market(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "2026-09-03.log"
    _write(
        log,
        "2026-09-03T10:29:23.359+01:00 ERROR [1] OneHand.MainFrm - "
        "System.InvalidOperationException: There is an error in XML document "
        "(3238, 6). ---> System.InvalidOperationException: Instance validation "
        "error: 'Jamaica' is not a valid value for Market.\n",
    )
    review = review_slot_logs(tmp_path)
    assert any(f.id == "market_invalid" for f in review.findings)
    hit = next(f for f in review.findings if f.id == "market_invalid")
    assert hit.severity == "error"
    assert hit.field_label == "Market"
    assert hit.captured_value == "Jamaica"
    mapped = finding_field_errors(review.findings)
    assert "Market" in mapped
    assert "Jamaica" in format_review_summary(review) or "market" in format_review_summary(
        review
    ).casefold()


def _write_sas_lock(goldclub: Path, *, on: bool) -> None:
    path = (
        goldclub
        / "Services"
        / "aurum"
        / "config"
        / "SASControler1"
        / "SASsetupData.xml"
    )
    flag = "true" if on else "false"
    _write(
        path,
        '<?xml version="1.0"?>\n'
        "<SASsetupData>"
        f"<LockGameWhenNoComms>{flag}</LockGameWhenNoComms>"
        "</SASsetupData>\n",
    )


def test_review_sas_lock_cleared(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T10:47:24.011+01:00 INFO NO SAS COMMUNICATIONS!\n"
        "2026-09-03T10:48:00.000+01:00 INFO Lock item removed: OnlineLock\n"
        "2026-09-03T10:48:01.000+01:00 INFO Unlocked by Host.\n",
    )
    review = review_slot_logs(tmp_path)
    assert any(f.id == "sas_lock_cleared" for f in review.findings)
    assert not any(f.id == "sas_lock" and f.severity == "warning" for f in review.findings)


def test_review_sas_lock_flag_idle_when_comms_hold(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-14T13:31:00.000+01:00 INFO Aurum EGM messenger created and started\n"
        "2026-09-14T13:31:10.000+01:00 INFO 'Select A Game'\n",
    )
    _write_sas_lock(tmp_path, on=True)
    review = review_slot_logs(tmp_path)
    idle = next(f for f in review.findings if f.id == "sas_lock_flag_idle")
    assert idle.severity == "info"
    assert idle.field_label == "Lock when no SAS"
    assert "31100" in idle.detail
    assert not any(f.id == "sas_lock" and f.severity == "warning" for f in review.findings)
    assert not review.has_actionable
    assert "unlocked is expected" in review.note.casefold()


def test_review_sas_lock_warning_when_flag_on(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-14T13:06:00.000+01:00 INFO Locked by Host. NO SAS COMMUNICATIONS!\n",
    )
    _write_sas_lock(tmp_path, on=True)
    review = review_slot_logs(tmp_path)
    hit = next(f for f in review.findings if f.id == "sas_lock")
    assert hit.severity == "warning"
    assert not any(f.id == "sas_lock_flag_idle" for f in review.findings)
    assert review.has_actionable


def test_review_since_filters_old_lines(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T08:00:00.000+01:00 ERROR Instance validation error: "
        "'Jamaica' is not a valid value for Market.\n"
        "2026-09-03T11:00:00.000+01:00 INFO game ok\n",
    )
    since = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    review = review_slot_logs(tmp_path, since=since)
    assert not any(f.id == "market_invalid" for f in review.findings)


def test_boot_noise_does_not_paint_live_matching_fields(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T13:56:41.130+01:00 WARN Return percent '' is not valid. "
        "Default percent 'return_92_0' was set for theme 'TutankhamenGSBHW'.\n"
        "2026-09-03T13:56:45.632+01:00 ERROR Invalid theme icon index:0\n"
        "2026-09-03T13:56:50.647+01:00 INFO HWCONTROLLER_TicketPrinter - "
        "Add lock RECOVER COMUNICATION ERROR\n"
        "2026-09-03T13:56:51.141+01:00 INFO HWCONTROLLER_TicketPrinter - "
        "DEVICE INITIALIZED\n",
    )
    review = review_slot_logs(tmp_path)
    ids = {f.id: f for f in review.findings}
    assert ids["return_percent"].severity == "info"
    assert ids["theme_icon"].severity == "info"
    assert ids["ticket_comms_cleared"].severity == "info"
    assert not review.has_actionable
    mapped = finding_field_errors(review.findings)
    assert "Denoms (cents)" not in mapped
    assert "Ticket printer" not in mapped
    assert "Display layout" not in mapped
    assert (
        field_highlight_error(
            matches_live=True,
            log_error=mapped.get("Ticket printer", "would-have-been-red"),
        )
        == ""
    )


def test_ticket_hard_fail_without_initialize(tmp_path: Path) -> None:
    slot_log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    oh_log = tmp_path / "var" / "log" / "OneHand" / "day.log"
    _write(
        slot_log,
        "2026-09-04T10:50:45.383+01:00 INFO HWCONTROLLER_TicketPrinter - "
        "COMMUNICATION ERROR\n"
        "2026-09-04T10:50:47.290+01:00 INFO HWCONTROLLER_TicketPrinter - "
        "Add lock ERROR TICKET PRINTING...\n",
    )
    _write(
        oh_log,
        "2026-09-04T10:50:13.861+01:00 ERRO tito0: Proxy error: channel_name=tito0\n",
    )
    review = review_slot_logs(tmp_path)
    hit = next(f for f in review.findings if f.id == "ticket_comms")
    assert hit.severity == "warning"
    assert "TicketError" in hit.fix_hint or "COMMUNICATION" in hit.detail
    assert finding_field_errors(review.findings).get("Ticket printer")


def test_ticket_comms_warns_only_without_initialize(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T13:56:50.647+01:00 INFO HWCONTROLLER_TicketPrinter - "
        "Add lock RECOVER COMUNICATION ERROR\n",
    )
    review = review_slot_logs(tmp_path)
    hit = next(f for f in review.findings if f.id == "ticket_comms")
    assert hit.severity == "warning"
    assert finding_field_errors(review.findings).get("Ticket printer")
    assert field_highlight_error(
        matches_live=True, log_error=finding_field_errors(review.findings)["Ticket printer"]
    ) == ""
    assert field_highlight_error(
        matches_live=False,
        log_error=finding_field_errors(review.findings)["Ticket printer"],
    )


def test_review_ramclear_and_denom(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T12:00:00.000+01:00 ERRO Trial expired with trial type "
        "ErrorRegistryDataNotFound RAMCLEAR REQUIRED\n"
        "2026-09-03T12:01:00.000+01:00 ERROR Invalid denomination 7 not supported\n",
    )
    review = review_slot_logs(tmp_path)
    ids = {f.id for f in review.findings}
    assert "ramclear_required" in ids or "trial_expired" in ids
    assert "denom_invalid" in ids
    assert finding_field_errors(review.findings).get("Denoms (cents)")


def test_restore_live_push_backup(tmp_path: Path) -> None:
    bak = tmp_path / "backup"
    live = tmp_path / "goldclub"
    _write(bak / "slot" / "themes" / "mgconfig.xml", "<old/>")
    _write(live / "slot" / "themes" / "mgconfig.xml", "<new/>")
    restored = restore_live_push_backup(bak, live)
    assert "slot/themes/mgconfig.xml" in restored
    assert (live / "slot" / "themes" / "mgconfig.xml").read_text(encoding="utf-8") == "<old/>"


def test_stale_aurum_stack_trace_before_since_is_ignored(tmp_path: Path) -> None:
    """Yesterday's undated AurumEGM..ctor frames must not fire after a good boot."""
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-03T15:29:31.526+01:00 CRIT AurumEGM creation error\n"
        "   at OneHand.AurumEGM..ctor(String setupPath)\n"
        "2026-09-04T08:19:56.051+01:00 INFO OneHand.MainFrm - "
        "Aurum EGM messenger created and started\n",
    )
    # 08:19:56+01 is 07:19:56 UTC — since must be before that good boot.
    since = datetime(2026, 9, 4, 7, 19, 0, tzinfo=timezone.utc)
    review = review_slot_logs(tmp_path, since=since)
    assert not any(f.id == "aurum_egm_nre" for f in review.findings)
    assert not any(f.severity == "error" for f in review.findings)


def test_aurum_nre_cleared_when_messenger_starts(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-04T08:19:40.000+01:00 ERROR AurumEGM creation error\n"
        "   at OneHand.AurumEGM..ctor(String setupPath)\n"
        "2026-09-04T08:19:56.051+01:00 INFO Aurum EGM messenger created and started\n",
    )
    review = review_slot_logs(tmp_path)
    assert any(f.id == "aurum_egm_cleared" for f in review.findings)
    assert not any(f.id == "aurum_egm_nre" and f.severity == "error" for f in review.findings)
    assert not review.has_actionable


def test_aurum_nre_stays_error_without_messenger(tmp_path: Path) -> None:
    log = tmp_path / "var" / "log" / "SlotLog" / "day.log"
    _write(
        log,
        "2026-09-04T08:19:40.000+01:00 ERROR AurumEGM creation error\n"
        "   at OneHand.AurumEGM..ctor(String setupPath)\n",
    )
    review = review_slot_logs(tmp_path)
    hit = next(f for f in review.findings if f.id == "aurum_egm_nre")
    assert hit.severity == "error"
    assert hit.field_label == "SAS enabled"


def test_live_push_panel_wires_slotlog_check() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "Check SlotLog" in src
    assert "review_slot_logs" in src
    assert "restore_live_push_backup" in src
    assert "field_highlight_error" in src
    assert "_start_slotlog_review" in src
    assert "wait_sec=90.0" in src
    assert "format_live_push_apply_status" in src
    assert 'QMessageBox.information(\n            self,\n            "Apply complete"' not in src
    assert "_set_apply_result" in src
    assert "LIVE_PUSH_APPLY_SLOTLOG_HINT" in src
