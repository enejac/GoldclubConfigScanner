"""LivePushPanel consumes worker-side load results; no SMB reads on the GUI thread."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_slot_setup import _fake_goldclub


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _empty_live_push_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "gui.live_push_panel.SettingsManager.get_live_push_target", lambda: ""
    )


def _panel(qt_app: QApplication):
    from PySide6.QtCore import Qt

    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    return panel


def test_partial_result_paints_form_but_stays_busy(qt_app: QApplication, tmp_path: Path) -> None:
    from config_scanner.live_push import LiveLoadOutcome, load_live_cabinet

    gold = _fake_goldclub(tmp_path)
    full = load_live_cabinet(str(gold))
    assert full.recipe is not None

    panel = _panel(qt_app)
    panel._set_busy(True)
    early = LiveLoadOutcome(
        full.root,
        full.recipe,
        "",
        full.status,
        has_magic_wheel_gamepack=full.has_magic_wheel_gamepack,
        partial=True,
    )
    panel._on_load_partial(early)
    qt_app.processEvents()

    assert panel._busy is True
    assert panel._loaded is full.recipe
    assert panel._goldclub == full.root
    assert "checking" in panel._status.text().casefold()

    panel._on_load_finished(full)
    qt_app.processEvents()
    assert panel._busy is False
    assert panel._status.text() == full.status


def test_partial_result_ignored_when_not_busy(qt_app: QApplication, tmp_path: Path) -> None:
    from config_scanner.live_push import LiveLoadOutcome, load_live_cabinet

    gold = _fake_goldclub(tmp_path)
    full = load_live_cabinet(str(gold))
    panel = _panel(qt_app)
    assert panel._busy is False
    panel._on_load_partial(
        LiveLoadOutcome(
            full.root,
            full.recipe,
            "",
            full.status,
            has_magic_wheel_gamepack=full.has_magic_wheel_gamepack,
            partial=True,
        )
    )
    assert panel._loaded is None


def test_finished_uses_worker_results_not_gui_thread_reads(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from gui import live_push_panel

    gold = _fake_goldclub(tmp_path)
    full = load_live_cabinet(str(gold))
    assert full.recipe is not None
    full.onehand_markets = frozenset({"Colombia", "TrinidadTobago"})
    full.ticket_printer_active = True

    def _no_smb(*_a, **_k):
        raise AssertionError("GUI thread must not re-read the cabinet")

    monkeypatch.setattr(live_push_panel, "markets_accepted_by_onehand", _no_smb)
    monkeypatch.setattr(live_push_panel, "read_ticket_printer_active", _no_smb)

    panel = _panel(qt_app)
    panel._set_busy(True)
    panel._on_load_finished(full)
    qt_app.processEvents()

    assert panel._onehand_markets == full.onehand_markets
    assert panel._ticket_printer_status.text().startswith("Active")
