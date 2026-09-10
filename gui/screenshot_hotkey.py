"""Screenshot that still works while a warning dialog is open."""

from __future__ import annotations

import sys
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
    QWidget,
)

from config_scanner.ui_screenshot import save_widget_screenshot

SCREENSHOT_SHORTCUT = "Ctrl+Shift+S"
SCREENSHOT_F12 = "F12"
OVERLAY_BUTTON_NAME = "csAnytimeScreenshot"
OVERLAY_MARGIN = 8

_WIN_HOTKEY_CTRL_SHIFT_S = 0x4353
_WIN_HOTKEY_F12 = 0x4354
_WM_HOTKEY = 0x0312
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_NOREPEAT = 0x4000
_VK_F12 = 0x7B


def is_screenshot_key(event: Any) -> bool:
    """True for Ctrl+Shift+S or F12 (no other modifiers on F12)."""
    try:
        key = event.key()
        mods = event.modifiers()
    except Exception:
        return False
    if key == Qt.Key.Key_F12:
        return not (mods & (Qt.KeyboardModifier.ControlModifier
                            | Qt.KeyboardModifier.AltModifier
                            | Qt.KeyboardModifier.MetaModifier))
    if key != Qt.Key.Key_S:
        return False
    return bool(
        (mods & Qt.KeyboardModifier.ControlModifier)
        and (mods & Qt.KeyboardModifier.ShiftModifier)
    )


def is_screenshot_target_dialog(obj: Any) -> bool:
    if obj is None:
        return False
    if isinstance(obj, QMessageBox):
        return True
    if isinstance(obj, QDialog) and obj.isModal():
        return True
    return False


def overlay_button_rect(dialog: QWidget, button: QPushButton) -> QRect:
    """Bottom-left corner of *dialog*; top-right if the dialog's own buttons sit there.

    A ``QMessageBox`` keeps its icon and text at the top and right-aligns its
    OK/Cancel row at the bottom, so bottom-left is the one corner that stays
    empty. The button is a child of the dialog, so it is never blocked by the
    dialog's modality and never floats over the main window.
    """
    button.adjustSize()
    size = button.size()
    bottom_left = QRect(
        OVERLAY_MARGIN,
        max(OVERLAY_MARGIN, dialog.height() - size.height() - OVERLAY_MARGIN),
        size.width(),
        size.height(),
    )
    for box in dialog.findChildren(QDialogButtonBox):
        if not box.isVisible():
            continue
        for own in box.buttons():
            own_rect = QRect(box.mapTo(dialog, own.pos()), own.size())
            if own.isVisible() and own_rect.intersects(bottom_left):
                return QRect(
                    max(OVERLAY_MARGIN, dialog.width() - size.width() - OVERLAY_MARGIN),
                    OVERLAY_MARGIN,
                    size.width(),
                    size.height(),
                )
    return bottom_left


def place_overlay_button(dialog: QWidget, button: QPushButton) -> None:
    button.setGeometry(overlay_button_rect(dialog, button))
    button.raise_()


class _OverlayPlacer(QObject):
    def __init__(self, dialog: QWidget, button: QPushButton) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._button = button

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # getattr: shiboken may hand us a bare re-created wrapper (no __dict__)
        # once the Python side has been collected but the C++ filter lives on.
        dialog = getattr(self, "_dialog", None)
        button = getattr(self, "_button", None)
        if dialog is None or button is None:
            return False
        if obj is dialog and event.type() == QEvent.Type.Resize:
            place_overlay_button(dialog, button)
        return False


class AnytimeScreenshot(QObject):
    """App-wide screenshot: F12 / Ctrl+Shift+S plus a button inside each warning."""

    def __init__(self, main_window: QWidget) -> None:
        super().__init__(main_window)
        self._win = main_window
        self._busy = False
        self._win_hotkeys: Any = None
        self._placers: list[_OverlayPlacer] = []

        for seq in (SCREENSHOT_SHORTCUT, SCREENSHOT_F12):
            shortcut = QShortcut(QKeySequence(seq), main_window)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.capture)
            shortcut.setObjectName(f"csAnytimeShortcut_{seq}")

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        main_window.installEventFilter(self)
        self._win_hotkeys = _install_win_hotkeys(self.capture)

    def shutdown(self) -> None:
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        try:
            self._win.removeEventFilter(self)
        except Exception:
            pass
        _uninstall_win_hotkeys(self._win_hotkeys)
        self._win_hotkeys = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        win = getattr(self, "_win", None)
        if win is None:
            return False
        et = event.type()
        if obj is win and et == QEvent.Type.Close:
            self.shutdown()
            return False
        if et == QEvent.Type.KeyPress and is_screenshot_key(event):
            if not getattr(event, "isAutoRepeat", lambda: False)():
                self.capture()
            return True
        if et == QEvent.Type.Show and is_screenshot_target_dialog(obj):
            # QMessageBox fixes its size inside its own showEvent; decorating
            # after that pass keeps its text/icon/buttons laid out untouched.
            QTimer.singleShot(0, lambda dialog=obj: self._decorate_if_alive(dialog))
        return False

    def _decorate_if_alive(self, dialog: QWidget) -> None:
        try:
            from shiboken6 import isValid
        except Exception:  # pragma: no cover - shiboken ships with PySide6
            isValid = None  # type: ignore[assignment]
        if isValid is not None and not isValid(dialog):
            return
        try:
            if not dialog.isVisible():
                return
        except RuntimeError:
            return
        self.decorate_dialog(dialog)

    def decorate_dialog(self, dialog: QWidget) -> None:
        if dialog.property("_cs_ss_ready"):
            return
        dialog.setProperty("_cs_ss_ready", True)
        button = QPushButton("Screenshot", dialog)
        button.setObjectName(OVERLAY_BUTTON_NAME)
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(
            "Save a PNG of the app and this warning (also F12 / Ctrl+Shift+S)."
        )
        button.clicked.connect(self.capture)
        place_overlay_button(dialog, button)
        button.show()
        placer = _OverlayPlacer(dialog, button)
        dialog.installEventFilter(placer)
        placers = getattr(self, "_placers", None)
        if placers is not None:
            placers.append(placer)
            dialog.destroyed.connect(
                lambda _obj=None, p=placer: p in placers and placers.remove(p)
            )

    def capture(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self._capture_once()
        finally:
            QTimer.singleShot(300, self._clear_busy)

    def _clear_busy(self) -> None:
        self._busy = False

    def _capture_once(self) -> None:
        show_status = getattr(self._win, "show_status", None)
        try:
            path = save_widget_screenshot(self._win)
        except OSError as exc:
            if callable(show_status):
                show_status(f"Screenshot failed: {exc}")
            return
        if callable(show_status):
            show_status(f"Saved {path.name} next to the exe")


def install_anytime_screenshot(main_window: QWidget) -> AnytimeScreenshot:
    return AnytimeScreenshot(main_window)


class _WinHotkeyFilter:
    """ctypes filter kept alive for RegisterHotKey WM_HOTKEY messages."""

    def __init__(self, callback: Callable[[], None], native: Any) -> None:
        self.callback = callback
        self.native = native
        self.registered: list[int] = []


def _install_win_hotkeys(callback: Callable[[], None]) -> _WinHotkeyFilter | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        from PySide6.QtCore import QAbstractNativeEventFilter
    except Exception:
        return None

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt_x", wintypes.LONG),
            ("pt_y", wintypes.LONG),
        ]

    class Native(QAbstractNativeEventFilter):
        def __init__(self, on_hotkey: Callable[[], None]) -> None:
            super().__init__()
            self._on_hotkey = on_hotkey

        def nativeEventFilter(self, eventType, message):  # noqa: N802
            try:
                et = eventType.data() if hasattr(eventType, "data") else eventType
                if isinstance(et, (bytes, bytearray)):
                    et = et.decode("ascii", "replace")
                else:
                    et = str(et)
                if "windows" not in et.lower():
                    return False
                msg = MSG.from_address(int(message))
                if msg.message != _WM_HOTKEY:
                    return False
                if int(msg.wParam) in (_WIN_HOTKEY_CTRL_SHIFT_S, _WIN_HOTKEY_F12):
                    QTimer.singleShot(0, self._on_hotkey)
                    return True
            except Exception:
                return False
            return False

    native = Native(callback)
    app = QApplication.instance()
    if app is None:
        return None
    app.installNativeEventFilter(native)
    holder = _WinHotkeyFilter(callback, native)
    user32 = ctypes.windll.user32
    specs = (
        (_WIN_HOTKEY_CTRL_SHIFT_S, _MOD_CONTROL | _MOD_SHIFT | _MOD_NOREPEAT, ord("S")),
        (_WIN_HOTKEY_F12, _MOD_NOREPEAT, _VK_F12),
    )
    for hot_id, modifiers, vk in specs:
        try:
            if user32.RegisterHotKey(None, hot_id, modifiers, vk):
                holder.registered.append(hot_id)
        except Exception:
            continue
    return holder


def _uninstall_win_hotkeys(holder: _WinHotkeyFilter | None) -> None:
    if holder is None or sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        for hot_id in list(holder.registered):
            try:
                user32.UnregisterHotKey(None, hot_id)
            except Exception:
                pass
        holder.registered.clear()
    except Exception:
        pass
    app = QApplication.instance()
    if app is not None and holder.native is not None:
        try:
            app.removeNativeEventFilter(holder.native)
        except Exception:
            pass
