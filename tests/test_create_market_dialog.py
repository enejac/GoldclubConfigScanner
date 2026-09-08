"""Create-market dialog validation."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.create_market_dialog import CreateMarketDialog  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_create_market_dialog_requires_label_and_valid_id(qt_app: QApplication) -> None:
    from PySide6.QtCore import Qt

    dialog = CreateMarketDialog(
        suggested_id="colombia_cop",
        suggested_label="Colombia (COP)",
        suggested_country="Colombia",
    )
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    qt_app.processEvents()
    assert dialog._ok.isEnabled()
    pid, label, country, _notes = dialog.values()
    assert pid == "colombia_cop"
    assert label == "Colombia (COP)"
    assert country == "Colombia"

    dialog._label.setText("  ")
    qt_app.processEvents()
    assert not dialog._ok.isEnabled()

    dialog._label.setText("Colombia (COP)")
    dialog._id.setText("Colombia COP")
    qt_app.processEvents()
    assert not dialog._ok.isEnabled()
    assert "lowercase" in dialog._error.text().casefold()

    dialog._id.setText("lab_cop")
    qt_app.processEvents()
    assert dialog._ok.isEnabled()
    assert dialog._error.text() == ""
