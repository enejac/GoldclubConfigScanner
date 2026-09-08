"""Country Selector import (lab) + field wizard UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_scanner.b2u_pack import pack_country_update
from config_scanner.cs_catalog import (
    CountryLeaf,
    apply_country_leaf,
    discover_leaves,
    filter_leaves,
    load_install_json,
    resolve_country_selector_tool,
    stage_country_pack,
    substitutions_from_machine_number,
)
from config_scanner.slot_setup import goldclub_root_from_target


class CountryPackAuthorPanel(QWidget):
    """Lab: import a CS folder and export a country-wizard B2U."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool: Path | None = None
        self._leaves: list[CountryLeaf] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("CS source:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            r"\\10.0.0.249\WinSystems_SLOT\_B2U\CS-Gamestar-TRI-01"
        )
        path_row.addWidget(self._path_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        load_btn = QPushButton("Import")
        load_btn.setObjectName("primary")
        load_btn.clicked.connect(self._import)
        path_row.addWidget(load_btn)
        root.addLayout(path_row)

        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText(
            "Import an unpacked Country Selector package to list overlay leaves."
        )
        root.addWidget(self._summary, stretch=1)

        export_btn = QPushButton("Export country-wizard B2U…")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export)
        root.addWidget(export_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select CS package or CountrySelectorTool")
        if path:
            self._path_edit.setText(path)

    def _import(self) -> None:
        raw = self._path_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Import", "Choose a CS package folder first.")
            return
        try:
            tool = resolve_country_selector_tool(Path(raw))
            leaves = discover_leaves(tool)
        except (OSError, FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Import", str(exc))
            return
        self._tool = tool
        self._leaves = leaves
        lines = [
            f"Tool: {tool}",
            f"Leaves: {len(leaves)}",
            "",
        ]
        for leaf in leaves[:40]:
            note = f" — {leaf.readme}" if leaf.readme else ""
            lines.append(f"• {leaf.label}{note}")
        if len(leaves) > 40:
            lines.append(f"… and {len(leaves) - 40} more")
        self._summary.setPlainText("\n".join(lines))
        self._status.setText(f"Imported {len(leaves)} leaf(ves)")

    def _export(self) -> None:
        if self._tool is None or not self._leaves:
            QMessageBox.warning(self, "Export", "Import a CS package first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Output folder for country B2U")
        if not out:
            return
        name = self._tool.parent.name
        if name.casefold() in {"tmp", "content"}:
            name = self._tool.parents[2].name if len(self._tool.parents) >= 3 else "Country"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:48]
        package_name = f"ConfigScanner_Country_{safe}" or "ConfigScanner_Country"
        try:
            staged_parent = Path(out) / "_stage_country"
            staged = stage_country_pack(
                self._tool, staged_parent, package_label="staged"
            )
            result = pack_country_update(
                Path(out),
                staged,
                package_name=package_name,
                encrypt=True,
            )
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        QMessageBox.information(self, "Export complete", result.note)
        self._status.setText(result.note)


class CountryWizardPanel(QWidget):
    """Field: pick country / screens / mode, enter machine #, Apply."""

    def __init__(self, country_pack: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pack = Path(country_pack)
        self._leaves: list[CountryLeaf] = []
        self._current: CountryLeaf | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Country Selector")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        form_box = QGroupBox("Overlay")
        form = QFormLayout(form_box)
        self._country = QComboBox()
        self._screens = QComboBox()
        self._mode = QComboBox()
        self._country.currentTextChanged.connect(self._on_axis_changed)
        self._screens.currentTextChanged.connect(self._on_axis_changed)
        self._mode.currentTextChanged.connect(self._on_axis_changed)
        form.addRow("Country / RTP:", self._country)
        form.addRow("Screens:", self._screens)
        form.addRow("Ticket / SAS:", self._mode)
        root.addWidget(form_box)

        self._readme = QTextEdit()
        self._readme.setReadOnly(True)
        self._readme.setMaximumHeight(120)
        root.addWidget(self._readme)

        machine_row = QHBoxLayout()
        machine_row.addWidget(QLabel("Machine number:"))
        self._machine = QLineEdit()
        self._machine.setPlaceholderText("e.g. 20664  (replaces !!MachineName!!)")
        machine_row.addWidget(self._machine, stretch=1)
        root.addLayout(machine_row)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Write to:"))
        self._dest = QLineEdit(r"C:\Goldclub")
        dest_row.addWidget(self._dest, stretch=1)
        root.addLayout(dest_row)

        self._dry = QCheckBox("Dry run (list actions only)")
        root.addWidget(self._dry)

        apply_btn = QPushButton("Apply country overlay")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        root.addStretch(1)

        self._load_catalog()

    def _load_catalog(self) -> None:
        try:
            tool = resolve_country_selector_tool(self._pack)
            self._leaves = discover_leaves(tool)
        except (OSError, FileNotFoundError, ValueError) as exc:
            self._status.setText(str(exc))
            return
        countries = sorted({leaf.country for leaf in self._leaves if leaf.country})
        self._country.blockSignals(True)
        self._country.clear()
        self._country.addItems(countries)
        self._country.blockSignals(False)
        self._on_axis_changed()

    def _on_axis_changed(self) -> None:
        country = self._country.currentText()
        by_country = filter_leaves(self._leaves, country=country or None)
        screens = sorted({leaf.screens for leaf in by_country if leaf.screens})
        self._screens.blockSignals(True)
        prev_s = self._screens.currentText()
        self._screens.clear()
        self._screens.addItems(screens)
        if prev_s in screens:
            self._screens.setCurrentText(prev_s)
        self._screens.blockSignals(False)

        screens_val = self._screens.currentText()
        by_screens = filter_leaves(
            by_country, country=country or None, screens=screens_val or None
        )
        modes = sorted({leaf.mode for leaf in by_screens if leaf.mode})
        self._mode.blockSignals(True)
        prev_m = self._mode.currentText()
        self._mode.clear()
        self._mode.addItems(modes)
        if prev_m in modes:
            self._mode.setCurrentText(prev_m)
        self._mode.blockSignals(False)

        matched = filter_leaves(
            self._leaves,
            country=self._country.currentText() or None,
            screens=self._screens.currentText() or None,
            mode=self._mode.currentText() or None,
        )
        self._current = matched[0] if matched else None
        if self._current is None:
            self._readme.setPlainText("No matching overlay leaf.")
            return
        text = self._current.readme or "(no Readme)"
        text += f"\n\nLeaf: {self._current.path}"
        self._readme.setPlainText(text)

    def _apply(self) -> None:
        if self._current is None:
            QMessageBox.warning(self, "Apply", "Select a valid country / screens / mode.")
            return
        machine = self._machine.text().strip()
        if not machine:
            QMessageBox.warning(self, "Apply", "Enter the machine number.")
            return
        dest = goldclub_root_from_target(self._dest.text().strip() or r"C:\Goldclub")
        if not self._dry.isChecked() and not dest.is_dir():
            QMessageBox.warning(self, "Apply", f"Destination not found:\n{dest}")
            return
        try:
            recipe = load_install_json(self._current.path / "install.json")
            subs = substitutions_from_machine_number(recipe, machine)
            result = apply_country_leaf(
                self._current,
                dest,
                substitutions=subs,
                dry_run=self._dry.isChecked(),
            )
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Apply", str(exc))
            return

        lines = [
            f"Deleted: {len(result.deleted)}",
            f"Copied: {len(result.copied)}",
            f"Substituted: {len(result.substituted)}",
            f"Skipped: {len(result.skipped)}",
            f"Errors: {len(result.errors)}",
        ]
        if result.errors:
            lines.append("")
            lines.extend(result.errors[:12])
        msg = "\n".join(lines)
        self._status.setText(msg)
        if result.errors:
            QMessageBox.warning(self, "Apply finished with errors", msg)
        else:
            QMessageBox.information(self, "Apply complete", msg)
