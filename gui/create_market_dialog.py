"""Dialog to name a Live Push form snapshot as a jurisdiction market."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from config_scanner.jurisdiction import jurisdiction_id_error


class CreateMarketDialog(QDialog):
    """Collect label / id / country / notes for a new market preset."""

    def __init__(
        self,
        parent=None,
        *,
        suggested_id: str = "",
        suggested_label: str = "",
        suggested_country: str = "",
        notes: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("createMarketDialog")
        self.setWindowTitle("Create market")
        self.setModal(True)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Saves the current Live Push fields as a Market preset. "
            "Dallas, doors, and cabinet identity stay on the machine."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self._label = QLineEdit(suggested_label)
        self._label.setObjectName("createMarketLabel")
        self._id = QLineEdit(suggested_id)
        self._id.setObjectName("createMarketId")
        self._country = QLineEdit(suggested_country)
        self._country.setObjectName("createMarketCountry")
        self._notes = QLineEdit(notes)
        self._notes.setObjectName("createMarketNotes")
        form.addRow("Label", self._label)
        form.addRow("Id", self._id)
        form.addRow("Country", self._country)
        form.addRow("Notes", self._notes)
        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setObjectName("createMarketError")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._label.textChanged.connect(self._refresh_ok)
        self._id.textChanged.connect(self._refresh_ok)
        self._refresh_ok()

    def accept(self) -> None:
        self._refresh_ok()
        if not self._ok.isEnabled():
            return
        super().accept()

    def _refresh_ok(self) -> None:
        label = self._label.text().strip()
        err = jurisdiction_id_error(self._id.text())
        if not label:
            err = err or "Label is required."
        self._error.setText(err or "")
        self._ok.setEnabled(err is None)

    def values(self) -> tuple[str, str, str, str]:
        """Return (id, label, country, notes)."""
        return (
            self._id.text().strip(),
            self._label.text().strip(),
            self._country.text().strip(),
            self._notes.text().strip(),
        )
