"""Reserved thin busy line — same height idle/busy, shared across the app."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.thin_progress import (  # noqa: E402
    THIN_BUSY_HEIGHT_PX,
    app_busy,
    attach_app_busy_bar,
    is_app_busy,
    make_thin_busy_progress,
    reset_app_busy_for_tests,
    set_app_busy,
    set_thin_busy_progress_active,
)


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_busy() -> None:
    reset_app_busy_for_tests()
    yield
    reset_app_busy_for_tests()


def test_idle_and_busy_keep_same_reserved_height(qt_app: QApplication) -> None:
    bar = make_thin_busy_progress()
    idle_h = bar.height()
    set_thin_busy_progress_active(bar, True)
    busy_h = bar.height()
    set_thin_busy_progress_active(bar, False)
    assert idle_h == THIN_BUSY_HEIGHT_PX
    assert busy_h == THIN_BUSY_HEIGHT_PX
    assert bar.height() == THIN_BUSY_HEIGHT_PX
    assert bar.maximum() == 1
    set_thin_busy_progress_active(bar, True)
    assert bar.maximum() == 0


def test_app_busy_refcount_nested_owners(qt_app: QApplication) -> None:
    bar = make_thin_busy_progress()
    attach_app_busy_bar(bar)
    set_app_busy(True, "load")
    set_app_busy(True, "validate")
    assert is_app_busy()
    assert bar.maximum() == 0
    set_app_busy(False, "load")
    assert is_app_busy()
    assert bar.maximum() == 0
    set_app_busy(False, "validate")
    assert not is_app_busy()
    assert bar.maximum() == 1


def test_app_busy_context_manager(qt_app: QApplication) -> None:
    bar = make_thin_busy_progress()
    attach_app_busy_bar(bar)
    with app_busy("block"):
        assert is_app_busy()
        assert bar.maximum() == 0
    assert not is_app_busy()
    assert bar.maximum() == 1


def test_snapshots_tab_drives_app_busy() -> None:
    tab = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "gui"
        / "config_scanner_tab.py"
    ).read_text(encoding="utf-8")
    assert "set_app_busy" in tab
    assert "attach_app_busy_bar" in tab
    assert 'set_app_busy(True, (id(self), "validate"))' in tab
