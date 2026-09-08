"""Capture the Config Scanner window and save a PNG next to the exe."""

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


def save_widget_screenshot(widget: Any, dest: Path | None = None) -> Path:
    """Grab only *widget*'s window (not the desktop) and write a PNG.

    Raises ``OSError`` when the grab is empty or the file cannot be written.
    """
    path = Path(dest) if dest is not None else screenshot_png_path()
    win = widget.window() if hasattr(widget, "window") else widget
    pix = win.grab()
    if pix is None or pix.isNull() or pix.width() < 1 or pix.height() < 1:
        raise OSError("Window grab was empty.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not pix.save(str(path), "PNG"):
        raise OSError(f"Could not write {path}")
    return path
