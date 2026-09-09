"""Busy spinner widget used while Live Push Load runs."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.busy_spinner import BusySpinner  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_busy_spinner_starts_and_stops(qt_app: QApplication) -> None:
    spinner = BusySpinner(diameter=16)
    assert not spinner.active
    assert spinner.isHidden()
    spinner.set_active(True)
    assert spinner.active
    assert spinner.isVisible()
    spinner.set_active(False)
    assert not spinner.active
    assert spinner.isHidden()


def test_busy_spinner_mounts_inside_button(qt_app: QApplication) -> None:
    from PySide6.QtWidgets import QPushButton

    btn = QPushButton("Load")
    btn.resize(88, 28)
    spinner = BusySpinner(btn, diameter=16)
    spinner.mount_on(btn)
    assert spinner.parent() is btn
    assert btn.minimumWidth() >= 72
    spinner.set_active(True)
    assert btn.text() == ""
    assert not spinner.isHidden()
    assert spinner.active
    assert abs(spinner.geometry().center().x() - btn.rect().center().x()) <= 1
    assert abs(spinner.geometry().center().y() - btn.rect().center().y()) <= 1
    spinner.set_active(False)
    assert btn.text() == "Load"
    assert spinner.isHidden()


def test_live_push_load_shows_spinner_while_busy(qt_app: QApplication) -> None:
    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel()
    assert hasattr(panel, "_load_spinner")
    assert panel._load_spinner.parent() is panel._load_btn
    assert panel._load_btn.text() == "Load"
    assert not panel._load_spinner.active
    panel._set_busy(True)
    assert panel._load_spinner.active
    assert panel._load_btn.text() == ""
    assert not panel._load_btn.isEnabled()
    panel._set_busy(False)
    assert not panel._load_spinner.active
    assert panel._load_btn.isEnabled()
    assert panel._load_btn.text() == "Load"


def test_load_defers_worker_start() -> None:
    src = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "gui"
        / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "BusySpinner" in src
    assert "mount_on" in src
    assert "_start_load_worker" in src
    assert "QTimer.singleShot(0" in src
    assert "WaitCursor" in src
