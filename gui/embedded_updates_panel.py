"""Picker for built-in GameStar country updates bundled in Config Scanner."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config_scanner.embedded_updates import (
    EmbeddedUpdate,
    export_b2u_copy,
    load_catalog,
    materialize_country_tool,
)


class OfficialUpdateCombo(QWidget):
    """Compact dropdown of built-in country updates + Apply / Copy actions."""

    apply_requested = Signal(object)  # EmbeddedUpdate
    copy_b2u_requested = Signal(object)  # EmbeddedUpdate

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        show_copy_b2u: bool = False,
        apply_label: str = "Apply",
    ) -> None:
        super().__init__(parent)
        self._entries = load_catalog()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._combo = QComboBox()
        self._combo.setMinimumContentsLength(36)
        if not self._entries:
            self._combo.addItem("(no built-in updates in this build)", None)
            self._combo.setEnabled(False)
        else:
            self._combo.addItem("(select official update)", None)
            for entry in self._entries:
                bits = [entry.label]
                if entry.gamestar_version:
                    bits.append(entry.gamestar_version)
                tip = entry.readme or entry.id
                if entry.b2u_path:
                    tip += f"\n.b2u: {entry.b2u_file}"
                if entry.staged_tool_path:
                    tip += "\n(pre-staged for offline restore)"
                idx = self._combo.count()
                self._combo.addItem(" — ".join(bits), entry.id)
                self._combo.setItemData(idx, tip, 3)  # Qt.ToolTipRole
        root.addWidget(self._combo, stretch=1)

        apply_btn = QPushButton(apply_label)
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._on_apply)
        root.addWidget(apply_btn)

        if show_copy_b2u:
            copy_btn = QPushButton("Copy .b2u…")
            copy_btn.clicked.connect(self._on_copy)
            root.addWidget(copy_btn)

    def selected(self) -> EmbeddedUpdate | None:
        update_id = self._combo.currentData()
        if not update_id:
            return None
        for entry in self._entries:
            if entry.id == update_id:
                return entry
        return None

    def _on_apply(self) -> None:
        entry = self.selected()
        if entry is None:
            QMessageBox.information(self, "Built-in", "Select an official update.")
            return
        self.apply_requested.emit(entry)

    def _on_copy(self) -> None:
        entry = self.selected()
        if entry is None:
            QMessageBox.information(self, "Built-in", "Select an official update.")
            return
        if entry.b2u_path is None:
            QMessageBox.warning(
                self,
                "Copy .b2u",
                f"{entry.label} has no bundled .b2u (staged overlay only).\n"
                "Export a client update from Create instead.",
            )
            return
        self.copy_b2u_requested.emit(entry)


class EmbeddedUpdatesPicker(QGroupBox):
    """List built-in updates; emit selection for restore or create flows.

    Prefer OfficialUpdateCombo for new UI. Kept for Advanced / legacy callers.
    """

    restore_requested = Signal(object)  # EmbeddedUpdate
    create_requested = Signal(object)  # EmbeddedUpdate
    export_b2u_requested = Signal(object)  # EmbeddedUpdate

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        mode: str = "restore",
    ) -> None:
        super().__init__("Built-in country updates (offline)", parent)
        self._mode = mode
        self._entries = load_catalog()

        root = QVBoxLayout(self)
        if not self._entries:
            root.addWidget(
                QLabel("No embedded updates in this build (run scripts/sync_embedded_updates.py).")
            )
            return

        self._list = QListWidget()
        for entry in self._entries:
            bits = [entry.label]
            if entry.gamestar_version:
                bits.append(entry.gamestar_version)
            item = QListWidgetItem(" — ".join(bits))
            item.setData(256, entry.id)
            tip = entry.readme or entry.id
            if entry.b2u_path:
                tip += f"\n.b2u: {entry.b2u_file}"
            if entry.staged_tool_path:
                tip += "\n(pre-staged for offline restore)"
            item.setToolTip(tip)
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(self._on_restore)
        root.addWidget(self._list)

        row = QHBoxLayout()
        if mode == "restore":
            btn = QPushButton("Restore selected")
            btn.setObjectName("primary")
            btn.clicked.connect(self._on_restore)
            row.addWidget(btn)
        else:
            load_btn = QPushButton("Load for export")
            load_btn.setObjectName("primary")
            load_btn.clicked.connect(self._on_create)
            row.addWidget(load_btn)
            export_btn = QPushButton("Copy .b2u to USB…")
            export_btn.clicked.connect(self._on_export_b2u)
            row.addWidget(export_btn)
        row.addStretch(1)
        root.addLayout(row)

    def _selected(self) -> EmbeddedUpdate | None:
        item = self._list.currentItem()
        if item is None:
            return None
        update_id = item.data(256)
        for entry in self._entries:
            if entry.id == update_id:
                return entry
        return None

    def _on_restore(self) -> None:
        entry = self._selected()
        if entry is None:
            QMessageBox.information(self, "Built-in", "Select an update from the list.")
            return
        self.restore_requested.emit(entry)

    def _on_create(self) -> None:
        entry = self._selected()
        if entry is None:
            QMessageBox.information(self, "Built-in", "Select an update from the list.")
            return
        self.create_requested.emit(entry)

    def _on_export_b2u(self) -> None:
        entry = self._selected()
        if entry is None:
            QMessageBox.information(self, "Built-in", "Select an update from the list.")
            return
        if entry.b2u_path is None:
            QMessageBox.warning(
                self,
                "Export",
                f"{entry.label} has no bundled .b2u (staged overlay only).\n"
                "Use Load for export → Export update for client.",
            )
            return
        self.export_b2u_requested.emit(entry)


def materialize_entry(entry: EmbeddedUpdate) -> Path:
    """Resolve embedded update to CountrySelectorTool (may decrypt cached .b2u)."""
    return materialize_country_tool(entry)


def copy_entry_b2u(entry: EmbeddedUpdate, dest_dir: Path) -> Path:
    return export_b2u_copy(entry, dest_dir)
