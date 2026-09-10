"""Capture Config Scanner windows (and warnings on top) to a PNG."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app_paths import app_install_dir


def screenshot_output_dir() -> Path:
    """Folder that currently holds the exe (repo root when running from source)."""
    return app_install_dir()


def screenshot_png_path(
    *,
    when: datetime | None = None,
    dest_dir: Path | None = None,
) -> Path:
    """Timestamped PNG path in *dest_dir* or next to the exe."""
    folder = Path(dest_dir) if dest_dir is not None else screenshot_output_dir()
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = folder / f"ConfigScanner-{stamp}.png"
    if path.exists():
        path = folder / f"ConfigScanner-{stamp}-{datetime.now().strftime('%f')}.png"
    return path


def pixmap_is_usable(pix: Any) -> bool:
    return (
        pix is not None
        and not pix.isNull()
        and pix.width() >= 1
        and pix.height() >= 1
    )


def visible_top_level_widgets() -> list[Any]:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return []
    app = QApplication.instance()
    if app is None:
        return []
    out: list[Any] = []
    for widget in app.topLevelWidgets():
        try:
            if widget.isVisible() and not widget.isMinimized():
                out.append(widget)
        except RuntimeError:
            continue
    return out


def _stitch_horizontal(pixmaps: list[Any]) -> Any:
    from PySide6.QtGui import QPainter, QPixmap

    width = sum(pix.width() for pix in pixmaps)
    height = max(pix.height() for pix in pixmaps)
    out = QPixmap(width, height)
    out.fill()
    painter = QPainter(out)
    x = 0
    for pix in pixmaps:
        painter.drawPixmap(x, 0, pix)
        x += pix.width()
    painter.end()
    return out


def _blit_by_geometry(parts: list[tuple[Any, Any]]) -> Any:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter, QPixmap

    union = QRect()
    for rect, _pix in parts:
        union = union.united(rect)
    if union.width() < 1 or union.height() < 1:
        return _stitch_horizontal([pix for _rect, pix in parts])
    out = QPixmap(union.size())
    out.fill()
    painter = QPainter(out)
    for rect, pix in parts:
        painter.drawPixmap(rect.topLeft() - union.topLeft(), pix)
    painter.end()
    return out


def composite_widget_grabs(widgets: list[Any] | None = None) -> Any:
    """Grab every visible top-level widget and compose them into one pixmap."""
    targets = list(widgets) if widgets is not None else visible_top_level_widgets()
    parts: list[tuple[Any, Any]] = []
    for widget in targets:
        try:
            pix = widget.grab()
        except Exception:
            continue
        if not pixmap_is_usable(pix):
            continue
        try:
            rect = widget.frameGeometry()
        except Exception:
            rect = None
        parts.append((rect, pix))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][1]
    rects = [rect for rect, _pix in parts]
    if any(rect is None for rect in rects):
        return _stitch_horizontal([pix for _rect, pix in parts])
    origin = rects[0].topLeft()
    stacked = all(rect.topLeft() == origin for rect in rects)
    degenerate = any(rect.width() < 1 or rect.height() < 1 for rect in rects)
    if stacked or degenerate:
        return _stitch_horizontal([pix for _rect, pix in parts])
    return _blit_by_geometry(parts)


def grab_all_screens() -> Any:
    """Grab every monitor. Includes modal warnings sitting above the app."""
    try:
        from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    except Exception:
        return None
    screens = list(QGuiApplication.screens() or [])
    if not screens:
        return None
    grabbed: list[tuple[Any, Any]] = []
    for screen in screens:
        try:
            pix = screen.grabWindow(0)
        except Exception:
            continue
        if not pixmap_is_usable(pix):
            continue
        grabbed.append((screen.geometry(), pix))
    if not grabbed:
        return None
    if len(grabbed) == 1:
        return grabbed[0][1]
    union = grabbed[0][0]
    for geo, _pix in grabbed[1:]:
        union = union.united(geo)
    out = QPixmap(union.size())
    out.fill()
    painter = QPainter(out)
    for geo, pix in grabbed:
        painter.drawPixmap(geo.topLeft() - union.topLeft(), pix)
    painter.end()
    return out


def grab_ui_pixmap(widget: Any | None = None) -> Any:
    """Screen grab first (warnings included), then all windows, then one widget."""
    pix = grab_all_screens()
    if pixmap_is_usable(pix):
        return pix
    widgets = visible_top_level_widgets()
    target = None
    if widget is not None and hasattr(widget, "window"):
        try:
            target = widget.window()
        except Exception:
            target = widget
    elif widget is not None:
        target = widget
    if target is not None and target not in widgets:
        try:
            if target.isVisible():
                widgets.append(target)
        except Exception:
            widgets.append(target)
    if len(widgets) > 1:
        pix = composite_widget_grabs(widgets)
        if pixmap_is_usable(pix):
            return pix
    if target is None and widgets:
        target = widgets[0]
    if target is None:
        return None
    try:
        return target.grab()
    except Exception:
        return None


def save_widget_screenshot(widget: Any | None = None, dest: Path | None = None) -> Path:
    """Write a PNG of the running UI, including warning dialogs on top.

    Prefers a screen grab so a modal ``QMessageBox`` is in the file. Falls back
    to composing visible top-level widgets, then a single-window grab.

    Raises ``OSError`` when the grab is empty or the file cannot be written.
    """
    path = Path(dest) if dest is not None else screenshot_png_path()
    pix = grab_ui_pixmap(widget)
    if not pixmap_is_usable(pix):
        raise OSError("Window grab was empty.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not pix.save(str(path), "PNG"):
        raise OSError(f"Could not write {path}")
    return path
