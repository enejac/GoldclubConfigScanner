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


def test_decorate_message_box_adds_button_without_touching_dialog() -> None:
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
    modality_before = box.windowModality()
    box.show()
    app.processEvents()
    size_before = box.size()
    guard.decorate_dialog(box)
    app.processEvents()
    button = box.findChild(QPushButton, OVERLAY_BUTTON_NAME)
    assert button is not None
    assert button.text() == "Screenshot"
    assert button.parent() is box, "button must live inside the dialog, not float"
    assert box.rect().contains(button.geometry())
    ok = box.button(QMessageBox.StandardButton.Ok)
    assert ok is not None
    from PySide6.QtCore import QRect

    ok_rect = QRect(ok.parentWidget().mapTo(box, ok.pos()), ok.size())
    assert not button.geometry().intersects(ok_rect)
    assert box.windowModality() == modality_before
    assert box.size() == size_before
    floating = [
        w
        for w in app.topLevelWidgets()
        if w not in (win, box) and w.findChild(QPushButton, OVERLAY_BUTTON_NAME) is not None
    ]
    assert not floating, "no floating top-level Screenshot window may be created"
    guard.shutdown()
    win.close()


def test_shown_dialog_is_decorated_after_its_own_show_pass() -> None:
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
    box.setText("Load failed")
    box.show()
    assert box.findChild(QPushButton, OVERLAY_BUTTON_NAME) is None
    for _ in range(5):
        app.processEvents()
    assert box.findChild(QPushButton, OVERLAY_BUTTON_NAME) is not None
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
    # Source-level check so it also runs where PySide6 is not installed.
    SCREENSHOT_SHORTCUT = "Ctrl+Shift+S"
    SCREENSHOT_F12 = "F12"

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
    assert f'SCREENSHOT_F12 = "{SCREENSHOT_F12}"' in hotkey
    assert f'SCREENSHOT_SHORTCUT = "{SCREENSHOT_SHORTCUT}"' in hotkey
    assert "ApplicationShortcut" in hotkey
    assert "grab_all_screens" in grab
    assert "composite_widget_grabs" in grab
    assert 'QPushButton("Screenshot"' in hotkey
    # The floating always-on-top tool window used to land mid-UI above the
    # dialog and the modality rewrite left QMessageBox bodies blank.
    assert "setWindowModality" not in hotkey
    assert "WindowStaysOnTopHint" not in hotkey
    assert "set_window_always_on_top" not in hotkey
    assert "Qt.WindowType.Tool" not in hotkey
