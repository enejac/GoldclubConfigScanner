"""Live cabinet push: edit safe settings, commit, restack."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QBrush, QColor, QPalette

from config_scanner.bill_tokens_view import (
    apply_bill_token_accept,
    bill_tokens_all_match,
    bill_tokens_by_code,
    bill_tokens_compare_rows,
    bill_tokens_warning_lines,
    resolve_target_bill_tokens,
    summarize_bill_tokens,
)
from config_scanner.live_push import (
    CASHOUT_MODES,
    CELEBRATION_LIMITS,
    CURRENCY_LABELS,
    CURRENCY_SYMBOL_CHOICES,
    DALLAS_CHOICES,
    DEFAULT_BETS,
    INACTIVITY_CHOICES,
    JACKPOT_COUNTERS,
    JACKPOT_LAYOUTS,
    MAGIC_WHEEL_AVERAGES,
    MAGIC_WHEEL_BETS,
    MAGIC_WHEEL_LIMITS,
    MAGIC_WHEEL_SPINS,
    DallasReadResult,
    LiveLoadOutcome,
    LivePushResult,
    commit_live_push,
    currency_symbol_for,
    default_live_cabinet_target,
    denom_combo_choices,
    goldclub_stack_kind,
    live_field_file_hover,
    live_field_highlight_state,
    live_field_matches,
    live_field_tooltip,
    live_field_validation_errors,
    recipe_display_corruption_errors,
    resolve_live_field_config_files,
    live_push_catalog,
    live_push_ramclear_reasons,
    load_live_cabinet,
    market_combo_label,
    ordered_live_markets,
    locale_defaults_for_currency,
    locale_defaults_for_market,
    overlay_jurisdiction_recipe,
    prepare_live_goldclub,
    recipe_change_lines,
    recipe_from_market_id,
    validate_live_push_recipe,
    wait_for_dallas_from_hardware,
    LIVE_OPTION_HELP,
    _lp_log,
)
from config_scanner.denom_compat import (
    expected_magic_wheel_for_denom,
    find_staged_leaf_for_denom,
    link2win_restage_change_line,
    list_link2win_math_replace_targets,
    playable_denoms_from_recipe,
    replace_cabinet_math_file,
    validate_live_push_warnings,
    MathReplaceTarget,
)
from config_scanner.hw_drivers import list_hw_driver_profiles
from config_scanner.slot_licence import (
    LiveLicenceStatus,
    discover_licence_source_files,
    discover_preferred_licence_pack,
    inspect_live_licences,
)
from config_scanner.jurisdiction import (
    find_jurisdiction,
    load_jurisdictions,
    profile_from_recipe,
    suggest_jurisdiction_id,
    suggest_jurisdiction_label,
    upsert_jurisdiction,
)
from gui.create_market_dialog import CreateMarketDialog
from config_scanner.cs_sources import pick_cs_source_for_export, resolve_cs_source
from config_scanner.cs_catalog import discover_leaves
from config_scanner.live_cs_export import export_full_country_selector
from config_scanner.slotlog_review import (
    SlotLogFinding,
    SlotLogReview,
    field_highlight_error,
    finding_field_errors,
    format_review_summary,
    restore_live_push_backup,
    review_slot_logs,
)
from config_scanner.slot_setup import (
    BILL_PROTOCOLS,
    BillToken,
    DOOR_SWITCH_ALERTS,
    DoorSwitchRow,
    DoorSwitchSettings,
    LIMIT_SETUP_FIELDS,
    SAS_CHANNEL_FIELDS,
    STANDARD_DOOR_SWITCH_NAMES,
    TICKET_PROTOCOL_LABELS,
    TICKET_PROTOCOLS,
    door_switch_auto_unlock_label,
    door_switch_label,
    goldclub_root_from_target,
    leftover_jurisdiction_single_denomination,
    load_recipe_from_goldclub,
    markets_accepted_by_onehand,
    is_onehand_debug_build,
    licence_push_default_checked,
    pick_onehand_allowed_market,
    read_aurum_currency_code,
    read_mgconfig_target_market,
    read_ticket_printer_active,
    resolve_target_market_for_mgconfig,
)
from gui.click_tip_label import (
    mouse_release_shows_tip,
    prepare_form_label_for_touch,
)
from gui.notepad_pp import open_with_notepad
from gui.palette_adapt import (
    live_changed_field_stylesheet,
    live_invalid_field_stylesheet,
    live_match_field_stylesheet,
    muted_text,
    text_success,
    text_warning,
)


def _combo_code(combo: QComboBox) -> str:
    text = combo.currentText().strip()
    idx = combo.currentIndex()
    if idx >= 0 and combo.itemText(idx) == combo.currentText():
        data = combo.itemData(idx)
        if data is not None:
            return str(data).strip()
    if "—" in text:
        return text.split("—", 1)[0].strip()
    return text


def _set_combo_code(combo: QComboBox, value: str, *, editable_ok: bool = True) -> None:
    want = (value or "").strip()
    if not want:
        if combo.count() and combo.itemData(0) in (None, ""):
            combo.setCurrentIndex(0)
        else:
            combo.setCurrentIndex(-1)
            if editable_ok and combo.isEditable():
                combo.setEditText("")
        return
    idx = combo.findData(want)
    if idx < 0:
        idx = combo.findText(want, Qt.MatchFlag.MatchFixedString)
    if idx < 0:
        for i in range(combo.count()):
            if str(combo.itemData(i) or "").casefold() == want.casefold():
                idx = i
                break
            text = combo.itemText(i).casefold()
            # "TTD  —  …" may match code TTD; do not let "TT" steal TrinidadTobago.
            if text.startswith(want.casefold() + " ") or text.startswith(
                want.casefold() + "—"
            ) or text.startswith(want.casefold() + "  —"):
                idx = i
                break
    if idx >= 0:
        combo.setCurrentIndex(idx)
        return
    if editable_ok and combo.isEditable():
        combo.setEditText(want)
        return
    combo.addItem(want, want)
    combo.setCurrentIndex(combo.count() - 1)


def _bool_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("leave as-is", None)
    combo.addItem("on", True)
    combo.addItem("off", False)
    return combo


def _int_combo(values: tuple[int, ...], *, suffix: str = "") -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("leave as-is", None)
    for value in values:
        combo.addItem(f"{value}{suffix}", int(value))
    return combo


def _str_combo(values: tuple[str, ...], *, editable: bool = True) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(editable)
    combo.addItem("leave as-is", None)
    for value in values:
        combo.addItem(value, value)
    return combo


def _optional_int(combo: QComboBox) -> int | None:
    data = combo.currentData()
    if data is None:
        text = combo.currentText().strip().replace(",", "")
        if not text or text.casefold().startswith("leave"):
            return None
        data = text
    try:
        return int(str(data).strip())
    except (TypeError, ValueError):
        return None


def _optional_bool(combo: QComboBox) -> bool | None:
    data = combo.currentData()
    if isinstance(data, bool):
        return data
    return None


def _optional_str(combo: QComboBox) -> str:
    data = combo.currentData()
    if data is None:
        text = combo.currentText().strip()
        if not text or text.casefold().startswith("leave"):
            return ""
        return text
    return str(data).strip()


def _set_optional_int(combo: QComboBox, value: int | None) -> None:
    if value is None:
        combo.setCurrentIndex(0)
        return
    idx = combo.findData(int(value))
    if idx < 0:
        combo.addItem(str(value), int(value))
        idx = combo.count() - 1
    combo.setCurrentIndex(idx)


def _set_optional_bool(combo: QComboBox, value: bool | None) -> None:
    if value is True:
        combo.setCurrentIndex(combo.findData(True))
    elif value is False:
        combo.setCurrentIndex(combo.findData(False))
    else:
        combo.setCurrentIndex(0)


def _set_optional_str(combo: QComboBox, value: str | None) -> None:
    want = (value or "").strip()
    if not want:
        combo.setCurrentIndex(0)
        return
    _set_combo_code(combo, want)


MIN_COLUMN_WIDTH = 360
MAX_COLUMNS = 3
_COLUMN_GAP = 12
# Keeps a scrollbar appearing/disappearing at a column boundary from flipping the
# layout back and forth forever.
_COLUMN_HYSTERESIS = 28


def _group_form(title: str) -> tuple[QGroupBox, QFormLayout]:
    """A group box whose rows are tight enough to read several side by side."""
    box = QGroupBox(title)
    form = QFormLayout(box)
    form.setContentsMargins(10, 6, 10, 8)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return box, form


def _fit_bill_tokens_columns(table: QTableWidget) -> None:
    """Share the viewport across bill-notes columns so they never overflow."""
    header = table.horizontalHeader()
    n = header.count()
    if n <= 0:
        return
    available = max(table.viewport().width(), 1)
    weights = (12, 24, 24, 20, 20) if n == 5 else tuple(1 for _ in range(n))
    total = sum(weights)
    widths = [max(1, int(round(available * w / total))) for w in weights]
    widths[-1] += available - sum(widths)
    overflow = sum(widths) - available
    i = 0
    while overflow > 0 and i < n:
        take = min(overflow, widths[i] - 1)
        widths[i] -= take
        overflow -= take
        i += 1
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    header.setStretchLastSection(False)
    for idx, width in enumerate(widths):
        header.resizeSection(idx, max(1, width))


class _BillNotesColumnFit(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show) and isinstance(
            watched, QTableWidget
        ):
            _fit_bill_tokens_columns(watched)
        return False


def _style_bill_tokens_table(table: QTableWidget) -> None:
    """Panel-colored table whose columns always fit (no horizontal bar)."""
    pal = table.palette()
    window = pal.color(QPalette.ColorRole.Window)
    pal.setColor(QPalette.ColorRole.Base, window)
    pal.setColor(QPalette.ColorRole.AlternateBase, window)
    table.setPalette(pal)
    table.setStyleSheet("QTableWidget { background-color: palette(window); }")
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setWordWrap(False)
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(28)
    filt = _BillNotesColumnFit(table)
    table.installEventFilter(filt)
    _fit_bill_tokens_columns(table)


class _ColumnBoard(QWidget):
    """Reflows the setting groups into 1-3 independent columns.

    Each column is its own vertical stack so a tall group cannot stretch a
    short neighbor in the same grid row. The board's minimum height is the
    tallest column so a QScrollArea cannot squash groups on top of each other.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._boxes: list[tuple[QWidget, int]] = []
        self._columns = 0
        self._relayouting = False
        self._column_hosts: list[QWidget] = []
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(_COLUMN_GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        for _ in range(MAX_COLUMNS):
            host = QWidget(self)
            col_lay = QVBoxLayout(host)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(10)
            col_lay.addStretch(1)
            host.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            self._row.addWidget(host, 1)
            self._column_hosts.append(host)
            host.hide()

    def add_box(self, widget: QWidget, weight: int) -> None:
        """Add a group; ``weight`` is its row count, used to balance columns."""
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._boxes.append((widget, max(1, weight)))
        self._relayout(force=True)

    def group_placements(self) -> dict[str, tuple[int, int]]:
        """Map group title to ``(row in column, column index)``."""
        out: dict[str, tuple[int, int]] = {}
        for col, host in enumerate(self._column_hosts):
            if host.isHidden():
                continue
            lay = host.layout()
            if lay is None:
                continue
            row = 0
            for i in range(lay.count()):
                widget = lay.itemAt(i).widget()
                if isinstance(widget, QGroupBox):
                    out[widget.title()] = (row, col)
                    row += 1
        return out

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(
            MIN_COLUMN_WIDTH * max(self._columns, 1)
            + _COLUMN_GAP * max(self._columns - 1, 0),
            self._content_height(),
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(MIN_COLUMN_WIDTH, self._content_height())

    def _content_height(self) -> int:
        height = 0
        for host in self._column_hosts:
            if host.isHidden():
                continue
            height = max(height, host.sizeHint().height())
        return max(height, 1)

    def _wanted_columns(self) -> int:
        width = self.width()
        if width <= 0:
            return self._columns or 1
        for count in range(MAX_COLUMNS, 1, -1):
            needed = count * MIN_COLUMN_WIDTH + (count - 1) * _COLUMN_GAP
            if self._columns == count:
                needed -= _COLUMN_HYSTERESIS
            if width >= needed:
                return count
        return 1

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._relayout()

    def _empty_host(self, host: QWidget) -> None:
        lay = host.layout()
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)

    def _relayout(self, *, force: bool = False) -> None:
        if self._relayouting:
            return
        columns = self._wanted_columns()
        if columns == self._columns and not force:
            return
        self._relayouting = True
        try:
            self._columns = columns
            for host in self._column_hosts:
                self._empty_host(host)

            heights = [0] * columns
            packed: list[list[QWidget]] = [[] for _ in range(columns)]
            for widget, weight in self._boxes:
                col = heights.index(min(heights))
                packed[col].append(widget)
                heights[col] += weight

            for i, host in enumerate(self._column_hosts):
                lay = host.layout()
                assert lay is not None
                if i < columns:
                    for widget in packed[i]:
                        lay.addWidget(widget, 0)
                    lay.addStretch(1)
                    host.show()
                else:
                    host.hide()
            self.setMinimumHeight(self._content_height())
            self.updateGeometry()
        finally:
            self._relayouting = False


class _PushEmitter(QObject):
    progress = Signal(str)
    finished = Signal(object)


class _LoadRunnable(QRunnable):
    def __init__(self, target: str, emitter: _PushEmitter) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._target = target
        self._emitter = emitter

    def run(self) -> None:
        try:
            self._emitter.finished.emit(load_live_cabinet(self._target))
        except Exception as exc:  # noqa: BLE001
            self._emitter.finished.emit(
                LiveLoadOutcome(None, None, f"Cannot load cabinet: {exc}", "")
            )


class _DallasReadRunnable(QRunnable):
    def __init__(self, dest: Path, emitter: _PushEmitter) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._dest = dest
        self._emitter = emitter

    def run(self) -> None:
        try:
            result = wait_for_dallas_from_hardware(
                self._dest,
                progress=self._emitter.progress.emit,
            )
            self._emitter.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self._emitter.finished.emit(DallasReadResult(None, source=str(exc)))


class _SlotLogReviewRunnable(QRunnable):
    """Wait for OneHand to write SlotLog, then scan for misconfig signatures."""

    def __init__(
        self,
        goldclub: Path,
        since: datetime | None,
        wait_sec: float,
        emitter: _PushEmitter,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._goldclub = goldclub
        self._since = since
        self._wait_sec = wait_sec
        self._emitter = emitter

    def run(self) -> None:
        import time

        try:
            if self._wait_sec > 0:
                self._emitter.progress.emit(
                    f"Waiting {int(self._wait_sec)}s for game logs…"
                )
                time.sleep(self._wait_sec)
            self._emitter.progress.emit("Reading SlotLog…")
            review = review_slot_logs(self._goldclub, since=self._since)
            self._emitter.finished.emit(review)
        except Exception as exc:  # noqa: BLE001
            self._emitter.finished.emit(
                SlotLogReview(note=f"SlotLog review failed: {exc}")
            )


class _CommitRunnable(QRunnable):
    def __init__(
        self,
        recipe,
        dest: Path,
        *,
        restart_stack: bool,
        scan_target: str,
        emitter: _PushEmitter,
        backup: bool = False,
        full_pack: bool = False,
        push_licences: bool = False,
        licence_source: str | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._recipe = recipe
        self._dest = dest
        self._restart = restart_stack
        self._scan_target = scan_target
        self._emitter = emitter
        self._backup = backup
        self._full_pack = full_pack
        self._push_licences = push_licences
        self._licence_source = licence_source

    def run(self) -> None:
        try:
            result = commit_live_push(
                self._recipe,
                self._dest,
                restart_stack=self._restart,
                scan_target=self._scan_target,
                progress=self._emitter.progress.emit,
                backup=self._backup,
                full_pack=self._full_pack,
                push_licences=self._push_licences,
                licence_source=self._licence_source,
            )
            self._emitter.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self._emitter.finished.emit(
                LivePushResult((), (), (str(exc),), False, False, "")
            )


class LivePushPanel(QWidget):
    """Load a live Goldclub tree, pick ready-made settings, commit + restack."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, autoload: bool = False) -> None:
        super().__init__(parent)
        self._loaded = None
        self._busy = False
        self._applying = False
        self._silent_load = False
        self._started = False
        self._catalog = live_push_catalog()
        self._emitter = _PushEmitter()
        self._emitter.progress.connect(self._on_progress)
        self._emitter.finished.connect(self._on_finished)
        self._load_emitter = _PushEmitter()
        self._load_emitter.finished.connect(self._on_load_finished)
        self._dallas_emitter = _PushEmitter()
        self._dallas_emitter.progress.connect(self._on_progress)
        self._dallas_emitter.finished.connect(self._on_dallas_finished)
        self._shortcut_btns: list[QPushButton] = []
        self._licence_status: LiveLicenceStatus | None = None
        self._licence_goldclub: Path | None = None
        self._licence_pack_origin = ""
        self._onehand_markets: frozenset[str] | None = None
        self._dallas_busy = False
        self._slotlog_findings: list[SlotLogFinding] = []
        self._goldclub: Path | None = None
        self._display_corruption: dict[str, str] = {}
        self._last_backup_dir = ""
        self._last_apply_since: datetime | None = None
        self._review_emitter = _PushEmitter()
        self._review_emitter.progress.connect(self._on_progress)
        self._review_emitter.finished.connect(self._on_slotlog_review_finished)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(75)
        self._refresh_timer.timeout.connect(self._refresh_changes_now)
        self._bill_accept: dict[str, QTableWidgetItem] = {}
        self._reset_bill_accept = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        back = QPushButton("← Home")
        back.setToolTip("Return to the Config Scanner home screen.")
        back.clicked.connect(self.back_requested.emit)
        head.addWidget(back)
        title = QLabel("Push to live cabinet")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        title.setToolTip(
            "Edit live cabinet settings over SMB, then Apply to write and restart the game."
        )
        head.addWidget(title)
        head.addStretch(1)
        outer.addLayout(head)

        blurb = QLabel(
            "Green = matches the live cabinet. Orange = your edit differs from the "
            "cabinet and will be written on apply. Red = invalid, or corrupt display "
            "text (weird '?' / non-ASCII — hover for why). Right-click a setting to "
            "open its config file in Notepad. Apply stops OneHand, writes files, "
            "starts Bootstrap."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: #999;")
        outer.addWidget(blurb)

        cab = QHBoxLayout()
        cab.addWidget(QLabel("Cabinet:"))
        self._path = QLineEdit(default_live_cabinet_target())
        self._path.setPlaceholderText(r"\\10.0.0.111\slot  or  C:\Goldclub")
        self._path.setToolTip(
            "Goldclub root on the EGM: UNC share (e.g. \\\\10.0.0.111\\slot) "
            "or a local path (C:\\Goldclub / G:\\ when unlocked)."
        )
        cab.addWidget(self._path, stretch=1)
        browse = QPushButton("Browse…")
        browse.setToolTip("Pick a local Goldclub folder.")
        browse.clicked.connect(self._browse)
        cab.addWidget(browse)
        load = QPushButton("Load")
        load.setObjectName("primary")
        load.setToolTip(
            "Read the cabinet configs into this form. Fields turn green when they "
            "match the live values."
        )
        load.clicked.connect(self._load)
        self._load_btn = load
        cab.addWidget(load)
        outer.addLayout(cab)

        quick = QHBoxLayout()
        for label, path in (
            ("This PC", r"C:\Goldclub"),
            ("10.0.0.90", r"\\10.0.0.90\c$\Goldclub"),
            ("10.0.0.111", r"\\10.0.0.111\slot"),
        ):
            btn = QPushButton(label)
            btn.setToolTip(f"Load cabinet at {path}")
            btn.clicked.connect(lambda _=False, p=path: self._pick_cabinet(p))
            self._shortcut_btns.append(btn)
            quick.addWidget(btn)
        quick.addSpacing(18)
        quick.addWidget(QLabel("Market:"))
        self._preset = QComboBox()
        self._preset.setToolTip(
            "Optional jurisdiction preset. Fills currency, culture, denoms, and "
            "related defaults; does not write until you Apply."
        )
        self._preset.addItem("(cabinet values / pick a market)", None)
        for prof in load_jurisdictions():
            self._preset.addItem(prof.label, prof.id)
        self._preset.currentIndexChanged.connect(self._market_chosen)
        quick.addWidget(self._preset, stretch=1)
        create_market = QPushButton("Create market…")
        create_market.setObjectName("createMarketButton")
        create_market.setToolTip(
            "Save the current Live Push fields as a new Market preset. "
            "Does not write the cabinet until you Apply."
        )
        create_market.clicked.connect(self._create_market)
        self._create_market_btn = create_market
        quick.addWidget(create_market)
        outer.addLayout(quick)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        board = _ColumnBoard()

        # --- Market first (top-left), then denoms, then the rest; licence last ---
        loc_box, loc = _group_form("Currency / market")
        self._currency = QComboBox()
        self._currency.setEditable(True)
        for code in self._catalog["currencies"]:
            label = CURRENCY_LABELS.get(code, code)
            self._currency.addItem(f"{code}  —  {label}", code)
        self._symbol = QComboBox()
        self._symbol.setEditable(True)
        for symbol in CURRENCY_SYMBOL_CHOICES:
            self._symbol.addItem(symbol, symbol)
        self._culture = QComboBox()
        self._culture.setEditable(True)
        self._culture.addItems(list(self._catalog["cultures"]))
        self._language = QComboBox()
        self._language.setEditable(True)
        self._language.addItems(list(self._catalog["languages"]))
        self._market = QComboBox()
        self._market.setEditable(True)
        self._fill_market_combo()
        loc.addRow("Currency", self._currency)
        loc.addRow("Symbol", self._symbol)
        loc.addRow("Culture", self._culture)
        loc.addRow("Language", self._language)
        loc.addRow("Target market", self._market)
        board.add_box(loc_box, 5)

        denom_box, denom = _group_form("Denoms / bets")
        self._denoms = QComboBox()
        self._denoms.setEditable(True)
        self._refresh_denom_choices()
        self._bets = QComboBox()
        self._bets.setEditable(True)
        self._bets.addItem("leave as-is", None)
        for preset in self._catalog.get("bet_multipliers", ()):
            self._bets.addItem(preset, preset)
        denom.addRow("Denoms (cents)", self._denoms)
        denom.addRow("Bet multipliers", self._bets)
        board.add_box(denom_box, 2)

        mw_box, mw = _group_form("Magic wheel")
        self._mw_limit = _int_combo(MAGIC_WHEEL_LIMITS)
        self._mw_bet = _int_combo(MAGIC_WHEEL_BETS)
        self._mw_enabled = _bool_combo()
        self._mw_spins = _int_combo(MAGIC_WHEEL_SPINS)
        self._mw_average = _int_combo(MAGIC_WHEEL_AVERAGES)
        mw.addRow("Money limit", self._mw_limit)
        mw.addRow("Wheel bet", self._mw_bet)
        mw.addRow("Enabled", self._mw_enabled)
        mw.addRow("Max spins", self._mw_spins)
        mw.addRow("Money average", self._mw_average)
        board.add_box(mw_box, 5)

        jp_box, jp = _group_form("Jackpots")
        self._jp_counters = _int_combo(JACKPOT_COUNTERS)
        self._jp_layout = _str_combo(JACKPOT_LAYOUTS)
        self._jp_celebration = _str_combo(CELEBRATION_LIMITS)
        self._cashout = _str_combo(CASHOUT_MODES)
        jp.addRow("Jackpot counters", self._jp_counters)
        jp.addRow("Jackpot receipt", self._jp_layout)
        jp.addRow("Celebration limit", self._jp_celebration)
        jp.addRow("Cashout button", self._cashout)
        board.add_box(jp_box, 4)

        ui_box, ui = _group_form("Game UI")
        self._default_bet = _str_combo(DEFAULT_BETS)
        self._show_denom = _bool_combo()
        self._inactivity = QComboBox()
        for value, label in INACTIVITY_CHOICES:
            self._inactivity.addItem(label, value)
        self._show_all_lines = _bool_combo()
        ui.addRow("Default bet", self._default_bet)
        ui.addRow("Show denom selector", self._show_denom)
        ui.addRow("Inactivity", self._inactivity)
        ui.addRow("Show all lines", self._show_all_lines)
        board.add_box(ui_box, 4)

        sas_box, sas = _group_form("SAS / cashless")
        self._sas_enabled = QCheckBox("SAS enabled")
        self._sas_enabled.setChecked(True)
        self._sas_address = QSpinBox()
        self._sas_address.setRange(1, 127)
        self._sas_address.setValue(1)
        self._sas_transfer = QComboBox()
        self._sas_transfer.addItems(["AFT", "NONE", "EFT"])
        self._sas_aft = QCheckBox("AFT enabled")
        self._sas_aft.setChecked(True)
        self._sas_lock = QCheckBox("Lock game when no SAS comms")
        self._sas_channels: dict[str, QCheckBox] = {}
        sas.addRow(self._sas_enabled)
        sas.addRow("Address", self._sas_address)
        sas.addRow("Funds transfer", self._sas_transfer)
        sas.addRow(self._sas_aft)
        sas.addRow(self._sas_lock)
        for field, label, _classes in SAS_CHANNEL_FIELDS:
            box = QCheckBox(f"is {label[0].lower()}{label[1:]}")
            box.setChecked(True)
            self._sas_channels[field] = box
            sas.addRow(box)
        board.add_box(sas_box, 10)

        sw_box, sw = _group_form("Door switches")
        self._switches_enabled = QCheckBox("Enable switches")
        self._switches_enabled.setChecked(True)
        self._sw_stacker = QCheckBox("Stacker installed auto-unlock")
        self._sw_stacker.setChecked(True)
        self._sw_all = QCheckBox("Auto unlock all doors")
        self._sw_all.setChecked(False)
        self._sw_all.setToolTip(
            "Sets HardwareConfig AutoUnlock on every door. "
            "Live 10.0.0.111 is all off. Switch Config Intelligent also "
            "writes encrypted bios/etc/application/game/switches.xml "
            "(not edited here)."
        )
        sw.addRow(self._switches_enabled)
        sw.addRow(self._sw_stacker)
        sw.addRow(self._sw_all)
        self._switch_auto: dict[str, QCheckBox] = {}
        self._switch_offline: dict[str, QCheckBox] = {}
        self._switch_alert: dict[str, QComboBox] = {}
        self._switch_order: list[str] = []
        for name, label in (
            ("cabinet_door", "Cabinet door"),
            ("logic_door", "Logic door"),
            ("note_door", "Note door"),
            ("drop_door", "Drop door"),
            ("stacker_door", "Stacker"),
            ("auxiliary_door", "Auxiliary door"),
        ):
            auto = QCheckBox("Auto unlock")
            auto.setChecked(False)
            offline = QCheckBox("Offline trigger")
            offline.setChecked(False)
            alert = QComboBox()
            alert.addItems(list(DOOR_SWITCH_ALERTS))
            alert.setCurrentText("BOTH" if name == "cabinet_door" else "SEMAPHORE")
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)
            row_l.addWidget(auto)
            row_l.addWidget(offline)
            row_l.addWidget(alert, 1)
            sw.addRow(label, row)
            self._switch_auto[name] = auto
            self._switch_offline[name] = offline
            self._switch_alert[name] = alert
            self._switch_order.append(name)
        self._sw_all.toggled.connect(self._on_switch_all_toggled)
        for box in self._switch_auto.values():
            box.toggled.connect(self._sync_switch_all_from_doors)
        board.add_box(sw_box, 10)

        hw_box, hw = _group_form("Bill & ticket hardware")
        self._bill = QComboBox()
        self._bill.addItem("(not set in QuixantHardware.xml)", "")
        for proto in BILL_PROTOCOLS:
            self._bill.addItem(proto, proto)
        self._ticket = QComboBox()
        self._ticket.addItem("(not set)", "")
        for proto in TICKET_PROTOCOLS:
            self._ticket.addItem(TICKET_PROTOCOL_LABELS[proto], proto)
        hw.addRow("Bill acceptor", self._bill)
        self._bill_tokens_table = QTableWidget(0, 5)
        self._bill_tokens_table.setHorizontalHeaderLabels(
            ["Code", "Live", "Target", "Accept", "Match"]
        )
        self._bill_tokens_table.verticalHeader().setVisible(False)
        self._bill_tokens_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._bill_tokens_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._bill_tokens_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._bill_tokens_table.setMaximumHeight(160)
        _style_bill_tokens_table(self._bill_tokens_table)
        self._bill_tokens_table.itemChanged.connect(self._on_bill_accept_item_changed)
        self._bill_tokens_table.setToolTip(
            "MEI/JCM bill codes from HardwareConfig.xml TokenMapping.\n"
            "Accept = CanAccept: off rejects that note but keeps the mapping "
            "(OneHand still needs the code). Apply writes HardwareConfig.xml."
        )
        hw.addRow("Bill notes", self._bill_tokens_table)
        self._bill_tokens_hint = QLabel(
            "Load a cabinet to preview bill note mappings (HardwareConfig TokenMapping)."
        )
        self._bill_tokens_hint.setWordWrap(True)
        self._bill_tokens_hint.setStyleSheet("color: #999; font-size: 11px;")
        hw.addRow("", self._bill_tokens_hint)
        hw.addRow("Ticket printer", self._ticket)
        self._ticket_printer_status = QLabel("Load a cabinet to detect printer status.")
        self._ticket_printer_status.setWordWrap(True)
        self._ticket_printer_status.setStyleSheet("color: #999; font-size: 11px;")
        hw.addRow("TITO / printer", self._ticket_printer_status)
        board.add_box(hw_box, 8)

        ticket_box, ticket = _group_form("Ticketing")
        self._offline = QComboBox()
        self._offline.addItem("Leave as-is", None)
        self._offline.addItem("Offline ticket mode on", True)
        self._offline.addItem("Offline ticket mode off", False)
        self._offline.setToolTip(
            "HardwareConfig OfflineEnabled — standalone ticket mode without a SAS host. "
            "This is not the ticket printer: JCM/FutureLogic TITO can print and redeem "
            "with offline mode off when Redeem enabled is on."
        )
        self._ticket_hint = QLabel("")
        self._ticket_hint.setWordWrap(True)
        self._ticket_hint.setStyleSheet("color: #999; font-size: 11px;")
        ticket.addRow("Offline ticket mode", self._offline)
        ticket.addRow("", self._ticket_hint)
        self._redeem = _bool_combo()
        self._ticket_iso = _bool_combo()
        ticket.addRow("Redeem enabled", self._redeem)
        ticket.addRow("Use currency ISO", self._ticket_iso)
        board.add_box(ticket_box, 3)

        limit_box, limit = _group_form("Limit setup")
        self._limit_spins: dict[str, QSpinBox] = {}
        currency_hint = QLabel("Amounts are in machine currency units (e.g. TTD).")
        currency_hint.setWordWrap(True)
        currency_hint.setStyleSheet("color: #888; font-size: 11px;")
        limit.addRow(currency_hint)
        for spec in LIMIT_SETUP_FIELDS:
            spin = QSpinBox()
            spin.setRange(0, 99_999_999)
            spin.setSingleStep(100)
            spin.setGroupSeparatorShown(True)
            self._limit_spins[spec.key] = spin
            limit.addRow(spec.label, spin)
        board.add_box(limit_box, 8)

        cab_hw_box, cab_hw = _group_form("Cabinet hardware")
        self._display_mode = QComboBox()
        self._display_mode.addItem("leave as-is", None)
        self._display_mode.addItem("2 screens (dual top)", "2")
        self._display_mode.addItem("3 screens (vertical stack)", "3")
        self._dallas = QComboBox()
        self._dallas.setEditable(True)
        for code, label in DALLAS_CHOICES:
            shown = label if not code else f"{label} ({code})"
            self._dallas.addItem(shown, code)
        dallas_row = QWidget()
        dallas_layout = QHBoxLayout(dallas_row)
        dallas_layout.setContentsMargins(0, 0, 0, 0)
        dallas_layout.setSpacing(6)
        dallas_layout.addWidget(self._dallas, 1)
        self._dallas_read = QPushButton("Read key")
        self._dallas_read.setToolTip(
            "Insert the Dallas iButton on the cabinet, then click.\n"
            "Reads today's SlotLog / MultiHardware logs first (~1s).\n"
            "If the key was already inserted, returns immediately.\n"
            "Otherwise waits up to ~15s watching today's logs."
        )
        self._dallas_read.clicked.connect(self._read_dallas_from_hardware)
        dallas_layout.addWidget(self._dallas_read)
        self._hw_deck = QComboBox()
        self._hw_deck.addItem("leave as-is", None)
        for prof in list_hw_driver_profiles():
            self._hw_deck.addItem(prof.label, prof.id)
        cab_hw.addRow("Display layout", self._display_mode)
        cab_hw.addRow("Dallas key", dallas_row)
        cab_hw.addRow("Button deck (keyboard + LEDs)", self._hw_deck)
        board.add_box(cab_hw_box, 3)

        lic_box, lic = _group_form("Licence")
        self._licence_box = lic_box
        self._licence_label = QLabel("Load a cabinet to detect licence files.")
        self._licence_label.setWordWrap(True)
        self._paint_licence_status()
        self._licence_push = QCheckBox("Push missing licence files")
        self._licence_push.setEnabled(False)
        self._licence_push_tip = (
            "After Load, tick this to copy licence XML / licence.dll onto the "
            "cabinet only where they are missing. Never overwrites a live "
            "licence. OneHand reads XML next to itself in slot\\ — a pack that "
            "landed only in Licenses\\ shows No licence!."
        )
        self._licence_push.setToolTip(self._licence_push_tip)
        src_row = QWidget()
        src_layout = QHBoxLayout(src_row)
        src_layout.setContentsMargins(0, 0, 0, 0)
        src_layout.setSpacing(6)
        self._licence_source = QLineEdit()
        self._licence_source.setPlaceholderText(
            "USB licence / licenses folder (auto-detected after Load)"
        )
        self._licence_browse = QPushButton("Browse…")
        self._licence_browse.clicked.connect(self._browse_licence_pack)
        src_layout.addWidget(self._licence_source, 1)
        src_layout.addWidget(self._licence_browse)
        lic.addRow(self._licence_label)
        lic.addRow(self._licence_push)
        lic.addRow("Source", src_row)
        board.add_box(lic_box, 3)

        scroll.setWidget(board)
        outer.addWidget(scroll, stretch=1)

        self._changes = QLabel(
            "Load a cabinet, set currency / market and denom first, then the rest. "
            "Licence is last. Apply writes and restarts."
        )
        self._changes.setWordWrap(True)
        self._changes.setStyleSheet("color: #999;")
        outer.addWidget(self._changes)

        self._math_fix = QFrame()
        math_fix_outer = QVBoxLayout(self._math_fix)
        math_fix_outer.setContentsMargins(0, 4, 0, 4)
        math_fix_outer.setSpacing(4)
        self._math_fix_hint = QLabel("")
        self._math_fix_hint.setWordWrap(True)
        self._math_fix_hint.setStyleSheet("color: #aaa;")
        math_fix_outer.addWidget(self._math_fix_hint)
        self._math_fix_buttons = QHBoxLayout()
        self._math_fix_buttons.setContentsMargins(0, 0, 0, 0)
        self._math_fix_buttons.setSpacing(8)
        math_fix_outer.addLayout(self._math_fix_buttons)
        self._math_fix.hide()
        outer.addWidget(self._math_fix)

        self._currency.currentTextChanged.connect(self._currency_chosen)
        self._market.currentTextChanged.connect(self._target_market_chosen)
        self._denoms.currentIndexChanged.connect(self._denom_chosen)
        for widget in (
            self._sas_enabled,
            self._sas_address,
            self._sas_transfer,
            self._sas_aft,
            self._sas_lock,
            *            self._sas_channels.values(),
            self._switches_enabled,
            self._sw_stacker,
            self._sw_all,
            *self._switch_auto.values(),
            *self._switch_offline.values(),
            *self._switch_alert.values(),
            self._currency,
            self._symbol,
            self._culture,
            self._language,
            self._market,
            self._denoms,
            self._bets,
            self._default_bet,
            self._show_denom,
            self._mw_limit,
            self._mw_bet,
            self._mw_enabled,
            self._mw_spins,
            self._mw_average,
            self._jp_counters,
            self._jp_layout,
            self._jp_celebration,
            self._cashout,
            self._bill,
            self._ticket,
            self._offline,
            self._redeem,
            self._ticket_iso,
            self._dallas,
            self._hw_deck,
            self._inactivity,
            self._show_all_lines,
            self._display_mode,
            self._licence_push,
            *self._limit_spins.values(),
        ):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._refresh_changes)
                widget.currentTextChanged.connect(self._refresh_changes)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._refresh_changes)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._refresh_changes)
        self._licence_source.textChanged.connect(self._refresh_changes)

        self._restart = QCheckBox("Restart game after write")
        self._restart.setChecked(True)
        self._restart.setToolTip(
            "After writing configs: stop OneHand if needed, then start Bootstrap "
            "so the new settings take effect. Turn off only if you will restart manually."
        )
        self._restart.toggled.connect(self._sync_commit_button)
        self._full_pack = QCheckBox("Write full pack")
        self._full_pack.setChecked(False)
        self._full_pack.setToolTip(
            "Off (default): only write files for fields that differ from the cabinet "
            "(delta). On: rewrite the full Live Push config pack even for unchanged fields."
        )
        self._backup = QCheckBox("Backup overwritten files")
        self._backup.setChecked(False)
        self._backup.setToolTip(
            "Optional, off by default. When checked, copy the live files that will "
            "change into live_push_backups/<timestamp>/ under the Config Scanner folder "
            "before overwrite."
        )
        flags = QHBoxLayout()
        flags.setContentsMargins(0, 0, 0, 0)
        flags.setSpacing(16)
        flags.addWidget(self._restart)
        flags.addWidget(self._full_pack)
        flags.addStretch(1)

        self._status = QLabel("")
        self._status.setWordWrap(True)

        opts = QVBoxLayout()
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(4)
        opts.addLayout(flags)
        opts.addWidget(self._status)

        self._commit = QPushButton("Apply")
        self._commit.setObjectName("primary")
        self._commit.setMinimumHeight(40)
        self._commit.setMinimumWidth(200)
        self._commit.setEnabled(True)
        self._commit.clicked.connect(self._commit_clicked)
        self._sync_commit_button()

        self._export_cs = QPushButton("Export full CS .b2u…")
        self._export_cs.setMinimumHeight(40)
        self._export_cs.setToolTip(
            "After the cabinet is tuned: list live settings, overlay them into a "
            "Country Selector leaf, and encrypt an official-style .b2u."
        )
        self._export_cs.clicked.connect(self._export_full_cs_clicked)

        self._check_logs = QPushButton("Check SlotLog")
        self._check_logs.setMinimumHeight(40)
        self._check_logs.setToolTip(
            "Read var/log/SlotLog after the game starts for misconfig "
            "(invalid market, denoms, SAS lock, RAMCLEAR). "
            "Runs automatically ~90s after Apply, once OneHand has time to finish boot."
        )
        self._check_logs.clicked.connect(self._check_slotlog_clicked)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(12)
        action_row.addLayout(opts, stretch=1)
        action_row.addWidget(
            self._check_logs,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        action_row.addWidget(
            self._export_cs,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        action_row.addWidget(
            self._commit,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        outer.addLayout(action_row)
        backup_row = QHBoxLayout()
        backup_row.setContentsMargins(0, 4, 0, 0)
        backup_row.addWidget(self._backup)
        backup_row.addStretch(1)
        outer.addLayout(backup_row)

        self._install_field_file_menus()
        self._install_label_click_tips()
        # Light paint only — do not SMB-autoload until ensure_started().
        self._paint_live_highlights()

        if autoload:
            QTimer.singleShot(0, self.ensure_started)

    def ensure_started(self) -> None:
        """Start the first cabinet load once (safe to call from rapid navigation)."""
        if self._started:
            return
        self._started = True
        QTimer.singleShot(0, self._autoload)

    def _live_field_widgets(self) -> list[tuple[str, QWidget]]:
        return [
            ("SAS enabled", self._sas_enabled),
            ("SAS address", self._sas_address),
            ("Funds transfer", self._sas_transfer),
            ("AFT", self._sas_aft),
            ("Lock when no SAS", self._sas_lock),
            *(
                (label, self._sas_channels[field])
                for field, label, _classes in SAS_CHANNEL_FIELDS
            ),
            ("Enable switches", self._switches_enabled),
            ("Stacker auto-unlock", self._sw_stacker),
            *(
                (door_switch_auto_unlock_label(name), self._switch_auto[name])
                for name in STANDARD_DOOR_SWITCH_NAMES
            ),
            ("Bill protocol", self._bill),
            ("Bill notes", self._bill_tokens_table),
            ("Ticket printer", self._ticket),
            ("Offline ticket", self._offline),
            ("Ticket redeem", self._redeem),
            ("Ticket currency ISO", self._ticket_iso),
            *(
                (spec.label, self._limit_spins[spec.key])
                for spec in LIMIT_SETUP_FIELDS
            ),
            ("Display layout", self._display_mode),
            ("Dallas key", self._dallas),
            ("Button deck", self._hw_deck),
            ("Currency", self._currency),
            ("Currency symbol", self._symbol),
            ("Culture", self._culture),
            ("Language", self._language),
            ("Market", self._market),
            ("Denoms (cents)", self._denoms),
            ("Bet multipliers", self._bets),
            ("Magic wheel limit", self._mw_limit),
            ("Magic wheel bet", self._mw_bet),
            ("Magic wheel enabled", self._mw_enabled),
            ("Magic wheel max spins", self._mw_spins),
            ("Magic wheel average", self._mw_average),
            ("Jackpot counters", self._jp_counters),
            ("Jackpot receipt", self._jp_layout),
            ("Jackpot celebration", self._jp_celebration),
            ("Cashout button", self._cashout),
            ("Default bet", self._default_bet),
            ("Show denom selector", self._show_denom),
            ("Inactivity to selector", self._inactivity),
            ("Show all lines", self._show_all_lines),
        ]

    def _is_live_field_editable(self, label: str, widget: QWidget) -> bool:
        for spec in LIMIT_SETUP_FIELDS:
            if spec.label == label:
                return not widget.isReadOnly()
        return True

    def _paint_live_highlights(self) -> None:
        matches: dict[str, bool] = {}
        invalid: dict[str, str] = {}
        form_corrupt: dict[str, str] = {}
        after = None
        if self._loaded is not None and not self._applying:
            try:
                after = self._recipe_from_form()
                matches = live_field_matches(self._loaded, after)
                invalid = live_field_validation_errors(
                    self._validation_errors(self._loaded, after)
                )
                form_corrupt = recipe_display_corruption_errors(after)
            except ValueError:
                matches = {}
                invalid = {}
                form_corrupt = {}
                after = None
        corrupt = {**self._display_corruption, **form_corrupt}
        palette = self.palette()
        match_sheet = live_match_field_stylesheet(palette)
        changed_sheet = live_changed_field_stylesheet(palette)
        invalid_sheet = live_invalid_field_stylesheet(palette)
        cabinet_loaded = self._loaded is not None
        log_errs = finding_field_errors(self._slotlog_findings)
        leftover_single = None
        if self._goldclub is not None and self._loaded is not None:
            leftover_single = leftover_jurisdiction_single_denomination(
                self._goldclub, list(self._loaded.denomination_list)
            )
        for label, widget in self._live_field_widgets():
            editable = self._is_live_field_editable(label, widget)
            matches_live = bool(matches.get(label))
            if label == "Denoms (cents)" and leftover_single is not None:
                matches_live = False
            corrupt_reason = corrupt.get(label, "")
            inv = field_highlight_error(
                matches_live=matches_live,
                validation_error=invalid.get(label, "") or corrupt_reason,
                log_error=log_errs.get(label, ""),
            )
            state = live_field_highlight_state(
                matches_live=matches_live,
                editable=editable,
                cabinet_loaded=cabinet_loaded,
                invalid_reason=inv,
            )
            help_text = LIVE_OPTION_HELP.get(label, "")
            if label == "Denoms (cents)" and leftover_single is not None:
                live_first = (
                    self._loaded.denomination_list[0]
                    if self._loaded and self._loaded.denomination_list
                    else "?"
                )
                help_text = (
                    f"{help_text}\n\nCabinet leftover: jurisdiction_config "
                    f"SingleDenomination is still {leftover_single}c while "
                    f"mgconfig is {live_first}c. Apply writes the on-screen denom."
                ).strip()
            kind = (
                "corrupt"
                if corrupt_reason and not invalid.get(label)
                else "live_math"
                if "link2win" in (inv or "").casefold()
                or "bonusmath" in (inv or "").casefold()
                else ""
            )
            file_note = live_field_file_hover(
                label,
                self._goldclub,
                playable_denoms_from_recipe(after) if after is not None else None,
                validation_error=inv,
            )
            tip = live_field_tooltip(
                state,
                detail=inv,
                help_text=help_text,
                invalid_kind=kind,
                file_note=file_note,
            )
            if isinstance(widget, QTableWidget):
                widget.setToolTip(tip)
                self._sync_form_label_tooltip(widget, widget.toolTip())
                continue
            if state == "invalid":
                widget.setStyleSheet(invalid_sheet)
                widget.setToolTip(tip)
            elif state == "match":
                widget.setStyleSheet(match_sheet)
                widget.setToolTip(tip)
            elif state in ("changed", "editable"):
                widget.setStyleSheet(changed_sheet)
                widget.setToolTip(tip)
            else:
                widget.setStyleSheet("")
                widget.setToolTip(tip if tip else help_text)
            self._sync_form_label_tooltip(widget, widget.toolTip())

    def _field_label_for_widget(self, widget: QWidget) -> str:
        for label, field in self._live_field_widgets():
            if widget is field:
                return label
            try:
                if widget.isAncestorOf(field) or field.isAncestorOf(widget):
                    return label
            except RuntimeError:
                continue
        return ""

    def _sync_form_label_tooltip(self, widget: QWidget, tip: str) -> None:
        """Copy field hover text onto the caption so a tap can show the same help."""
        for form in self.findChildren(QFormLayout):
            lab = form.labelForField(widget)
            parent = widget.parentWidget()
            if lab is None and parent is not None:
                lab = form.labelForField(parent)
            if lab is not None:
                lab.setToolTip(tip)
                return

    def _install_label_click_tips(self) -> None:
        """Form captions show the field tooltip on tap (no mouse hover on EGMs)."""
        for form in self.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                if label_item is None:
                    continue
                lab = label_item.widget()
                if not isinstance(lab, QLabel):
                    continue
                prepare_form_label_for_touch(lab)
                lab.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if mouse_release_shows_tip(watched, event):
            return True
        return super().eventFilter(watched, event)

    def _install_field_file_menus(self) -> None:
        seen: set[int] = set()
        for label, widget in self._live_field_widgets():
            self._attach_open_config_menu(widget, label)
            seen.add(id(widget))
            for child in widget.findChildren(QLineEdit):
                if id(child) not in seen:
                    self._attach_open_config_menu(child, label)
                    seen.add(id(child))
        for form in self.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field_w = field_item.widget() if field_item is not None else None
                if field_w is None:
                    continue
                label = self._field_label_for_widget(field_w)
                if not label:
                    continue
                if id(field_w) not in seen:
                    self._attach_open_config_menu(field_w, label)
                    seen.add(id(field_w))
                if label_item is None:
                    continue
                lab_w = label_item.widget()
                if lab_w is not None and id(lab_w) not in seen:
                    self._attach_open_config_menu(lab_w, label)
                    seen.add(id(lab_w))

    def _attach_open_config_menu(self, widget: QWidget, label: str) -> None:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, w=widget, lab=label: self._show_field_file_menu(w, pos, lab)
        )

    def _show_field_file_menu(self, widget: QWidget, pos, label: str) -> None:
        menu = QMenu(widget)
        goldclub = self._goldclub
        if goldclub is None:
            act = menu.addAction("Load a cabinet to open this setting's file")
            act.setEnabled(False)
            menu.exec(widget.mapToGlobal(pos))
            return
        paths = resolve_live_field_config_files(goldclub, label)
        if not paths:
            act = menu.addAction(f"Config file for {label} not found")
            act.setEnabled(False)
        else:
            for path in paths:
                act = menu.addAction(f"Open {path.name} in Notepad")
                act.triggered.connect(
                    lambda _checked=False, p=path: self._open_config_in_notepad(p)
                )
        menu.exec(widget.mapToGlobal(pos))

    def _open_config_in_notepad(self, path: Path) -> None:
        ok, msg = open_with_notepad(path)
        if not ok:
            QMessageBox.warning(self, "Open file", msg)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_live_highlights()
            self._paint_licence_status()

    def _autoload(self) -> None:
        if self._busy:
            return
        self._silent_load = True
        self._status.setText("Reading live cabinet…")
        self._load()

    def _pick_cabinet(self, path: str) -> None:
        self._path.setText(path)
        self._load()

    def _browse(self) -> None:
        start = self._path.text().strip() or r"C:\Goldclub"
        if start.startswith("\\\\"):
            start = r"C:\Goldclub"
        path = QFileDialog.getExistingDirectory(self, "Goldclub root", start)
        if path:
            self._path.setText(path)
            self._load()

    def _load(self) -> None:
        if self._busy:
            return
        raw = self._path.text().strip()
        if not raw:
            QMessageBox.warning(self, "Load", "Enter a cabinet Goldclub path.")
            return
        self._set_busy(True)
        self._status.setText("Connecting to cabinet…")
        QThreadPool.globalInstance().start(_LoadRunnable(raw, self._load_emitter))

    def _on_load_finished(self, outcome: object) -> None:
        silent = self._silent_load
        self._silent_load = False
        self._set_busy(False)
        if not isinstance(outcome, LiveLoadOutcome):
            self._status.setText("Load failed.")
            return
        if outcome.error or outcome.recipe is None:
            msg = outcome.error or "Cannot load cabinet."
            if not silent:
                QMessageBox.warning(self, "Load", msg)
            self._status.setText(msg)
            self._goldclub = None
            self._display_corruption = {}
            self._update_licence_ui(None)
            self._paint_live_highlights()
            return
        self._loaded = outcome.recipe
        self._goldclub = outcome.root
        self._display_corruption = dict(outcome.display_corruption or {})
        if outcome.root is not None:
            self._onehand_markets = markets_accepted_by_onehand(outcome.root)
            self._fill_market_combo(keep=outcome.recipe.jurisdiction.tag)
        self._fill_form(outcome.recipe)
        self._update_ticket_hint(outcome.root)
        self._update_licence_ui(outcome.licence, goldclub=outcome.root)
        self._status.setText(outcome.status)
        self._refresh_changes()

    def _update_ticket_hint(self, root) -> None:
        if root is None:
            self._ticket_hint.setText("")
            self._ticket_printer_status.setText("Load a cabinet to detect printer status.")
            return
        try:
            printer_on = read_ticket_printer_active(root)
        except (OSError, TimeoutError, ValueError):
            printer_on = False
        offline = self._loaded.offline_enabled if self._loaded else None
        ticket_proto = (self._loaded.ticket_protocol or "").strip() if self._loaded else ""
        if printer_on:
            proto_s = ticket_proto or "configured"
            self._ticket_printer_status.setText(
                f"Active ({proto_s}). Printing and redeem work independently of "
                f"offline ticket mode below."
            )
        else:
            self._ticket_printer_status.setText(
                "Not active in HardwareConfig (printer disabled or redeem off)."
            )
        if printer_on and offline is False:
            self._ticket_hint.setText(
                "Offline ticket mode is off, but TITO printing still works — that flag "
                "only enables standalone hostless ticket mode, not the physical printer."
            )
        elif printer_on and offline is True:
            self._ticket_hint.setText(
                "Both offline ticket mode and TITO printing are enabled on this cabinet."
            )
        elif printer_on:
            self._ticket_hint.setText("")
        else:
            self._ticket_hint.setText("")

    def _paint_licence_status(self) -> None:
        pal = self.palette()
        status = self._licence_status
        if status is None:
            color = muted_text(pal)
        elif status.playable:
            color = text_success(pal)
        elif status.needs_push:
            color = text_warning(pal)
        else:
            color = muted_text(pal)
        self._licence_label.setStyleSheet(
            f"color: {color.name()}; font-size: 11px;"
            + (" font-weight: 600;" if status is not None and status.playable else "")
        )
        box = getattr(self, "_licence_box", None)
        if box is not None:
            if status is not None and status.playable:
                box.setStyleSheet(f"QGroupBox::title {{ color: {color.name()}; }}")
            else:
                box.setStyleSheet("")

    def _update_licence_ui(
        self,
        status: LiveLicenceStatus | None,
        *,
        goldclub: Path | None = None,
    ) -> None:
        self._licence_status = status
        self._licence_goldclub = goldclub
        self._licence_pack_origin = ""
        if status is None:
            self._licence_label.setText("Load a cabinet to detect licence files.")
            self._licence_push.setChecked(False)
            self._licence_push.setEnabled(False)
            self._licence_source.clear()
            self._licence_source.setEnabled(False)
            self._licence_browse.setEnabled(False)
            self._licence_push.setToolTip(self._licence_push_tip)
            self._paint_licence_status()
            return
        self._licence_label.setText(status.detail)
        self._licence_push.setEnabled(True)
        self._licence_source.setEnabled(True)
        self._licence_browse.setEnabled(True)
        self._autofill_licence_source(goldclub)
        debug_onehand = False
        if goldclub is not None:
            try:
                debug_onehand = is_onehand_debug_build(goldclub)
            except OSError:
                debug_onehand = False
        self._licence_push.setChecked(
            licence_push_default_checked(
                needs_push=status.needs_push,
                can_mirror=status.can_mirror,
                has_source=bool(self._licence_source.text().strip()),
                debug_onehand=debug_onehand,
            )
        )
        if debug_onehand:
            self._licence_push.setToolTip(
                "OneHand version is Debug — licence push is off so lab debug "
                "builds do not get production licence XML. Tick to force a copy."
            )
            if status.needs_push:
                self._licence_label.setText(
                    status.detail.rstrip(".")
                    + ". OneHand is Debug — licence push left off."
                )
        else:
            self._licence_push.setToolTip(self._licence_push_tip)
        self._paint_licence_status()

    def _autofill_licence_source(self, goldclub: Path | None) -> None:
        status = self._licence_status
        if status is None:
            self._licence_source.clear()
            return
        skip = [goldclub] if goldclub is not None else []
        extra_hosts: list[str] = []
        if goldclub is not None:
            from config_scanner.stack_restart import unc_host_from_target

            host = unc_host_from_target(str(goldclub))
            if host:
                extra_hosts.append(host)
        hit = discover_preferred_licence_pack(
            skip_roots=skip,
            extra_hosts=extra_hosts or None,
        )
        if hit is None:
            self._licence_source.clear()
            self._licence_source.setToolTip(
                "No USB licence or licenses folder found. Leave empty to copy "
                "from this cabinet's licence/licenses folder when it has files."
            )
            return
        self._licence_source.setText(str(hit.root))
        self._licence_pack_origin = hit.origin
        self._licence_source.setToolTip(
            f"USB: {hit.file_count} licence file(s) in {hit.root}"
        )

    def _browse_licence_pack(self) -> None:
        start = self._licence_source.text().strip() or r"C:\Goldclub"
        path = QFileDialog.getExistingDirectory(self, "Licence pack folder", start)
        if not path:
            return
        found = discover_licence_source_files(Path(path))
        if not found:
            QMessageBox.warning(
                self,
                "Licence pack",
                "No licence XML or licence.dll in that folder "
                "(looked in Licenses/, slot/, and Content/tmp).",
            )
            return
        self._licence_source.setText(path)
        self._licence_pack_origin = "browse"
        if self._licence_push.isEnabled():
            self._licence_push.setChecked(True)

    def _licence_change_lines(self) -> list[str]:
        if not self._licence_push.isChecked():
            return []
        status = self._licence_status
        if status is None or not status.needs_push:
            return []
        src = self._licence_source.text().strip()
        if src:
            extra = " (USB)" if self._licence_pack_origin == "usb" else ""
            return [f"Licence files: missing → copy from {src} into slot\\{extra}"]
        if status.can_mirror:
            return [
                "Licence files: missing next to OneHand → copy into slot\\"
            ]
        return []

    def _want_licence_push(self) -> bool:
        if not self._licence_push.isChecked():
            return False
        status = self._licence_status
        if status is None or not status.needs_push:
            return False
        src = self._licence_source.text().strip()
        return bool(status.can_mirror or src)

    def _fill_form(self, recipe) -> None:
        self._applying = True
        self._refresh_timer.stop()
        widgets = [w for _, w in self._live_field_widgets()]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self._sas_enabled.setChecked(bool(recipe.sas.enabled))
            self._sas_address.setValue(int(recipe.sas.address or 1))
            idx = self._sas_transfer.findText(recipe.sas.funds_transfer_type or "AFT")
            self._sas_transfer.setCurrentIndex(max(idx, 0))
            self._sas_aft.setChecked(bool(recipe.sas.aft_enabled))
            self._sas_lock.setChecked(bool(recipe.sas.lock_game_when_no_comms))
            for field, box in self._sas_channels.items():
                box.setChecked(bool(getattr(recipe.sas, field, True)))
            self._switches_enabled.setChecked(bool(recipe.door_switches.enabled))
            self._sw_stacker.setChecked(
                bool(recipe.door_switches.stacker_installed_auto_unlock)
            )
            by_name = {row.name: row for row in recipe.door_switches.items}
            for name in self._switch_order:
                row = by_name.get(name)
                self._switch_auto[name].setChecked(
                    bool(row.auto_unlock) if row else False
                )
                self._switch_offline[name].setChecked(
                    bool(row.offline_trigger) if row else False
                )
                alert = row.alert_type if row else (
                    "BOTH" if name == "cabinet_door" else "SEMAPHORE"
                )
                idx = self._switch_alert[name].findText(alert)
                self._switch_alert[name].setCurrentIndex(max(idx, 0))
            self._sync_switch_all_from_doors()
            currency = recipe.jurisdiction.currency_name or recipe.hardware_currency_name
            _set_combo_code(self._currency, currency)
            symbol = recipe.jurisdiction.currency_symbol or currency_symbol_for(currency)
            _set_combo_code(self._symbol, symbol)
            _set_combo_code(self._culture, recipe.jurisdiction.culture_name)
            lang = (recipe.mg_identity.language or "").strip()
            if lang:
                _set_combo_code(self._language, lang)
            else:
                self._language.setCurrentIndex(-1)
                if self._language.isEditable():
                    self._language.setEditText("")
            _set_combo_code(self._market, recipe.jurisdiction.tag)
            denoms = ", ".join(str(d) for d in recipe.denomination_list)
            self._refresh_denom_choices(keep=denoms)
            _set_combo_code(self._denoms, denoms, editable_ok=False)
            pl = recipe.play_limits
            bets = list(pl.bet_multipliers)
            if not bets and recipe.math:
                bets = list(recipe.math[0].bet_multipliers)
            if bets:
                _set_combo_code(
                    self._bets, ", ".join(str(n) for n in bets)
                )
            else:
                self._bets.setCurrentIndex(0)
            _set_optional_str(self._default_bet, pl.default_bet)
            _set_optional_bool(self._show_denom, pl.show_denom_selector)
            _set_optional_int(self._mw_limit, recipe.jurisdiction.magic_wheel_money_limit)
            _set_optional_int(self._mw_bet, pl.magic_wheel_bet)
            _set_optional_bool(self._mw_enabled, pl.magic_wheel_enabled)
            _set_optional_int(self._mw_spins, pl.magic_wheel_max_spins)
            _set_optional_int(self._mw_average, pl.magic_wheel_average)
            _set_optional_int(self._jp_counters, pl.jackpot_counters)
            _set_optional_str(self._jp_layout, pl.jackpot_receipt_layout)
            _set_optional_str(self._jp_celebration, pl.celebration_limit)
            _set_optional_str(self._cashout, pl.cashout_button_mode)
            proto = (recipe.bill_protocol or "").strip()
            bidx = self._bill.findText(proto) if proto else -1
            self._bill.setCurrentIndex(bidx if bidx >= 0 else -1)
            _set_combo_code(self._ticket, (recipe.ticket_protocol or "").strip())
            if recipe.offline_enabled is True:
                self._offline.setCurrentIndex(1)
            elif recipe.offline_enabled is False:
                self._offline.setCurrentIndex(2)
            else:
                self._offline.setCurrentIndex(0)
            _set_optional_bool(self._redeem, pl.ticket_redeem_enabled)
            _set_optional_bool(self._ticket_iso, pl.ticket_use_currency_iso)
            dallas = recipe.dallas.code or ""
            _set_combo_code(self._dallas, dallas)
            if dallas and self._dallas.findData(dallas) < 0:
                self._dallas.setEditText(dallas)
            ina = recipe.mg_identity.inactivity_seconds_to_game_selector
            want_ina = -1 if ina is None else int(ina)
            iidx = self._inactivity.findData(want_ina)
            if iidx < 0 and want_ina >= 0:
                self._inactivity.addItem(f"{want_ina} seconds", want_ina)
                iidx = self._inactivity.findData(want_ina)
            self._inactivity.setCurrentIndex(max(iidx, 0))
            _set_optional_bool(self._show_all_lines, pl.show_all_lines)
            mode = recipe.display_mode
            if mode in ("2", "3"):
                idx = self._display_mode.findData(mode)
                if idx < 0:
                    self._display_mode.addItem(f"{mode} screens", mode)
                    idx = self._display_mode.findData(mode)
                self._display_mode.setCurrentIndex(max(idx, 0))
            else:
                self._display_mode.setCurrentIndex(0)
            hw = recipe.hw_driver_profile
            if hw:
                hidx = self._hw_deck.findData(hw)
                if hidx < 0:
                    self._hw_deck.addItem(hw, hw)
                    hidx = self._hw_deck.findData(hw)
                self._hw_deck.setCurrentIndex(max(hidx, 0))
            else:
                self._hw_deck.setCurrentIndex(0)
            ls = recipe.limit_setup
            for spec in LIMIT_SETUP_FIELDS:
                self._limit_spins[spec.key].setValue(int(ls.value_for(spec.key) or 0))
            self._apply_limit_field_locks(ls)
        finally:
            for widget in widgets:
                widget.blockSignals(False)
            self._applying = False
        self._reset_bill_accept = True
        self._refresh_changes_now()

    def _on_switch_all_toggled(self, checked: bool) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            for box in self._switch_auto.values():
                box.setChecked(bool(checked))
        finally:
            self._applying = False
        self._refresh_changes()

    def _sync_switch_all_from_doors(self) -> None:
        all_on = bool(self._switch_auto) and all(
            box.isChecked() for box in self._switch_auto.values()
        )
        self._sw_all.blockSignals(True)
        self._sw_all.setChecked(all_on)
        self._sw_all.blockSignals(False)

    def _apply_limit_field_locks(self, limits) -> None:
        for spec in LIMIT_SETUP_FIELDS:
            spin = self._limit_spins[spec.key]
            if limits.host_locked_for(spec.key):
                spin.setReadOnly(True)
                spin.setToolTip(
                    f"{spec.label}: locked by SAS host (read-only, not editable in Live Push)"
                )
            elif limits.egm_locked_for(spec.key):
                spin.setReadOnly(True)
                spin.setToolTip(
                    f"{spec.label}: locked by EGM software (read-only, not editable in Live Push)"
                )
            else:
                spin.setReadOnly(False)
                spin.setToolTip("")

    def _on_bill_accept_item_changed(self, item: QTableWidgetItem) -> None:
        if self._applying or item is None or item.column() != 3:
            return
        self._refresh_changes()

    def _bill_accept_checked(self) -> dict[str, bool]:
        return {
            code: item.checkState() == Qt.CheckState.Checked
            for code, item in self._bill_accept.items()
        }

    def _refresh_bill_tokens_view(self) -> None:
        """Live HardwareConfig vs target values, plus CanAccept checkboxes."""
        if self._loaded is None:
            self._bill_accept.clear()
            self._bill_tokens_table.setRowCount(0)
            self._bill_tokens_hint.setText(
                "Load a cabinet to preview bill note mappings "
                "(HardwareConfig TokenMapping)."
            )
            self._bill_tokens_hint.setStyleSheet("color: #999; font-size: 11px;")
            return

        live = list(self._loaded.bill_tokens)
        live_map = bill_tokens_by_code(live)
        reset_accept = self._reset_bill_accept
        self._reset_bill_accept = False
        preserved: dict[str, bool] = {}
        if not reset_accept:
            preserved = self._bill_accept_checked()

        preset_tokens: list[BillToken] = []
        preset_label = ""
        jid = self._preset.currentData()
        if jid:
            preset = recipe_from_market_id(str(jid))
            if preset and preset.bill_tokens:
                preset_tokens = list(preset.bill_tokens)
                preset_label = preset.label or str(jid)
        currency = (
            _combo_code(self._currency)
            or self._loaded.jurisdiction.currency_name
            or self._loaded.hardware_currency_name
            or ""
        )
        target, target_label = resolve_target_bill_tokens(
            preset_tokens=preset_tokens,
            preset_label=preset_label,
            currency_name=currency,
        )
        has_target = bool(target)

        rows = bill_tokens_compare_rows(live, target)
        ok_bg = QBrush(QColor(40, 90, 40, 80))
        warn_bg = QBrush(QColor(120, 80, 20, 90))
        miss_bg = QBrush(QColor(120, 40, 40, 80))
        idle_bg = QBrush(QColor(80, 80, 80, 40))
        row_codes = tuple(r.code for r in rows)
        current_codes = tuple(
            (self._bill_tokens_table.item(i, 0).text() if self._bill_tokens_table.item(i, 0) else "")
            for i in range(self._bill_tokens_table.rowCount())
        )
        reuse = (
            not reset_accept
            and current_codes == row_codes
            and len(self._bill_accept) == sum(1 for r in rows if r.code in live_map)
        )

        def _row_style(row) -> tuple[str, QBrush]:
            if not has_target:
                return "\u2014", idle_bg
            if row.matches:
                return "yes", ok_bg
            if row.live_only or row.target_only:
                return "missing", miss_bg
            return "no", warn_bg

        was_applying = self._applying
        self._applying = True
        try:
            if not reuse:
                self._bill_accept.clear()
                self._bill_tokens_table.clearContents()
                self._bill_tokens_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                live_txt = "\u2014" if row.live_value is None else str(row.live_value)
                target_txt = "\u2014" if row.target_value is None else str(row.target_value)
                match_txt, bg = _row_style(row)
                for col, text in enumerate((row.code, live_txt, target_txt)):
                    item = QTableWidgetItem(text)
                    item.setBackground(bg)
                    self._bill_tokens_table.setItem(i, col, item)
                if not reuse:
                    live_token = live_map.get(row.code)
                    if live_token is not None:
                        checked = preserved.get(row.code, live_token.can_accept)
                        accept_item = QTableWidgetItem()
                        accept_item.setFlags(
                            Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsSelectable
                        )
                        accept_item.setCheckState(
                            Qt.CheckState.Checked
                            if checked
                            else Qt.CheckState.Unchecked
                        )
                        accept_item.setToolTip(
                            f"CanAccept for code {row.code}. Off rejects this bill; "
                            "the mapping stays so OneHand can still look up the code."
                        )
                        accept_item.setBackground(bg)
                        self._bill_tokens_table.setItem(i, 3, accept_item)
                        self._bill_accept[row.code] = accept_item
                    else:
                        empty = QTableWidgetItem("")
                        empty.setBackground(bg)
                        empty.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                        self._bill_tokens_table.setItem(i, 3, empty)
                else:
                    accept_item = self._bill_tokens_table.item(i, 3)
                    if accept_item is not None:
                        accept_item.setBackground(bg)
                match_item = QTableWidgetItem(match_txt)
                match_item.setBackground(bg)
                self._bill_tokens_table.setItem(i, 4, match_item)
        finally:
            self._applying = was_applying
        _fit_bill_tokens_columns(self._bill_tokens_table)

        live_sum = summarize_bill_tokens(live)
        if target_label:
            hint = (
                f"Live: {live_sum} | Target ({target_label}): "
                f"{summarize_bill_tokens(target)}"
            )
        else:
            hint = (
                f"Live: {live_sum} | No bill.tokens for this currency yet "
                "(only TTD has a built-in table)."
            )
        warnings = bill_tokens_warning_lines(live, target)
        if warnings:
            hint += "\n" + " | ".join(warnings[:4])
        if target and bill_tokens_all_match(live, target) and not warnings:
            self._bill_tokens_hint.setStyleSheet("color: #6a6; font-size: 11px;")
        elif warnings or (target and not bill_tokens_all_match(live, target)):
            self._bill_tokens_hint.setStyleSheet("color: #c96; font-size: 11px;")
        else:
            self._bill_tokens_hint.setStyleSheet("color: #999; font-size: 11px;")
        self._bill_tokens_hint.setText(hint)

    def _parse_int_list(self, combo: QComboBox) -> list[int]:
        out: list[int] = []
        for part in _combo_code(combo).replace(";", ",").split(","):
            bit = part.strip().rstrip("cC")
            if not bit:
                continue
            try:
                out.append(int(bit))
            except ValueError:
                continue
        return out

    def _parse_denoms(self) -> list[int]:
        return self._parse_int_list(self._denoms)

    def _recipe_from_form(self, base=None):
        seed = base if base is not None else self._loaded
        if seed is None:
            jid = self._preset.currentData()
            if jid:
                seed = recipe_from_market_id(str(jid))
            if seed is None:
                raise ValueError("Load a cabinet or pick a market first.")
        recipe = type(seed).from_dict(seed.to_dict())
        recipe.sas.enabled = self._sas_enabled.isChecked()
        recipe.sas.address = int(self._sas_address.value())
        recipe.sas.funds_transfer_type = self._sas_transfer.currentText()
        recipe.sas.aft_enabled = self._sas_aft.isChecked()
        recipe.sas.lock_game_when_no_comms = self._sas_lock.isChecked()
        for field, box in self._sas_channels.items():
            setattr(recipe.sas, field, box.isChecked())
        items: list[DoorSwitchRow] = []
        for name in self._switch_order:
            default_alert = "BOTH" if name == "cabinet_door" else "SEMAPHORE"
            items.append(
                DoorSwitchRow(
                    name=name,
                    alert_type=self._switch_alert[name].currentText() or default_alert,
                    auto_unlock=self._switch_auto[name].isChecked(),
                    offline_trigger=self._switch_offline[name].isChecked(),
                )
            )
        recipe.door_switches = DoorSwitchSettings(
            enabled=self._switches_enabled.isChecked(),
            stacker_installed_auto_unlock=self._sw_stacker.isChecked(),
            items=items,
        )
        currency = _combo_code(self._currency)
        recipe.jurisdiction.currency_name = currency
        recipe.jurisdiction.culture_name = _combo_code(self._culture)
        recipe.jurisdiction.tag = _combo_code(self._market)
        symbol = _combo_code(self._symbol) or currency_symbol_for(currency)
        recipe.jurisdiction.currency_symbol = symbol
        recipe.mg_identity.language = _combo_code(self._language).strip()
        recipe.hardware_currency_name = currency
        denoms = self._parse_denoms()
        if denoms:
            recipe.denomination_list = denoms
            recipe.credit_rate_values = list(denoms)
            if len(denoms) == 1 and self._loaded is not None:
                live_denoms = list(self._loaded.denomination_list or [])
                if live_denoms != denoms:
                    bet, average = expected_magic_wheel_for_denom(denoms[0])
                    recipe.play_limits.magic_wheel_bet = bet
                    recipe.play_limits.magic_wheel_average = average
        bets = self._parse_int_list(self._bets)
        if bets:
            recipe.play_limits.bet_multipliers = bets
        default_bet = _optional_str(self._default_bet)
        if default_bet:
            recipe.play_limits.default_bet = default_bet
        show_denom = _optional_bool(self._show_denom)
        if show_denom is not None:
            recipe.play_limits.show_denom_selector = show_denom
        mw_limit = _optional_int(self._mw_limit)
        if mw_limit is not None:
            recipe.jurisdiction.magic_wheel_money_limit = mw_limit
        mw_bet = _optional_int(self._mw_bet)
        if mw_bet is not None:
            recipe.play_limits.magic_wheel_bet = mw_bet
        mw_on = _optional_bool(self._mw_enabled)
        if mw_on is not None:
            recipe.play_limits.magic_wheel_enabled = mw_on
        mw_spins = _optional_int(self._mw_spins)
        if mw_spins is not None:
            recipe.play_limits.magic_wheel_max_spins = mw_spins
        mw_avg = _optional_int(self._mw_average)
        if mw_avg is not None:
            recipe.play_limits.magic_wheel_average = mw_avg
        jp_n = _optional_int(self._jp_counters)
        if jp_n is not None:
            recipe.play_limits.jackpot_counters = jp_n
        jp_layout = _optional_str(self._jp_layout)
        if jp_layout:
            recipe.play_limits.jackpot_receipt_layout = jp_layout
        celebration = _optional_str(self._jp_celebration)
        if celebration:
            recipe.play_limits.celebration_limit = celebration
        cashout = _optional_str(self._cashout)
        if cashout:
            recipe.play_limits.cashout_button_mode = cashout
        bill = self._bill.currentData()
        if bill is None:
            bill = self._bill.currentText().strip()
        recipe.bill_protocol = str(bill).strip() if str(bill).strip() in BILL_PROTOCOLS else ""
        if recipe.bill_tokens and self._bill_accept:
            recipe.bill_tokens = apply_bill_token_accept(
                recipe.bill_tokens,
                self._bill_accept_checked(),
            )
        ticket = self._ticket.currentData()
        if ticket is None:
            ticket = _combo_code(self._ticket)
        ticket_s = str(ticket).strip().upper()
        recipe.ticket_protocol = ticket_s if ticket_s in TICKET_PROTOCOLS else ""
        offline = self._offline.currentData()
        if offline is not None:
            recipe.offline_enabled = offline
            recipe.include_oticket = bool(offline)
        redeem = _optional_bool(self._redeem)
        if redeem is not None:
            recipe.play_limits.ticket_redeem_enabled = redeem
        ticket_iso = _optional_bool(self._ticket_iso)
        if ticket_iso is not None:
            recipe.play_limits.ticket_use_currency_iso = ticket_iso
        dallas = _combo_code(self._dallas)
        if dallas:
            recipe.dallas.code = dallas
        ina = self._inactivity.currentData()
        if ina is None or int(ina) < 0:
            recipe.mg_identity.inactivity_seconds_to_game_selector = None
        else:
            recipe.mg_identity.inactivity_seconds_to_game_selector = int(ina)
        show_lines = _optional_bool(self._show_all_lines)
        if show_lines is not None:
            recipe.play_limits.show_all_lines = show_lines
        disp = self._display_mode.currentData()
        if disp in ("2", "3"):
            recipe.display_mode = str(disp)
        else:
            recipe.display_mode = None
        hw = self._hw_deck.currentData()
        recipe.hw_driver_profile = str(hw).strip() if hw else None
        for spec in LIMIT_SETUP_FIELDS:
            if recipe.limit_setup.editable_for(spec.key):
                recipe.limit_setup.set_value(
                    spec.key, int(self._limit_spins[spec.key].value())
                )
        return recipe

    def _live_denoms_for_choices(self) -> tuple[int, ...]:
        if self._loaded is not None and self._loaded.denomination_list:
            return tuple(int(d) for d in self._loaded.denomination_list)
        return tuple(self._parse_denoms())

    def _fill_market_combo(self, *, keep: str = "") -> None:
        codes = ordered_live_markets(
            self._catalog["markets"],
            accepted=self._onehand_markets,
        )
        current = (keep or _combo_code(self._market)).strip()
        was = self._applying
        self._applying = True
        try:
            self._market.blockSignals(True)
            self._market.clear()
            for code in codes:
                self._market.addItem(market_combo_label(code), code)
            if current:
                _set_combo_code(self._market, current, editable_ok=True)
            elif self._market.count():
                self._market.setCurrentIndex(0)
        finally:
            self._market.blockSignals(False)
            self._applying = was

    def _refresh_denom_choices(self, *, keep: str = "") -> None:
        currency = _combo_code(self._currency)
        market = _combo_code(self._market)
        choices = denom_combo_choices(
            currency, market, live_denoms=self._live_denoms_for_choices()
        )
        current = (keep or _combo_code(self._denoms)).strip()
        if not current and self._loaded is not None and len(self._loaded.denomination_list) == 1:
            current = str(self._loaded.denomination_list[0])
        self._applying = True
        try:
            self._denoms.clear()
            for choice in choices:
                self._denoms.addItem(choice, choice)
            if current:
                _set_combo_code(self._denoms, current, editable_ok=True)
        finally:
            self._applying = False

    def _read_dallas_from_hardware(self) -> None:
        if self._busy or self._dallas_busy:
            return
        raw = self._path.text().strip()
        root, err = prepare_live_goldclub(raw)
        if root is None:
            QMessageBox.warning(self, "Dallas key", err or "Cabinet path not ready.")
            return
        self._dallas_busy = True
        self._dallas_read.setEnabled(False)
        self._status.setText(
            "Insert the iButton now — reading OneHand/SlotLog and bottom HW logs…"
        )
        runnable = _DallasReadRunnable(root, self._dallas_emitter)
        QThreadPool.globalInstance().start(runnable)

    def _on_dallas_finished(self, result: object) -> None:
        self._dallas_busy = False
        self._dallas_read.setEnabled(not self._busy)
        if not isinstance(result, DallasReadResult) or not result.ok or not result.code:
            detail = ""
            if isinstance(result, DallasReadResult):
                if result.source:
                    detail = f"\n\n({result.source})"
                if result.diagnostics:
                    detail += f"\n\n{result.diagnostics}"
            QMessageBox.information(
                self,
                "Dallas key",
                "No Dallas code found yet.\n\n"
                "Insert the iButton while OneHand is running, or in BiOS2 / "
                "HardwareSetup (bottom hardware).\n"
                "Then click Read key again — it waits up to ~20s with slow polls."
                + detail,
            )
            self._status.setText("Dallas key not found.")
            return
        code = result.code
        if self._dallas.findData(code) < 0:
            label = "from OneHand" if result.via == "onehand" else "from hardware"
            self._dallas.addItem(f"{label} ({code})", code)
        _set_combo_code(self._dallas, code, editable_ok=True)
        self._refresh_changes()
        via = result.via or "log"
        src = f" ({result.source})" if result.source else ""
        self._status.setText(f"Dallas key read via {via}: {code}{src}")

    def _denom_chosen(self, _index: int = -1) -> None:
        if self._applying:
            return
        denoms = self._parse_denoms()
        if len(denoms) != 1:
            self._refresh_changes()
            return
        bet, average = expected_magic_wheel_for_denom(denoms[0])
        self._applying = True
        try:
            _set_combo_code(self._mw_bet, str(bet))
            _set_combo_code(self._mw_average, str(average))
        finally:
            self._applying = False
        self._refresh_changes()

    def _market_or_currency_changed(self, _text: str = "") -> None:
        if self._applying:
            return
        keep = ""
        if self._loaded is not None and len(self._loaded.denomination_list) == 1:
            keep = str(self._loaded.denomination_list[0])
        elif self._denoms.currentIndex() >= 0:
            keep = _combo_code(self._denoms)
        self._refresh_denom_choices(keep=keep)
        self._refresh_changes()

    def _target_market_chosen(self, _text: str = "") -> None:
        """Target market dropdown: apply jurisdiction locale as a soft UI preset."""
        if self._applying:
            return
        market = _combo_code(self._market)
        snapped = False
        if self._onehand_markets:
            existing = (
                self._loaded.jurisdiction.tag if self._loaded is not None else ""
            )
            resolved = resolve_target_market_for_mgconfig(market, existing)
            if resolved not in self._onehand_markets:
                market = pick_onehand_allowed_market(
                    self._onehand_markets, preferred=resolved or market
                )
                snapped = True
                self._applying = True
                try:
                    _set_combo_code(self._market, market)
                finally:
                    self._applying = False
        defaults = locale_defaults_for_market(market)
        if defaults is None:
            self._market_or_currency_changed()
            if snapped:
                self._status.setText(
                    f"Target market snapped to {market} "
                    "(not in this OneHand Market enum)."
                )
            return
        self._applying = True
        try:
            if defaults.currency:
                _set_combo_code(self._currency, defaults.currency)
            if defaults.culture:
                _set_combo_code(self._culture, defaults.culture)
            if defaults.language:
                _set_combo_code(self._language, defaults.language)
            if defaults.symbol:
                _set_combo_code(self._symbol, defaults.symbol)
            # Keep the operator's exact market token if they typed a variant.
            if defaults.market and not market:
                _set_combo_code(self._market, defaults.market)
            keep = ""
            if self._loaded is not None and len(self._loaded.denomination_list) == 1:
                keep = str(self._loaded.denomination_list[0])
            elif defaults.denoms:
                keep = str(defaults.denoms[0])
            self._refresh_denom_choices(keep=keep)
        finally:
            self._applying = False
        self._refresh_changes()
        bits = [
            part
            for part in (
                defaults.currency,
                defaults.culture,
                defaults.language,
            )
            if part
        ]
        note = (
            f"Snapped to {market} (not in this OneHand). "
            if snapped
            else ""
        )
        self._status.setText(
            note
            + f"Preset from {defaults.market or market}: "
            + ", ".join(bits)
            + " (editable)."
        )

    def _reload_market_combo(self, select_id: str | None = None) -> None:
        keep = select_id if select_id is not None else self._preset.currentData()
        was = self._applying
        self._applying = True
        try:
            self._preset.blockSignals(True)
            self._preset.clear()
            self._preset.addItem("(cabinet values / pick a market)", None)
            for prof in load_jurisdictions():
                self._preset.addItem(prof.label, prof.id)
            if keep:
                idx = self._preset.findData(keep)
                if idx >= 0:
                    self._preset.setCurrentIndex(idx)
        finally:
            self._preset.blockSignals(False)
            self._applying = was

    def _create_market(self) -> None:
        try:
            recipe = self._recipe_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, "Create market", str(exc))
            return
        currency = str(recipe.jurisdiction.currency_name or "").strip()
        market = str(recipe.jurisdiction.tag or "").strip()
        suggested_label = suggest_jurisdiction_label(market=market, currency=currency)
        suggested_id = suggest_jurisdiction_id(market=market, currency=currency)
        dialog = CreateMarketDialog(
            self,
            suggested_id=suggested_id,
            suggested_label=suggested_label,
            suggested_country=market or currency,
            notes="Saved from Live Push.",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile_id, label, country, notes = dialog.values()
        existing = find_jurisdiction(profile_id)
        if existing is not None:
            answer = QMessageBox.question(
                self,
                "Replace market?",
                f"A market named {existing.label} ({profile_id}) already exists. Replace it?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        profile = profile_from_recipe(
            recipe,
            profile_id=profile_id,
            label=label,
            country=country,
            notes=notes or "Saved from Live Push.",
        )
        _path, replaced = upsert_jurisdiction(profile)
        self._reload_market_combo(select_id=profile.id)
        action = "Replaced" if replaced else "Created"
        self._status.setText(f"{action} market {profile.label} ({profile.id}).")

    def _market_chosen(self) -> None:
        if self._applying:
            return
        jid = self._preset.currentData()
        if not jid:
            if self._loaded is not None:
                self._fill_form(self._loaded)
                self._refresh_changes()
            return
        preset = recipe_from_market_id(str(jid))
        if preset is None:
            return
        if self._loaded is not None:
            merged = overlay_jurisdiction_recipe(self._loaded, preset)
        else:
            merged = preset
        snapped = ""
        if self._onehand_markets:
            resolved = resolve_target_market_for_mgconfig(
                merged.jurisdiction.tag,
                self._loaded.jurisdiction.tag if self._loaded is not None else "",
            )
            if resolved not in self._onehand_markets:
                snapped = pick_onehand_allowed_market(
                    self._onehand_markets, preferred=resolved
                )
                merged.jurisdiction.tag = snapped
        self._fill_form(merged)
        self._refresh_changes()
        msg = (
            f"Filled from {self._preset.currentText()}. Dallas key kept from the cabinet."
        )
        if snapped:
            msg += f" Target market snapped to {snapped}."
        self._status.setText(msg)

    def _currency_chosen(self, _text: str = "") -> None:
        if self._applying:
            return
        code = _combo_code(self._currency)
        defaults = locale_defaults_for_currency(code)
        if defaults is None:
            self._refresh_changes()
            return
        snapped = False
        self._applying = True
        try:
            _set_combo_code(self._culture, defaults.culture)
            _set_combo_code(self._language, defaults.language)
            market = defaults.market
            if self._onehand_markets:
                existing = ""
                if self._loaded is not None:
                    existing = self._loaded.jurisdiction.tag
                resolved = resolve_target_market_for_mgconfig(market, existing)
                if resolved in self._onehand_markets:
                    market = resolved
                else:
                    market = pick_onehand_allowed_market(
                        self._onehand_markets,
                        preferred=resolved or existing or market,
                    )
                    snapped = True
            _set_combo_code(self._market, market)
            if defaults.symbol:
                _set_combo_code(self._symbol, defaults.symbol)
            keep = ""
            if self._loaded is not None and len(self._loaded.denomination_list) == 1:
                keep = str(self._loaded.denomination_list[0])
            elif defaults.denoms:
                keep = str(defaults.denoms[-1])
            self._refresh_denom_choices(keep=keep)
            if keep and self._loaded is None:
                _set_combo_code(self._denoms, keep, editable_ok=False)
        finally:
            self._applying = False
        self._refresh_changes()
        if snapped:
            self._status.setText(
                f"Currency {code}: Target market set to {market} "
                "(allowed by this OneHand)."
            )

    def _validation_errors(self, live, after) -> list[str]:
        raw = self._path.text().strip()
        if not raw:
            return ["Enter a cabinet Goldclub path."]
        root = goldclub_root_from_target(raw)
        return validate_live_push_recipe(live, after, root)

    def _clear_math_fix_buttons(self) -> None:
        while self._math_fix_buttons.count():
            item = self._math_fix_buttons.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _update_math_fix_row(self, targets: tuple[MathReplaceTarget, ...]) -> None:
        self._clear_math_fix_buttons()
        if not targets:
            self._math_fix.hide()
            return
        need = ", ".join(f"{d}c" for d in targets[0].denoms)
        self._math_fix_hint.setText(
            f"Cabinet Link2Win math must include {need}. Browse a matching file "
            "to replace the live copy on disk, then configuration is re-checked."
        )
        for target in targets:
            btn = QPushButton(f"Browse {target.label}…")
            btn.setToolTip(
                f"Replace {target.relative_path} on the cabinet with math "
                f"that includes {need}."
            )
            btn.clicked.connect(
                lambda checked=False, t=target: self._browse_math_replacement(t)
            )
            self._math_fix_buttons.addWidget(btn)
        self._math_fix_buttons.addStretch(1)
        self._math_fix.show()

    def _browse_math_replacement(self, target: MathReplaceTarget) -> None:
        raw = self._path.text().strip()
        if not raw:
            QMessageBox.warning(self, "Math file", "Load a cabinet path first.")
            return
        root = goldclub_root_from_target(raw)
        start = str(root / "slot/themes/Link2WinFeature")
        try:
            after = self._recipe_from_form()
            screens = _combo_code(self._display_mode) or None
            leaf = find_staged_leaf_for_denom(
                min(target.denoms),
                currency=_combo_code(self._currency),
                market=_combo_code(self._market),
                screens=screens,
            )
            if leaf is not None:
                candidate = leaf / "slot/themes/Link2WinFeature" / target.label
                if candidate.is_file():
                    start = str(candidate.parent)
        except (ValueError, OSError):
            pass
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Replace {target.label} on cabinet",
            start,
            "Link2Win math (*.json);;All files (*.*)",
        )
        if not path:
            return
        backup_dir: Path | None = None
        if self._backup.isChecked():
            from config_scanner.live_push import tool_root

            backup_dir = (
                tool_root()
                / "live_push_backups"
                / datetime.now().strftime("%Y%m%d-%H%M%S")
                / "math"
            )
        try:
            replace_cabinet_math_file(
                root, target, Path(path), backup_dir=backup_dir
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Math file", str(exc))
            return
        try:
            self._loaded = load_recipe_from_goldclub(root, label="live")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Math file",
                f"Replaced {target.label} but could not reload cabinet: {exc}",
            )
        self._refresh_changes_now()
        self._paint_live_highlights()
        self._status.setText(
            f"Replaced {target.relative_path} on cabinet; configuration re-checked."
        )

    def _refresh_changes(self) -> None:
        """Debounced — rapid combo edits coalesce into one paint pass."""
        if self._applying:
            return
        self._refresh_timer.start()

    def _refresh_changes_now(self) -> None:
        if self._applying:
            return
        if self._loaded is None:
            self._update_math_fix_row(())
            self._changes.setText(
                "Waiting for the live cabinet (local Goldclub, or \\\\10.0.0.111\\slot). "
                "Green = matches; orange = pending edit; red = invalid."
            )
            self._changes.setStyleSheet("color: #999;")
            self._commit.setEnabled(not self._busy)
            self._paint_live_highlights()
            self._refresh_bill_tokens_view()
            return
        try:
            after = self._recipe_from_form()
        except ValueError:
            return
        errors = self._validation_errors(self._loaded, after)
        lines = recipe_change_lines(self._loaded, after)
        lines.extend(self._licence_change_lines())
        raw = self._path.text().strip()
        math_targets: tuple[MathReplaceTarget, ...] = ()
        if raw:
            math_targets = list_link2win_math_replace_targets(
                self._loaded, after, goldclub_root_from_target(raw)
            )
        self._update_math_fix_row(math_targets)
        if raw:
            restage = link2win_restage_change_line(
                self._loaded, after, goldclub_root_from_target(raw)
            )
            if restage:
                lines.append(restage)
        if errors:
            self._changes.setText("Cannot apply:\n• " + "\n• ".join(errors))
            self._changes.setStyleSheet("color: #c66;")
            self._commit.setEnabled(False)
        elif not lines:
            self._changes.setText(
                "All editable fields match the live cabinet (green). Nothing queued to write."
            )
            self._changes.setStyleSheet("color: #999;")
            self._commit.setEnabled(not self._busy)
        else:
            self._changes.setText("Will change:\n• " + "\n• ".join(lines))
            self._changes.setStyleSheet("color: #999;")
            self._commit.setEnabled(not self._busy)
        self._paint_live_highlights()
        self._refresh_bill_tokens_view()

    def _sync_commit_button(self, *_args) -> None:
        restart = self._restart.isChecked()
        if restart:
            self._commit.setText("Apply & restart game")
            self._commit.setToolTip(
                "Write the orange (changed) fields to the cabinet, stop the game, "
                "then start Bootstrap so settings take effect. Red fields block Apply."
            )
        else:
            self._commit.setText("Apply")
            self._commit.setToolTip(
                "Write the orange (changed) fields to the cabinet without restarting "
                "the game. Turn on Restart game after write if you want Bootstrap started. "
                "Red fields block Apply."
            )

    def _commit_clicked(self) -> None:
        if self._busy:
            return
        raw = self._path.text().strip()
        root, err = prepare_live_goldclub(raw)
        if root is None:
            QMessageBox.warning(self, "Apply", err)
            return
        try:
            live = load_recipe_from_goldclub(root, label="live")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Apply", str(exc))
            return
        self._loaded = live
        try:
            after = self._recipe_from_form(base=live)
        except ValueError as exc:
            QMessageBox.warning(self, "Apply", str(exc))
            return
        errors = self._validation_errors(live, after)
        if errors:
            QMessageBox.warning(self, "Apply", errors[0])
            self._refresh_changes()
            return
        self._licence_status = inspect_live_licences(root)
        lines = recipe_change_lines(live, after)
        lines.extend(self._licence_change_lines())
        restage = link2win_restage_change_line(live, after, root)
        if restage:
            lines.append(restage)
        restart = self._restart.isChecked()
        backup = self._backup.isChecked()
        full_pack = self._full_pack.isChecked()
        push_licences = self._want_licence_push()
        if not lines and not full_pack:
            QMessageBox.information(self, "Apply", "Nothing changed.")
            self._fill_form(live)
            return
        kind = goldclub_stack_kind(root)
        try:
            aurum_code = read_aurum_currency_code(root)
        except (OSError, ValueError):
            aurum_code = ""
        ramclear_why = live_push_ramclear_reasons(
            live, after, aurum_currency=aurum_code
        )
        force_restart = bool(ramclear_why) and kind == "slot"
        effective_restart = restart or force_restart
        if effective_restart and kind == "slot":
            extra = (
                "\n\nOneHand will stop, the files will be written, then Bootstrap starts. "
                "Windows will not reboot."
            )
            if force_restart and not restart:
                extra += (
                    "\n(Restart is required because a RAM clear will run.)"
                )
        elif effective_restart:
            extra = (
                "\n\nThe game will stop, the files will be written, then the stack starts again. "
                "Windows will not reboot."
            )
        else:
            extra = "\n\nFiles will be written. The game will not be restarted."
        if full_pack:
            extra += "\n\nFull pack: all Live Push config files will be rewritten."
        else:
            extra += "\n\nDelta: only files for the listed changes will be written."
        if backup:
            extra += "\nA backup of those live files is taken first."
        if push_licences:
            extra += (
                "\n\nMissing licence XML / licence.dll will be copied next to "
                "OneHand (existing licence files are not overwritten)."
            )
        warns = validate_live_push_warnings(live, after, root)
        if warns:
            extra += "\n\nNote:\n• " + "\n• ".join(warns[:4])
        if ramclear_why and kind == "slot":
            extra += (
                "\n\nRAM clear will run after write (required for: "
                + ", ".join(ramclear_why)
                + "). This clears meters / NVRAM trial state. HWSubsys is "
                "restarted before Bootstrap."
            )
        body = (
            "Write these settings?\n\n• " + "\n• ".join(lines) + extra
            if lines
            else "Write the full Live Push pack?" + extra
        )
        reply = QMessageBox.question(self, "Apply to cabinet", body)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        self._status.setText("Starting…")
        runnable = _CommitRunnable(
            after,
            root,
            restart_stack=effective_restart,
            scan_target=raw,
            emitter=self._emitter,
            backup=backup,
            full_pack=full_pack,
            push_licences=push_licences,
            licence_source=self._licence_source.text().strip() or None,
        )
        QThreadPool.globalInstance().start(runnable)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._commit.setEnabled(not busy)
        self._load_btn.setEnabled(not busy)
        self._dallas_read.setEnabled(not busy and not self._dallas_busy)
        for btn in self._shortcut_btns:
            btn.setEnabled(not busy)

    def _on_progress(self, message: str) -> None:
        self._status.setText(message)

    def _export_full_cs_clicked(self) -> None:
        raw = self._path.text().strip()
        if not raw:
            QMessageBox.warning(self, "Export CS", "Load a live cabinet path first.")
            return
        try:
            live_root = goldclub_root_from_target(raw)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export CS", str(exc))
            return
        if not live_root.is_dir():
            QMessageBox.warning(self, "Export CS", f"Goldclub not found:\n{live_root}")
            return

        market = _combo_code(self._market) or ""
        profile_id = self._preset.currentData()
        allowed = markets_accepted_by_onehand(live_root)
        existing_market = read_mgconfig_target_market(live_root)
        resolved = (
            resolve_target_market_for_mgconfig(market, existing_market)
            if market
            else existing_market
        )
        if allowed and resolved and resolved not in allowed:
            listed = ", ".join(sorted(allowed))
            QMessageBox.warning(
                self,
                "Export CS",
                f"This cabinet's OneHand does not accept Target market {resolved!r} "
                f"(Market enum: {listed}).\n\n"
                "A Jamaica Country Selector pack may exist on the lab share, but it "
                "will not run on this GameStar 2.0.1 TRI binary. Set Target market to "
                f"{listed} or TT, then Export CS (Trinidad pack).",
            )
            return
        if allowed == frozenset({"PuertoRico"}):
            market = "Trinidad"
        src = pick_cs_source_for_export(
            market,
            profile_id=str(profile_id or ""),
        )
        if src is None:
            QMessageBox.warning(
                self,
                "Export CS",
                "No Country Selector pack found for this market.\n"
                "Use Create → pick a pack/leaf → Export full Country Selector from live.",
            )
            return

        out = QFileDialog.getExistingDirectory(
            self, "Where to save the full Country Selector .b2u"
        )
        if not out:
            return

        self._status.setText(f"Materializing {src.label}…")
        try:
            tool = resolve_cs_source(src)
            leaves = discover_leaves(tool)
            if not leaves:
                raise FileNotFoundError(f"no leaves under {tool}")
            denoms = self._denoms.currentText().strip()
            prefer_bits: list[str] = []
            if self._offline.currentData() is True:
                prefer_bits.append("OL")
            if denoms:
                first = denoms.split(",")[0].strip()
                if first.isdigit():
                    prefer_bits.append(f"{first}c")
            scored: list[tuple[int, object]] = []
            for cand in leaves:
                score = 0
                mode_u = (cand.mode or "").upper()
                country_u = (cand.country or "").casefold()
                for bit in prefer_bits:
                    if bit.upper() in mode_u or bit in (cand.mode or ""):
                        score += 1
                if market and (
                    market.casefold() in country_u or country_u in market.casefold()
                ):
                    score += 2
                scored.append((score, cand))
            scored.sort(key=lambda t: t[0], reverse=True)
            leaf = scored[0][1] if scored else leaves[0]

            package_name = f"CS-{src.id}-Live".replace("share-", "")
            result = export_full_country_selector(
                Path(out),
                live_goldclub=live_root,
                country_tool_dir=tool,
                leaf=leaf,
                package_name=package_name,
                encrypt=True,
            )
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Export CS", str(exc))
            self._status.setText("Export failed.")
            return

        sample = "\n".join(
            f"  {r['label']}: {r['value']}" for r in result.settings_rows[:10]
        )
        QMessageBox.information(
            self,
            "Full Country Selector ready",
            f"{result.note}\n\n"
            f"Pack: {src.label}\n"
            f"Leaf: {leaf.country} / {leaf.screens} / {leaf.mode}\n"
            f"Settings: {result.settings_report}\n\n"
            f"{sample}",
        )
        self._status.setText(result.note)

    def _on_finished(self, result: object) -> None:
        self._set_busy(False)
        if not isinstance(result, LivePushResult):
            self._status.setText("Apply failed.")
            return
        bits = [
            f"Wrote {len(result.written)} file(s).",
        ]
        if result.sections:
            bits.append(f"Sections: {', '.join(result.sections)}.")
        if result.backup_dir:
            bits.append(f"Backup: {result.backup_dir}")
        if result.skipped:
            bits.append(f"Skipped {len(result.skipped)}.")
        if result.stack_killed:
            bits.append("Game was stopped.")
        if result.ramclear_ran:
            bits.append("RAM clear ran.")
        elif result.ramclear_detail:
            bits.append(result.ramclear_detail.splitlines()[0][:120])
        if result.stack_started:
            bits.append("Game started.")
        elif result.stack_detail:
            bits.append(result.stack_detail.splitlines()[-1])
        text = " ".join(bits)
        if result.errors:
            QMessageBox.warning(
                self,
                "Apply finished with errors",
                text + "\n\n" + "\n".join(result.errors[:8]),
            )
            self._status.setText("Finished with errors.")
            return
        self._last_backup_dir = result.backup_dir or ""
        self._last_apply_since = datetime.now().astimezone()
        self._slotlog_findings = []
        QMessageBox.information(
            self,
            "Apply complete",
            text
            + "\n\nAfter the game starts, Config Scanner will review SlotLog "
            "for misconfig (invalid market, denoms, SAS lock). "
            "You can also click Check SlotLog.",
        )
        self._status.setText(text)
        self._load()
        if result.stack_started:
            self._start_slotlog_review(wait_sec=90.0)
        else:
            self._start_slotlog_review(wait_sec=5.0)

    def _check_slotlog_clicked(self) -> None:
        if self._busy or self._dallas_busy:
            return
        self._start_slotlog_review(wait_sec=0.0)

    def _start_slotlog_review(self, *, wait_sec: float) -> None:
        raw = self._path.text().strip()
        if not raw:
            QMessageBox.warning(self, "SlotLog", "Load a cabinet path first.")
            return
        try:
            goldclub = goldclub_root_from_target(raw)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "SlotLog", str(exc))
            return
        if not goldclub.is_dir():
            QMessageBox.warning(self, "SlotLog", f"Goldclub not found:\n{goldclub}")
            return
        since = self._last_apply_since
        if since is None:
            # Manual Check without a recent Apply: prefer recent noise, not all morning.
            since = datetime.now().astimezone() - timedelta(minutes=30)
        self._check_logs.setEnabled(False)
        self._status.setText(
            f"SlotLog review queued ({int(wait_sec)}s wait)…"
            if wait_sec
            else "Reading SlotLog…"
        )
        QThreadPool.globalInstance().start(
            _SlotLogReviewRunnable(
                goldclub, since, wait_sec, self._review_emitter
            )
        )

    def _on_slotlog_review_finished(self, result: object) -> None:
        self._check_logs.setEnabled(True)
        if not isinstance(result, SlotLogReview):
            self._status.setText("SlotLog review failed.")
            return
        self._slotlog_findings = [
            f for f in result.findings if f.severity in ("error", "warning")
        ]
        _lp_log(
            "slotlog review actionable="
            f"{int(result.has_actionable)} ids="
            f"{[f.id for f in result.findings]!r} note={result.note!r}"
        )
        self._paint_live_highlights()
        if not result.has_actionable:
            self._status.setText(result.note or "SlotLog: no misconfig found.")
            return
        self._status.setText(
            f"SlotLog: {len(self._slotlog_findings)} issue(s) — see dialog."
        )
        self._show_slotlog_findings(result)

    def _show_slotlog_findings(self, review: SlotLogReview) -> None:
        summary = format_review_summary(review)
        # Enrich market fix with live OneHand enum when possible.
        extra = ""
        try:
            goldclub = goldclub_root_from_target(self._path.text().strip())
            allowed = sorted(markets_accepted_by_onehand(goldclub) or ())
            if allowed:
                extra = f"\n\nThis OneHand accepts Target market: {', '.join(allowed)}"
        except (OSError, ValueError, TypeError):
            extra = ""

        has_backup = bool(self._last_backup_dir) and Path(self._last_backup_dir).is_dir()
        if has_backup:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("SlotLog misconfig")
            box.setText(summary + extra)
            box.setInformativeText(
                "Fix the highlighted field(s) and Apply again, or restore the "
                "pre-push backup."
            )
            restore_btn = box.addButton(
                "Restore backup…", QMessageBox.ButtonRole.ActionRole
            )
            box.addButton("Acknowledge", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is restore_btn:
                self._restore_last_backup()
            return

        QMessageBox.warning(
            self,
            "SlotLog misconfig",
            summary
            + extra
            + "\n\nFix the highlighted field(s) (e.g. Target market / denoms) "
            "and Apply again.",
        )

    def _restore_last_backup(self) -> None:
        bak = self._last_backup_dir
        if not bak or not Path(bak).is_dir():
            QMessageBox.warning(self, "Restore", "No pre-push backup is available.")
            return
        raw = self._path.text().strip()
        try:
            goldclub = goldclub_root_from_target(raw)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Restore", str(exc))
            return
        reply = QMessageBox.question(
            self,
            "Restore backup",
            f"Copy files from:\n{bak}\n\nback onto:\n{goldclub}\n\n"
            "Then restart the game from Apply (or reboot). Continue?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = restore_live_push_backup(Path(bak), goldclub)
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Restore", str(exc))
            return
        self._slotlog_findings = []
        self._paint_live_highlights()
        QMessageBox.information(
            self,
            "Backup restored",
            f"Restored {len(restored)} file(s).\n"
            "Use Apply & restart (or restart Bootstrap) so OneHand reloads them.",
        )
        self._status.setText(f"Restored {len(restored)} file(s) from backup.")
        self._load()
