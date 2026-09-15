"""Live Push dialog: per-game RTP and bet-step toggles."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config_scanner.game_math import (
    allowed_return_choices,
    clone_math_rows,
    copy_bet_steps_to_compatible,
    format_game_combo_label,
    format_return_percent,
    game_math_change_lines,
    math_by_theme,
    offered_bet_steps,
    set_return_percent_where_allowed,
    theme_display_name,
)
from config_scanner.slot_setup import MathDenomSettings


class GameMathDialog(QDialog):
    """Master–detail editor for each theme's AllowedReturnPercents and bets."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        live_rows: list[MathDenomSettings],
        form_rows: list[MathDenomSettings],
        focus_theme: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("gameMathDialog")
        self.setWindowTitle("Games / math")
        self.setModal(True)
        self.resize(760, 520)

        self._live = clone_math_rows(live_rows)
        self._rows = clone_math_rows(form_rows or live_rows)
        self._current_theme = ""
        self._rtp_group = QButtonGroup(self)
        self._rtp_buttons: list[QRadioButton] = []
        self._bet_boxes: list[QCheckBox] = []
        self._loading = False

        hint = QLabel(
            "Each game keeps its own MathSettings.xml. RTP choices come from "
            "that file's AllowedReturnPercents. Bet steps can only be dropped "
            "from the ladder already on this title."
        )
        hint.setWordWrap(True)

        self._filter = QLineEdit()
        self._filter.setObjectName("gameMathFilter")
        self._filter.setPlaceholderText("Filter games…")
        self._filter.textChanged.connect(self._apply_filter)

        self._list = QListWidget()
        self._list.setObjectName("gameMathList")
        self._list.currentItemChanged.connect(self._list_changed)

        left = QVBoxLayout()
        left.addWidget(self._filter)
        left.addWidget(self._list, stretch=1)

        self._detail_title = QLabel("")
        self._detail_title.setWordWrap(True)
        self._rtp_box = QGroupBox("Return percent")
        self._rtp_layout = QVBoxLayout(self._rtp_box)
        self._bets_box = QGroupBox("Bet steps")
        self._bets_layout = QGridLayout(self._bets_box)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_inner = QWidget()
        right = QVBoxLayout(right_inner)
        right.addWidget(self._detail_title)
        right.addWidget(self._rtp_box)
        right.addWidget(self._bets_box)
        right.addStretch(1)
        right_scroll.setWidget(right_inner)

        body = QHBoxLayout()
        body.addLayout(left, 2)
        body.addWidget(right_scroll, 3)

        set_rtp = QPushButton("Set this RTP on every game that allows it")
        set_rtp.setObjectName("gameMathSetRtpAll")
        set_rtp.clicked.connect(self._set_rtp_all)
        copy_bets = QPushButton("Copy these bet steps to all games")
        copy_bets.setObjectName("gameMathCopyBets")
        copy_bets.clicked.connect(self._copy_bets_all)
        reset_one = QPushButton("Reset this game")
        reset_one.setObjectName("gameMathResetOne")
        reset_one.clicked.connect(self._reset_current)
        reset_all = QPushButton("Reset all")
        reset_all.setObjectName("gameMathResetAll")
        reset_all.clicked.connect(self._reset_all)

        bulk = QHBoxLayout()
        bulk.addWidget(set_rtp)
        bulk.addWidget(copy_bets)
        bulk.addStretch(1)
        bulk.addWidget(reset_one)
        bulk.addWidget(reset_all)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(body, stretch=1)
        layout.addLayout(bulk)
        layout.addWidget(buttons)

        self._rebuild_list(focus_theme)

    def result_rows(self) -> list[MathDenomSettings]:
        self._flush_current()
        return clone_math_rows(self._rows)

    def _row_for(self, theme: str) -> MathDenomSettings | None:
        return math_by_theme(self._rows).get((theme or "").strip())

    def _live_for(self, theme: str) -> MathDenomSettings | None:
        return math_by_theme(self._live).get((theme or "").strip())

    def _rebuild_list(self, focus_theme: str = "") -> None:
        self._flush_current()
        want = (focus_theme or self._current_theme or "").strip()
        self._list.blockSignals(True)
        self._list.clear()
        selected: QListWidgetItem | None = None
        needle = self._filter.text().casefold()
        for row in self._rows:
            if not (row.theme or "").strip() or row.theme == "*":
                continue
            label = format_game_combo_label(row)
            if needle and needle not in label.casefold() and needle not in row.theme.casefold():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row.theme)
            if self._row_is_changed(row):
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setText(f"• {label}")
            self._list.addItem(item)
            if row.theme == want or selected is None:
                selected = item
        self._list.blockSignals(False)
        if selected is not None:
            self._list.setCurrentItem(selected)
        elif self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._show_row(None)

    def _apply_filter(self, _text: str = "") -> None:
        self._rebuild_list(self._current_theme)

    def _list_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if self._loading:
            return
        self._flush_current()
        theme = ""
        if current is not None:
            theme = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self._show_row(self._row_for(theme))

    def _row_is_changed(self, row: MathDenomSettings) -> bool:
        live = self._live_for(row.theme)
        if live is None:
            return False
        return bool(
            game_math_change_lines([live], [row])
        )

    def _flush_current(self) -> None:
        if self._loading or not self._current_theme:
            return
        row = self._row_for(self._current_theme)
        if row is None:
            return
        checked = self._rtp_group.checkedButton()
        if checked is not None:
            token = str(checked.property("rtpToken") or "")
            if token:
                row.return_percent = token
        steps: list[int] = []
        for box in self._bet_boxes:
            if box.isChecked():
                steps.append(int(box.property("betStep")))
        if steps:
            row.bet_multipliers = steps

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_row(self, row: MathDenomSettings | None) -> None:
        self._loading = True
        try:
            self._current_theme = (row.theme if row else "") or ""
            self._clear_layout(self._rtp_layout)
            self._clear_layout(self._bets_layout)
            self._rtp_buttons.clear()
            self._bet_boxes.clear()
            for btn in list(self._rtp_group.buttons()):
                self._rtp_group.removeButton(btn)
            if row is None:
                self._detail_title.setText("No game selected.")
                return
            live = self._live_for(row.theme)
            self._detail_title.setText(theme_display_name(row.theme))
            choices = allowed_return_choices(row)
            if not choices:
                empty = QLabel(format_return_percent(row.return_percent))
                empty.setEnabled(False)
                self._rtp_layout.addWidget(empty)
            else:
                current = (row.return_percent or "").strip()
                for token in choices:
                    radio = QRadioButton(format_return_percent(token))
                    radio.setProperty("rtpToken", token)
                    radio.setChecked(token == current)
                    self._rtp_group.addButton(radio)
                    self._rtp_layout.addWidget(radio)
                    self._rtp_buttons.append(radio)
                    radio.toggled.connect(self._mark_dirty)
            steps = offered_bet_steps(row, live)
            if not steps:
                self._bets_layout.addWidget(QLabel("No bet steps on this theme."), 0, 0)
            else:
                selected = {int(x) for x in (row.bet_multipliers or [])}
                for index, step in enumerate(steps):
                    box = QCheckBox(str(step))
                    box.setProperty("betStep", step)
                    box.setChecked(step in selected)
                    box.stateChanged.connect(self._mark_dirty)
                    self._bet_boxes.append(box)
                    self._bets_layout.addWidget(box, index // 4, index % 4)
        finally:
            self._loading = False

    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        self._flush_current()
        self._rebuild_list(self._current_theme)

    def _set_rtp_all(self) -> None:
        self._flush_current()
        row = self._row_for(self._current_theme)
        token = (row.return_percent or "").strip() if row else ""
        if not token:
            return
        self._rows, count = set_return_percent_where_allowed(self._rows, token)
        self._rebuild_list(self._current_theme)
        QMessageBox.information(
            self,
            "Games / math",
            f"Set {format_return_percent(token)} on {count} game(s) that allow it.",
        )

    def _copy_bets_all(self) -> None:
        self._flush_current()
        row = self._row_for(self._current_theme)
        if row is None or not row.bet_multipliers:
            return
        confirm = QMessageBox.question(
            self,
            "Copy bet steps",
            "Copy these bet steps onto every game whose live ladder already "
            "contains every selected step? Other titles are left unchanged.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._rows, skipped = copy_bet_steps_to_compatible(
            self._rows, row.bet_multipliers, self._live
        )
        self._rebuild_list(self._current_theme)
        extra = ""
        if skipped:
            extra = "\nSkipped: " + ", ".join(theme_display_name(name) for name in skipped)
        QMessageBox.information(
            self,
            "Games / math",
            "Copied bet steps onto compatible games." + extra,
        )

    def _reset_current(self) -> None:
        live = self._live_for(self._current_theme)
        if live is None:
            return
        for index, row in enumerate(self._rows):
            if row.theme == live.theme:
                self._rows[index] = clone_math_rows([live])[0]
                break
        self._current_theme = live.theme
        self._rebuild_list(live.theme)

    def _reset_all(self) -> None:
        self._rows = clone_math_rows(self._live)
        self._rebuild_list(self._current_theme)
