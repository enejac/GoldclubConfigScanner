"""Companion Updates authoring + field apply UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_scanner.b2u_pack import pack_companion_update
from config_scanner.companion_pack import (
    CompanionKind,
    apply_companion_pack,
    companion_summary_lines,
    detect_kind_from_source,
    find_keyboard_leaf,
    list_keyboard_variants,
    load_manifest,
    stage_companion_from_source,
)
from config_scanner.cs_sources import companion_share_shortcuts, share_browse_start
from config_scanner.slot_setup import goldclub_root_from_target


_KIND_LABELS = {
    CompanionKind.KEYBOARDS: "Keyboards (cabinet layouts)",
    CompanionKind.BILLS: "Bills / currency (e.g. BillsTTD)",
    CompanionKind.DALLAS: "Dallas (OneHandConfigurer)",
    CompanionKind.LICENCES: "Licences (explicit confirm)",
    CompanionKind.ONEHAND: "OneHand binary",
    CompanionKind.THEME_OVERLAY: "Theme overlay (Clovers / Tutankhamen)",
    CompanionKind.OTICKET: "Offline ticket (oticket.xml)",
    CompanionKind.SERIAL_MUX: "Serial / MUX -> G: drive (dangerous)",
}


class CompanionPackAuthorPanel(QWidget):
    """Lab: import a GameStar Updates/_B2U companion folder and export a B2U."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pack_dir: Path | None = None
        self._staging: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hint = QLabel(
            "Companion packs ship under GameStar Updates / _B2U (Bills, Keyboards, "
            "Dallas, OneHand, Clovers/Tutankhamen overlays, OffLineTicket, Licences, "
            "Serial/MUX, TrialReset). Country Selectors stay on Create. "
            "Keyboard Updates and _BILLS (JCM/MEI) are on the same lab share."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Source:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            r"\\10.0.0.249\WinSystems_SLOT\_B2U\CS-Keyboards-00"
        )
        path_row.addWidget(self._path_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        root.addLayout(path_row)

        shortcuts = QHBoxLayout()
        for label, path in companion_share_shortcuts():
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, p=str(path): self._path_edit.setText(p))
            shortcuts.addWidget(btn)
        shortcuts.addStretch(1)
        root.addLayout(shortcuts)

        form = QFormLayout()
        self._kind = QComboBox()
        for kind, label in _KIND_LABELS.items():
            self._kind.addItem(label, kind)
        self._label_edit = QLineEdit()
        form.addRow("Kind", self._kind)
        form.addRow("Label", self._label_edit)
        root.addLayout(form)

        detect_btn = QPushButton("Detect kind from source")
        detect_btn.clicked.connect(self._detect)
        import_btn = QPushButton("Import / stage")
        import_btn.setObjectName("primary")
        import_btn.clicked.connect(self._import)
        row = QHBoxLayout()
        row.addWidget(detect_btn)
        row.addWidget(import_btn)
        row.addStretch(1)
        root.addLayout(row)

        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        root.addWidget(self._summary, stretch=1)

        export_btn = QPushButton("Export companion B2U…")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export)
        root.addWidget(export_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

    def _browse(self) -> None:
        start = share_browse_start(
            self._path_edit.text().strip() or str(companion_share_shortcuts()[0][1])
        )
        path = QFileDialog.getExistingDirectory(
            self, "Select Updates / _B2U companion folder", start
        )
        if path:
            self._path_edit.setText(path)

    def _detect(self) -> None:
        raw = self._path_edit.text().strip()
        if not raw:
            return
        kind = detect_kind_from_source(Path(raw))
        idx = self._kind.findData(kind)
        if idx >= 0:
            self._kind.setCurrentIndex(idx)
        if not self._label_edit.text().strip():
            self._label_edit.setText(Path(raw).name)
        self._status.setText(f"Detected kind: {kind.value}")

    def _import(self) -> None:
        raw = self._path_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Import", "Choose a source folder.")
            return
        source = Path(raw)
        kind = self._kind.currentData()
        if not isinstance(kind, CompanionKind):
            kind = CompanionKind.ONEHAND
        out = QFileDialog.getExistingDirectory(self, "Staging folder for companion pack")
        if not out:
            return
        staging = Path(out) / "_companion_stage"
        try:
            manifest = stage_companion_from_source(
                source,
                staging,
                kind=kind,
                label=self._label_edit.text().strip() or source.name,
            )
        except (OSError, FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Import", str(exc))
            return
        self._staging = staging
        self._summary.setPlainText("\n".join(companion_summary_lines(manifest)))
        if manifest.kind == CompanionKind.KEYBOARDS:
            variants = list_keyboard_variants(staging)
            self._summary.append("\nKeyboard variants:\n" + "\n".join(f"• {v}" for v in variants))
        self._status.setText(f"Staged at {staging}")

    def _export(self) -> None:
        if self._staging is None or not (self._staging / "companion.json").is_file():
            QMessageBox.warning(self, "Export", "Import / stage a companion pack first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Output folder for companion B2U")
        if not out:
            return
        try:
            manifest = load_manifest(self._staging / "companion.json")
            safe = "".join(
                c if c.isalnum() or c in "-_" else "_"
                for c in (manifest.label or manifest.kind.value)
            )[:48]
            result = pack_companion_update(
                Path(out),
                self._staging,
                package_name=f"ConfigScanner_{safe}" or "ConfigScanner_Companion",
                encrypt=True,
            )
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        QMessageBox.information(self, "Export complete", result.note)
        self._status.setText(result.note)


class CompanionApplyPanel(QWidget):
    """Field: review companion pack and Apply (with licence / G: confirmations)."""

    def __init__(self, pack_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pack = Path(pack_dir)
        try:
            self._manifest = load_manifest(self._pack / "companion.json")
        except (OSError, ValueError) as exc:
            self._manifest = None
            self._load_error = str(exc)
        else:
            self._load_error = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Apply companion update")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        root.addWidget(self._summary, stretch=1)

        self._keyboard = QComboBox()
        kb_row = QHBoxLayout()
        kb_row.addWidget(QLabel("Keyboard variant:"))
        kb_row.addWidget(self._keyboard, stretch=1)
        root.addLayout(kb_row)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Goldclub:"))
        self._dest = QLineEdit(r"C:\Goldclub")
        dest_row.addWidget(self._dest, stretch=1)
        root.addLayout(dest_row)

        self._allow_licences = QCheckBox(
            "I confirm this licence set is for this EGM / fleet (required for licences)"
        )
        self._allow_g = QCheckBox(
            "Unlocker/G: is mounted — allow Serial/MUX write to G:\\ (dangerous)"
        )
        self._dry = QCheckBox("Dry run")
        root.addWidget(self._allow_licences)
        root.addWidget(self._allow_g)
        root.addWidget(self._dry)

        apply_btn = QPushButton("Apply companion pack")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._populate()

    def _populate(self) -> None:
        if self._manifest is None:
            self._summary.setPlainText(self._load_error or "Invalid companion pack")
            return
        lines = companion_summary_lines(self._manifest)
        self._summary.setPlainText("\n".join(lines))
        self._keyboard.clear()
        if self._manifest.kind == CompanionKind.KEYBOARDS:
            for label in list_keyboard_variants(self._pack):
                self._keyboard.addItem(label)
            self._keyboard.setEnabled(True)
        else:
            self._keyboard.setEnabled(False)
        self._allow_licences.setVisible(self._manifest.kind == CompanionKind.LICENCES)
        self._allow_g.setVisible(self._manifest.kind == CompanionKind.SERIAL_MUX)

    def _apply(self) -> None:
        if self._manifest is None:
            QMessageBox.warning(self, "Apply", "Invalid companion pack.")
            return
        if self._manifest.kind == CompanionKind.LICENCES and not self._allow_licences.isChecked():
            QMessageBox.warning(
                self, "Apply", "Confirm the licence checkbox before applying licences."
            )
            return
        if self._manifest.kind == CompanionKind.SERIAL_MUX and not self._allow_g.isChecked():
            QMessageBox.warning(
                self,
                "Apply",
                "Serial/MUX writes G:\\. Confirm Unlocker is mounted and check the box.",
            )
            return

        leaf = None
        if self._manifest.kind == CompanionKind.KEYBOARDS and self._keyboard.currentText():
            leaf = find_keyboard_leaf(self._pack, self._keyboard.currentText())

        try:
            result = apply_companion_pack(
                self._pack,
                goldclub_root=goldclub_root_from_target(
                    self._dest.text().strip() or r"C:\Goldclub"
                ),
                keyboard_leaf=leaf,
                allow_licences=self._allow_licences.isChecked(),
                allow_g_drive=self._allow_g.isChecked(),
                dry_run=self._dry.isChecked(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Apply", str(exc))
            return

        msg = (
            f"Written: {len(result.written)}\n"
            f"Skipped: {len(result.skipped)}\n"
            f"Errors: {len(result.errors)}\n"
            + "\n".join(result.notes)
            + ("\n" + "\n".join(result.errors[:8]) if result.errors else "")
        )
        self._status.setText(msg)
        if result.errors:
            QMessageBox.warning(self, "Apply finished with errors", msg)
        else:
            QMessageBox.information(self, "Apply complete", msg)
