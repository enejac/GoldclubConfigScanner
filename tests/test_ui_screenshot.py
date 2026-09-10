"""Window-only screenshot saved next to the exe (no hardcoded paths)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from config_scanner.ui_screenshot import (
    composite_widget_grabs,
    pixmap_is_usable,
    save_widget_screenshot,
    screenshot_output_dir,
    screenshot_png_path,
)


def test_screenshot_output_dir_follows_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "portable"
    install.mkdir()
    monkeypatch.setattr("config_scanner.ui_screenshot.app_install_dir", lambda: install)
    assert screenshot_output_dir() == install


def test_screenshot_png_path_uses_dest_dir_not_cwd(tmp_path: Path) -> None:
    dest = tmp_path / "beside-exe"
    dest.mkdir()
    when = datetime(2026, 9, 4, 15, 16, 17)
    path = screenshot_png_path(when=when, dest_dir=dest)
    assert path.parent == dest
    assert path.name == "ConfigScanner-20260904-151617.png"
    assert path.suffix == ".png"


def test_screenshot_png_path_avoids_overwrite(tmp_path: Path) -> None:
    when = datetime(2026, 9, 4, 15, 16, 17)
    first = screenshot_png_path(when=when, dest_dir=tmp_path)
    first.write_bytes(b"x")
    second = screenshot_png_path(when=when, dest_dir=tmp_path)
    assert second != first
    assert second.parent == tmp_path
    assert second.suffix == ".png"


def test_save_widget_screenshot_writes_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    monkeypatch.setattr("config_scanner.ui_screenshot.grab_all_screens", lambda: None)
    app = QApplication.instance() or QApplication([])
    widget = QLabel("ui")
    widget.resize(160, 80)
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    app.processEvents()
    dest = tmp_path / "ConfigScanner-test.png"
    saved = save_widget_screenshot(widget, dest)
    assert saved == dest
    assert dest.is_file()
    assert dest.stat().st_size > 0
    assert dest.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_composite_widget_grabs_includes_second_window() -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    main = QLabel("main")
    warn = QLabel("warning")
    for widget, width in ((main, 120), (warn, 80)):
        widget.resize(width, 40)
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        widget.show()
    app.processEvents()
    pix = composite_widget_grabs([main, warn])
    assert pixmap_is_usable(pix)
    assert pix.width() >= 120 + 80
    assert pix.height() >= 40


def test_window_wires_screenshot_control() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "gui" / "config_scanner_window.py"
    ).read_text(encoding="utf-8")
    assert "save_widget_screenshot" in src
    assert 'QPushButton("Screenshot")' in src
    assert "Ctrl+Shift+S" in src
    assert "ApplicationShortcut" in src
    assert "install_anytime_screenshot" in src
    assert "F12" in src
