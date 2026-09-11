"""Screenshot stays available while a warning dialog is open."""

from __future__ import annotations

from pathlib import Path

import pytest


def _destroy(app, *widgets) -> None:
    """Delete test windows now instead of leaving them to Python's cyclic GC.

    A guard holds ``_win`` while the window owns the guard, so the pair only
    dies when the GC happens to run - which crashed unrelated Qt tests
    mid-layout once this module grew. Deleting the C++ side here leaves only
    harmless Python shells behind."""
    import shiboken6

    for widget in widgets:
        try:
            widget.hide()
        except RuntimeError:
            continue
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)
    for _ in range(3):
        app.processEvents()


def _import_qt():
    pytest.importorskip("PySide6")
    try:
        from PySide6.QtCore import QEvent, QPoint, Qt
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
    return (
        QEvent,
        QPoint,
        Qt,
        QKeyEvent,
        QApplication,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
    )


def _hide_leftover_windows(app) -> None:
    """QMessageBox is app-modal by default; a box left open by an earlier test
    would block clicks in later ones, so start from a clean window list."""
    for widget in list(app.topLevelWidgets()):
        try:
            if widget.isVisible():
                widget.hide()
        except RuntimeError:
            continue
    for _ in range(3):
        app.processEvents()


def test_is_screenshot_key_matches_global_shortcuts() -> None:
    QEvent, _QPoint, Qt, QKeyEvent, *_rest = _import_qt()
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
    _QEvent, _QPoint, Qt, _QKeyEvent, QApplication, QLabel, _QMainWindow, QMessageBox, _QPush = (
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


def test_corner_tool_sits_on_main_bottom_right_not_dialog() -> None:
    _QEvent, QPoint, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, _QPush = (
        _import_qt()
    )
    from gui.screenshot_hotkey import corner_tool_screen_pos
    app = QApplication.instance() or QApplication([])
    win = QMainWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    # Keep the frame inside the (possibly 800x600 offscreen) screen so the
    # position is the plain bottom-right, not the on-screen clamp.
    avail = app.primaryScreen().availableGeometry()
    win.setGeometry(
        avail.left() + 40, avail.top() + 40, avail.width() - 120, avail.height() - 120
    )
    win.show()
    app.processEvents()
    pos = corner_tool_screen_pos(win, 90, 28, margin=8)
    frame = win.frameGeometry()
    assert pos.x() == frame.right() - 90 - 8
    assert pos.y() == frame.bottom() - 28 - 8
    # Must not use a dialog's top-right (that was the mid-UI SAS hover).
    box = QMessageBox(win)
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.setGeometry(220, 200, 360, 160)
    box.show()
    app.processEvents()
    dialog_top_right = QPoint(box.frameGeometry().right() - 90, box.frameGeometry().top() - 32)
    assert pos != dialog_top_right
    _destroy(app, box, win)


def test_modal_does_not_inject_screenshot_into_message_box() -> None:
    _QEvent, _QPoint, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, QPushButton = (
        _import_qt()
    )
    from gui.screenshot_hotkey import TOOL_BUTTON_NAME, AnytimeScreenshot

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
    for _ in range(5):
        app.processEvents()
    assert box.findChild(QPushButton, TOOL_BUTTON_NAME) is None
    assert guard._tool.isVisible()
    box.hide()
    guard.shutdown()
    _destroy(app, guard._tool, win)


def test_hotkey_captures_while_warning_is_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _QEvent, _QPoint, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, QPushButton = (
        _import_qt()
    )
    from gui.screenshot_hotkey import TOOL_BUTTON_NAME, AnytimeScreenshot

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
    for _ in range(5):
        app.processEvents()
    button = guard._tool.findChild(QPushButton, TOOL_BUTTON_NAME)
    assert button is not None
    button.click()
    app.processEvents()
    assert statuses
    assert "from-hotkey.png" in statuses[-1]
    box.hide()
    guard.shutdown()
    _destroy(app, guard._tool, win)


def test_corner_button_takes_real_click_while_app_modal_error_is_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: 'Apply finished with errors' (app-modal QMessageBox.warning)
    blocked mouse input to the overlay, so its Screenshot button did nothing.
    Drive the click through the window handle (the path Qt's modal block guards)."""
    _QEvent, _QPoint, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, QPushButton = (
        _import_qt()
    )
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest

    from gui.screenshot_hotkey import TOOL_BUTTON_NAME, AnytimeScreenshot

    app = QApplication.instance() or QApplication([])
    _hide_leftover_windows(app)
    saved = tmp_path / "from-modal-click.png"
    monkeypatch.setattr(
        "gui.screenshot_hotkey.save_widget_screenshot",
        lambda _widget=None: saved,
    )
    win = QMainWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(800, 600)
    statuses: list[str] = []
    win.show_status = statuses.append  # type: ignore[method-assign]
    win.show()
    guard = AnytimeScreenshot(win)
    box = QMessageBox(win)
    box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    box.setText("Wrote 0 file(s). ServerNotTrusted")
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    seen: dict[str, object] = {}

    def click_overlay() -> None:
        for _ in range(5):
            app.processEvents()
        seen["modality"] = box.windowModality()
        seen["tool_visible"] = guard._tool.isVisible()
        handle = guard._tool.windowHandle()
        seen["transient_parent"] = handle.transientParent() if handle else None
        button = guard._tool.findChild(QPushButton, TOOL_BUTTON_NAME)
        QTest.mouseClick(
            handle,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            button.geometry().center(),
        )
        for _ in range(5):
            app.processEvents()
        box.accept()

    QTimer.singleShot(50, click_overlay)
    box.exec()  # QMessageBox.warning() uses exec -> ApplicationModal
    app.processEvents()

    assert seen["modality"] == Qt.WindowModality.ApplicationModal
    assert seen["tool_visible"] is True
    assert seen["transient_parent"] is not None
    assert statuses, "overlay click was swallowed by the modal block"
    assert "from-modal-click.png" in statuses[-1]
    # Popup closed: overlay released and no longer tied to the dead dialog.
    assert not guard._tool.isVisible()
    assert guard._tool.windowHandle().transientParent() is None
    guard.shutdown()
    _destroy(app, guard._tool, win)


def test_overlay_follows_topmost_of_stacked_modals() -> None:
    _QEvent, _QPoint, Qt, _QKeyEvent, QApplication, _QLabel, QMainWindow, QMessageBox, _QPush = (
        _import_qt()
    )
    from gui.screenshot_hotkey import AnytimeScreenshot

    app = QApplication.instance() or QApplication([])
    _hide_leftover_windows(app)
    win = QMainWindow()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    guard = AnytimeScreenshot(win)
    first = QMessageBox(win)
    first.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    first.setModal(True)
    first.show()
    second = QMessageBox(win)
    second.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    second.setModal(True)
    second.show()
    for _ in range(5):
        app.processEvents()
    handle = guard._tool.windowHandle()
    assert handle.transientParent() == second.windowHandle()
    second.hide()
    for _ in range(5):
        app.processEvents()
    assert handle.transientParent() == first.windowHandle()
    first.hide()
    for _ in range(5):
        app.processEvents()
    assert handle.transientParent() is None
    guard.shutdown()
    _destroy(app, guard._tool, win)


def test_window_and_hotkey_module_wire_anytime_capture() -> None:
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
    assert "corner_tool_screen_pos" in hotkey
    assert "pin_to_main_bottom_right" in hotkey
    assert "decorate_dialog" not in hotkey
    assert "overlay_button_rect" not in hotkey
    assert "setWindowModality" not in hotkey
