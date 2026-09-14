"""LivePushPanel Language combo is built from the loaded cabinet, per EGM."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_cabinet_languages import _goldclub


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _empty_live_push_memory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "gui.live_push_panel.SettingsManager.get_live_push_target", lambda: ""
    )


def _panel(qt_app: QApplication):
    from PySide6.QtCore import Qt

    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    return panel


def _items(combo) -> list[tuple[str, str]]:
    return [(combo.itemText(i), str(combo.itemData(i))) for i in range(combo.count())]


def test_language_shows_pack_initial_and_installed_choices(qt_app, tmp_path: Path) -> None:
    from config_scanner.live_push import load_live_cabinet
    from gui.live_push_panel import _combo_code

    root = _goldclub(tmp_path, files=("en", "es", "nl"))
    outcome = load_live_cabinet(str(root))
    assert outcome.recipe is not None

    panel = _panel(qt_app)
    panel._set_busy(True)
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    # Field is no longer blank: initial pack language selected.
    assert _combo_code(panel._language) == "Spanish"
    names = [data for _label, data in _items(panel._language)]
    assert names == ["English", "Spanish", "Dutch"]
    labels = [label for label, _data in _items(panel._language)]
    assert labels[1].startswith("Spanish — es") and "(in pack)" in labels[1]
    assert "(in pack)" not in labels[2]  # Dutch installed but not in the pack


def test_language_choices_follow_the_loaded_cabinet(qt_app, tmp_path: Path) -> None:
    """Loading a second EGM with a different slot\\languages rebuilds the list."""
    from config_scanner.live_push import load_live_cabinet

    first = load_live_cabinet(str(_goldclub(tmp_path / "a", files=("en", "es"))))
    second = load_live_cabinet(str(_goldclub(tmp_path / "b", files=("en", "pl", "fr"))))

    panel = _panel(qt_app)
    panel._set_busy(True)
    panel._on_load_finished(first)
    assert [d for _l, d in _items(panel._language)] == ["English", "Spanish"]

    panel._set_busy(True)
    panel._on_load_finished(second)
    assert [d for _l, d in _items(panel._language)] == ["English", "French", "Polish"]


def test_language_falls_back_to_catalog_without_cabinet(qt_app) -> None:
    from config_scanner.live_push import LANGUAGE_CHOICES

    panel = _panel(qt_app)
    assert [d for _l, d in _items(panel._language)] == list(LANGUAGE_CHOICES)


def test_uninstalled_language_blocks_apply(qt_app, tmp_path: Path) -> None:
    from config_scanner.live_push import load_live_cabinet

    root = _goldclub(tmp_path, files=("en", "es"))
    outcome = load_live_cabinet(str(root))
    panel = _panel(qt_app)
    panel._path.setText(str(root))
    panel._set_busy(True)
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    panel._language.setEditText("Portuguese")
    after = panel._recipe_from_form()
    assert after.mg_identity.language == "Portuguese"
    errors = panel._validation_errors(panel._loaded, after)
    assert any("Portuguese" in e and "not installed" in e for e in errors)
