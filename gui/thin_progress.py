"""Always-visible thin busy progress line (no show/hide layout flicker).

One reserved 3px slot — idle and busy keep the same height so the UI never
jumps. A ref-counted app bus drives every attached bar so Live Push, Snapshots,
Create, Apply, and dialogs share the same animation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from weakref import WeakSet

from PySide6.QtWidgets import (
    QApplication,
    QLayout,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Keep idle and busy at the same reserved height — Windows styles sometimes
# ignore stylesheet min/max-height on an indeterminate bar, so FixedHeight wins.
THIN_BUSY_HEIGHT_PX = 3
APP_BUSY_HOST_NAME = "csAppBusyHost"
APP_BUSY_BAR_NAME = "csAppBusyLine"

_THIN_BUSY_STYLE = f"""
QProgressBar {{
    border: none;
    background: #dde3ea;
    border-radius: 1px;
    max-height: {THIN_BUSY_HEIGHT_PX}px;
    min-height: {THIN_BUSY_HEIGHT_PX}px;
}}
QProgressBar::chunk {{
    background-color: #2f7dbf;
    border-radius: 1px;
    margin: 0px;
}}
"""

_bars: WeakSet[QProgressBar] = WeakSet()
_owners: set[object] = set()


def make_thin_busy_progress(parent: QWidget | None = None) -> QProgressBar:
    """Hairline indeterminate bar that keeps its layout slot when idle."""
    bar = QProgressBar(parent)
    bar.setObjectName(APP_BUSY_BAR_NAME)
    bar.setTextVisible(False)
    bar.setFixedHeight(THIN_BUSY_HEIGHT_PX)
    bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    bar.setStyleSheet(_THIN_BUSY_STYLE)
    set_thin_busy_progress_active(bar, False)
    return bar


def set_thin_busy_progress_active(bar: QProgressBar, active: bool) -> None:
    """Toggle indeterminate animation without resetting an already-busy bar.

    Re-applying ``setRange(0, 0)`` while busy restarts the chunk animation and
    makes the line look stuttery when callers refresh busy state frequently.
    """
    # Re-assert the reserved height every toggle — some styles grow the bar
    # when it becomes indeterminate.
    bar.setFixedHeight(THIN_BUSY_HEIGHT_PX)
    want = bool(active)
    is_busy = bar.maximum() == 0  # Qt indeterminate convention
    if want:
        if is_busy:
            return
        bar.setRange(0, 0)
        return
    # Idle: normalize to a quiescent 0..1 bar (default QProgressBar is 0..100).
    if not is_busy and bar.maximum() == 1 and bar.value() == 0:
        return
    bar.setRange(0, 1)
    bar.setValue(0)


def attach_app_busy_bar(bar: QProgressBar) -> QProgressBar:
    """Register a reserved bar so app-wide loads animate it."""
    _bars.add(bar)
    set_thin_busy_progress_active(bar, bool(_owners))
    return bar


def is_app_busy() -> bool:
    return bool(_owners)


def reset_app_busy_for_tests() -> None:
    """Drop owners between tests; attached bars stay (widgets own them)."""
    _owners.clear()
    _sync_app_busy_bars()


def set_app_busy(active: bool, owner: object) -> None:
    """Mark *owner* busy or idle. Any remaining owner keeps the line moving.

    *owner* should be a stable token such as ``(id(widget), \"load\")`` so
    nested Live Push / Snapshots / wizard work does not cancel each other.
    """
    if owner is None:
        return
    if active:
        _owners.add(owner)
    else:
        _owners.discard(owner)
    _sync_app_busy_bars()


def paint_app_busy() -> None:
    """Let the reserved line start moving before a blocking call."""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


@contextmanager
def app_busy(owner: object) -> Iterator[None]:
    """Busy the line around a blocking load; paints once before the work."""
    set_app_busy(True, owner)
    paint_app_busy()
    try:
        yield
    finally:
        set_app_busy(False, owner)


def _sync_app_busy_bars() -> None:
    active = bool(_owners)
    dead: list[QProgressBar] = []
    for bar in list(_bars):
        try:
            set_thin_busy_progress_active(bar, active)
        except RuntimeError:
            dead.append(bar)
    for bar in dead:
        _bars.discard(bar)


def insert_reserved_busy_line(layout: QLayout, *, index: int = 0) -> QProgressBar:
    """Add a reserved 3px bar to *layout* and attach it to the app bus."""
    parent = layout.parentWidget()
    bar = make_thin_busy_progress(parent)
    if isinstance(layout, QVBoxLayout):
        layout.insertWidget(index, bar)
    else:
        layout.addWidget(bar)
    return attach_app_busy_bar(bar)


def install_window_busy_line(window: QMainWindow) -> QProgressBar:
    """Wrap the central widget with a reserved top bar. Layout height is fixed.

    Safe to call once after ``setCentralWidget``. Does not hide/show the bar.
    """
    existing = window.findChild(QProgressBar, APP_BUSY_BAR_NAME)
    if existing is not None and existing.objectName() == APP_BUSY_BAR_NAME:
        host = existing.parentWidget()
        if host is not None and host.objectName() == APP_BUSY_HOST_NAME:
            return attach_app_busy_bar(existing)

    inner = window.takeCentralWidget()
    host = QWidget(window)
    host.setObjectName(APP_BUSY_HOST_NAME)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    bar = make_thin_busy_progress(host)
    lay.addWidget(bar)
    if inner is not None:
        lay.addWidget(inner, 1)
    window.setCentralWidget(host)
    return attach_app_busy_bar(bar)
