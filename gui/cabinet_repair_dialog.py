"""Diagnose & repair dialog for known GoldClub cabinet faults.

Lists what ``config_scanner.cabinet_repairs`` found on the live cabinet and lets
the operator apply the fixes. Background on every fault is in
``docs/cabinet-repairs.md``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from config_scanner.cabinet_repairs import (
    STATUS_BROKEN,
    STATUS_NOT_APPLICABLE,
    STATUS_OK,
    STATUS_UNKNOWN,
    repair_by_id,
)
from config_scanner.service import ConfigScannerService
from gui.config_scanner_worker import (
    ConfigScannerEmitter,
    schedule_diagnose_cabinet,
    schedule_repair_cabinet,
)

_STATUS_TEXT = {
    STATUS_OK: "OK",
    STATUS_BROKEN: "Needs repair",
    STATUS_UNKNOWN: "Unknown",
    STATUS_NOT_APPLICABLE: "Not applicable",
}

_STATUS_COLOR = {
    STATUS_OK: "#2e7d32",
    STATUS_BROKEN: "#c62828",
    STATUS_UNKNOWN: "#ef6c00",
    STATUS_NOT_APPLICABLE: "#757575",
}

_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class CabinetRepairDialog(QDialog):
    """Check a live cabinet against known faults and fix the ones selected."""

    def __init__(
        self,
        service: ConfigScannerService,
        scan_target: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._scan_target = scan_target
        self._pool = QThreadPool.globalInstance()
        self._emitter = ConfigScannerEmitter(self)
        self._busy = False

        self.setObjectName("cabinetRepairDialog")
        self.setWindowTitle("Diagnose & repair cabinet")
        self.resize(940, 620)

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Cabinet: <b>{scan_target}</b><br>"
            "Checks the live machine against faults we have hit before. "
            "Tick what you want fixed, then Repair selected.",
            self,
        )
        header.setWordWrap(True)
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        self._tree = QTreeWidget(self)
        self._tree.setObjectName("cabinetRepairTree")
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Fault", "Status", "Detail"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setWordWrap(True)
        header_view = self._tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tree.setColumnWidth(0, 300)
        layout.addWidget(self._tree, 3)

        self._log = QPlainTextEdit(self)
        self._log.setObjectName("cabinetRepairLog")
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Progress and results appear here.")
        layout.addWidget(self._log, 2)

        buttons = QHBoxLayout()
        self._recheck_btn = QPushButton("Re-check", self)
        self._recheck_btn.clicked.connect(self._start_diagnose)
        buttons.addWidget(self._recheck_btn)
        self._repair_btn = QPushButton("Repair selected", self)
        self._repair_btn.setDefault(True)
        self._repair_btn.clicked.connect(self._start_repair)
        buttons.addWidget(self._repair_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

        self._emitter.progress.connect(self._append_log)
        self._emitter.repairs_diagnosed.connect(self._on_diagnosed)
        self._emitter.repairs_applied.connect(self._on_repaired)

        self._start_diagnose()

    # -- helpers ---------------------------------------------------------

    def _append_log(self, message: str) -> None:
        self._log.appendPlainText(message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._recheck_btn.setEnabled(not busy)
        self._repair_btn.setEnabled(not busy)
        self._tree.setEnabled(not busy)

    def _checked_ids(self) -> list[str]:
        ids: list[str] = []
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item.checkState(0) == Qt.CheckState.Checked:
                repair_id = item.data(0, _ID_ROLE)
                if repair_id:
                    ids.append(str(repair_id))
        return ids

    # -- diagnose --------------------------------------------------------

    def _start_diagnose(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._tree.clear()
        self._log.clear()
        self._append_log("Checking the cabinet …")
        schedule_diagnose_cabinet(
            self._pool, self._service, self._scan_target, self._emitter
        )

    def _on_diagnosed(self, ok: bool, findings, error: str) -> None:
        self._set_busy(False)
        if not ok or findings is None:
            self._append_log(f"Diagnose failed: {error}")
            QMessageBox.warning(self, "Diagnose failed", error or "Unknown error.")
            return

        broken = 0
        for finding in findings:
            item = QTreeWidgetItem(
                [
                    finding.title,
                    _STATUS_TEXT.get(finding.status, finding.status),
                    finding.detail,
                ]
            )
            item.setData(0, _ID_ROLE, finding.repair_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # Only pre-tick safe repairs for faults we actually found. Destructive
            # ones always need a deliberate tick.
            should_check = finding.needs_repair and not finding.destructive
            item.setCheckState(
                0,
                Qt.CheckState.Checked if should_check else Qt.CheckState.Unchecked,
            )
            colour = _STATUS_COLOR.get(finding.status)
            if colour:
                item.setForeground(1, QBrush(QColor(colour)))
            repair = repair_by_id(finding.repair_id)
            tip = finding.detail
            if repair is not None:
                tip = f"{repair.summary}\n\n{finding.detail}"
                if repair.destructive:
                    tip += "\n\nDESTRUCTIVE - clears cabinet state."
            for column in range(3):
                item.setToolTip(column, tip)
            if finding.needs_repair:
                broken += 1
            self._tree.addTopLevelItem(item)

        if broken:
            self._append_log(f"{broken} fault(s) need repair.")
        else:
            self._append_log("No known faults found on this cabinet.")

    # -- repair ----------------------------------------------------------

    def _start_repair(self) -> None:
        if self._busy:
            return
        selected = self._checked_ids()
        if not selected:
            QMessageBox.information(
                self, "Nothing selected", "Tick at least one repair to run."
            )
            return

        chosen = [(rid, repair_by_id(rid)) for rid in selected]
        prompt = "Run these repairs on the live cabinet?\n\n" + "\n".join(
            f"  - {repair.title if repair else rid}" for rid, repair in chosen
        )
        if any(repair is not None and repair.destructive for _, repair in chosen):
            prompt += (
                "\n\nWARNING: one or more of these clear cabinet state "
                "(meters / NVRAM). Make sure you have a snapshot first."
            )
        answer = QMessageBox.question(
            self,
            "Repair cabinet",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._append_log("")
        self._append_log("Applying repairs …")
        schedule_repair_cabinet(
            self._pool, self._service, self._scan_target, selected, self._emitter
        )

    def _on_repaired(self, ok: bool, outcomes, error: str) -> None:
        self._set_busy(False)
        if not ok or outcomes is None:
            self._append_log(f"Repair failed: {error}")
            QMessageBox.warning(self, "Repair failed", error or "Unknown error.")
            return

        failed = 0
        for outcome in outcomes:
            marker = "OK" if outcome.ok else "FAILED"
            self._append_log(f"[{marker}] {outcome.title}: {outcome.detail}")
            for note in outcome.notes:
                self._append_log(f"        {note}")
            if not outcome.ok:
                failed += 1

        if failed:
            QMessageBox.warning(
                self,
                "Repair finished with errors",
                f"{failed} of {len(outcomes)} repair(s) failed. See the log.",
            )
        else:
            QMessageBox.information(
                self,
                "Repair finished",
                f"{len(outcomes)} repair(s) applied. Re-checking the cabinet.",
            )
        self._start_diagnose()
