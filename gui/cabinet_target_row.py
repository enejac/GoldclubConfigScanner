"""Shared "Cabinet:" target row — the Live Push UI, reused by Snapshots.

One editable combo (recent cabinets + lab cabinets that are up on SMB),
``This PC``, ``Browse…`` and a primary ``Load`` button. Local / remote
handling is the Live Push logic: a typed IP becomes a UNC Goldclub root,
``This PC`` resolves G: / C:\\Goldclub, and a successful use is remembered in
the *same* setting Live Push reads, so both screens always show the cabinet
that was last used on either of them.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from config_manager import SettingsManager
from config_scanner.live_push import (
    THIS_PC_GOLDCLUB,
    THIS_PC_MISSING_STATUS,
    format_cabinet_combo_label,
    initial_live_cabinet_target,
    merge_live_target_history,
    remember_cabinet_serial_for_target,
    resolve_live_target_from_user,
    strip_cabinet_combo_label,
    this_pc_live_target,
)

CABINET_FIELD_TOOLTIP = (
    "Goldclub root on the EGM: type a UNC share (\\\\host\\slot), an IP, "
    "or a local path (C:\\Goldclub / G:\\ when unlocked). The dropdown "
    "lists cabinets that are up on the lab network (SMB) plus recent Loads."
)
CABINET_FIELD_PLACEHOLDER = r"\\host\slot  or  C:\Goldclub"
THIS_PC_TOOLTIP = (
    "Load G: or C:\\Goldclub when this machine is a cabinet. "
    "No popup if there is no local Goldclub tree."
)
BROWSE_TOOLTIP = "Pick a local Goldclub folder."


def shared_cabinet_target(*, fallback: str = "") -> str:
    """Cabinet path both screens start from: last used anywhere, else This PC.

    *fallback* is a legacy per-screen value (e.g. the old Snapshots drive); it
    is used only when nothing was ever remembered and this PC is not a cabinet.
    """
    saved = SettingsManager.get_live_push_target()
    initial = initial_live_cabinet_target(saved=saved, local=this_pc_live_target())
    if initial:
        return initial
    text = (fallback or "").strip()
    return "" if text.upper().rstrip("\\") == "D:" else text


def remember_shared_cabinet_target(target: str, *, serial: str | None = None) -> list[str]:
    """Persist a cabinet path for *both* Live Push and Snapshots. Returns history."""
    text = strip_cabinet_combo_label(target)
    if not text:
        return SettingsManager.get_live_push_recent()
    recent = SettingsManager.remember_live_push_target(text)
    SettingsManager.set_config_scanner_game_drive(text)
    # Cheap when *serial* is known; otherwise one small SMB/local read of
    # ProductSerialNumber / mgconfig MachineID — never on every keystroke.
    remember_cabinet_serial_for_target(text, serial=serial)
    return recent


def _cabinet_item_label(path: str) -> str:
    return format_cabinet_combo_label(path, SettingsManager.get_cabinet_serial(path))


def _combo_has_path(combo: QComboBox, path: str) -> bool:
    want = strip_cabinet_combo_label(path).replace("/", "\\").rstrip("\\").casefold()
    for index in range(combo.count()):
        data = combo.itemData(index)
        raw = str(data) if data is not None else combo.itemText(index)
        key = strip_cabinet_combo_label(raw).replace("/", "\\").rstrip("\\").casefold()
        if key == want:
            return True
    return False


def is_cabinet_load_enter(event: object, *, popup_open: bool = False) -> bool:
    """True for Return/Enter in the Cabinet field when the dropdown is closed.

    An editable combo only emits ``activated`` when the operator picks a
    list item. Typing a new last octet and pressing Enter must Load too.
    """
    if popup_open:
        return False
    try:
        if event.type() != QEvent.Type.KeyPress:
            return False
        return int(event.key()) in (int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter))
    except Exception:
        return False


def combo_popup_is_open(combo: QComboBox | None) -> bool:
    if combo is None:
        return False
    view = combo.view()
    return bool(view is not None and view.isVisible())


def sort_fleet_ips(ips: list[str]) -> list[str]:
    def _key(item: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in item.split("."))
        except ValueError:
            return (999, 999, 999, 999)

    return sorted({ip.strip() for ip in ips if str(ip).strip()}, key=_key)


class _FleetScanEmitter(QObject):
    found = Signal(str)
    finished = Signal(object)


class _SerialPeekEmitter(QObject):
    done = Signal(str, str)  # host/path, serial


class _SerialPeekRunnable(QRunnable):
    """One tiny SMB/local read of ProductSerialNumber — never blocks the UI."""

    def __init__(self, target: str, emitter: _SerialPeekEmitter) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._target = (target or "").strip()
        self._emitter = emitter

    def run(self) -> None:
        try:
            from config_scanner.app_shutdown import is_shutting_down
            from config_scanner.build_version import read_machine_serial_from_target
            from network.cabinet_identity import read_cabinet_machine_name_from_state
            from network.lab_access import lab_lan_ip_from_text

            if is_shutting_down() or not self._target:
                return
            sn = read_machine_serial_from_target(self._target) or ""
            if not sn:
                ip = lab_lan_ip_from_text(self._target)
                if ip:
                    sn = read_cabinet_machine_name_from_state(ip) or ""
            sn = (sn or "").strip().upper()
            if sn:
                self._emitter.done.emit(self._target, sn)
        except Exception:  # noqa: BLE001
            return


class _FleetScanRunnable(QRunnable):
    """Probe 10.0.0.0/24 SMB so the dropdown lists cabinets that are up."""

    def __init__(self, recent: list[str] | tuple[str, ...], emitter: _FleetScanEmitter) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._recent = tuple(recent or ())
        self._emitter = emitter

    def run(self) -> None:
        try:
            from config_scanner.app_shutdown import is_shutting_down
            from network.lab_access import discover_active_lab_fleet, priority_lab_scan_ips

            if is_shutting_down():
                self._emitter.finished.emit([])
                return
            live = discover_active_lab_fleet(
                priority_hosts=priority_lab_scan_ips(self._recent),
                on_found=self._emitter.found.emit,
            )
            self._emitter.finished.emit(live)
        except Exception:  # noqa: BLE001
            self._emitter.finished.emit([])


class CabinetTargetRow(QWidget):
    """``Cabinet: [combo] [This PC] [Browse…] [Load]`` exactly as on Live Push."""

    load_requested = Signal(str)
    text_changed = Signal(str)
    editing_finished = Signal()
    this_pc_missing = Signal(str)
    fleet_finished = Signal(list)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        label: str = "Cabinet:",
        load_label: str = "Load",
        load_tooltip: str = "",
        initial: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._fleet_ips: list[str] = []
        self._fleet_scanning = False
        self._fleet_emitter = _FleetScanEmitter()
        self._fleet_emitter.found.connect(self._on_fleet_found)
        self._fleet_emitter.finished.connect(self._on_fleet_finished)
        self._serial_emitter = _SerialPeekEmitter()
        self._serial_emitter.done.connect(self._on_serial_peeked)
        self._serial_peeking: set[str] = set()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._label = QLabel(label)
        lay.addWidget(self._label)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo.setToolTip(CABINET_FIELD_TOOLTIP)
        edit = self._combo.lineEdit()
        if edit is None:
            raise RuntimeError("cabinet combo must be editable")
        self._edit: QLineEdit = edit
        self._edit.setPlaceholderText(CABINET_FIELD_PLACEHOLDER)
        self._edit.setClearButtonEnabled(True)
        self._edit.setToolTip(CABINET_FIELD_TOOLTIP)
        self._combo.setCompleter(None)
        self._edit.textChanged.connect(self.text_changed.emit)
        self._edit.editingFinished.connect(self.editing_finished.emit)
        self._edit.returnPressed.connect(self._emit_load)
        self._edit.installEventFilter(self)
        self._combo.activated.connect(lambda _i: self._emit_load())
        lay.addWidget(self._combo, stretch=1)

        self._this_pc = QPushButton("This PC")
        self._this_pc.setToolTip(THIS_PC_TOOLTIP)
        self._this_pc.clicked.connect(self.pick_this_pc)
        lay.addWidget(self._this_pc)

        self._browse = QPushButton("Browse…")
        self._browse.setToolTip(BROWSE_TOOLTIP)
        self._browse.clicked.connect(self.browse)
        lay.addWidget(self._browse)

        self._load = QPushButton(load_label)
        self._load.setObjectName("primary")
        if load_tooltip:
            self._load.setToolTip(load_tooltip)
        self._load.clicked.connect(self._emit_load)
        lay.addWidget(self._load)

        start = shared_cabinet_target() if initial is None else initial
        self.refresh_history(current=start)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._edit and is_cabinet_load_enter(
            event, popup_open=combo_popup_is_open(self._combo)
        ):
            self._emit_load()
            return True
        return super().eventFilter(watched, event)

    # -- accessors ---------------------------------------------------------
    def line_edit(self) -> QLineEdit:
        return self._edit

    def combo(self) -> QComboBox:
        return self._combo

    def load_button(self) -> QPushButton:
        return self._load

    def text(self) -> str:
        return strip_cabinet_combo_label(self._edit.text())

    def set_text(self, text: str, *, silent: bool = False) -> None:
        path = strip_cabinet_combo_label(text)
        shown = _cabinet_item_label(path) if path else ""
        if silent:
            self._combo.blockSignals(True)
            self._edit.blockSignals(True)
        try:
            self._edit.setText(shown)
        finally:
            if silent:
                self._edit.blockSignals(False)
                self._combo.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        for btn in (self._this_pc, self._browse, self._load):
            btn.setEnabled(not busy)

    # -- history / fleet ---------------------------------------------------
    def refresh_history(self, *, current: str | None = None) -> None:
        """Rebuild the dropdown from the shared recent list (newest first)."""
        recent = SettingsManager.get_live_push_recent()
        typed = self.text() if current is None else strip_cabinet_combo_label(current)
        items = merge_live_target_history(typed, recent)
        self._combo.blockSignals(True)
        try:
            self._combo.clear()
            for item in items:
                self._combo.addItem(_cabinet_item_label(item), item)
            for ip in self._fleet_ips:
                if not _combo_has_path(self._combo, ip):
                    self._combo.addItem(_cabinet_item_label(ip), ip)
            self._combo.setEditText(_cabinet_item_label(typed) if typed else "")
        finally:
            self._combo.blockSignals(False)
        for item in items:
            self._peek_serial_if_needed(item)
        for ip in self._fleet_ips:
            self._peek_serial_if_needed(ip)

    def remember(self, target: str, *, serial: str | None = None) -> None:
        text = strip_cabinet_combo_label(target)
        if not text:
            return
        remember_shared_cabinet_target(text, serial=serial)
        self.refresh_history(current=text)

    def sync_from_settings(self) -> bool:
        """Adopt the cabinet last used on the other screen. True when changed."""
        saved = SettingsManager.get_live_push_target()
        if not saved:
            return False
        if saved.casefold().rstrip("\\") == self.text().casefold().rstrip("\\"):
            return False
        self.refresh_history(current=saved)
        return True

    def start_fleet_scan(self) -> None:
        if self._fleet_scanning:
            return
        from config_scanner.app_shutdown import is_shutting_down

        if is_shutting_down():
            return
        self._fleet_scanning = True
        QThreadPool.globalInstance().start(
            _FleetScanRunnable(SettingsManager.get_live_push_recent(), self._fleet_emitter)
        )

    def _on_fleet_found(self, ip: object) -> None:
        text = str(ip or "").strip()
        if text:
            self.apply_fleet_ips([text])
            self._peek_serial_if_needed(text)

    def _on_fleet_finished(self, ips: object) -> None:
        self._fleet_scanning = False
        found = [str(i).strip() for i in ips if str(i).strip()] if isinstance(ips, (list, tuple)) else []
        self.apply_fleet_ips(found)
        for ip in found:
            self._peek_serial_if_needed(ip)
        self.fleet_finished.emit(list(self._fleet_ips))

    def apply_fleet_ips(self, ips: list[str]) -> None:
        """Add live 10.0.0.x hosts to the dropdown; keep the typed value + selection."""
        self._fleet_ips = sort_fleet_ips(self._fleet_ips + list(ips))
        typed = self._edit.text()
        sel_start = self._edit.selectionStart()
        sel_len = len(self._edit.selectedText())
        self._combo.blockSignals(True)
        try:
            for ip in self._fleet_ips:
                if not _combo_has_path(self._combo, ip):
                    self._combo.addItem(_cabinet_item_label(ip), ip)
            self._combo.setEditText(typed)
            if sel_len > 0 and sel_start >= 0:
                self._edit.setSelection(sel_start, sel_len)
        finally:
            self._combo.blockSignals(False)

    def fleet_ips(self) -> list[str]:
        return list(self._fleet_ips)

    def _peek_serial_if_needed(self, target: str) -> None:
        text = strip_cabinet_combo_label(target)
        if not text or SettingsManager.get_cabinet_serial(text):
            return
        key = text.replace("/", "\\").rstrip("\\").casefold()
        if key in self._serial_peeking:
            return
        self._serial_peeking.add(key)
        QThreadPool.globalInstance().start(_SerialPeekRunnable(text, self._serial_emitter))

    def _on_serial_peeked(self, target: object, serial: object) -> None:
        path = strip_cabinet_combo_label(str(target or ""))
        sn = str(serial or "").strip().upper()
        key = path.replace("/", "\\").rstrip("\\").casefold()
        self._serial_peeking.discard(key)
        if not path or not sn:
            return
        SettingsManager.remember_cabinet_serial(path, sn)
        typed = self.text()
        # Refresh labels without disturbing what the operator is typing.
        self._combo.blockSignals(True)
        try:
            for index in range(self._combo.count()):
                data = self._combo.itemData(index)
                raw = str(data) if data is not None else self._combo.itemText(index)
                item_path = strip_cabinet_combo_label(raw)
                if item_path.replace("/", "\\").rstrip("\\").casefold() != key:
                    continue
                self._combo.setItemText(index, _cabinet_item_label(item_path))
                self._combo.setItemData(index, item_path)
            if typed.replace("/", "\\").rstrip("\\").casefold() == key:
                self._combo.setEditText(_cabinet_item_label(path))
        finally:
            self._combo.blockSignals(False)

    # -- actions -----------------------------------------------------------
    def normalized_target(self) -> str:
        """Typed IP → UNC Goldclub root (no network probe); paths pass through.

        Always read the line edit. ``currentIndex`` stays on the last loaded
        cabinet after the operator changes only the last octet, so itemData
        would Load the old IP.
        """
        raw = self.text()
        if not raw:
            return ""
        resolved = resolve_live_target_from_user(raw, probe=False)
        if resolved and resolved != raw:
            self.set_text(resolved, silent=True)
            return resolved
        return raw

    def _emit_load(self) -> None:
        target = self.normalized_target()
        if target:
            self.load_requested.emit(target)

    def pick_this_pc(self) -> None:
        local = this_pc_live_target()
        if not local:
            self.set_text(THIS_PC_GOLDCLUB)
            self.this_pc_missing.emit(THIS_PC_MISSING_STATUS)
            return
        self.set_text(local)
        self.load_requested.emit(local)

    def browse(self) -> None:
        start = self.text() or THIS_PC_GOLDCLUB
        if start.startswith("\\\\"):
            start = THIS_PC_GOLDCLUB
        path = QFileDialog.getExistingDirectory(self, "Goldclub root", start)
        if path:
            self.set_text(path)
            self.load_requested.emit(path)
