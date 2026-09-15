"""Qt coverage for the Live Push per-game math dialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QRadioButton  # noqa: E402

from config_scanner.game_math import format_return_percent  # noqa: E402
from config_scanner.slot_setup import MathDenomSettings  # noqa: E402
from gui.game_math_dialog import GameMathDialog  # noqa: E402
from gui.live_push_panel import LivePushPanel  # noqa: E402
from tests.test_slot_setup import _fake_goldclub  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _row(
    theme: str, bets: list[int], rtp: str, allowed: list[str]
) -> MathDenomSettings:
    return MathDenomSettings(
        theme=theme,
        bet_multipliers=list(bets),
        return_percent=rtp,
        allowed_return_percents=list(allowed),
    )


def test_dialog_toggles_rtp_and_drops_bet_step(qt_app: QApplication) -> None:
    live = [
        _row(
            "PR3_RedZone",
            [1, 2, 3, 4, 5],
            "return_92_0",
            ["return_92_0", "return_94_0"],
        )
    ]
    dialog = GameMathDialog(live_rows=live, form_rows=live, focus_theme="PR3_RedZone")
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    qt_app.processEvents()
    radios = dialog.findChildren(QRadioButton)
    assert len(radios) == 2
    target = next(
        radio
        for radio in radios
        if radio.property("rtpToken") == "return_94_0"
    )
    target.click()
    qt_app.processEvents()
    drop = next(box for box in dialog._bet_boxes if int(box.property("betStep")) == 5)
    drop.setChecked(False)
    qt_app.processEvents()
    result = dialog.result_rows()
    assert result[0].return_percent == "return_94_0"
    assert result[0].bet_multipliers == [1, 2, 3, 4]
    assert format_return_percent(result[0].return_percent) == "94.0%"


def test_dialog_bulk_set_rtp(qt_app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    live = [
        _row(
            "PR3_RedZone",
            [1, 2],
            "return_92_0",
            ["return_92_0", "return_94_0"],
        ),
        _row(
            "PR2_GoldRushDeluxe",
            [1, 2],
            "return_92_0",
            ["return_92_0", "return_94_0"],
        ),
        _row(
            "Frog",
            [1, 2],
            "return_frog_92_0",
            ["return_frog_92_0"],
        ),
    ]
    monkeypatch.setattr(
        "gui.game_math_dialog.QMessageBox.information", lambda *a, **k: None
    )
    dialog = GameMathDialog(live_rows=live, form_rows=live, focus_theme="PR3_RedZone")
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    qt_app.processEvents()
    target = next(
        radio
        for radio in dialog.findChildren(QRadioButton)
        if radio.property("rtpToken") == "return_94_0"
    )
    target.click()
    qt_app.processEvents()
    dialog._set_rtp_all()
    by_theme = {row.theme: row for row in dialog.result_rows()}
    assert by_theme["PR3_RedZone"].return_percent == "return_94_0"
    assert by_theme["PR2_GoldRushDeluxe"].return_percent == "return_94_0"
    assert by_theme["Frog"].return_percent == "return_frog_92_0"


def test_live_push_panel_loads_game_combo(qt_app: QApplication, tmp_path) -> None:
    from config_scanner.live_push import load_live_cabinet

    gold = _fake_goldclub(tmp_path)
    outcome = load_live_cabinet(str(gold))
    assert outcome.recipe is not None
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()
    assert panel._game_combo.count() >= 1
    assert panel._game_combo.currentData() == "BigSafari_HnW"
    assert panel._game_math_edit.isEnabled()
    assert "94.0%" in panel._game_math_summary.text()
    assert "background-color" in panel._game_combo.styleSheet()
    assert "background-color" not in (panel._games_math.styleSheet() or "")
    assert "border: none" in panel._game_math_summary.styleSheet()
    recipe = panel._recipe_from_form()
    assert recipe.play_limits.bet_multipliers == []
    assert recipe.math[0].theme == "BigSafari_HnW"
    assert recipe.math[0].allowed_return_percents == ["return_92_0", "return_94_0"]
