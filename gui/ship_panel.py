"""Ship / packaging helpers UI (Tool B2U export)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_scanner.b2u_pack import pack_tool_update


class ShipPanel(QWidget):
    """Export the full Config Scanner as a Tool B2U for lab/cabinet use."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Ship packages")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(
            "Tool B2U — opens Snapshots directly (Create full snapshot, Restore). "
            "Also: EGM setup, Companion packs via dev launch without --snapshots.\n"
            "  Ship beside GameStar tooling / lab USB.\n\n"
            "Country Selector .b2u — export from home → Create client update; ship under "
            "GameStar …\\Country Selectors.\n\n"
            "EGM setup packs — from EGM setup → Export EGM update; sparse recipe apply.\n\n"
            "Companion packs — from Companion packs tab; ship under GameStar …\\Updates "
            "(Bills, Keyboards, Dallas, OneHand, Licences, Serial/MUX).\n\n"
            "Requires ConfigScanner.exe (run .\\build_exe.ps1). Optional encrypt uses "
            "BiOS2_PackageGenerator.exe when installed."
        )
        root.addWidget(notes, stretch=1)

        export_btn = QPushButton("Export Tool B2U…")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export_tool_b2u)
        root.addWidget(export_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

    def _export_tool_b2u(self) -> None:
        out = QFileDialog.getExistingDirectory(
            self, "Output folder for ConfigScanner_Tool B2U"
        )
        if not out:
            return
        try:
            result = pack_tool_update(
                Path(out),
                package_name="ConfigScanner_Tool",
                encrypt=True,
            )
        except (OSError, FileNotFoundError, RuntimeError) as exc:
            QMessageBox.warning(self, "Export Tool B2U", str(exc))
            return
        QMessageBox.information(self, "Export complete", result.note)
        self._status.setText(result.note)
