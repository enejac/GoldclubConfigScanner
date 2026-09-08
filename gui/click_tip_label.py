"""Show field help on tap — hover tooltips do not appear on EGM touchscreens."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QToolTip, QWidget

_TIP_MS = 20_000


def tip_text_for_label(label: QLabel) -> str:
    """Tooltip on the label, or on its form-row buddy (the combo / spin)."""
    text = (label.toolTip() or "").strip()
    if text:
        return text
    buddy = label.buddy()
    if buddy is not None:
        return (buddy.toolTip() or "").strip()
    return ""


def show_click_tip(widget: QWidget, text: str, global_pos: QPoint | None = None) -> None:
    """Sticky tooltip at *global_pos* (touch has no hover)."""
    body = (text or "").strip()
    if not body:
        return
    if global_pos is None:
        global_pos = widget.mapToGlobal(widget.rect().center())
    QToolTip.showText(global_pos, body, widget, widget.rect(), _TIP_MS)


def prepare_form_label_for_touch(label: QLabel) -> None:
    """Make a QFormLayout caption look and act tappable."""
    label.setCursor(Qt.CursorShape.PointingHandCursor)
    label.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)


def mouse_release_shows_tip(watched: QWidget, event: QEvent) -> bool:
    """True when *event* is a left-button release that should show field help."""
    if not isinstance(watched, QLabel):
        return False
    if event.type() != QEvent.Type.MouseButtonRelease:
        return False
    if not isinstance(event, QMouseEvent):
        return False
    if event.button() != Qt.MouseButton.LeftButton:
        return False
    text = tip_text_for_label(watched)
    if not text:
        return False
    show_click_tip(watched, text, event.globalPosition().toPoint())
    return True
