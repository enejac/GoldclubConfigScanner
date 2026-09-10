"""Config Scanner remembers window size/maximize and opens Live Push maximized first."""

from __future__ import annotations

from pathlib import Path

import pytest

from config_manager import (
    SHOW_MODE_FULLSCREEN,
    SHOW_MODE_MAXIMIZED,
    SHOW_MODE_NORMAL,
    SettingsManager,
    config_scanner_show_mode,
)


def test_first_launch_opens_maximized() -> None:
    assert (
        config_scanner_show_mode(has_saved=False, maximized=False, fullscreen=False)
        == SHOW_MODE_MAXIMIZED
    )


def test_saved_stretched_size_stays_normal() -> None:
    assert (
        config_scanner_show_mode(has_saved=True, maximized=False, fullscreen=False)
        == SHOW_MODE_NORMAL
    )


def test_saved_maximized_and_fullscreen() -> None:
    assert (
        config_scanner_show_mode(has_saved=True, maximized=True, fullscreen=False)
        == SHOW_MODE_MAXIMIZED
    )
    assert (
        config_scanner_show_mode(has_saved=True, maximized=True, fullscreen=True)
        == SHOW_MODE_FULLSCREEN
    )


def test_window_display_flags_with_qt_enum() -> None:
    pytest.importorskip("PySide6.QtCore")
    from PySide6.QtCore import Qt

    class _FlagWin:
        def isMaximized(self) -> bool:
            return False

        def isFullScreen(self) -> bool:
            return False

        def windowState(self):
            return Qt.WindowState.WindowMaximized

    maximized, fullscreen = SettingsManager._window_display_flags(_FlagWin())
    assert maximized is True
    assert fullscreen is False


def test_settings_bool_parses_qsettings_strings() -> None:
    assert SettingsManager._settings_bool(True) is True
    assert SettingsManager._settings_bool("true") is True
    assert SettingsManager._settings_bool("False") is False
    assert SettingsManager._settings_bool(None, True) is True
    assert SettingsManager._settings_bool(1) is True
    assert SettingsManager._settings_bool(0) is False


class _FakeRect:
    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h

    def isValid(self) -> bool:
        return self._w > 0 and self._h > 0


class _FakeWindow:
    def __init__(
        self,
        *,
        x: int = 40,
        y: int = 50,
        w: int = 1920,
        h: int = 1080,
        maximized: bool = False,
        fullscreen: bool = False,
    ) -> None:
        self._geo = _FakeRect(x, y, w, h)
        self._max = maximized
        self._fs = fullscreen
        self._state = 0
        if maximized:
            self._state |= 0x00000002  # Qt.WindowMaximized
        if fullscreen:
            self._state |= 0x00000004  # Qt.WindowFullScreen

    def saveGeometry(self):
        from PySide6.QtCore import QByteArray

        return QByteArray(b"cs-geom")

    def restoreGeometry(self, _g) -> bool:
        return False

    def geometry(self) -> _FakeRect:
        return self._geo

    def frameGeometry(self) -> _FakeRect:
        return self._geo

    def isMaximized(self) -> bool:
        return self._max

    def isFullScreen(self) -> bool:
        return self._fs

    def windowState(self) -> int:
        return self._state

    def setGeometry(self, x: int, y: int, w: int, h: int) -> None:
        self._geo = _FakeRect(x, y, w, h)

    def move(self, x: int, y: int) -> None:
        self._geo = _FakeRect(x, y, self._geo.width(), self._geo.height())

    def resize(self, w: int, h: int) -> None:
        self._geo = _FakeRect(self._geo.x(), self._geo.y(), w, h)


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings

    ini = str(tmp_path / "cs.ini")

    def _s() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(SettingsManager, "_s", staticmethod(_s))
    return ini


def test_save_restore_stretched_size(
    isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SettingsManager, "_ensure_window_on_screen", lambda _w: None)
    src = _FakeWindow(x=10, y=20, w=1840, h=1000, maximized=False)
    SettingsManager.save_config_scanner_window_geometry(src)
    dest = _FakeWindow(x=0, y=0, w=800, h=600)
    mode = SettingsManager.restore_config_scanner_window_geometry(dest)
    assert mode == SHOW_MODE_NORMAL
    assert dest.geometry().x() == 10
    assert dest.geometry().y() == 20
    assert dest.geometry().width() == 1840
    assert dest.geometry().height() == 1000


def test_save_restore_maximized_flag(isolated_settings: str) -> None:
    src = _FakeWindow(maximized=True, w=1920, h=1080)
    SettingsManager.save_config_scanner_window_geometry(src)
    dest = _FakeWindow()
    mode = SettingsManager.restore_config_scanner_window_geometry(dest)
    assert mode == SHOW_MODE_MAXIMIZED


def test_first_restore_without_saved_geometry_is_maximized(
    isolated_settings: str,
) -> None:
    dest = _FakeWindow(w=1180, h=860)
    mode = SettingsManager.restore_config_scanner_window_geometry(dest)
    assert mode == SHOW_MODE_MAXIMIZED


def test_window_defaults_to_live_push_and_maximized(isolated_settings: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(str(exc))
    QApplication.instance() or QApplication([])
    from gui.config_scanner_window import ConfigScannerWindow

    win = ConfigScannerWindow()
    assert win._cs_show_mode == SHOW_MODE_MAXIMIZED
    assert win._should_open_live_push_on_launch() is True
    win._restore_b2u = Path("pack.b2u")
    assert win._should_open_live_push_on_launch() is False


def test_simple_shell_show_push_opens_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(str(exc))
    QApplication.instance() or QApplication([])
    from gui.simple_home import SimpleShell

    shell = SimpleShell()
    monkeypatch.setattr(
        "gui.live_push_panel.LivePushPanel.ensure_started", lambda self: None
    )
    assert shell._push is None
    shell.show_push()
    assert shell._push is not None
    assert shell._stack.currentWidget() is shell._push
