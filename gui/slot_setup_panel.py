"""Slot EGM setup authoring + apply-only review UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_scanner.b2u_pack import pack_egm_update
from config_scanner.slot_setup import (
    BILL_PROTOCOLS,
    KEYBOARD_FUNCTIONS,
    AurumIdentitySettings,
    BillToken,
    DallasSettings,
    JurisdictionSettings,
    MathDenomSettings,
    MgIdentitySettings,
    SasSettings,
    SlotSetupRecipe,
    apply_config_pack,
    build_config_pack,
    goldclub_root_from_target,
    load_recipe,
    load_recipe_from_goldclub,
    recipe_summary_lines,
)


class SlotSetupPanel(QWidget):
    """Author SAS / bill / keyboard / denoms / jurisdiction and export an EGM B2U."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._goldclub: Path | None = None
        self._recipe = SlotSetupRecipe()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Goldclub root:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(r"C:\Goldclub")
        self._path_edit.setText(r"C:\Goldclub")
        path_row.addWidget(self._path_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_goldclub)
        path_row.addWidget(browse)
        load_btn = QPushButton("Load from machine")
        load_btn.setObjectName("primary")
        load_btn.clicked.connect(self._load_from_machine)
        path_row.addWidget(load_btn)
        root.addLayout(path_row)

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Update label (e.g. Trinidad SAS MEI)")
        root.addWidget(self._label_edit)

        # SAS
        sas_box = QGroupBox("SAS")
        sas_form = QFormLayout(sas_box)
        self._sas_enabled = QCheckBox("Enable SAS / online")
        self._sas_enabled.setChecked(True)
        self._sas_address = QSpinBox()
        self._sas_address.setRange(1, 127)
        self._sas_address.setValue(1)
        self._sas_aft = QCheckBox("AFT enabled")
        self._sas_aft.setChecked(True)
        self._sas_transfer = QComboBox()
        self._sas_transfer.addItems(["AFT", "NONE", "EFT"])
        self._sas_lock = QCheckBox("Lock game when no comms")
        self._sas_lock.setChecked(True)
        sas_form.addRow(self._sas_enabled)
        sas_form.addRow("SAS address", self._sas_address)
        sas_form.addRow(self._sas_aft)
        sas_form.addRow("Funds transfer", self._sas_transfer)
        sas_form.addRow(self._sas_lock)
        root.addWidget(sas_box)

        # Bill
        bill_box = QGroupBox("Bill acceptor")
        bill_form = QFormLayout(bill_box)
        self._bill_protocol = QComboBox()
        self._bill_protocol.addItems(list(BILL_PROTOCOLS))
        bill_form.addRow("Protocol (MEI / JCM)", self._bill_protocol)
        note = QLabel("COM port is left unchanged (never edits serialport layout).")
        note.setWordWrap(True)
        bill_form.addRow(note)
        root.addWidget(bill_box)

        # Jurisdiction / identity
        jur_box = QGroupBox("Jurisdiction / currency")
        jur_form = QFormLayout(jur_box)
        self._jur_tag = QLineEdit()
        self._jur_tag.setPlaceholderText("e.g. Trinidad, PuertoRico")
        self._jur_culture = QLineEdit()
        self._jur_culture.setPlaceholderText("e.g. en-US, es-PR")
        self._jur_currency = QLineEdit()
        self._jur_currency.setPlaceholderText("e.g. TTD, USD")
        self._jur_symbol = QLineEdit()
        self._jur_symbol.setPlaceholderText("$")
        self._jur_limit = QSpinBox()
        self._jur_limit.setRange(0, 10_000_000)
        self._jur_limit.setSpecialValueText("(unchanged)")
        self._jur_limit.setValue(0)
        self._hw_currency = QLineEdit()
        self._hw_currency.setPlaceholderText("HardwareConfig CurrencyName")
        jur_form.addRow("Tag", self._jur_tag)
        jur_form.addRow("Culture", self._jur_culture)
        jur_form.addRow("Currency (jurisdiction)", self._jur_currency)
        jur_form.addRow("Currency symbol", self._jur_symbol)
        jur_form.addRow("MagicWheel MoneyLimit", self._jur_limit)
        jur_form.addRow("Hardware currency", self._hw_currency)
        root.addWidget(jur_box)

        ticket_box = QGroupBox("Offline ticket / Dallas / identity")
        ticket_form = QFormLayout(ticket_box)
        self._offline = QComboBox()
        self._offline.addItems(["(unchanged)", "Enabled (OL+SAS)", "Disabled (SAS only)"])
        self._include_oticket = QCheckBox("Include bios/…/oticket.xml when present")
        self._dallas_code = QLineEdit()
        self._dallas_code.setPlaceholderText("iButton code e.g. 01D68A721B000019")
        self._dallas_group = QLineEdit("Service")
        self._dallas_unlock = QCheckBox("Dallas Unlock")
        self._dallas_unlock.setChecked(True)
        self._machine_id = QLineEdit("GST!!MachineName!!")
        self._language = QLineEdit()
        self._language.setPlaceholderText("English / Spanish")
        self._inactivity = QSpinBox()
        self._inactivity.setRange(-1, 86_400)
        self._inactivity.setSpecialValueText("(unchanged)")
        self._inactivity.setValue(-1)
        self._aurum_host = QLineEdit("GST!!MachineName!!")
        ticket_form.addRow("Offline ticket", self._offline)
        ticket_form.addRow(self._include_oticket)
        ticket_form.addRow("Dallas key code", self._dallas_code)
        ticket_form.addRow("Dallas group", self._dallas_group)
        ticket_form.addRow(self._dallas_unlock)
        ticket_form.addRow("mgconfig MachineID", self._machine_id)
        ticket_form.addRow("Language", self._language)
        ticket_form.addRow("Inactivity→selector (s)", self._inactivity)
        ticket_form.addRow("Aurum NetworkHostName", self._aurum_host)
        root.addWidget(ticket_box)

        # Keyboard
        kb_box = QGroupBox("Keyboard.xml buttons")
        kb_layout = QVBoxLayout(kb_box)
        self._keyboard_table = QTableWidget(0, 2)
        self._keyboard_table.setHorizontalHeaderLabels(["Hardware id", "Function"])
        self._keyboard_table.horizontalHeader().setStretchLastSection(True)
        self._keyboard_table.setMinimumHeight(140)
        kb_layout.addWidget(self._keyboard_table)
        kb_btns = QHBoxLayout()
        add_kb = QPushButton("Add row")
        add_kb.clicked.connect(self._add_keyboard_row)
        kb_btns.addWidget(add_kb)
        kb_btns.addStretch(1)
        kb_layout.addLayout(kb_btns)
        root.addWidget(kb_box)

        # Denoms / math
        math_box = QGroupBox("Denominations / bet steps (per game)")
        math_layout = QVBoxLayout(math_box)
        self._denoms_edit = QLineEdit()
        self._denoms_edit.setPlaceholderText("mgconfig DenominationList, e.g. 5 or 5,10")
        self._credit_edit = QLineEdit()
        self._credit_edit.setPlaceholderText("CreditRateValues, e.g. 5")
        math_form = QFormLayout()
        math_form.addRow("DenominationList", self._denoms_edit)
        math_form.addRow("CreditRateValues", self._credit_edit)
        math_layout.addLayout(math_form)
        self._math_table = QTableWidget(0, 5)
        self._math_table.setHorizontalHeaderLabels(
            ["Theme", "Denom×", "FixedBet", "Bet steps", "RTP"]
        )
        self._math_table.horizontalHeader().setStretchLastSection(True)
        self._math_table.setMinimumHeight(160)
        math_layout.addWidget(self._math_table)
        root.addWidget(math_box)

        # Bill tokens
        tokens_box = QGroupBox("Bill note values (HardwareConfig TokenMapping)")
        tokens_layout = QVBoxLayout(tokens_box)
        self._tokens_table = QTableWidget(0, 2)
        self._tokens_table.setHorizontalHeaderLabels(["Code", "Value"])
        self._tokens_table.horizontalHeader().setStretchLastSection(True)
        self._tokens_table.setMaximumHeight(120)
        tokens_layout.addWidget(self._tokens_table)
        root.addWidget(tokens_box)

        actions = QHBoxLayout()
        export_btn = QPushButton("Export EGM update…")
        export_btn.setObjectName("primary")
        export_btn.clicked.connect(self._export_egm_update)
        actions.addWidget(export_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        root.addStretch(1)

    def _browse_goldclub(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Goldclub root", r"C:\Goldclub")
        if path:
            self._path_edit.setText(path)

    def _resolved_goldclub(self) -> Path:
        raw = self._path_edit.text().strip() or r"C:\Goldclub"
        return goldclub_root_from_target(raw)

    def _load_from_machine(self) -> None:
        root = self._resolved_goldclub()
        if not root.is_dir():
            QMessageBox.warning(self, "Load", f"Folder not found:\n{root}")
            return
        try:
            recipe = load_recipe_from_goldclub(root, label=self._label_edit.text().strip())
        except OSError as exc:
            QMessageBox.warning(self, "Load", str(exc))
            return
        self._goldclub = root
        self._recipe = recipe
        self._populate_from_recipe(recipe)
        self._status.setText(f"Loaded settings from {root}")

    def _populate_from_recipe(self, recipe: SlotSetupRecipe) -> None:
        self._label_edit.setText(recipe.label)
        self._sas_enabled.setChecked(recipe.sas.enabled)
        self._sas_address.setValue(recipe.sas.address)
        self._sas_aft.setChecked(recipe.sas.aft_enabled)
        idx = self._sas_transfer.findText(recipe.sas.funds_transfer_type)
        self._sas_transfer.setCurrentIndex(max(0, idx))
        self._sas_lock.setChecked(recipe.sas.lock_game_when_no_comms)
        pidx = self._bill_protocol.findText(recipe.bill_protocol)
        self._bill_protocol.setCurrentIndex(max(0, pidx))

        self._keyboard_table.setRowCount(0)
        for hid, function in sorted(recipe.keyboard.items()):
            self._add_keyboard_row(hid, function)

        self._denoms_edit.setText(",".join(str(x) for x in recipe.denomination_list))
        self._credit_edit.setText(",".join(str(x) for x in recipe.credit_rate_values))

        self._math_table.setRowCount(0)
        for math in recipe.math:
            row = self._math_table.rowCount()
            self._math_table.insertRow(row)
            self._math_table.setItem(row, 0, QTableWidgetItem(math.theme))
            self._math_table.setItem(
                row, 1, QTableWidgetItem(str(math.denomination_multiplier))
            )
            self._math_table.setItem(
                row,
                2,
                QTableWidgetItem("" if math.fixed_bet is None else str(math.fixed_bet)),
            )
            self._math_table.setItem(
                row, 3, QTableWidgetItem(",".join(str(x) for x in math.bet_multipliers))
            )
            self._math_table.setItem(
                row, 4, QTableWidgetItem(math.return_percent or "")
            )

        self._tokens_table.setRowCount(0)
        for token in recipe.bill_tokens:
            row = self._tokens_table.rowCount()
            self._tokens_table.insertRow(row)
            self._tokens_table.setItem(row, 0, QTableWidgetItem(token.code))
            self._tokens_table.setItem(row, 1, QTableWidgetItem(str(token.value)))

        self._jur_tag.setText(recipe.jurisdiction.tag)
        self._jur_culture.setText(recipe.jurisdiction.culture_name)
        self._jur_currency.setText(recipe.jurisdiction.currency_name)
        self._jur_symbol.setText(recipe.jurisdiction.currency_symbol)
        if recipe.jurisdiction.magic_wheel_money_limit is None:
            self._jur_limit.setValue(0)
        else:
            self._jur_limit.setValue(recipe.jurisdiction.magic_wheel_money_limit)
        self._hw_currency.setText(recipe.hardware_currency_name)
        if recipe.offline_enabled is None:
            self._offline.setCurrentIndex(0)
        elif recipe.offline_enabled:
            self._offline.setCurrentIndex(1)
        else:
            self._offline.setCurrentIndex(2)
        self._include_oticket.setChecked(recipe.include_oticket)
        self._dallas_code.setText(recipe.dallas.code)
        self._dallas_group.setText(recipe.dallas.group or "Service")
        self._dallas_unlock.setChecked(recipe.dallas.unlock)
        self._machine_id.setText(recipe.mg_identity.machine_id_template)
        self._language.setText(recipe.mg_identity.language)
        if recipe.mg_identity.inactivity_seconds_to_game_selector is None:
            self._inactivity.setValue(-1)
        else:
            self._inactivity.setValue(
                recipe.mg_identity.inactivity_seconds_to_game_selector
            )
        self._aurum_host.setText(recipe.aurum_identity.network_hostname_template)

    def _add_keyboard_row(
        self, hardware_id: str = "", function: str = "Spin"
    ) -> None:
        row = self._keyboard_table.rowCount()
        self._keyboard_table.insertRow(row)
        self._keyboard_table.setItem(row, 0, QTableWidgetItem(str(hardware_id)))
        combo = QComboBox()
        combo.addItems(list(KEYBOARD_FUNCTIONS))
        idx = combo.findText(function)
        combo.setCurrentIndex(max(0, idx))
        self._keyboard_table.setCellWidget(row, 1, combo)

    def _parse_int_list(self, text: str) -> list[int]:
        values: list[int] = []
        for part in (text or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            values.append(int(part))
        return values

    def _collect_recipe(self) -> SlotSetupRecipe:
        keyboard: dict[str, str] = {}
        for row in range(self._keyboard_table.rowCount()):
            id_item = self._keyboard_table.item(row, 0)
            combo = self._keyboard_table.cellWidget(row, 1)
            if id_item is None or not id_item.text().strip():
                continue
            function = (
                combo.currentText() if isinstance(combo, QComboBox) else "Spin"
            )
            keyboard[id_item.text().strip()] = function

        math: list[MathDenomSettings] = []
        for row in range(self._math_table.rowCount()):
            theme_item = self._math_table.item(row, 0)
            if theme_item is None or not theme_item.text().strip():
                continue
            denom = self._math_table.item(row, 1)
            fixed = self._math_table.item(row, 2)
            bets = self._math_table.item(row, 3)
            rtp = self._math_table.item(row, 4)
            fixed_bet = None
            if fixed is not None and fixed.text().strip():
                fixed_bet = float(fixed.text().strip())
            math.append(
                MathDenomSettings(
                    theme=theme_item.text().strip(),
                    denomination_multiplier=int(
                        (denom.text() if denom else "1").strip() or "1"
                    ),
                    fixed_bet=fixed_bet,
                    bet_multipliers=self._parse_int_list(
                        bets.text() if bets else ""
                    ),
                    return_percent=(rtp.text().strip() if rtp else "") or None,
                )
            )

        tokens: list[BillToken] = []
        for row in range(self._tokens_table.rowCount()):
            code_item = self._tokens_table.item(row, 0)
            value_item = self._tokens_table.item(row, 1)
            if code_item is None or value_item is None:
                continue
            if not code_item.text().strip():
                continue
            tokens.append(
                BillToken(
                    code=code_item.text().strip(),
                    value=int(value_item.text().strip() or "0"),
                )
            )

        return SlotSetupRecipe(
            label=self._label_edit.text().strip(),
            sas=SasSettings(
                enabled=self._sas_enabled.isChecked(),
                address=self._sas_address.value(),
                aft_enabled=self._sas_aft.isChecked(),
                funds_transfer_type=self._sas_transfer.currentText(),
                lock_game_when_no_comms=self._sas_lock.isChecked(),
            ),
            bill_protocol=self._bill_protocol.currentText(),
            keyboard=keyboard,
            bill_tokens=tokens,
            math=math,
            denomination_list=self._parse_int_list(self._denoms_edit.text()),
            credit_rate_values=self._parse_int_list(self._credit_edit.text()),
            jurisdiction=JurisdictionSettings(
                tag=self._jur_tag.text().strip(),
                culture_name=self._jur_culture.text().strip(),
                currency_name=self._jur_currency.text().strip(),
                currency_symbol=self._jur_symbol.text().strip(),
                magic_wheel_money_limit=(
                    None if self._jur_limit.value() == 0 else self._jur_limit.value()
                ),
            ),
            mg_identity=MgIdentitySettings(
                machine_id_template=self._machine_id.text().strip()
                or "GST!!MachineName!!",
                language=self._language.text().strip(),
                inactivity_seconds_to_game_selector=(
                    None if self._inactivity.value() < 0 else self._inactivity.value()
                ),
            ),
            offline_enabled=(
                None
                if self._offline.currentIndex() == 0
                else self._offline.currentIndex() == 1
            ),
            hardware_currency_name=self._hw_currency.text().strip(),
            dallas=DallasSettings(
                code=self._dallas_code.text().strip(),
                unlock=self._dallas_unlock.isChecked(),
                group=self._dallas_group.text().strip() or "Service",
            ),
            aurum_identity=AurumIdentitySettings(
                network_hostname_template=self._aurum_host.text().strip()
                or "GST!!MachineName!!",
            ),
            include_oticket=self._include_oticket.isChecked(),
        )

    def _export_egm_update(self) -> None:
        root = self._resolved_goldclub()
        if not root.is_dir():
            QMessageBox.warning(self, "Export", f"Goldclub root not found:\n{root}")
            return
        try:
            recipe = self._collect_recipe()
        except ValueError as exc:
            QMessageBox.warning(self, "Export", f"Invalid value: {exc}")
            return

        out_dir = QFileDialog.getExistingDirectory(
            self, "Export EGM update folder", str(Path.home())
        )
        if not out_dir:
            return
        out = Path(out_dir)
        pack_dir = out / "_config-pack-staging"
        try:
            built = build_config_pack(recipe, root, pack_dir)
            safe_label = "".join(
                ch if ch.isalnum() or ch in "-_" else "_"
                for ch in (recipe.label or "EGM")
            ).strip("_") or "EGM"
            result = pack_egm_update(
                out,
                pack_dir,
                package_name=f"ConfigScanner_EGM_{safe_label}",
                encrypt=True,
            )
        except (OSError, FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        finally:
            # Keep staging only if pack failed mid-way; prefer cleanup.
            pass

        summary = "\n".join(recipe_summary_lines(built))
        QMessageBox.information(
            self,
            "Export complete",
            f"{result.note}\n\n{summary}\n\nFiles: {len(built.files)}",
        )
        self._status.setText(result.note)


class SlotApplyPanel(QWidget):
    """Apply-only review UI for a field ``--apply-pack`` launch."""

    def __init__(self, pack_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pack_dir = Path(pack_dir)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Apply EGM configuration pack")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        root.addWidget(self._summary, stretch=1)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Write to:"))
        self._dest_edit = QLineEdit(r"C:\Goldclub")
        dest_row.addWidget(self._dest_edit, stretch=1)
        root.addLayout(dest_row)

        apply_btn = QPushButton("Apply to this machine")
        apply_btn.setObjectName("primary")
        apply_btn.clicked.connect(self._apply)
        root.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._load_summary()

    def _load_summary(self) -> None:
        recipe_path = self._pack_dir / "recipe.json"
        if not recipe_path.is_file():
            self._summary.setPlainText(f"Missing recipe.json in:\n{self._pack_dir}")
            return
        try:
            recipe = load_recipe(recipe_path)
        except (OSError, ValueError, TypeError) as exc:
            self._summary.setPlainText(f"Failed to read recipe:\n{exc}")
            return
        lines = recipe_summary_lines(recipe)
        lines.append("")
        lines.append("Files to write:")
        for rel in recipe.files:
            lines.append(f"  • {rel}")
        if not recipe.files:
            lines.append("  (all staged files under config-pack)")
        self._summary.setPlainText("\n".join(lines))

    def _apply(self) -> None:
        dest = goldclub_root_from_target(self._dest_edit.text().strip() or r"C:\Goldclub")
        if not dest.is_dir():
            QMessageBox.warning(self, "Apply", f"Destination not found:\n{dest}")
            return
        reply = QMessageBox.question(
            self,
            "Apply configuration",
            f"Write the packed settings onto:\n{dest}\n\n"
            "Licence XML and serialport layout are never written.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = apply_config_pack(self._pack_dir, dest)
        msg = (
            f"Wrote {len(result.written)} file(s).\n"
            f"Skipped: {len(result.skipped)}\n"
            f"Errors: {len(result.errors)}"
        )
        if result.errors:
            msg += "\n\n" + "\n".join(result.errors[:12])
            QMessageBox.warning(self, "Apply finished with errors", msg)
        else:
            QMessageBox.information(self, "Apply complete", msg)
        self._status.setText(msg)
