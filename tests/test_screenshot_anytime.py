"""Screenshot stays available while a warning dialog is open."""

from __future__ import annotations

from pathlib import Path

import pytest


def _import_qt():
    pytest.importorskip("PySide6")
    try:
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import (
            QApplication,
            QLabel,
            QMainWindow,
            QMessageBox,
            QPushButton,
        )
    except ImportError as exc:
        pytest.skip(f"PySide6 Qt plugins unavailable: {exc}")
    return QEvent, Qt, QKeyEvent, QApplication, QLabel, QMainWindow, QMessageBox, QPushButton


def test_is_screenshot_key_matches_global_shortcuts() -> None:
    QEvent, Qt, QKeyEvent, *_rest = _import_qt()
    from gui.screenshot_hotkey import is_screenshot_key

    f12 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier)
    chord = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    plain_s = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier
    )
    assert is_screenshot_key(f12)
    assert is_screenshot_key(chord)
    assert not is_screenshot_key(plain_s)


def test_message_box_is_screenshot_target() -> None:
    _QEvent, Qt, _QKeyEvent, QApplication, QLabel, _QMainWindow, QMessageBox, _QPushButton = (
        _import_qt()
    )
    from gui.screenshot_hotkey import is_screenshot_target_dialog

    app = QApplication.instance() or QApplication([])
    box = QMessageBox()
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.setText("warn")
    assert is_screenshot_target_dialog(box)
    label = QLabel("not a dialog")
    assert not is_screenshot_target_dialog(label)
    app.processEvents()


def test_decorate_message_box_adds_button_and_window_modal() -> None:
    _QEvent, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, QPushButton = (
        _import_qt()
    )
    from gui.screenshot_hotkey import OVERLAY_BUTTON_NAME, AnytimeScreenshot

    app = QApplication.instance() or QApplication([])
    win = QMainWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    guard = AnytimeScreenshot(win)
    box = QMessageBox(win)
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.setText("Cabinet warning")
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.show()
    app.processEvents()
    guard.decorate_dialog(box)
    button = box.findChild(QPushButton, OVERLAY_BUTTON_NAME)
    assert button is not None
    assert button.text() == "Screenshot"
    assert box.windowModality() == Qt.WindowModality.WindowModal
    guard.shutdown()
    win.close()


def test_hotkey_captures_while_warning_is_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _QEvent, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, QPushButton = (
        _import_qt()
    )
    from gui.screenshot_hotkey import OVERLAY_BUTTON_NAME, AnytimeScreenshot

    app = QApplication.instance() or QApplication([])
    saved = tmp_path / "from-hotkey.png"
    monkeypatch.setattr(
        "gui.screenshot_hotkey.save_widget_screenshot",
        lambda _widget=None: saved,
    )
    win = QMainWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    statuses: list[str] = []
    win.show_status = statuses.append  # type: ignore[method-assign]
    win.show()
    guard = AnytimeScreenshot(win)
    box = QMessageBox(win)
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.setText("crash?")
    box.show()
    app.processEvents()
    guard.decorate_dialog(box)
    button = box.findChild(QPushButton, OVERLAY_BUTTON_NAME)
    assert button is not None
    button.click()
    app.processEvents()
    assert statuses
    assert "from-hotkey.png" in statuses[-1]
    guard.shutdown()
    win.close()


def test_window_and_hotkey_module_wire_anytime_capture() -> None:
    from gui.screenshot_hotkey import SCREENSHOT_F12, SCREENSHOT_SHORTCUT

    window = (
        Path(__file__).resolve().parents[1] / "gui" / "config_scanner_window.py"
    ).read_text(encoding="utf-8")
    hotkey = (
        Path(__file__).resolve().parents[1] / "gui" / "screenshot_hotkey.py"
    ).read_text(encoding="utf-8")
    grab = (
        Path(__file__).resolve().parents[1]
        / "config_scanner"
        / "ui_screenshot.py"
    ).read_text(encoding="utf-8")
    assert "install_anytime_screenshot" in window
    assert "ApplicationShortcut" in window
    assert SCREENSHOT_SHORTCUT in window
    assert SCREENSHOT_F12 in hotkey
    assert "ApplicationShortcut" in hotkey
    assert "WindowModal" in hotkey
    assert "grab_all_screens" in grab
    assert "composite_widget_grabs" in grab
    assert 'QPushButton("Screenshot"' in hotkey
