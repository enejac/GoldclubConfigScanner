"""Green tick on cabinet dropdown rows whose host answers SMB.

Probes run only when the combo popup opens — never on panel construct or
every keystroke. The closed line-edit stays text-only; the icon is on the
list item.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QComboBox

from config_scanner.live_push import strip_cabinet_combo_label
from network.lab_access import cabinet_target_answers_smb, smb_host_from_cabinet_target


def is_network_cabinet_target(raw: str) -> bool:
    return smb_host_from_cabinet_target(strip_cabinet_combo_label(raw)) is not None


def green_tick_icon(*, size: int = 14) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(34, 158, 68))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.setPen(QPen(QColor(255, 255, 255), max(1.6, size / 8)))
    mid = size / 2
    painter.drawLine(int(size * 0.28), int(mid), int(size * 0.44), int(size * 0.70))
    painter.drawLine(int(size * 0.44), int(size * 0.70), int(size * 0.74), int(size * 0.32))
    painter.end()
    return QIcon(pix)


class CabinetPathCombo(QComboBox):
    """Editable cabinet combo that announces when the dropdown opens."""

    popup_shown = Signal()

    def showPopup(self) -> None:
        self.popup_shown.emit()
        super().showPopup()


class _SmbProbeEmitter(QObject):
    result = Signal(str, bool)
    finished = Signal()


class _SmbProbeRunnable(QRunnable):
    def __init__(self, hosts: tuple[str, ...], emitter: _SmbProbeEmitter) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._hosts = hosts
        self._emitter = emitter

    def run(self) -> None:
        try:
            from config_scanner.app_shutdown import is_shutting_down

            for host in self._hosts:
                if is_shutting_down():
                    break
                ok = bool(cabinet_target_answers_smb(host))
                self._emitter.result.emit(host, ok)
        except Exception:  # noqa: BLE001
            pass
        self._emitter.finished.emit()


class CabinetSmbTickController(QObject):
    """Attach to a cabinet combo: probe SMB hosts when the popup opens."""

    def __init__(self, combo: QComboBox, parent: QObject | None = None) -> None:
        super().__init__(parent or combo)
        self._combo = combo
        self._generation = 0
        self._icon = green_tick_icon()
        self._emitter = _SmbProbeEmitter()
        self._emitter.result.connect(self._on_probe_result)
        if hasattr(combo, "popup_shown"):
            combo.popup_shown.connect(self.refresh)

    def refresh(self) -> None:
        combo = self._combo
        hosts: list[str] = []
        seen: set[str] = set()
        for index in range(combo.count()):
            host = self._host_at(index)
            if not host:
                combo.setItemIcon(index, QIcon())
                continue
            key = host.casefold()
            if key not in seen:
                seen.add(key)
                hosts.append(host)
        self._generation += 1
        if not hosts:
            return
        QThreadPool.globalInstance().start(
            _SmbProbeRunnable(tuple(hosts), self._emitter)
        )

    def _host_at(self, index: int) -> str | None:
        data = self._combo.itemData(index)
        raw = str(data) if data is not None else self._combo.itemText(index)
        return smb_host_from_cabinet_target(strip_cabinet_combo_label(raw))

    def _on_probe_result(self, host: object, ok: object) -> None:
        key = str(host or "").strip().casefold()
        if not key:
            return
        tick = self._icon if bool(ok) else QIcon()
        for index in range(self._combo.count()):
            item_host = self._host_at(index)
            if item_host and item_host.casefold() == key:
                self._combo.setItemIcon(index, tick)
