"""Jurisdiction-first wizard: pick jurisdiction → pack/leaf → green/amber/red matrix → export."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config_scanner.b2u_pack import pack_country_update
from config_scanner.cs_catalog import CountryLeaf, discover_leaves, stage_country_pack
from config_scanner.live_cs_export import export_full_country_selector
from config_scanner.cs_sources import (
    CsSource,
    CsSourceKind,
    clear_share_scan_cache,
    is_debug_or_test_pack,
    list_cs_sources,
    load_leaves_for_source,
    materialize_cs_path,
    recommend_cs_source,
    share_browse_start,
    share_offline_note,
    share_shortcuts,
    sort_cs_sources,
    source_is_not_shipped,
)
from config_scanner.net_gate import remote_path_available, unc_host
from config_scanner.embedded_updates import EmbeddedUpdate, export_b2u_copy, load_catalog
from config_scanner.jurisdiction import (
    JurisdictionProfile,
    consistency_issues_from_readings,
    ensure_expected_locale_keys,
    leaf_matches_profile_country,
    load_jurisdictions,
    probe_against_profile,
)
from config_scanner.setting_probe import SettingState, format_value, probe_tree
from config_scanner.setting_spec import SETTING_GROUPS, all_specs
from config_scanner.slot_setup import (
    build_config_pack,
    goldclub_root_from_target,
    recipe_from_jurisdiction_profile,
    save_recipe,
)

_STATE_COLORS = {
    SettingState.MATCH: QColor("#2e7d32"),
    SettingState.DIFFERS: QColor("#f9a825"),
    SettingState.ABSENT: QColor("#c62828"),
    SettingState.NOT_SUPPLIED: QColor("#757575"),
}


def _parse_denom_from_mode(mode: str) -> int | None:
    m = re.search(r"(\d+)\s*c\b", mode, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


class JurisdictionWizard(QWidget):
    """Four-step Create flow for jurisdiction profiling + client export."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles = load_jurisdictions()
        self._profile: JurisdictionProfile | None = None
        self._source: CsSource | None = None
        self._entry: EmbeddedUpdate | None = None
        self._tool: Path | None = None
        self._leaves: list[CountryLeaf] = []
        self._leaf: CountryLeaf | None = None
        self._live_root: Path | None = None
        self._listed_sources: list[CsSource] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        back = QPushButton("← Home")
        back.setToolTip("Return to the Config Scanner home screen.")
        back.clicked.connect(self.back_requested.emit)
        head.addWidget(back)
        title = QLabel("Create client update")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        title.setToolTip(
            "Build a client Country Selector update, or export a full CS .b2u "
            "from live cabinet settings."
        )
        head.addWidget(title)
        head.addStretch(1)
        root.addLayout(head)

        self._step_lbl = QLabel("Step 1 of 4 — Market")
        self._step_lbl.setToolTip("Wizard progress: Market → Pack/leaf → Matrix → Export.")
        root.addWidget(self._step_lbl)

        self._status = QLabel("")
        self._status.setWordWrap(True)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_step_jurisdiction())
        self._stack.addWidget(self._build_step_pack())
        self._stack.addWidget(self._build_step_matrix())
        self._stack.addWidget(self._build_step_export())

        nav = QHBoxLayout()
        self._prev_btn = QPushButton("Back")
        self._prev_btn.setToolTip("Go to the previous wizard step (or Home from step 1).")
        self._prev_btn.clicked.connect(self._go_prev)
        nav.addWidget(self._prev_btn)
        nav.addStretch(1)
        self._next_btn = QPushButton("Next")
        self._next_btn.setObjectName("primary")
        self._next_btn.setToolTip("Continue to the next step.")
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        root.addWidget(self._status)
        self._refresh_nav()

    def _set_status(self, text: str) -> None:
        if hasattr(self, "_status"):
            self._status.setText(text)

    def _build_step_jurisdiction(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(
            QLabel(
                "Select the market first. Next loads the matching Country Selector "
                "and picks the newest official pack (you can still change it)."
            )
        )
        self._juris_combo = QComboBox()
        self._juris_combo.setToolTip(
            "Jurisdiction preset (currency, culture, recommended denoms). "
            "Pick custom if you only want pack/live values in the matrix."
        )
        self._juris_combo.addItem("(custom — no preset)", None)
        for prof in self._profiles:
            self._juris_combo.addItem(f"{prof.label} [{prof.id}]", prof.id)
        # Default Trinidad
        for i in range(self._juris_combo.count()):
            if self._juris_combo.itemData(i) == "trinidad_ttd":
                self._juris_combo.setCurrentIndex(i)
                break
        lay.addWidget(self._juris_combo)
        self._juris_info = QLabel("")
        self._juris_info.setWordWrap(True)
        self._juris_info.setStyleSheet("color: #bbb;")
        lay.addWidget(self._juris_info)
        self._juris_combo.currentIndexChanged.connect(self._on_juris_changed)
        self._on_juris_changed()
        lay.addStretch(1)
        return w

    def _build_step_pack(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(
            QLabel(
                "The program lists official packs for this market and pre-selects "
                "the newest one. Built-in packs work offline; lab share needs "
                "\\\\10.0.0.249 (GOLD-CLUB\\test). Debug/Test packs stay hidden unless you tick the box. "
                "Grey GameStar+22/+30 zips are cabinet-apply only — Restore on the EGM, do not Create from them."
            )
        )

        self._pack_combo = QComboBox()
        self._pack_combo.setMinimumContentsLength(40)
        self._pack_combo.setToolTip(
            "Official Country Selector pack for this market. Built-in packs work offline; "
            "share packs need \\\\10.0.0.249. Grey GS+22/+30 zips are apply-only."
        )
        self._pack_combo.currentIndexChanged.connect(self._on_pack_changed)
        lay.addWidget(self._pack_combo)

        self._share_lbl = QLabel("")
        self._share_lbl.setWordWrap(True)
        self._share_lbl.setStyleSheet("color: #f9a825;")
        self._share_lbl.setVisible(False)
        lay.addWidget(self._share_lbl)

        self._show_debug = QCheckBox("Show Debug / Test packs")
        self._show_debug.setToolTip(
            "Include lab Debug/Test overlays that are normally hidden from operators."
        )
        self._show_debug.toggled.connect(self._refresh_pack_list)
        lay.addWidget(self._show_debug)

        src_row = QHBoxLayout()
        browse_file = QPushButton("Open file (.b2u / folder)…")
        browse_file.setToolTip(
            "Open a GameStar CS .b2u or an unpacked CountrySelectorTool folder."
        )
        browse_file.clicked.connect(self._browse_cs_file)
        src_row.addWidget(browse_file)
        browse_share = QPushButton("Browse share…")
        browse_share.setToolTip(
            r"Browse \\10.0.0.249\WinSystems_SLOT Country Selectors / _B2U."
        )
        browse_share.clicked.connect(self._browse_share)
        src_row.addWidget(browse_share)
        refresh = QPushButton("Refresh list")
        refresh.setToolTip("Rescan embedded and share Country Selector sources.")
        refresh.clicked.connect(self._force_refresh_packs)
        src_row.addWidget(refresh)
        src_row.addStretch(1)
        lay.addLayout(src_row)

        self._pack_note = QLabel("")
        self._pack_note.setWordWrap(True)
        self._pack_note.setStyleSheet("color: #999;")
        lay.addWidget(self._pack_note)

        lay.addWidget(QLabel("Leaf (country / mode / screens):"))
        self._leaf_combo = QComboBox()
        self._leaf_combo.setToolTip(
            "One overlay leaf under the pack: country / screens / mode "
            "(e.g. OL+SAS 10c, 2 Screens)."
        )
        self._leaf_combo.currentIndexChanged.connect(self._on_leaf_changed)
        lay.addWidget(self._leaf_combo)

        live_row = QHBoxLayout()
        live_row.addWidget(QLabel("Live Goldclub (optional compare):"))
        self._live_edit = QLineEdit(r"C:\Goldclub")
        self._live_edit.setToolTip(
            "Optional live cabinet path for the matrix Live column and for "
            "Export full Country Selector from live."
        )
        live_row.addWidget(self._live_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.setToolTip("Pick a local Goldclub folder to compare.")
        browse.clicked.connect(self._browse_live)
        live_row.addWidget(browse)
        lay.addLayout(live_row)

        lay.addWidget(
            QLabel(
                "Recommended denoms (from jurisdiction — uncheck to drop, "
                "or add a custom value):"
            )
        )
        self._denom_checks_row = QHBoxLayout()
        self._denom_checkboxes: dict[int, QCheckBox] = {}
        lay.addLayout(self._denom_checks_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Add custom (cents):"))
        self._denom_custom = QSpinBox()
        self._denom_custom.setRange(1, 1000)
        self._denom_custom.setValue(1)
        custom_row.addWidget(self._denom_custom)
        add_custom = QPushButton("Add")
        add_custom.clicked.connect(self._add_custom_denom)
        custom_row.addWidget(add_custom)
        custom_row.addStretch(1)
        lay.addLayout(custom_row)

        pref_row = QHBoxLayout()
        pref_row.addWidget(QLabel("Preferred / leaf denom:"))
        self._denom_pref = QComboBox()
        self._denom_pref.setMinimumContentsLength(8)
        pref_row.addWidget(self._denom_pref)
        pref_row.addStretch(1)
        lay.addLayout(pref_row)

        self._denom_hint = QLabel("")
        self._denom_hint.setStyleSheet("color: #999;")
        lay.addWidget(self._denom_hint)

        lay.addStretch(1)
        self._sync_denom_ui_from_profile()
        return w

    def _build_step_matrix(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self._issues_lbl = QLabel("")
        self._issues_lbl.setWordWrap(True)
        self._issues_lbl.setStyleSheet("color: #ef9a9a;")
        lay.addWidget(self._issues_lbl)

        filt = QHBoxLayout()
        self._problems_only = QCheckBox("Problems only (amber/red)")
        self._problems_only.setToolTip(
            "Hide green / matching rows so only amber differs and red absent settings remain."
        )
        self._problems_only.toggled.connect(self._fill_matrix)
        filt.addWidget(self._problems_only)
        refresh = QPushButton("Refresh probe")
        refresh.setToolTip("Re-read pack leaf and live Goldclub values into the matrix.")
        refresh.clicked.connect(self._fill_matrix)
        filt.addWidget(refresh)
        filt.addStretch(1)
        lay.addLayout(filt)

        legend = QLabel(
            "Green = match profile · Amber = present but differs · "
            "Red = absent · Gray = not supplied by this source"
        )
        legend.setStyleSheet("color: #999;")
        lay.addWidget(legend)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Group", "Setting", "Expected", "Live", "Pack", "Live / Pack"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        lay.addWidget(self._table, stretch=1)
        return w

    def _build_step_export(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(
            QLabel(
                "Export a client Country Selector update, or build a full official-style "
                "CS .b2u from the live cabinet (settings list + leaf overlay + encrypt)."
            )
        )
        self._export_summary = QLabel("")
        self._export_summary.setWordWrap(True)
        lay.addWidget(self._export_summary)
        self._include_recipe = QCheckBox(
            "Also write jurisdiction recipe.json (for Slot setup / apply-pack)"
        )
        self._include_recipe.setChecked(True)
        self._include_recipe.setToolTip(
            "Beside the client update, also save a SlotSetup recipe.json "
            "(and a config-pack if Live Goldclub is set) for apply-pack workflows."
        )
        lay.addWidget(self._include_recipe)
        export_btn = QPushButton("Export client update…")
        export_btn.setObjectName("primary")
        export_btn.setMinimumHeight(40)
        export_btn.setToolTip(
            "Bundle CountrySelectorTool data into a ConfigScanner client .b2u "
            "(field wizard). Clients open Apply update on cabinet."
        )
        export_btn.clicked.connect(self._do_export)
        lay.addWidget(export_btn)
        full_btn = QPushButton("Export full Country Selector from live…")
        full_btn.setMinimumHeight(40)
        full_btn.setToolTip(
            "Probe live Goldclub settings, copy matching files into the selected leaf, "
            "and encrypt a BiOS2 .b2u that runs CountrySelector.exe (not ConfigScanner)."
        )
        full_btn.clicked.connect(self._do_export_full_cs)
        lay.addWidget(full_btn)
        copy_btn = QPushButton("Copy official .b2u to USB…")
        copy_btn.setToolTip(
            "When the selected pack has a bundled .b2u, copy it as-is to a USB folder."
        )
        copy_btn.clicked.connect(self._copy_official_b2u)
        lay.addWidget(copy_btn)
        lay.addStretch(1)
        return w

    def _on_juris_changed(self) -> None:
        jid = self._juris_combo.currentData()
        self._profile = None
        if jid:
            for p in self._profiles:
                if p.id == jid:
                    self._profile = p
                    break
        if self._profile is None:
            self._juris_info.setText("No preset — matrix will only show pack/live values.")
            return
        p = self._profile
        ensure_expected_locale_keys(p)
        self._juris_info.setText(
            f"Country: {p.country}\n"
            f"Currency: {p.currency} · Culture: {p.culture} · Language: {p.language}\n"
            f"Target market: {p.target_market}\n"
            f"Recommended denoms: {p.allowed_denoms or '—'}\n"
            f"{p.notes}"
        )
        if hasattr(self, "_pack_combo") and self._stack.currentIndex() == 1:
            self._refresh_pack_list()
        if hasattr(self, "_denom_checks_row"):
            self._sync_denom_ui_from_profile()

    def _clear_denom_checks(self) -> None:
        while self._denom_checks_row.count():
            item = self._denom_checks_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._denom_checkboxes = {}

    def _sync_denom_ui_from_profile(self) -> None:
        if not hasattr(self, "_denom_checks_row"):
            return
        self._clear_denom_checks()
        denoms = list(self._profile.allowed_denoms) if self._profile else []
        if not denoms:
            self._denom_hint.setText(
                "No jurisdiction denoms — pick a leaf or add custom values."
            )
            self._refresh_pref_combo()
            return
        self._denom_hint.setText(
            f"Defaults for {self._profile.label if self._profile else 'jurisdiction'}: "
            f"{', '.join(str(d) + 'c' for d in denoms)}"
        )
        for d in denoms:
            self._add_denom_checkbox(d, checked=True)
        self._refresh_pref_combo(prefer=denoms[-1] if denoms else None)

    def _add_denom_checkbox(self, cents: int, *, checked: bool = True) -> None:
        if cents in self._denom_checkboxes:
            self._denom_checkboxes[cents].setChecked(checked)
            return
        cb = QCheckBox(f"{cents}c")
        cb.setChecked(checked)
        cb.toggled.connect(lambda _=False: self._refresh_pref_combo())
        self._denom_checkboxes[cents] = cb
        self._denom_checks_row.addWidget(cb)

    def _add_custom_denom(self) -> None:
        cents = int(self._denom_custom.value())
        self._add_denom_checkbox(cents, checked=True)
        self._refresh_pref_combo(prefer=cents)

    def _selected_denoms(self) -> list[int]:
        return sorted(
            d for d, cb in self._denom_checkboxes.items() if cb.isChecked()
        )

    def _preferred_denom(self) -> int | None:
        data = self._denom_pref.currentData()
        if data is None:
            selected = self._selected_denoms()
            return selected[0] if selected else None
        return int(data)

    def _refresh_pref_combo(self, prefer: int | None = None) -> None:
        if not hasattr(self, "_denom_pref"):
            return
        current = prefer
        if current is None and self._denom_pref.currentData() is not None:
            current = int(self._denom_pref.currentData())
        selected = self._selected_denoms()
        self._denom_pref.blockSignals(True)
        self._denom_pref.clear()
        if not selected:
            self._denom_pref.addItem("(none selected)", None)
        else:
            for d in selected:
                self._denom_pref.addItem(f"{d}c", d)
            if current in selected:
                self._denom_pref.setCurrentIndex(selected.index(current))
            else:
                self._denom_pref.setCurrentIndex(len(selected) - 1)
        self._denom_pref.blockSignals(False)

    def _profile_for_probe(self) -> JurisdictionProfile | None:
        if self._profile is None:
            return None
        profile = ensure_expected_locale_keys(self._profile)
        denoms = self._selected_denoms()
        if denoms:
            profile.expected["denom.list"] = list(denoms)
            profile.expected["denom.credit_rate_values"] = list(denoms)
        return profile

    def _force_refresh_packs(self) -> None:
        clear_share_scan_cache()
        self._refresh_pack_list()

    def _refresh_pack_list(self) -> None:
        if not hasattr(self, "_pack_combo"):
            return
        prev = self._source.id if self._source else None
        include_debug = bool(
            getattr(self, "_show_debug", None) is not None and self._show_debug.isChecked()
        )
        country = self._profile.country if self._profile else None
        self._set_status("Listing Country Selector packs…")
        all_src = sort_cs_sources(
            list_cs_sources(
                profile_country=country,
                authoring_only=False,
                include_share_scan=True,
            )
        )
        self._update_share_note()
        authoring = [s for s in all_src if s.authoring]
        apply_only = [s for s in all_src if not s.authoring]
        if not include_debug:
            authoring = [s for s in authoring if not is_debug_or_test_pack(s)]
            apply_only = [s for s in apply_only if not is_debug_or_test_pack(s)]
        self._listed_sources = authoring + apply_only
        recommended = recommend_cs_source(
            authoring,
            profile_id=self._profile.id if self._profile else "",
            include_debug=include_debug,
        )

        self._pack_combo.blockSignals(True)
        self._pack_combo.clear()
        last_group = ""
        select_idx: int | None = None

        def _add_src(src: CsSource, *, enabled: bool) -> None:
            nonlocal last_group, select_idx
            if src.group != last_group:
                self._pack_combo.addItem(f"— {src.group} —", None)
                idx = self._pack_combo.count() - 1
                item = self._pack_combo.model().item(idx)
                if item is not None:
                    item.setEnabled(False)
                last_group = src.group
            label = src.label
            if src.gamestar_line:
                label = f"{label} ({src.gamestar_line})"
            if recommended is not None and src.id == recommended.id:
                label = f"Recommended — {label}"
            self._pack_combo.addItem(label, src.id)
            idx = self._pack_combo.count() - 1
            if not enabled:
                item = self._pack_combo.model().item(idx)
                if item is not None:
                    item.setEnabled(False)
            tip = src.note or str(src.path or src.embedded_id or "")
            self._pack_combo.setItemData(idx, tip, Qt.ItemDataRole.ToolTipRole)
            if prev and src.id == prev and enabled:
                select_idx = idx
            elif (
                select_idx is None
                and recommended is not None
                and src.id == recommended.id
            ):
                select_idx = idx

        for src in authoring:
            _add_src(src, enabled=True)
        for src in apply_only:
            _add_src(src, enabled=False)
        self._pack_combo.blockSignals(False)

        if not authoring:
            bits = [
                "No usable Country Selector overlay for this market on this PC. Create needs a "
                "GameStar 2.0.x / _B2U .b2u or an unpacked CS folder.",
            ]
            not_shipped = [s for s in apply_only if source_is_not_shipped(s)]
            zips = [s for s in apply_only if not source_is_not_shipped(s)]
            if not_shipped:
                names = ", ".join(s.embedded_id or s.label for s in not_shipped)
                bits.append(
                    f"Built-in {names}: catalog entry only (grey) — no .b2u / staged tree "
                    "in this build. Stage it beside the exe or use the lab share."
                )
            if zips:
                bits.append(
                    f"{len(zips)} GameStar+ cabinet-apply zip(s) are listed "
                    "(grey) — Restore those on the EGM, do not Create from them."
                )
            offline = share_offline_note()
            if offline:
                bits.append(offline)
            bits.append("Use Open file / Browse share if you already have a pack.")
            self._pack_note.setText("\n".join(bits))
            self._set_status("No usable pack for this market — see note above.")
            self._source = None
            self._leaf_combo.clear()
            return

        # Select with signals blocked, then load once: setCurrentIndex after
        # clear() emits currentIndexChanged, which used to run _on_pack_changed
        # twice (two decrypt attempts, two error dialogs).
        self._pack_combo.blockSignals(True)
        if select_idx is not None:
            self._pack_combo.setCurrentIndex(select_idx)
        elif self._pack_combo.currentData():
            pass
        elif self._pack_combo.count() > 1:
            self._pack_combo.setCurrentIndex(1)
        self._pack_combo.blockSignals(False)
        if self._pack_combo.currentData():
            self._on_pack_changed()

    def _update_share_note(self) -> None:
        if not hasattr(self, "_share_lbl"):
            return
        note = share_offline_note()
        self._share_lbl.setText(note)
        self._share_lbl.setVisible(bool(note))

    def _all_sources(self) -> list[CsSource]:
        listed = getattr(self, "_listed_sources", None)
        if listed:
            return listed
        country = self._profile.country if self._profile else None
        return list_cs_sources(
            profile_country=country,
            authoring_only=True,
            include_share_scan=True,
        )

    def _source_by_id(self, source_id: str) -> CsSource | None:
        for src in self._all_sources():
            if src.id == source_id:
                return src
        return None

    def _current_source(self) -> CsSource | None:
        sid = self._pack_combo.currentData()
        if not sid:
            return self._source
        sid = str(sid)
        if self._source and self._source.id == sid:
            return self._source
        return self._source_by_id(sid)

    def _on_pack_changed(self) -> None:
        self._source = self._current_source()
        src = self._source
        if src is None:
            self._pack_note.setText("")
            return
        bits = [src.group]
        if src.path:
            bits.append(str(src.path))
        if src.note:
            bits.append(src.note)
        self._pack_note.setText("\n".join(bits))
        self._reload_leaves()

    def _on_leaf_changed(self) -> None:
        leaf = self._current_leaf()
        if leaf is None:
            return
        parsed = _parse_denom_from_mode(leaf.mode)
        if parsed is None:
            return
        # Ensure leaf denom is among recommended (checked), then select as preferred.
        if parsed not in self._denom_checkboxes:
            self._add_denom_checkbox(parsed, checked=True)
        else:
            self._denom_checkboxes[parsed].setChecked(True)
        self._refresh_pref_combo(prefer=parsed)

    def _browse_cs_file(self) -> None:
        start = share_browse_start(
            r"\\10.0.0.249\WinSystems_SLOT\GameStar 2.0.1\Country Selectors"
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Country Selector (.b2u)",
            start,
            "Country Selector (*.b2u);;All files (*.*)",
        )
        if not path:
            path = QFileDialog.getExistingDirectory(
                self,
                "Unpacked CountrySelectorTool folder",
                share_browse_start(r"\\10.0.0.249\WinSystems_SLOT\_B2U"),
            )
        if not path:
            return
        local = CsSource(
            id=f"local-{Path(path).name}",
            label=f"Local — {Path(path).name}",
            country=self._profile.country if self._profile else "",
            gamestar_line="local",
            kind=CsSourceKind.LOCAL,
            path=Path(path),
            authoring=True,
        )
        self._source = local
        self._pack_combo.blockSignals(True)
        self._pack_combo.insertItem(0, local.label, local.id)
        self._pack_combo.setCurrentIndex(0)
        self._pack_combo.blockSignals(False)
        self._pack_note.setText(str(path))
        self._reload_leaves(interactive=True)

    def _browse_share(self) -> None:
        start = ""
        for _label, path in share_shortcuts():
            if not remote_path_available(path):
                continue
            try:
                if path.is_dir():
                    start = str(path)
                    break
            except OSError:
                continue
        self._update_share_note()
        offline = share_offline_note()
        if not start and offline:
            self._set_status(offline)
            QMessageBox.information(
                self,
                "Lab share",
                offline + "\n\nPick a built-in pack, or Open file for a local .b2u / folder.",
            )
            return
        if not start:
            start = share_browse_start(
                r"\\10.0.0.249\WinSystems_SLOT\GameStar 2.0.1\Country Selectors"
            )
        path = QFileDialog.getExistingDirectory(self, "Lab share folder", start)
        if not path:
            return
        local = CsSource(
            id=f"local-{Path(path).name}",
            label=f"Share — {Path(path).name}",
            country=self._profile.country if self._profile else "",
            gamestar_line="share",
            kind=CsSourceKind.SHARE_FOLDER,
            path=Path(path),
            authoring=True,
        )
        self._source = local
        self._pack_combo.blockSignals(True)
        self._pack_combo.insertItem(0, local.label, local.id)
        self._pack_combo.setCurrentIndex(0)
        self._pack_combo.blockSignals(False)
        self._pack_note.setText(str(path))
        self._reload_leaves(interactive=True)

    def _browse_live(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Live Goldclub root", self._live_edit.text().strip() or r"C:\Goldclub"
        )
        if path:
            self._live_edit.setText(path)

    def _reload_leaves(self, *, interactive: bool = False) -> None:
        """Load leaves for the selected pack.

        *interactive* is True only when the user just picked a file/folder
        themselves; then a failure is worth a dialog. Automatic selection
        (market change, Next, Refresh list) reports inline instead — a modal
        that pops up on its own every time step 2 opens is what the operator
        sees as "the tool keeps complaining".
        """
        self._leaf_combo.clear()
        self._leaves = []
        self._tool = None
        self._entry = None
        src = self._source
        if src is None:
            return
        if not src.authoring:
            note = src.note or "This entry is apply-only; pick an authoring pack."
            self._pack_note.setText(f"{src.group}\n{note}")
            self._set_status(f"{src.label}: not usable for Create.")
            return
        try:
            if src.kind == CsSourceKind.EMBEDDED and src.embedded_id:
                self._entry = next(
                    (e for e in load_catalog() if e.id == src.embedded_id), None
                )
            if src.kind == CsSourceKind.LOCAL and src.path is not None:
                tool = materialize_cs_path(src.path)
                leaves = discover_leaves(tool)
            else:
                tool, leaves = load_leaves_for_source(src)
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            self._report_pack_failure(src, str(exc), interactive=interactive)
            return
        self._tool = tool
        profile = self._profile
        filtered = leaves
        if profile is not None:
            matched = [
                leaf
                for leaf in leaves
                if leaf_matches_profile_country(leaf.country, profile)
            ]
            if matched:
                filtered = matched
        self._leaves = filtered
        for i, leaf in enumerate(filtered):
            extra = f" — {leaf.readme}" if leaf.readme else ""
            self._leaf_combo.addItem(f"{leaf.label}{extra}", i)
        if filtered:
            self._on_leaf_changed()
        label = src.label
        self._set_status(f"Loaded {len(filtered)} leaves from {label}")

    def _report_pack_failure(self, src: CsSource, why: str, *, interactive: bool) -> None:
        hint = "Pick another pack from the list, or Open file for a local .b2u / folder."
        text = f"Could not open {src.label}:\n{why}\n{hint}"
        self._pack_note.setText(text)
        self._set_status(f"Could not open {src.label} — {why.splitlines()[0]}")
        if interactive:
            QMessageBox.warning(self, "Pack", f"{why}\n\n{hint}")

    def _current_leaf(self) -> CountryLeaf | None:
        idx = self._leaf_combo.currentData()
        if idx is None or not self._leaves:
            return None
        try:
            return self._leaves[int(idx)]
        except (IndexError, TypeError, ValueError):
            return None

    def _fill_matrix(self) -> None:
        self._table.setRowCount(0)
        leaf = self._leaf
        if leaf is None:
            self._issues_lbl.setText("No leaf selected.")
            return
        profile = self._profile_for_probe()
        live_text = self._live_edit.text().strip()
        live_root: Path | None = None
        live_note = ""
        if live_text:
            if not remote_path_available(live_text):
                live_note = (
                    f"Live \\\\{unc_host(live_text)} not reachable — Live column skipped."
                )
            else:
                try:
                    live_root = goldclub_root_from_target(live_text)
                    if not live_root.is_dir():
                        live_root = None
                except (OSError, ValueError):
                    live_root = None
        self._live_root = live_root

        if profile is not None:
            pack_readings = probe_against_profile(
                leaf.path, profile, source_is_cs_leaf=True
            )
        else:
            pack_readings = probe_tree(
                leaf.path, expected=None, source_is_cs_leaf=True
            )

        live_readings = {}
        if live_root is not None:
            if profile is not None:
                live_readings = probe_against_profile(
                    live_root, profile, source_is_cs_leaf=False
                )
            else:
                live_readings = probe_tree(
                    live_root, expected=None, source_is_cs_leaf=False
                )

        issues = consistency_issues_from_readings(pack_readings, profile=profile)
        if live_readings:
            issues.extend(
                consistency_issues_from_readings(live_readings, profile=profile)
            )
        # de-dupe
        issues = list(dict.fromkeys(issues))
        consistency = "Consistency: " + (" · ".join(issues) if issues else "OK")
        if live_note:
            consistency = f"{live_note}\n{consistency}"
        self._issues_lbl.setText(consistency)

        problems_only = self._problems_only.isChecked()
        rows: list[tuple] = []
        for group in SETTING_GROUPS:
            for spec in all_specs():
                if spec.group != group:
                    continue
                pack_r = pack_readings.get(spec.id)
                live_r = live_readings.get(spec.id) if live_readings else None
                if problems_only:
                    bad = False
                    if pack_r and pack_r.state in (
                        SettingState.DIFFERS,
                        SettingState.ABSENT,
                    ):
                        bad = True
                    if live_r and live_r.state in (
                        SettingState.DIFFERS,
                        SettingState.ABSENT,
                    ):
                        bad = True
                    if not bad:
                        continue
                expected = (
                    format_value(profile.expected.get(spec.id))
                    if profile
                    else "—"
                )
                live_txt = format_value(live_r.value) if live_r else "—"
                pack_txt = format_value(pack_r.value) if pack_r else "—"
                rows.append((spec, expected, live_txt, pack_txt, live_r, pack_r))

        self._table.setRowCount(len(rows))
        for row, (spec, expected, live_txt, pack_txt, live_r, pack_r) in enumerate(rows):
            self._table.setItem(row, 0, QTableWidgetItem(spec.group))
            self._table.setItem(row, 1, QTableWidgetItem(spec.label))
            self._table.setItem(row, 2, QTableWidgetItem(expected))
            self._table.setItem(row, 3, QTableWidgetItem(live_txt))
            self._table.setItem(row, 4, QTableWidgetItem(pack_txt))
            live_state = live_r.state if live_r else SettingState.NOT_SUPPLIED
            pack_state = pack_r.state if pack_r else SettingState.NOT_SUPPLIED
            combo = QTableWidgetItem(f"{live_state.value} / {pack_state.value}")
            worst = pack_state
            for st in (live_state, pack_state):
                if st == SettingState.ABSENT:
                    worst = st
                    break
                if st == SettingState.DIFFERS:
                    worst = st
            combo.setForeground(_STATE_COLORS.get(worst, QColor("#757575")))
            combo.setFlags(combo.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 5, combo)
            for col in range(5):
                item = self._table.item(row, col)
                if item is not None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._set_status(f"Probed {len(rows)} settings on {leaf.label}")

    def _refresh_export_summary(self) -> None:
        bits = []
        if self._profile:
            bits.append(f"Jurisdiction: {self._profile.label}")
        if self._source:
            bits.append(f"Source: {self._source.label}")
        elif self._entry:
            bits.append(f"Pack: {self._entry.label}")
        if self._leaf:
            bits.append(f"Leaf: {self._leaf.label}")
            d = self._preferred_denom() or _parse_denom_from_mode(self._leaf.mode)
            if d:
                bits.append(f"Preferred denom: {d}c")
            selected = self._selected_denoms()
            if selected:
                bits.append(
                    "Denom list: " + ", ".join(f"{x}c" for x in selected)
                )
        self._export_summary.setText("\n".join(bits) or "Nothing selected.")

    def _refresh_nav(self) -> None:
        idx = self._stack.currentIndex()
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setText("Next" if idx < 3 else "Done")
        labels = (
            "Step 1 of 4 — Market",
            "Step 2 of 4 — Official pack",
            "Step 3 of 4 — Review settings",
            "Step 4 of 4 — Export",
        )
        self._step_lbl.setText(labels[idx])

    def _go_prev(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
        self._refresh_nav()

    def _go_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 0:
            self._stack.setCurrentIndex(1)
            # _refresh_pack_list already loads leaves for the selected pack;
            # re-running _on_pack_changed here retried a failed decrypt and
            # showed the same error twice.
            self._refresh_pack_list()
        elif idx == 1:
            leaf = self._current_leaf()
            if leaf is None:
                QMessageBox.information(self, "Leaf", "Load a pack and select a leaf.")
                return
            self._leaf = leaf
            parsed = _parse_denom_from_mode(leaf.mode)
            if parsed:
                if parsed not in self._denom_checkboxes:
                    self._add_denom_checkbox(parsed, checked=True)
                else:
                    self._denom_checkboxes[parsed].setChecked(True)
                self._refresh_pref_combo(prefer=parsed)
            elif not self._selected_denoms() and self._profile and self._profile.allowed_denoms:
                self._sync_denom_ui_from_profile()
            self._stack.setCurrentIndex(2)
            self._fill_matrix()
        elif idx == 2:
            self._refresh_export_summary()
            self._stack.setCurrentIndex(3)
        else:
            self.back_requested.emit()
        self._refresh_nav()

    def _do_export(self) -> None:
        if self._tool is None or self._leaf is None:
            QMessageBox.warning(self, "Export", "Select a pack and leaf first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Where to save the client update")
        if not out:
            return
        out_path = Path(out)
        name = (
            self._entry.id
            if self._entry
            else (self._source.id if self._source else self._tool.parent.name)
        ) or "Country"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:48]
        package_name = f"ConfigScanner_Country_{safe}"
        try:
            staged = stage_country_pack(
                self._tool, out_path / "_stage_country", package_label="staged"
            )
            result = pack_country_update(
                out_path, staged, package_name=package_name, encrypt=True
            )
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return

        if self._include_recipe.isChecked() and self._profile is not None:
            denoms = self._selected_denoms()
            preferred = self._preferred_denom() or _parse_denom_from_mode(
                self._leaf.mode
            )
            offline = None
            if "OL" in (self._leaf.mode or "").upper():
                offline = True
            elif "SAS" in (self._leaf.mode or "").upper() and "OL" not in (
                self._leaf.mode or ""
            ).upper():
                offline = False
            recipe = recipe_from_jurisdiction_profile(
                self._profile,
                denom=preferred,
                denomination_list=denoms or None,
                offline_enabled=offline,
            )
            recipe_dir = out_path / f"{package_name}_recipe"
            recipe_dir.mkdir(parents=True, exist_ok=True)
            save_recipe(recipe, recipe_dir / "recipe.json")
            # If live goldclub exists, also materialize a config pack
            if self._live_root is not None and self._live_root.is_dir():
                try:
                    build_config_pack(recipe, self._live_root, recipe_dir / "config-pack")
                except (OSError, ValueError) as exc:
                    self._set_status(f"Recipe saved; config-pack skipped: {exc}")

        QMessageBox.information(
            self,
            "Client update ready",
            f"{result.note}\n\n"
            "Give the client the .b2u (or unpacked folder).\n"
            "They open Config Scanner → Apply update on cabinet.",
        )
        self._set_status(result.note)

    def _do_export_full_cs(self) -> None:
        if self._tool is None or self._leaf is None:
            QMessageBox.warning(self, "Export", "Select a pack and leaf first.")
            return
        live_text = self._live_edit.text().strip()
        if not live_text:
            QMessageBox.warning(
                self,
                "Export",
                "Set Live Goldclub (step 2) to the tuned cabinet path, e.g. "
                r"\\10.0.0.111\slot or C:\Goldclub.",
            )
            return
        if not remote_path_available(live_text):
            QMessageBox.warning(
                self,
                "Export",
                f"\\\\{unc_host(live_text)} is not reachable (SMB port 445 did not answer).\n"
                "The cabinet is off or this PC is not on the lab network.",
            )
            return
        try:
            live_root = goldclub_root_from_target(live_text)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        if not live_root.is_dir():
            QMessageBox.warning(self, "Export", f"Live Goldclub not found:\n{live_root}")
            return

        out = QFileDialog.getExistingDirectory(
            self, "Where to save the full Country Selector .b2u"
        )
        if not out:
            return
        out_path = Path(out)
        name = (
            self._entry.id
            if self._entry
            else (self._source.id if self._source else self._tool.parent.name)
        ) or "Live"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]
        package_name = f"CS-{safe}-Live"
        try:
            result = export_full_country_selector(
                out_path,
                live_goldclub=live_root,
                country_tool_dir=self._tool,
                leaf=self._leaf,
                package_name=package_name,
                encrypt=True,
            )
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Full Country Selector", str(exc))
            return

        sample = "\n".join(
            f"  {r['label']}: {r['value']}" for r in result.settings_rows[:12]
        )
        more = (
            f"\n  … and {len(result.settings_rows) - 12} more"
            if len(result.settings_rows) > 12
            else ""
        )
        QMessageBox.information(
            self,
            "Full Country Selector ready",
            f"{result.note}\n\n"
            f"Settings report: {result.settings_report}\n"
            f"Overlaid files: {len(result.overlay_files)}\n\n"
            f"Live settings (sample):\n{sample}{more}\n\n"
            "Apply this .b2u on a cabinet via BiOS update (runs CountrySelector.exe).",
        )
        self._set_status(result.note)

    def _copy_official_b2u(self) -> None:
        entry = self._entry
        if entry is None and self._source is not None and self._source.embedded_id:
            entry = next(
                (e for e in load_catalog() if e.id == self._source.embedded_id),
                None,
            )
            self._entry = entry
        if entry is None or entry.b2u_path is None:
            QMessageBox.warning(
                self,
                "Copy .b2u",
                "The selected pack has no bundled official .b2u.\n"
                "Use Export client update to build one, or pick a built-in pack that ships a .b2u.",
            )
            return
        out = QFileDialog.getExistingDirectory(
            self, "Copy official .b2u to (e.g. lab USB root)"
        )
        if not out:
            return
        try:
            dest = export_b2u_copy(entry, Path(out))
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Copy .b2u", str(exc))
            return
        QMessageBox.information(
            self,
            "Copied",
            f"Official update copied to:\n{dest}\n\n"
            "Apply via BiOS or Config Scanner → Apply update on cabinet.",
        )
        self._set_status(f"Copied {dest.name}")
