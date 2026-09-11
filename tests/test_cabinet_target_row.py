"""Snapshots and Live Push share one Cabinet row and one remembered cabinet."""

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
    ini = str(tmp_path / "shared-cabinet.ini")

    def _s() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(SettingsManager, "_s", staticmethod(_s))
    return ini


def test_shared_cabinet_target_prefers_last_used_then_this_pc(
    isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui import cabinet_target_row as row

    monkeypatch.setattr(row, "this_pc_live_target", lambda: None)
    # Nothing remembered, not a cabinet: legacy "D:" default is not a cabinet.
    assert row.shared_cabinet_target(fallback="D:") == ""
    assert row.shared_cabinet_target(fallback=r"\\10.0.0.90\c$\Goldclub") == (
        r"\\10.0.0.90\c$\Goldclub"
    )
    monkeypatch.setattr(row, "this_pc_live_target", lambda: r"C:\Goldclub")
    assert row.shared_cabinet_target(fallback="D:") == r"C:\Goldclub"
    # Last cabinet used on either screen wins over This PC.
    SettingsManager.remember_live_push_target(r"\\10.0.0.111\c$\Goldclub")
    assert row.shared_cabinet_target(fallback="D:") == r"\\10.0.0.111\c$\Goldclub"


def test_remember_shared_cabinet_target_writes_both_screens(isolated_settings: str) -> None:
    from gui.cabinet_target_row import remember_shared_cabinet_target

    recent = remember_shared_cabinet_target(r"\\10.0.0.111\c$\Goldclub")
    assert recent[0] == r"\\10.0.0.111\c$\Goldclub"
    assert SettingsManager.get_live_push_target() == r"\\10.0.0.111\c$\Goldclub"
    assert SettingsManager.get_config_scanner_game_drive() == r"\\10.0.0.111\c$\Goldclub"
    assert remember_shared_cabinet_target("") == recent


def test_row_has_live_push_controls_and_normalizes_ip(
    qt_app: QApplication, isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui import cabinet_target_row as row

    monkeypatch.setattr(row, "this_pc_live_target", lambda: None)
    widget = row.CabinetTargetRow(initial="")
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    qt_app.processEvents()

    assert widget._this_pc.text() == "This PC"
    assert widget._browse.text() == "Browse…"
    assert widget.load_button().text() == "Load"
    assert widget.load_button().objectName() == "primary"
    assert widget.combo().isEditable()
    assert widget.line_edit().placeholderText() == row.CABINET_FIELD_PLACEHOLDER

    got: list[str] = []
    widget.load_requested.connect(got.append)
    widget.set_text("10.0.0.111")
    widget.load_button().click()
    # Typed IP resolves to the UNC Goldclub root, like Live Push.
    assert got == [r"\\10.0.0.111\c$\Goldclub"]
    assert widget.text() == r"\\10.0.0.111\c$\Goldclub"

    # This PC without a local tree: no load, a status message instead.
    missing: list[str] = []
    widget.this_pc_missing.connect(missing.append)
    widget.pick_this_pc()
    assert len(got) == 1
    assert missing and "no Goldclub tree" in missing[0]
    assert widget.text() == row.THIS_PC_GOLDCLUB

    monkeypatch.setattr(row, "this_pc_live_target", lambda: r"G:\\")
    widget.pick_this_pc()
    assert got[-1] == r"G:\\"


def test_row_history_fleet_and_sync(
    qt_app: QApplication, isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui import cabinet_target_row as row

    monkeypatch.setattr(row, "this_pc_live_target", lambda: None)
    SettingsManager.remember_live_push_target(r"\\10.0.0.90\c$\Goldclub")
    widget = row.CabinetTargetRow()
    assert widget.text() == r"\\10.0.0.90\c$\Goldclub"

    widget.set_text("10.0.0.1")
    widget.apply_fleet_ips(["10.0.0.111", "10.0.0.76"])
    assert widget.text() == "10.0.0.1"
    assert widget.fleet_ips() == ["10.0.0.76", "10.0.0.111"]
    assert widget.combo().findText("10.0.0.111") >= 0

    # The other screen used .111 meanwhile: the row adopts it once.
    SettingsManager.remember_live_push_target(r"\\10.0.0.111\c$\Goldclub")
    assert widget.sync_from_settings() is True
    assert widget.text() == r"\\10.0.0.111\c$\Goldclub"
    assert widget.sync_from_settings() is False
    assert widget.combo().itemText(0) == r"\\10.0.0.111\c$\Goldclub"

    widget.remember(r"\\10.0.0.76\c$\Goldclub")
    assert SettingsManager.get_live_push_target() == r"\\10.0.0.76\c$\Goldclub"
    assert SettingsManager.get_config_scanner_game_drive() == r"\\10.0.0.76\c$\Goldclub"


def test_snapshots_tab_uses_shared_cabinet_row() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "config_scanner_tab.py"
    ).read_text(encoding="utf-8")
    assert "CabinetTargetRow(" in src
    assert "self._drive_edit = self._target_row.line_edit()" in src
    assert "shared_cabinet_target(" in src
    assert "def sync_cabinet_from_settings" in src
    assert "_remember_valid_target()" in src
    # The old bare line edit with a hardcoded .90 placeholder is gone.
    assert "10.0.0.90\\\\c$\\\\Goldclub\")" not in src
    assert "QLineEdit(SettingsManager.get_config_scanner_game_drive())" not in src


def test_live_push_panel_shares_cabinet_with_snapshots(
    qt_app: QApplication, isolated_settings: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.live_push_panel import LivePushPanel

    monkeypatch.setattr("gui.live_push_panel.this_pc_live_target", lambda: None)
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()

    panel._remember_cabinet(r"\\10.0.0.111\c$\Goldclub")
    # Live Push remembers into the key Snapshots reads too.
    assert SettingsManager.get_config_scanner_game_drive() == r"\\10.0.0.111\c$\Goldclub"

    # Snapshots used .76: reopening Live Push adopts it (after detect finished).
    SettingsManager.remember_live_push_target(r"\\10.0.0.76\c$\Goldclub")
    panel._started = True
    panel._detect_finished = True
    loads: list[str] = []
    monkeypatch.setattr(panel, "_autoload", lambda: loads.append(panel._path.text()))
    assert panel.sync_cabinet_from_settings() is True
    assert panel._path.text() == r"\\10.0.0.76\c$\Goldclub"
    assert loads == [r"\\10.0.0.76\c$\Goldclub"]
    assert panel.sync_cabinet_from_settings() is False

    shell_src = (
        Path(__file__).resolve().parents[1] / "gui" / "simple_home.py"
    ).read_text(encoding="utf-8")
    assert "sync_cabinet_from_settings()" in shell_src
