"""Last-used Live Push cabinet path persists across launches."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config_manager import SettingsManager  # noqa: E402


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ini = str(tmp_path / "live-push.ini")

    def _s() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(SettingsManager, "_s", staticmethod(_s))
    return ini


def test_remember_live_push_target_round_trip(isolated_settings: str) -> None:
    assert SettingsManager.get_live_push_target() == ""
    assert SettingsManager.get_live_push_recent() == []

    first = SettingsManager.remember_live_push_target(r"\\10.0.0.90\c$\Goldclub")
    assert first == [r"\\10.0.0.90\c$\Goldclub"]
    second = SettingsManager.remember_live_push_target(r"C:\Goldclub")
    assert second == [r"C:\Goldclub", r"\\10.0.0.90\c$\Goldclub"]
    assert SettingsManager.get_live_push_target() == r"C:\Goldclub"
    assert SettingsManager.get_live_push_recent() == second

    SettingsManager.remember_live_push_target(r"//10.0.0.90/c$/Goldclub")
    assert SettingsManager.get_live_push_recent()[0] == r"//10.0.0.90/c$/Goldclub"
    assert r"\\10.0.0.90\c$\Goldclub" not in SettingsManager.get_live_push_recent()


def test_panel_restores_saved_cabinet_and_skips_this_pc(
    qt_app: QApplication, isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.live_push_panel import LivePushPanel

    monkeypatch.setattr(
        "gui.live_push_panel.this_pc_live_target", lambda: r"C:\Goldclub"
    )
    SettingsManager.remember_live_push_target(r"\\10.0.0.98\c$\Goldclub")

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    assert panel._path.text() == r"\\10.0.0.98\c$\Goldclub"
    assert panel._cabinet.findText(r"\\10.0.0.98\c$\Goldclub") >= 0


def test_successful_remember_refills_combo(
    qt_app: QApplication, isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.live_push_panel import LivePushPanel

    monkeypatch.setattr("gui.live_push_panel.this_pc_live_target", lambda: None)
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    assert panel._path.text() == ""

    panel._remember_cabinet(r"\\host\slot")
    assert SettingsManager.get_live_push_target() == r"\\host\slot"
    assert panel._path.text() == r"\\host\slot"
    assert panel._cabinet.itemText(0) == r"\\host\slot"

    again = LivePushPanel(autoload=False)
    assert again._path.text() == r"\\host\slot"
