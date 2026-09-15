"""Closing Config Scanner with X must not leave background workers running."""

from __future__ import annotations

from pathlib import Path

import pytest

from config_scanner import app_shutdown as shut
from config_scanner.live_push import _SLOT_WATCHDOG_MARKER
from network import lab_access as la


@pytest.fixture(autouse=True)
def _reset_shutdown_flags() -> None:
    shut.reset_shutdown_for_tests()
    yield
    shut.reset_shutdown_for_tests()


def test_watchdog_marker_is_a_helper_we_kill() -> None:
    assert _SLOT_WATCHDOG_MARKER in shut.HELPER_CMDLINE_MARKERS
    assert shut.helper_process_matches(
        r"powershell.exe -File C:\Temp\GoldClub-LivePush-Watchdog.ps1"
    )
    assert shut.helper_process_matches(r"C:\Temp\glci_winrm_inline_abc\winrm_inline.ps1")
    assert not shut.helper_process_matches("notepad.exe")
    assert not shut.helper_process_matches("ConfigScanner.exe")


def test_pids_matching_helpers_skips_this_process() -> None:
    import os

    me = os.getpid()
    rows = [
        (me, "GoldClub-LivePush-Watchdog"),
        (4242, "powershell -File GoldClub-LivePush-Watchdog.ps1"),
        (7, "explorer.exe"),
        (9, r"C:\Temp\glci_winrm_probe_x\probe.ps1"),
    ]
    assert shut.pids_matching_helpers(rows) == [4242, 9]


def test_stop_owned_helpers_terminates_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    dead: list[int] = []
    monkeypatch.setattr(shut, "_terminate_pid", lambda pid: dead.append(pid) or True)
    monkeypatch.setattr(shut, "_remove_watchdog_script", lambda: None)
    n = shut.stop_owned_helper_processes(
        rows=[(44, "GoldClub-LivePush-Watchdog"), (1, "notepad")]
    )
    assert n == 1
    assert dead == [44]


def test_discover_fleet_stops_when_shutting_down() -> None:
    shut.request_shutdown()
    seen: list[str] = []

    live = la.discover_active_lab_fleet(
        hosts=("10.0.0.1", "10.0.0.2", "10.0.0.76"),
        probe=lambda host: seen.append(host) or True,
        skip_hosts=(),
        workers=3,
    )
    assert live == []
    assert seen == []


def test_discover_fleet_still_finds_hosts_when_not_shutting_down() -> None:
    live = la.discover_active_lab_fleet(
        hosts=("10.0.0.1", "10.0.0.76", "10.0.0.90"),
        probe=lambda host: host in {"10.0.0.76", "10.0.0.90"},
        skip_hosts=(),
        workers=3,
    )
    assert live == ["10.0.0.76", "10.0.0.90"]


def test_shutdown_runtime_does_not_force_exit_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shut, "stop_owned_helper_processes", lambda **_k: 0)
    monkeypatch.setattr(shut, "drain_qt_thread_pool", lambda **_k: None)
    monkeypatch.setattr(shut, "process_still_busy", lambda: True)
    exits: list[int] = []
    monkeypatch.setattr(shut.os, "_exit", lambda code: exits.append(code))
    shut.shutdown_runtime(wait_ms=1, force_exit=None)
    assert shut.is_shutting_down()
    assert exits == []


def test_shutdown_runtime_force_exits_when_workers_stuck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shut, "stop_owned_helper_processes", lambda **_k: 0)
    monkeypatch.setattr(shut, "drain_qt_thread_pool", lambda **_k: None)
    monkeypatch.setattr(shut, "process_still_busy", lambda: True)
    exits: list[int] = []
    monkeypatch.setattr(shut.os, "_exit", lambda code: exits.append(code))
    shut.shutdown_runtime(wait_ms=1, force_exit=True)
    assert exits == [0]


def test_window_close_and_app_run_wire_shutdown() -> None:
    root = Path(__file__).resolve().parents[1]
    window = (root / "gui" / "config_scanner_window.py").read_text(encoding="utf-8")
    row = (root / "gui" / "cabinet_target_row.py").read_text(encoding="utf-8")
    assert "notify_window_closing" in window
    assert "mark_real_app_session" in window
    assert "shutdown_runtime" in window
    assert "clear_real_app_session" in window
    assert "is_shutting_down" in row


def test_notify_window_closing_only_in_real_app_session() -> None:
    shut.notify_window_closing()
    assert shut.is_shutting_down() is False
    shut.mark_real_app_session()
    shut.notify_window_closing()
    assert shut.is_shutting_down() is True
