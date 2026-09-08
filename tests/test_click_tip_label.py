from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QLabel, QToolTip, QWidget

from gui.click_tip_label import (
    mouse_release_shows_tip,
    prepare_form_label_for_touch,
    show_click_tip,
    tip_text_for_label,
)


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app
    QToolTip.hideText()
    app.processEvents()


def test_tip_text_falls_back_to_buddy(qt_app: QApplication) -> None:
    combo = QComboBox()
    combo.setToolTip("Denom help")
    label = QLabel("Denoms (cents)")
    label.setBuddy(combo)
    assert tip_text_for_label(label) == "Denom help"
    label.setToolTip("Copied")
    assert tip_text_for_label(label) == "Copied"


def test_show_click_tip_sets_tooltip_text(qt_app: QApplication) -> None:
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    host.show()
    show_click_tip(host, "Bet multipliers help", QPoint(40, 40))
    assert "Bet multipliers help" in (QToolTip.text() or "")
    QToolTip.hideText()
    qt_app.processEvents()
    host.close()


def test_mouse_release_on_form_label_shows_buddy_tip(qt_app: QApplication) -> None:
    form_host = QWidget()
    form = QFormLayout(form_host)
    field = QComboBox()
    field.setToolTip("Tap label for the same hover text")
    form.addRow("Denoms (cents)", field)
    lab = form.labelForField(field)
    assert isinstance(lab, QLabel)
    prepare_form_label_for_touch(lab)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(1, 1),
        QPointF(1, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert mouse_release_shows_tip(lab, ev) is True
    assert "hover text" in (QToolTip.text() or "")
    QToolTip.hideText()
    qt_app.processEvents()


def test_live_push_panel_installs_label_click_tips() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py"
    ).read_text(encoding="utf-8")
    assert "_install_label_click_tips" in src
    assert "mouse_release_shows_tip" in src
    assert "_sync_form_label_tooltip" in src
