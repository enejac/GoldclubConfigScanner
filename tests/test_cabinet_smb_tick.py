"""Green SMB ticks appear only after the cabinet dropdown opens."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, QThreadPool, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config_manager import SettingsManager  # noqa: E402


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ini = str(tmp_path / "smb-tick.ini")

    def _s() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(SettingsManager, "_s", staticmethod(_s))
    return ini


def test_is_network_cabinet_target() -> None:
    from gui.cabinet_smb_tick import is_network_cabinet_target

    assert is_network_cabinet_target(r"\\10.0.0.76\c$\Goldclub")
    assert is_network_cabinet_target("10.0.0.28")
    assert not is_network_cabinet_target(r"C:\Goldclub")
    assert not is_network_cabinet_target("G:")


def test_ticks_only_after_popup(
    qt_app: QApplication,
    isolated_settings: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gui import cabinet_target_row as row
    from gui import cabinet_smb_tick as ticks

    probed: list[str] = []

    def fake(target: str, *, timeout_sec: float = 0.25) -> bool:
        probed.append(target)
        return target == "10.0.0.76"

    monkeypatch.setattr(ticks, "cabinet_target_answers_smb", fake)
    monkeypatch.setattr(row, "this_pc_live_target", lambda: None)
    monkeypatch.setattr(
        row.CabinetTargetRow, "_peek_serial_if_needed", lambda self, _t: None
    )
    SettingsManager.remember_live_push_target(r"\\10.0.0.76\c$\Goldclub")
    widget = row.CabinetTargetRow()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    qt_app.processEvents()
    widget.apply_fleet_ips(["10.0.0.28"])
    assert probed == []
    for index in range(widget.combo().count()):
        assert widget.combo().itemIcon(index).isNull()

    widget.combo().showPopup()
    QThreadPool.globalInstance().waitForDone(3000)
    qt_app.processEvents()
    assert "10.0.0.76" in probed
    assert "10.0.0.28" in probed
    by_host = {}
    for index in range(widget.combo().count()):
        data = str(widget.combo().itemData(index) or "")
        by_host[data] = not widget.combo().itemIcon(index).isNull()
    assert by_host.get(r"\\10.0.0.76\c$\Goldclub") is True
    assert by_host.get("10.0.0.28") is False
    widget.combo().hidePopup()


def test_live_push_combo_probes_on_popup_only(
    qt_app: QApplication,
    isolated_settings: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gui import cabinet_smb_tick as ticks
    from gui.live_push_panel import LivePushPanel

    probed: list[str] = []
    monkeypatch.setattr(
        ticks, "cabinet_target_answers_smb", lambda t, **_k: probed.append(t) or True
    )
    monkeypatch.setattr("gui.live_push_panel.this_pc_live_target", lambda: None)
    monkeypatch.setattr("gui.live_push_panel.detect_local_live_cabinet", lambda: "")
    monkeypatch.setattr("gui.live_push_panel.LivePushPanel._load", lambda self: None)
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._apply_fleet_ips(["10.0.0.90"])
    assert probed == []
    panel._cabinet.showPopup()
    QThreadPool.globalInstance().waitForDone(3000)
    qt_app.processEvents()
    assert "10.0.0.90" in probed
    idx = panel._cabinet.findData("10.0.0.90")
    assert idx >= 0
    assert not panel._cabinet.itemIcon(idx).isNull()
    panel._cabinet.hidePopup()
