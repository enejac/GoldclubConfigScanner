"""The live-push settings board must pack groups into columns on wide windows."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QGroupBox, QTableWidget  # noqa: E402

from gui.live_push_panel import (  # noqa: E402
    MAX_COLUMNS,
    MIN_COLUMN_WIDTH,
    _ColumnBoard,
    _group_form,
)

# Market / denoms first, peripherals next, licence last (add_box order).
PANEL_GROUPS = (
    ("Currency / market", 5),
    ("Denoms / bets", 2),
    ("Magic wheel", 5),
    ("Jackpots", 4),
    ("Game UI", 4),
    ("SAS / cashless", 10),
    ("Door switches", 10),
    ("Bill & ticket hardware", 8),
    ("Ticketing", 3),
    ("Limit setup", 8),
    ("Cabinet hardware", 3),
    ("Licence", 3),
)


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _board(qt_app: QApplication) -> _ColumnBoard:
    board = _ColumnBoard()
    for title, weight in PANEL_GROUPS:
        box, _form = _group_form(title)
        board.add_box(box, weight)
    # Qt defers resize events on a hidden widget, so the board would never
    # reflow. WA_DontShowOnScreen keeps the real event path without a window.
    board.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    board.show()
    qt_app.processEvents()
    return board


def _resize(board: _ColumnBoard, qt_app: QApplication, width: int) -> None:
    board.resize(width, 900)
    qt_app.processEvents()


def _columns_used(board: _ColumnBoard) -> set[int]:
    return {col for _row, col in _placements(board).values()}


def _placements(board: _ColumnBoard) -> dict[str, tuple[int, int]]:
    return board.group_placements()


def _column_weights(board: _ColumnBoard) -> dict[int, int]:
    weights = dict(PANEL_GROUPS)
    totals: dict[int, int] = {}
    for title, (_row, col) in _placements(board).items():
        totals[col] = totals.get(col, 0) + weights[title]
    return totals


def test_narrow_window_uses_a_single_column(qt_app: QApplication) -> None:
    board = _board(qt_app)
    _resize(board, qt_app, MIN_COLUMN_WIDTH + 40)

    assert len(_placements(board)) == len(PANEL_GROUPS)
    assert _columns_used(board) == {0}


def test_wide_window_fills_every_column(qt_app: QApplication) -> None:
    board = _board(qt_app)
    _resize(board, qt_app, MAX_COLUMNS * MIN_COLUMN_WIDTH + 400)

    assert len(_placements(board)) == len(PANEL_GROUPS)
    assert _columns_used(board) == set(range(MAX_COLUMNS))


def test_medium_window_uses_two_columns(qt_app: QApplication) -> None:
    board = _board(qt_app)
    _resize(board, qt_app, 2 * MIN_COLUMN_WIDTH + 60)

    assert _columns_used(board) == {0, 1}


def test_columns_are_balanced_by_row_count(qt_app: QApplication) -> None:
    board = _board(qt_app)
    _resize(board, qt_app, MAX_COLUMNS * MIN_COLUMN_WIDTH + 400)

    totals = _column_weights(board)
    # Greedy shortest-column packing; no column should tower over another.
    assert max(totals.values()) - min(totals.values()) <= 5


def test_no_group_is_lost_or_duplicated_across_resizes(qt_app: QApplication) -> None:
    board = _board(qt_app)
    for width in (1600, 400, 900, 1600, 380, 1200):
        _resize(board, qt_app, width)
        placements = _placements(board)
        assert sorted(placements) == sorted(title for title, _w in PANEL_GROUPS)
        # One widget per column cell.
        assert len(set(placements.values())) == len(placements)


def test_wide_window_fills_each_column_with_several_groups(
    qt_app: QApplication,
) -> None:
    """Independent stacks + bill weight must not leave a nearly empty column."""
    from collections import Counter

    board = _board(qt_app)
    _resize(board, qt_app, MAX_COLUMNS * MIN_COLUMN_WIDTH + 400)
    counts = Counter(col for _row, col in _placements(board).values())
    assert set(counts) == set(range(MAX_COLUMNS))
    assert min(counts.values()) >= 3


def test_groups_in_the_same_column_do_not_overlap(qt_app: QApplication) -> None:
    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.resize(1280, 520)
    panel.show()
    qt_app.processEvents()

    by_parent: dict[int, list[QGroupBox]] = {}
    for box in panel.findChildren(QGroupBox):
        if box.title() not in {t for t, _w in PANEL_GROUPS}:
            continue
        by_parent.setdefault(id(box.parentWidget()), []).append(box)
    assert by_parent
    for boxes in by_parent.values():
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                inter = a.geometry().intersected(b.geometry())
                assert inter.isEmpty(), (
                    f"{a.title()} overlaps {b.title()} at {inter!r}"
                )


def test_bill_notes_columns_fit_without_horizontal_bar(qt_app: QApplication) -> None:
    from gui.live_push_panel import _style_bill_tokens_table

    table = QTableWidget(3, 5)
    table.setHorizontalHeaderLabels(["Code", "Live", "Target", "Accept", "Match"])
    _style_bill_tokens_table(table)
    table.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    table.show()
    table.resize(320, 140)
    qt_app.processEvents()

    header = table.horizontalHeader()
    used = sum(header.sectionSize(i) for i in range(header.count()))
    assert used <= table.viewport().width()
    assert table.horizontalScrollBar().maximum() == 0


def test_bill_accept_cell_uses_same_tint_as_code_cell(
    qt_app: QApplication, tmp_path
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from gui.live_push_panel import LivePushPanel
    from tests.test_slot_setup import _fake_goldclub

    gold = _fake_goldclub(tmp_path)
    outcome = load_live_cabinet(str(gold))
    assert outcome.recipe is not None

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    table = panel._bill_tokens_table
    assert table.rowCount() >= 1
    code_item = table.item(0, 0)
    accept_item = table.item(0, 3)
    assert code_item is not None
    assert accept_item is not None
    assert table.cellWidget(0, 3) is None
    assert accept_item.checkState() in (
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
    )
    assert accept_item.background().color() == code_item.background().color()


def test_column_count_is_sticky_at_the_boundary(qt_app: QApplication) -> None:
    """A scrollbar appearing must not bounce the layout between column counts."""
    board = _board(qt_app)
    three_col = MAX_COLUMNS * MIN_COLUMN_WIDTH + 2 * 12
    _resize(board, qt_app, three_col)
    assert _columns_used(board) == set(range(MAX_COLUMNS))

    # Losing a scrollbar's worth of width keeps the three-column layout.
    _resize(board, qt_app, three_col - 17)
    assert _columns_used(board) == set(range(MAX_COLUMNS))


def test_panel_add_box_order_is_market_denom_then_licence_last() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "gui" / "live_push_panel.py").read_text(
        encoding="utf-8"
    )
    # Only the LivePushPanel constructor board section.
    start = src.index("board = _ColumnBoard()")
    end = src.index("scroll.setWidget(board)", start)
    chunk = src[start:end]
    titles = []
    needle = 'board.add_box('
    pos = 0
    while True:
        i = chunk.find(needle, pos)
        if i < 0:
            break
        # Look backward for the most recent _group_form("Title")
        ahead = chunk[:i]
        g = ahead.rfind('_group_form("')
        assert g >= 0
        title = ahead[g + len('_group_form("') :].split('"', 1)[0]
        titles.append(title)
        pos = i + len(needle)
    assert titles[0] == "Currency / market"
    assert titles[1] == "Denoms / bets"
    assert titles[-1] == "Licence"
    assert titles == [t for t, _w in PANEL_GROUPS]


def test_set_combo_code_does_not_steal_trinidad_for_tt(qt_app: QApplication) -> None:
    from PySide6.QtWidgets import QComboBox

    from gui.live_push_panel import _combo_code, _set_combo_code

    del qt_app
    combo = QComboBox()
    combo.addItem("TT", "TT")
    combo.addItem("TrinidadTobago", "TrinidadTobago")
    _set_combo_code(combo, "TT")
    assert _combo_code(combo) == "TT"
    assert combo.currentText() == "TT"


def test_set_combo_code_adds_missing_value_on_non_editable_combo(
    qt_app: QApplication,
) -> None:
    from PySide6.QtWidgets import QComboBox

    from gui.live_push_panel import _combo_code, _set_combo_code

    del qt_app
    combo = QComboBox()
    combo.setEditable(False)
    combo.addItem("5", "5")
    _set_combo_code(combo, "10", editable_ok=False)
    assert _combo_code(combo) == "10"
    assert combo.currentText() == "10"


def test_live_fields_highlight_green_when_they_match_cabinet(
    qt_app: QApplication, tmp_path
) -> None:
    from config_scanner.live_push import LIVE_FIELD_TOOLTIP_MATCH, load_live_cabinet
    from gui.live_push_panel import LivePushPanel
    from tests.test_slot_setup import _fake_goldclub

    gold = _fake_goldclub(tmp_path)
    outcome = load_live_cabinet(str(gold))
    assert outcome.recipe is not None
    outcome.recipe.bill_protocol = "JCM"
    outcome.recipe.ticket_protocol = "JCM"

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    assert LIVE_FIELD_TOOLTIP_MATCH.casefold() in panel._bill.toolTip().casefold()
    assert panel._bill.styleSheet()
    assert panel._bill.currentData() == "JCM"
    assert "JCM" in panel._bill.currentText()
    assert panel._ticket.currentData() == "JCM"
    assert "FutureLogic" in panel._ticket.currentText()
    assert panel._ticket.styleSheet()

    panel._bill.setCurrentText("MEI")
    panel._refresh_changes_now()
    qt_app.processEvents()
    assert panel._bill.styleSheet()
    assert "orange" in panel._bill.toolTip().casefold()
    assert panel._currency.styleSheet()
    panel._ticket.setCurrentIndex(panel._ticket.findData("TRANSACT"))
    panel._refresh_changes_now()
    qt_app.processEvents()
    assert panel._ticket.styleSheet()
    assert "orange" in panel._ticket.toolTip().casefold()


def test_live_fields_green_when_language_empty_in_mgconfig(
    qt_app: QApplication, tmp_path
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from gui.live_push_panel import LivePushPanel, _combo_code
    from tests.test_slot_setup import _fake_goldclub

    gold = _fake_goldclub(tmp_path)
    mg = gold / "slot" / "themes" / "mgconfig.xml"
    text = mg.read_text(encoding="utf-8")
    import re

    text = re.sub(r"<Language>.*?</Language>", "<Language></Language>", text, count=1)
    mg.write_text(text, encoding="utf-8")

    outcome = load_live_cabinet(str(gold))
    assert outcome.recipe is not None
    assert outcome.recipe.mg_identity.language == ""

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    assert _combo_code(panel._language) == ""
    assert panel._language.styleSheet()
    assert "green" in panel._language.toolTip().casefold()
    assert panel._denoms.styleSheet()


def test_licence_section_offers_push_when_xml_only_in_licenses(
    qt_app: QApplication, tmp_path, monkeypatch
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from gui.live_push_panel import LivePushPanel
    from tests.test_slot_setup import _fake_goldclub

    monkeypatch.setattr(
        "gui.live_push_panel.discover_preferred_licence_pack",
        lambda **_kw: None,
    )
    gold = _fake_goldclub(tmp_path)
    (gold / "Licenses").mkdir()
    (gold / "Licenses" / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence/>", encoding="utf-8"
    )
    outcome = load_live_cabinet(str(gold))
    assert outcome.licence is not None
    assert outcome.licence.needs_push is True
    assert outcome.licence.can_mirror is True

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    assert panel._licence_push.isEnabled()
    assert panel._licence_push.isChecked()
    assert "slot" in panel._licence_label.text().casefold()
    lines = panel._licence_change_lines()
    assert lines
    assert "Licence files" in lines[0]


def test_licence_status_is_green_when_playable_on_cabinet(
    qt_app: QApplication, tmp_path, monkeypatch
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from gui.live_push_panel import LivePushPanel
    from gui.palette_adapt import text_success
    from tests.test_slot_setup import _fake_goldclub

    monkeypatch.setattr(
        "gui.live_push_panel.discover_preferred_licence_pack",
        lambda **_kw: None,
    )
    gold = _fake_goldclub(tmp_path)
    slot = gold / "slot"
    (slot / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence/>", encoding="utf-8"
    )
    (slot / "licence.dll").write_bytes(b"x" * 64)
    outcome = load_live_cabinet(str(gold))
    assert outcome.licence is not None
    assert outcome.licence.playable is True

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    assert panel._licence_push.isChecked() is False
    assert panel._licence_push.isEnabled() is True
    panel._licence_push.setChecked(True)
    assert panel._want_licence_push() is False
    panel._licence_push.setChecked(False)
    green = text_success(panel.palette()).name().casefold()
    assert green in panel._licence_label.styleSheet().casefold()
    assert "will not overwrite" in panel._licence_label.text().casefold()


def test_licence_source_prefers_usb_pack_over_embedded(
    qt_app: QApplication, tmp_path, monkeypatch
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from config_scanner.slot_licence import LicencePackHit
    from gui.live_push_panel import LivePushPanel
    from tests.test_slot_setup import _fake_goldclub

    usb = tmp_path / "usb" / "Licences_PR"
    (usb / "Licenses").mkdir(parents=True)
    (usb / "Licenses" / "Licence12-usb.xml").write_text("<Licence/>", encoding="utf-8")
    embedded = tmp_path / "exe" / "Licenses"
    embedded.mkdir(parents=True)
    (embedded / "Licence12-embedded.xml").write_text("<Licence/>", encoding="utf-8")

    def fake_discover(*, skip_roots=(), usb_roots=None, embedded_roots=None, **_kw):
        del skip_roots, usb_roots, embedded_roots
        return LicencePackHit(
            usb, ("Licence12-usb.xml",), "usb"
        )

    monkeypatch.setattr(
        "gui.live_push_panel.discover_preferred_licence_pack",
        fake_discover,
    )
    gold = _fake_goldclub(tmp_path)
    (gold / "Licenses").mkdir()
    (gold / "Licenses" / "Licence12-cabinet.xml").write_text(
        "<Licence/>", encoding="utf-8"
    )
    outcome = load_live_cabinet(str(gold))
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    assert panel._licence_source.text() == str(usb)
    assert panel._licence_push.isChecked()
    lines = panel._licence_change_lines()
    assert lines
    assert "USB" in lines[0]
    assert str(usb) in lines[0]


def test_licence_source_uses_embedded_when_usb_empty(
    qt_app: QApplication, tmp_path, monkeypatch
) -> None:
    from config_scanner.live_push import load_live_cabinet
    from config_scanner.slot_licence import LicencePackHit
    from gui.live_push_panel import LivePushPanel
    from tests.test_slot_setup import _fake_goldclub

    bundled = tmp_path / "ConfigScanner" / "Licenses"
    bundled.mkdir(parents=True)
    (bundled / "Licence12-tool.xml").write_text("<Licence/>", encoding="utf-8")
    monkeypatch.setattr(
        "gui.live_push_panel.discover_preferred_licence_pack",
        lambda **_kw: LicencePackHit(
            bundled.parent, ("Licence12-tool.xml",), "usb"
        ),
    )
    gold = _fake_goldclub(tmp_path)
    outcome = load_live_cabinet(str(gold))
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()

    assert panel._licence_source.text() == str(bundled.parent)
    assert panel._licence_push.isChecked()
    assert "USB" in panel._licence_change_lines()[0]


def test_licence_autofill_passes_cabinet_unc_host(
    qt_app: QApplication, monkeypatch
) -> None:
    from config_scanner.slot_licence import LiveLicenceStatus
    from gui.live_push_panel import LivePushPanel

    captured: dict[str, object] = {}

    def fake_discover(*, skip_roots=(), extra_hosts=None, **_kw):
        captured["hosts"] = tuple(extra_hosts or ())
        return None

    monkeypatch.setattr(
        "gui.live_push_panel.discover_preferred_licence_pack",
        fake_discover,
    )
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    status = LiveLicenceStatus(
        playable_xml=(),
        licenses_dir_xml=(),
        dll_rel="",
        playable=False,
        needs_push=True,
        can_mirror=False,
        detail="No licence next to OneHand.",
    )
    panel._update_licence_ui(status, goldclub=Path(r"\\10.0.0.171\slot"))
    qt_app.processEvents()
    assert captured.get("hosts") == ("10.0.0.171",)
    assert panel._licence_push.isEnabled()
    assert panel._licence_push.isChecked() is False
    assert panel._want_licence_push() is False


def test_licence_push_defaults_off_when_onehand_is_debug(
    qt_app: QApplication, tmp_path, monkeypatch
) -> None:
    from config_scanner.slot_licence import LiveLicenceStatus
    from gui.live_push_panel import LivePushPanel

    monkeypatch.setattr(
        "gui.live_push_panel.discover_preferred_licence_pack",
        lambda **_kw: None,
    )
    monkeypatch.setattr("gui.live_push_panel.is_onehand_debug_build", lambda _g: True)
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    status = LiveLicenceStatus(
        playable_xml=(),
        licenses_dir_xml=(),
        dll_rel="",
        playable=False,
        needs_push=True,
        can_mirror=True,
        detail="No licence next to OneHand.",
    )
    gold = tmp_path / "Goldclub"
    gold.mkdir()
    panel._licence_source.setText(r"\\10.0.0.111\USB\Licences_SlotQA_01")
    panel._update_licence_ui(status, goldclub=gold)
    qt_app.processEvents()
    assert panel._licence_push.isEnabled()
    assert panel._licence_push.isChecked() is False
    assert "debug" in panel._licence_label.text().casefold()
    assert panel._want_licence_push() is False


def test_live_push_footer_keeps_apply_beside_options(
    qt_app: QApplication,
) -> None:
    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.resize(1100, 800)
    panel.show()
    qt_app.processEvents()

    apply_g = panel._commit.geometry()
    restart_g = panel._restart.geometry()
    status_g = panel._status.geometry()
    backup_g = panel._backup.geometry()
    restore_g = panel._restore_backup.geometry()
    assert apply_g.left() > restart_g.right()
    assert apply_g.top() <= restart_g.bottom() + 6
    assert apply_g.bottom() >= status_g.top()
    assert status_g.left() <= restart_g.left() + 8
    assert not panel._backup.isChecked()
    assert backup_g.top() >= apply_g.bottom() - 2
    assert restore_g.top() >= apply_g.bottom() - 2
    assert restore_g.left() >= backup_g.right() - 2
    assert panel._restore_backup.text().startswith("Restore backup")


def test_door_switch_defaults_match_111_and_auto_unlock_all(
    qt_app: QApplication,
) -> None:
    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()

    assert panel._switches_enabled.isChecked() is True
    assert panel._sw_stacker.isChecked() is True
    assert panel._sw_all.isChecked() is False
    assert all(not box.isChecked() for box in panel._switch_auto.values())
    assert panel._switch_alert["cabinet_door"].currentText() == "BOTH"
    assert panel._switch_alert["logic_door"].currentText() == "SEMAPHORE"

    panel._sw_all.setChecked(True)
    qt_app.processEvents()
    assert all(box.isChecked() for box in panel._switch_auto.values())
    panel._switch_auto["cabinet_door"].setChecked(False)
    qt_app.processEvents()
    assert panel._sw_all.isChecked() is False


def test_create_market_button_is_on_the_toolbar(qt_app: QApplication) -> None:
    from gui.live_push_panel import LivePushPanel

    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    assert panel._create_market_btn.isEnabled()
    assert "Create market" in panel._create_market_btn.text()


def test_create_market_writes_user_sidecar(
    qt_app: QApplication, tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QDialog

    from config_scanner.jurisdiction import find_jurisdiction, load_jurisdictions
    from config_scanner.live_push import load_live_cabinet
    from gui.live_push_panel import LivePushPanel
    from tests.test_slot_setup import _fake_goldclub

    user = tmp_path / "jurisdictions.user.json"
    monkeypatch.setattr(
        "config_scanner.jurisdiction.user_jurisdictions_path", lambda: user
    )

    class _AcceptDialog:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def exec(self) -> object:
            return QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, str, str, str]:
            return ("lab_cop_live", "Lab Colombia COP", "Colombia", "from test")

    monkeypatch.setattr("gui.live_push_panel.CreateMarketDialog", _AcceptDialog)

    gold = _fake_goldclub(tmp_path / "gold")
    outcome = load_live_cabinet(str(gold))
    panel = LivePushPanel(autoload=False)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    qt_app.processEvents()
    panel._on_load_finished(outcome)
    qt_app.processEvents()
    panel._create_market()
    qt_app.processEvents()

    assert user.is_file()
    found = find_jurisdiction("lab_cop_live")
    assert found is not None
    assert found.label == "Lab Colombia COP"
    assert found.id in {p.id for p in load_jurisdictions()}
    assert panel._preset.currentData() == "lab_cop_live"
    assert "Created market" in panel._status.text()

