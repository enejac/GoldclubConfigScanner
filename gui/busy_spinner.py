"""Windows-style circular busy spinner for button / toolbar wait states."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget


class BusySpinner(QWidget):
    """Indeterminate ring spinner (fading arcs), similar to the Windows wait glyph."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        diameter: int = 18,
        line_width: float = 2.4,
        color: QColor | None = None,
    ) -> None:
        super().__init__(parent)
        self._diameter = max(12, int(diameter))
        self._line_width = float(line_width)
        self._color = QColor(color) if color is not None else QColor(255, 255, 255)
        self._angle = 0
        self._host: QWidget | None = None
        self._host_label = ""
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        side = self._diameter + 4
        self.setFixedSize(side, side)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def mount_on(self, host: QWidget) -> None:
        """Parent and center on *host* so layout size never changes."""
        self._host = host
        self.setParent(host)
        host.installEventFilter(self)
        if isinstance(host, QAbstractButton):
            # Keep the button width stable when the label is cleared for the spin.
            host.setMinimumWidth(max(host.minimumWidth(), host.sizeHint().width(), 72))
        self._center_on_host()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self._center_on_host()
        return super().eventFilter(obj, event)

    def _center_on_host(self) -> None:
        host = self._host
        if host is None:
            return
        self.move(
            (host.width() - self.width()) // 2,
            (host.height() - self.height()) // 2,
        )
        self.raise_()

    def set_active(self, active: bool) -> None:
        want = bool(active)
        host = self._host
        if want == self._timer.isActive():
            if want:
                self.show()
                self._center_on_host()
            else:
                self.hide()
            return
        if want:
            self._angle = 0
            if isinstance(host, QAbstractButton):
                self._host_label = host.text()
                host.setText("")
            self.show()
            self._center_on_host()
            self._timer.start()
            self.update()
            return
        self._timer.stop()
        self.hide()
        if isinstance(host, QAbstractButton) and self._host_label:
            host.setText(self._host_label)
            self._host_label = ""
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._timer.isActive():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        pad = self._line_width
        rect = QRectF(pad, pad, side - 2 * pad, side - 2 * pad)
        pen = QPen()
        pen.setWidthF(self._line_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        base = self._color
        for i in range(8):
            alpha = 40 + int(215 * (i / 7.0))
            pen.setColor(QColor(base.red(), base.green(), base.blue(), alpha))
            painter.setPen(pen)
            start = -self._angle - i * 45
            painter.drawArc(rect, int(start * 16), int(36 * 16))
        painter.end()
