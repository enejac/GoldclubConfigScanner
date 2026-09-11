"""Slot EGM setup recipe: SAS, MEI/JCM bill, ticket printer, Keyboard.xml,
denoms / bet steps, jurisdiction, offline ticket, Dallas key, door switches
(HardwareConfig AutoUnlock), mgconfig/Aurum identity placeholders.

Used by the authoring GUI and by ``--apply-pack`` on the field EGM.
Does not rewrite serialport layout/locations or licence XML.
"""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config_scanner.machine_identity import (
    is_jurisdiction_config_path,
    merge_xml_bytes_preserving_identity,
    normalize_rel_path,
    postprocess_jurisdiction_xml_bytes,
)
from config_scanner.read_cache import (
    cached_parse,
    cached_resolve,
    read_exe_bytes_cached,
)
from config_scanner.write_scope import _SERIALPORT_DIR_RE
from network.lab_access import safe_join_under

RECIPE_VERSION = 2

KEYBOARD_FUNCTIONS: tuple[str, ...] = (
    "Collect",
    "WaitBonus",
    "Help",
    "BetMinus",
    "Call",
    "BetPlus",
    "MultiGameSelection",
    "MaxBet",
    "Spin",
    "IGTKeyReset",
    "IGTKeyAudit",
)

BILL_PROTOCOLS: tuple[str, ...] = ("MEI", "JCM")

# HWSetup 2.2 only ships two TicketPrinter DLLs. GEN5 is a JCM device, not a third driver.
TICKET_PROTOCOLS: tuple[str, ...] = ("JCM", "TRANSACT")
TICKET_PROTOCOL_LABELS: dict[str, str] = {
    "JCM": "JCM — FutureLogic GEN2 / GEN5",
    "TRANSACT": "TRANSACT — Ithaca Epic 950",
}
TICKET_HW_DRIVER: dict[str, str] = {
    "JCM": "GoldClub.HW.Subsys.Driver.TicketPrinter.FutureLogic.PSA66ST2",
    "TRANSACT": "GoldClub.HW.Subsys.Driver.TicketPrinter.Ithaca.Epic950",
}

_QUIXANT_REL = "slot/hwdrivers/QuixantHardware.xml"
_KEYBOARD_REL = "slot/hwdrivers/Keyboard.xml"
_HARDWARE_CONFIG_REL = "slot/themes/HardwareConfig.xml"
_MGCONFIG_REL = "slot/themes/mgconfig.xml"
_JURISDICTION_REL = "slot/themes/jurisdiction_config.xml"
_CLIENTS_SET_REL = "Services/aurum/config/SASControler1/ClientsSet.xml"
_SAS_SETUP_REL = "Services/aurum/config/SASControler1/SASsetupData.xml"
_AURUM_SETUP_REL = "Services/aurum/config/AurumSetup.xml"
_OTICKET_REL = "bios/etc/application/slot/oticket.xml"
_MAGICWHEEL_REL = "slot/themes/magicwheel_Config.xml"
# Newer OneHand / gamepack trees also keep wheel knobs on the theme file
# named by mgconfig MagicWheelPath, or only in jurisdiction_config.
_MAGICWHEEL_THEME_RELS: tuple[str, ...] = (
    "slot/themes/magicwheel.xml",
    "slot/themes/magicwheel_3Screens.xml",
    "themes/magicwheel.xml",
    "themes/magicwheel_3Screens.xml",
)
_BILL_PROTO_DIR = "slot/hwdrivers/protocols/billacceptor"
_TICKET_PROTO_DIR = "slot/hwdrivers/protocols/ticketprinter"
_DRIVERSSETUP_RELS: tuple[str, ...] = (
    "bios/etc/application/HW/driverssetup/configuration.xml",
    "config/etc/application/HW/driverssetup/configuration.xml",
)
_TICKET_DRIVER_HINT_RE = re.compile(
    r"ticketprinter|futurelogic|ithaca|epic950|psa66",
    re.IGNORECASE,
)
_BRACKET_RE = re.compile(r"\[([^\]]+)\]")

_NS_STRIP_RE = re.compile(r"^\{[^}]+\}")
_IGT_DALLAS_RE = re.compile(r"^IGTKey", re.IGNORECASE)


# Aurum "SAS channel functionality" checkboxes (GoldClub spelling: controler).
# Stored as EgmsDevices/OwnerHostId on the SAS host (SASControler1), not ClientsSet.
SAS_CHANNEL_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("validation_controler", "Validation controler", ("voucher",)),
    ("cashless_controler", "Cashless controler", ("WAT",)),
    ("handpay_controler", "Handpay controler", ("handpay",)),
    ("bonusing_controler", "Bonusing controler", ("bonus",)),
    ("note_acceptor_controler", "Note acceptor controler", ("noteAcceptor",)),
)
SAS_CHANNEL_HOST_NAMES: tuple[str, ...] = ("SASControler1", "SASController1")

# OneHand Hardware Setup → Switch Settings. Din pins are board/firmware, not here.
DOOR_SWITCH_ALERTS: tuple[str, ...] = ("NONE", "SEMAPHORE", "SOUND", "BOTH")
DOOR_SWITCH_NAMES: tuple[tuple[str, str], ...] = (
    ("cabinet_door", "Cabinet door"),
    ("logic_door", "Logic door"),
    ("note_door", "Note door"),
    ("drop_door", "Drop door"),
    ("stacker_door", "Stacker"),
    ("auxiliary_door", "Auxiliary door"),
    ("custom", "Custom"),
    ("reserved", "Reserved"),
)
DOOR_SWITCH_LABELS: dict[str, str] = {name: label for name, label in DOOR_SWITCH_NAMES}
# Live HardwareConfig on 10.0.0.111 (4 Sep 2026) — no custom/reserved rows.
STANDARD_DOOR_SWITCH_NAMES: tuple[str, ...] = tuple(
    name for name, _ in DOOR_SWITCH_NAMES if name not in ("custom", "reserved")
)


@dataclass
class SasSettings:
    enabled: bool = True
    address: int = 1
    aft_enabled: bool = True
    funds_transfer_type: str = "AFT"
    lock_game_when_no_comms: bool = True
    validation_controler: bool = True
    cashless_controler: bool = True
    handpay_controler: bool = True
    bonusing_controler: bool = True
    note_acceptor_controler: bool = True


@dataclass
class DoorSwitchRow:
    name: str
    alert_type: str = "SEMAPHORE"
    auto_unlock: bool = False
    offline_trigger: bool = False


def default_door_switch_row(name: str) -> DoorSwitchRow:
    return DoorSwitchRow(
        name=name,
        alert_type="BOTH" if name == "cabinet_door" else "SEMAPHORE",
        auto_unlock=False,
        offline_trigger=False,
    )


def default_door_switch_items() -> list[DoorSwitchRow]:
    """Match live 10.0.0.111 HardwareConfig (all AutoUnlock off)."""
    return [default_door_switch_row(name) for name in STANDARD_DOOR_SWITCH_NAMES]


@dataclass
class DoorSwitchSettings:
    """OneHand HardwareConfig SwitchesSettings + stacker auto-unlock.

    Switch Config Intelligent also writes encrypted
    ``bios/etc/application/game/switches.xml``; Live Push does not rewrite that.
    """

    enabled: bool = True
    stacker_installed_auto_unlock: bool = True
    items: list[DoorSwitchRow] = field(default_factory=default_door_switch_items)

    def row(self, name: str) -> DoorSwitchRow | None:
        want = (name or "").strip()
        for item in self.items:
            if item.name == want:
                return item
        return None

    def auto_unlock_for(self, name: str) -> bool:
        found = self.row(name)
        return bool(found.auto_unlock) if found is not None else False

    def set_auto_unlock(self, name: str, value: bool) -> None:
        found = self.row(name)
        if found is None:
            found = default_door_switch_row(name)
            self.items.append(found)
        found.auto_unlock = bool(value)

    def all_auto_unlock(self) -> bool:
        rows = [self.row(name) for name in STANDARD_DOOR_SWITCH_NAMES]
        present = [item for item in rows if item is not None]
        return bool(present) and all(item.auto_unlock for item in present)

    def touches(self) -> bool:
        return True


@dataclass
class BillToken:
    code: str
    value: int
    can_accept: bool = True
    can_return: bool = True


# Trinidad TTD OL+SAS CS leaves: MEI hardware codes 97-102 (not 97-103 USD layout).
TTD_MEI_BILL_TOKENS: tuple[BillToken, ...] = (
    BillToken(code="97", value=100),
    BillToken(code="98", value=500),
    BillToken(code="99", value=1000),
    BillToken(code="100", value=2000),
    BillToken(code="101", value=5000),
    BillToken(code="102", value=10000),
)
MEI_BILL_CODES: tuple[str, ...] = tuple(str(c) for c in range(97, 103))


def default_bill_tokens_for_currency(currency_name: str) -> list[BillToken]:
    """Shipped bill-token table for a currency when jurisdiction JSON has no bill.tokens."""
    if (currency_name or "").strip().upper() == "TTD":
        return list(TTD_MEI_BILL_TOKENS)
    return []


def mei_bill_token_issues(tokens: list[BillToken]) -> list[str]:
    """Detect MEI bill-code layouts that break OneHand BillAcceptorPanel (KeyNotFoundException)."""
    if not tokens:
        return []
    codes = {(t.code or "").strip() for t in tokens}
    issues: list[str] = []
    if "103" in codes:
        issues.append(
            "bill code 103 is a 7-note USD layout; MEI OneHand setup expects codes 97-102 only"
        )
    if codes & set(MEI_BILL_CODES) and "98" not in codes:
        issues.append(
            "missing bill code 98; OneHand BillAcceptorPanel lookup fails on MEI denominations"
        )
    extra = sorted(c for c in codes if c.isdigit() and int(c) > 102)
    if extra:
        issues.append(f"unexpected high bill codes: {', '.join(extra)}")
    return issues


def normalize_mei_bill_tokens_for_currency(
    tokens: list[BillToken], currency_name: str
) -> list[BillToken]:
    """Replace broken MEI token maps with the shipped table for known currencies."""
    if mei_bill_token_issues(tokens):
        default = default_bill_tokens_for_currency(currency_name)
        if default:
            return list(default)
    return list(tokens)


@dataclass
class MathDenomSettings:
    theme: str
    denomination_multiplier: int = 1
    fixed_bet: float | None = None
    bet_multipliers: list[int] = field(default_factory=list)
    return_percent: str | None = None


@dataclass
class JurisdictionSettings:
    tag: str = ""
    culture_name: str = ""
    currency_name: str = ""
    currency_symbol: str = ""
    magic_wheel_money_limit: int | None = None


@dataclass
class MgIdentitySettings:
    machine_id_template: str = "GST!!MachineName!!"
    language: str = ""
    inactivity_seconds_to_game_selector: int | None = None
    jurisdiction_settings_file: str = r"themes\\jurisdiction_config.xml"


@dataclass
class DallasSettings:
    code: str = ""
    unlock: bool = True
    group: str = "Service"


@dataclass
class AurumIdentitySettings:
    network_hostname_template: str = "GST!!MachineName!!"


@dataclass
class PlayLimitsSettings:
    """Jackpot / magic wheel / UI play knobs. None or empty = leave live value."""

    jackpot_counters: int | None = None
    jackpot_receipt_layout: str = ""
    celebration_limit: str = ""
    cashout_button_mode: str = ""
    show_all_lines: bool | None = None
    show_denom_selector: bool | None = None
    ticket_redeem_enabled: bool | None = None
    ticket_use_currency_iso: bool | None = None
    default_bet: str = ""
    magic_wheel_enabled: bool | None = None
    magic_wheel_bet: int | None = None
    magic_wheel_max_spins: int | None = None
    magic_wheel_average: int | None = None
    bet_multipliers: list[int] = field(default_factory=list)

    def touches_mgconfig(self) -> bool:
        return bool(
            self.jackpot_counters is not None
            or self.celebration_limit
            or self.cashout_button_mode
            or self.show_all_lines is not None
            or self.show_denom_selector is not None
            or self.default_bet
        )

    def touches_hardware(self) -> bool:
        return bool(
            self.jackpot_receipt_layout
            or self.ticket_redeem_enabled is not None
            or self.ticket_use_currency_iso is not None
        )

    def touches_magicwheel(self) -> bool:
        return bool(
            self.magic_wheel_enabled is not None
            or self.magic_wheel_bet is not None
            or self.magic_wheel_max_spins is not None
            or self.magic_wheel_average is not None
        )


@dataclass(frozen=True)
class LimitSetupFieldSpec:
    """One Limit Setup row in OneHand (Configuration -> Limit Setup)."""

    key: str
    xml_tag: str
    label: str


# mgconfig.xml Multigamer/LimitSetup child tags (OneHand BillAcceptorPanel / LimitSetup form).
LIMIT_SETUP_FIELDS: tuple[LimitSetupFieldSpec, ...] = (
    LimitSetupFieldSpec("credit_limit", "CreditLimit", "Credit limit"),
    LimitSetupFieldSpec("jackpot_limit", "JackpotLimit", "Jackpot limit"),
    LimitSetupFieldSpec("max_hopper_payout", "MaxHopperPayout", "Max hopper payout limit"),
    LimitSetupFieldSpec("handpay_in_limit", "HandpayInLimit", "Handpay in limit"),
    LimitSetupFieldSpec("bill_limit", "BillLimit", "Bill limit"),
    LimitSetupFieldSpec("ticket_payout_limit", "TicketPayoutLimit", "Ticket payout limit"),
    LimitSetupFieldSpec("handpay_limit", "HandpayLimit", "Handpay limit"),
)


@dataclass
class LimitSetupSettings:
    """Machine credit/handpay limits stored under mgconfig LimitSetup."""

    credit_limit: int | None = None
    jackpot_limit: int | None = None
    max_hopper_payout: int | None = None
    handpay_in_limit: int | None = None
    bill_limit: int | None = None
    ticket_payout_limit: int | None = None
    handpay_limit: int | None = None
    credit_limit_host_locked: bool = False
    credit_limit_egm_locked: bool = False
    jackpot_limit_host_locked: bool = False
    jackpot_limit_egm_locked: bool = False
    max_hopper_payout_host_locked: bool = False
    max_hopper_payout_egm_locked: bool = False
    handpay_in_limit_host_locked: bool = False
    handpay_in_limit_egm_locked: bool = False
    bill_limit_host_locked: bool = False
    bill_limit_egm_locked: bool = False
    ticket_payout_limit_host_locked: bool = False
    ticket_payout_limit_egm_locked: bool = False
    handpay_limit_host_locked: bool = False
    handpay_limit_egm_locked: bool = False

    def value_for(self, key: str) -> int | None:
        return getattr(self, key)

    def host_locked_for(self, key: str) -> bool:
        return bool(getattr(self, f"{key}_host_locked"))

    def egm_locked_for(self, key: str) -> bool:
        return bool(getattr(self, f"{key}_egm_locked"))

    def editable_for(self, key: str) -> bool:
        return not (self.host_locked_for(key) or self.egm_locked_for(key))

    def touches_mgconfig(self) -> bool:
        return False

    def set_value(self, key: str, value: int | None) -> None:
        setattr(self, key, value)


def limit_setup_changed(
    live: LimitSetupSettings, recipe: LimitSetupSettings
) -> bool:
    """True when the recipe changes any editable limit field."""
    for spec in LIMIT_SETUP_FIELDS:
        if not live.editable_for(spec.key):
            continue
        if recipe.value_for(spec.key) is None:
            continue
        if recipe.value_for(spec.key) != live.value_for(spec.key):
            return True
    return False


def merge_play_limits(
    live: PlayLimitsSettings, preset: PlayLimitsSettings
) -> PlayLimitsSettings:
    data = asdict(live)
    for key, value in asdict(preset).items():
        if value is None or value == "" or value == []:
            continue
        data[key] = value
    return PlayLimitsSettings(**data)


@dataclass
class SlotSetupRecipe:
    version: int = RECIPE_VERSION
    label: str = ""
    sas: SasSettings = field(default_factory=SasSettings)
    bill_protocol: str = "MEI"
    ticket_protocol: str = ""
    keyboard: dict[str, str] = field(default_factory=dict)
    bill_tokens: list[BillToken] = field(default_factory=list)
    math: list[MathDenomSettings] = field(default_factory=list)
    denomination_list: list[int] = field(default_factory=list)
    credit_rate_values: list[int] = field(default_factory=list)
    jurisdiction: JurisdictionSettings = field(default_factory=JurisdictionSettings)
    mg_identity: MgIdentitySettings = field(default_factory=MgIdentitySettings)
    offline_enabled: bool | None = None
    hardware_currency_name: str = ""
    dallas: DallasSettings = field(default_factory=DallasSettings)
    door_switches: DoorSwitchSettings = field(default_factory=DoorSwitchSettings)
    aurum_identity: AurumIdentitySettings = field(default_factory=AurumIdentitySettings)
    play_limits: PlayLimitsSettings = field(default_factory=PlayLimitsSettings)
    limit_setup: LimitSetupSettings = field(default_factory=LimitSetupSettings)
    include_oticket: bool = False
    # ``2`` or ``3`` to swap mgconfig UI paths; ``None`` leaves live paths.
    display_mode: str | None = None
    # ST3 / Rhapsody / Sublime_Axiomtek — whole Keyboard.xml + Lights.xml pack.
    hw_driver_profile: str | None = None
    # Relative Goldclub paths that the packed apply tree will write.
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "label": self.label,
            "sas": asdict(self.sas),
            "bill_protocol": self.bill_protocol,
            "ticket_protocol": self.ticket_protocol,
            "keyboard": dict(self.keyboard),
            "bill_tokens": [asdict(t) for t in self.bill_tokens],
            "math": [asdict(m) for m in self.math],
            "denomination_list": list(self.denomination_list),
            "credit_rate_values": list(self.credit_rate_values),
            "jurisdiction": asdict(self.jurisdiction),
            "mg_identity": asdict(self.mg_identity),
            "offline_enabled": self.offline_enabled,
            "hardware_currency_name": self.hardware_currency_name,
            "dallas": asdict(self.dallas),
            "door_switches": {
                "enabled": self.door_switches.enabled,
                "stacker_installed_auto_unlock": (
                    self.door_switches.stacker_installed_auto_unlock
                ),
                "items": [asdict(row) for row in self.door_switches.items],
            },
            "aurum_identity": asdict(self.aurum_identity),
            "play_limits": asdict(self.play_limits),
            "limit_setup": asdict(self.limit_setup),
            "include_oticket": self.include_oticket,
            "display_mode": self.display_mode,
            "hw_driver_profile": self.hw_driver_profile,
            "files": list(self.files),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlotSetupRecipe:
        sas_raw = data.get("sas") or {}
        sas = SasSettings(
            enabled=bool(sas_raw.get("enabled", True)),
            address=int(sas_raw.get("address", 1)),
            aft_enabled=bool(sas_raw.get("aft_enabled", True)),
            funds_transfer_type=str(sas_raw.get("funds_transfer_type") or "AFT"),
            lock_game_when_no_comms=bool(sas_raw.get("lock_game_when_no_comms", True)),
            validation_controler=bool(sas_raw.get("validation_controler", True)),
            cashless_controler=bool(sas_raw.get("cashless_controler", True)),
            handpay_controler=bool(sas_raw.get("handpay_controler", True)),
            bonusing_controler=bool(sas_raw.get("bonusing_controler", True)),
            note_acceptor_controler=bool(sas_raw.get("note_acceptor_controler", True)),
        )
        tokens = [
            BillToken(
                code=str(t.get("code", "")),
                value=int(t.get("value", 0)),
                can_accept=bool(t.get("can_accept", True)),
                can_return=bool(t.get("can_return", True)),
            )
            for t in (data.get("bill_tokens") or [])
            if isinstance(t, dict)
        ]
        math = [
            MathDenomSettings(
                theme=str(m.get("theme", "")),
                denomination_multiplier=int(m.get("denomination_multiplier", 1)),
                fixed_bet=(
                    float(m["fixed_bet"])
                    if m.get("fixed_bet") is not None
                    else None
                ),
                bet_multipliers=[int(x) for x in (m.get("bet_multipliers") or [])],
                return_percent=(
                    str(m["return_percent"]) if m.get("return_percent") else None
                ),
            )
            for m in (data.get("math") or [])
            if isinstance(m, dict) and m.get("theme")
        ]
        keyboard = {
            str(k): str(v)
            for k, v in (data.get("keyboard") or {}).items()
            if k is not None and v is not None
        }
        protocol = str(data.get("bill_protocol") or "MEI").upper()
        if protocol not in BILL_PROTOCOLS:
            protocol = "MEI"
        ticket_protocol = str(data.get("ticket_protocol") or "").upper()
        if ticket_protocol not in TICKET_PROTOCOLS:
            ticket_protocol = ""
        j_raw = data.get("jurisdiction") or {}
        jurisdiction = JurisdictionSettings(
            tag=str(j_raw.get("tag") or ""),
            culture_name=str(j_raw.get("culture_name") or ""),
            currency_name=str(j_raw.get("currency_name") or ""),
            currency_symbol=str(j_raw.get("currency_symbol") or ""),
            magic_wheel_money_limit=(
                int(j_raw["magic_wheel_money_limit"])
                if j_raw.get("magic_wheel_money_limit") is not None
                else None
            ),
        )
        mg_raw = data.get("mg_identity") or {}
        mg_identity = MgIdentitySettings(
            machine_id_template=str(
                mg_raw.get("machine_id_template") or "GST!!MachineName!!"
            ),
            language=str(mg_raw.get("language") or ""),
            inactivity_seconds_to_game_selector=(
                int(mg_raw["inactivity_seconds_to_game_selector"])
                if mg_raw.get("inactivity_seconds_to_game_selector") is not None
                else None
            ),
            jurisdiction_settings_file=str(
                mg_raw.get("jurisdiction_settings_file")
                or r"themes\\jurisdiction_config.xml"
            ),
        )
        d_raw = data.get("dallas") or {}
        dallas = DallasSettings(
            code=str(d_raw.get("code") or ""),
            unlock=bool(d_raw.get("unlock", True)),
            group=str(d_raw.get("group") or "Service"),
        )
        sw_raw = data.get("door_switches") or {}
        parsed_items = [
            DoorSwitchRow(
                name=str(row.get("name") or "").strip(),
                alert_type=_normalize_switch_alert(row.get("alert_type")),
                auto_unlock=bool(row.get("auto_unlock", False)),
                offline_trigger=bool(row.get("offline_trigger", False)),
            )
            for row in (sw_raw.get("items") or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        door_switches = DoorSwitchSettings(
            enabled=bool(sw_raw.get("enabled", True)),
            stacker_installed_auto_unlock=bool(
                sw_raw.get("stacker_installed_auto_unlock", True)
            ),
            items=parsed_items or default_door_switch_items(),
        )
        a_raw = data.get("aurum_identity") or {}
        aurum_identity = AurumIdentitySettings(
            network_hostname_template=str(
                a_raw.get("network_hostname_template") or "GST!!MachineName!!"
            ),
        )
        offline_raw = data.get("offline_enabled", None)
        offline_enabled = None if offline_raw is None else bool(offline_raw)
        p_raw = data.get("play_limits") or {}
        play_limits = PlayLimitsSettings(
            jackpot_counters=_parse_opt_int(p_raw.get("jackpot_counters")),
            jackpot_receipt_layout=str(p_raw.get("jackpot_receipt_layout") or ""),
            celebration_limit=str(p_raw.get("celebration_limit") or ""),
            cashout_button_mode=str(p_raw.get("cashout_button_mode") or ""),
            show_all_lines=_parse_opt_bool(p_raw.get("show_all_lines")),
            show_denom_selector=_parse_opt_bool(p_raw.get("show_denom_selector")),
            ticket_redeem_enabled=_parse_opt_bool(p_raw.get("ticket_redeem_enabled")),
            ticket_use_currency_iso=_parse_opt_bool(p_raw.get("ticket_use_currency_iso")),
            default_bet=str(p_raw.get("default_bet") or ""),
            magic_wheel_enabled=_parse_opt_bool(p_raw.get("magic_wheel_enabled")),
            magic_wheel_bet=_parse_opt_int(p_raw.get("magic_wheel_bet")),
            magic_wheel_max_spins=_parse_opt_int(p_raw.get("magic_wheel_max_spins")),
            magic_wheel_average=_parse_opt_int(p_raw.get("magic_wheel_average")),
            bet_multipliers=[int(x) for x in (p_raw.get("bet_multipliers") or [])],
        )
        ls_raw = data.get("limit_setup") or {}
        limit_setup = LimitSetupSettings(
            **{
                spec.key: _parse_opt_int(ls_raw.get(spec.key))
                for spec in LIMIT_SETUP_FIELDS
            },
            **{
                f"{spec.key}_host_locked": bool(ls_raw.get(f"{spec.key}_host_locked"))
                for spec in LIMIT_SETUP_FIELDS
            },
            **{
                f"{spec.key}_egm_locked": bool(ls_raw.get(f"{spec.key}_egm_locked"))
                for spec in LIMIT_SETUP_FIELDS
            },
        )
        return cls(
            version=int(data.get("version") or RECIPE_VERSION),
            label=str(data.get("label") or ""),
            sas=sas,
            bill_protocol=protocol,
            ticket_protocol=ticket_protocol,
            keyboard=keyboard,
            bill_tokens=tokens,
            math=math,
            denomination_list=[int(x) for x in (data.get("denomination_list") or [])],
            credit_rate_values=[
                int(x) for x in (data.get("credit_rate_values") or [])
            ],
            jurisdiction=jurisdiction,
            mg_identity=mg_identity,
            offline_enabled=offline_enabled,
            hardware_currency_name=str(data.get("hardware_currency_name") or ""),
            dallas=dallas,
            door_switches=door_switches,
            aurum_identity=aurum_identity,
            play_limits=play_limits,
            limit_setup=limit_setup,
            include_oticket=bool(data.get("include_oticket", False)),
            display_mode=_normalize_display_mode(data.get("display_mode")),
            hw_driver_profile=(
                str(data["hw_driver_profile"]).strip() or None
                if data.get("hw_driver_profile")
                else None
            ),
            files=[normalize_rel_path(p) for p in (data.get("files") or [])],
        )


@dataclass(frozen=True)
class ApplyResult:
    written: tuple[str, ...]
    skipped: tuple[str, ...]
    errors: tuple[str, ...]


def save_recipe(recipe: SlotSetupRecipe, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(recipe.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_recipe(path: Path) -> SlotSetupRecipe:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("recipe.json must be a JSON object")
    return SlotSetupRecipe.from_dict(data)


def _unc_parent_is_host_only(path: Path) -> bool:
    """True when ``path`` is ``\\\\host`` with no share (not a usable Goldclub root)."""
    text = str(path).replace("/", "\\").rstrip("\\")
    if not text.startswith("\\\\"):
        return False
    parts = [p for p in text[2:].split("\\") if p]
    return len(parts) < 2


def goldclub_root_from_target(target: str | Path) -> Path:
    """Lift ``…\\slot`` to the Goldclub root when OneHand lives there.

    Never walk a UNC ``\\\\host\\slot`` share up to ``\\\\host`` — that is not a
    folder. Prefer ``\\\\host\\c$\\Goldclub`` when the share itself is the inner
    slot directory.
    """
    root = Path(target)
    try:
        if (root / "slot" / "OneHand.exe").is_file() or (root / "slot" / "hwdrivers").is_dir():
            return root
        if root.name.casefold() == "slot" and (
            (root / "OneHand.exe").is_file() or (root / "hwdrivers").is_dir()
        ):
            parent = root.parent
            if _unc_parent_is_host_only(parent):
                host = str(parent).replace("/", "\\").strip("\\").split("\\")[0]
                for admin in (rf"\\{host}\c$\Goldclub", rf"\\{host}\c$\goldclub"):
                    admin_p = Path(admin)
                    try:
                        if (admin_p / "slot" / "hwdrivers").is_dir() or (
                            admin_p / "slot" / "OneHand.exe"
                        ).is_file():
                            return admin_p
                    except (OSError, TimeoutError):
                        continue
                return root
            return parent
    except (OSError, TimeoutError, ValueError):
        return root
    return root


def _local(tag: str) -> str:
    return _NS_STRIP_RE.sub("", tag)


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _find_desc(root: ET.Element, name: str) -> ET.Element | None:
    for el in root.iter():
        if _local(el.tag) == name:
            return el
    return None


def _ensure_child(parent: ET.Element, name: str) -> ET.Element:
    existing = _find_child(parent, name)
    if existing is not None:
        return existing
    # Preserve parent namespace if present.
    ns = ""
    if "}" in parent.tag:
        ns = parent.tag.split("}")[0] + "}"
    child = ET.SubElement(parent, f"{ns}{name}")
    return child


def _set_text(parent: ET.Element, name: str, text: str) -> None:
    el = _ensure_child(parent, name)
    el.text = text


def _elem_text(root: ET.Element, name: str) -> str:
    el = _find_desc(root, name)
    if el is None:
        return ""
    return (el.text or "").strip()


def _parse_opt_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return None


def _parse_opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool_xml(value: bool) -> str:
    return "true" if value else "false"


def _normalize_switch_alert(value: Any) -> str:
    text = str(value or "SEMAPHORE").strip().upper()
    if text in DOOR_SWITCH_ALERTS:
        return text
    return "SEMAPHORE"


def door_switch_label(name: str) -> str:
    token = (name or "").strip()
    return DOOR_SWITCH_LABELS.get(token, token.replace("_", " ").title() or "Switch")


def door_switch_auto_unlock_label(name: str) -> str:
    return f"{door_switch_label(name)} auto unlock"


def _xml_attr(el: ET.Element, *names: str) -> str:
    for name in names:
        raw = el.attrib.get(name)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
        for key, val in el.attrib.items():
            if _local(key) == name and str(val).strip():
                return str(val).strip()
    return ""


def _parse_xml(path: Path) -> ET.ElementTree:
    # Memoised while a live-load read scope is open (same file is read by
    # several recipe readers); plain ``ET.parse`` otherwise.
    return cached_parse(path, ET.parse)


def _xml_default_namespace(root: ET.Element) -> str | None:
    tag = root.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def _write_tree(tree: ET.ElementTree, path: Path) -> None:
    """Serialize XML without turning ``xmlns="…"`` into ``ns0:`` prefixes.

    ClientsSet / SASsetupData use a default namespace. ElementTree's default
    writer rewrites that as ``<ns0:ClientsSet xmlns:ns0="…"`` which C#
    XmlSerializer then fails to bind — SAS address/AFT never load.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    root = tree.getroot()
    kwargs: dict[str, object] = {"encoding": "utf-8", "xml_declaration": True}
    ns = _xml_default_namespace(root)
    if ns:
        kwargs["default_namespace"] = ns
    path.write_bytes(ET.tostring(root, **kwargs))


def _write_jurisdiction_config(tree: ET.ElementTree, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)
    path.write_bytes(postprocess_jurisdiction_xml_bytes(raw))


def read_keyboard_map(goldclub: Path) -> dict[str, str]:
    path = goldclub / _KEYBOARD_REL.replace("/", "\\")
    if not path.is_file():
        path = goldclub / _KEYBOARD_REL
    if not path.is_file():
        return {}
    root = _parse_xml(path).getroot()
    mapping = _find_desc(root, "mapping")
    if mapping is None:
        mapping = root
    out: dict[str, str] = {}
    for el in mapping:
        name = (el.attrib.get("name") or "").strip()
        text = (el.text or "").strip()
        if not name or not text:
            continue
        # ButtonMapping (modern) or letter tags from HWDrivers_ST3 packs.
        if _local(el.tag) == "ButtonMapping" or el.attrib.get("name") is not None:
            out[name] = text
    return out


def patch_keyboard_xml(src: Path, dest: Path, mapping: dict[str, str]) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()
    container = _find_desc(root, "mapping")
    if container is None:
        container = _ensure_child(root, "mapping")
    existing: dict[str, ET.Element] = {}
    for el in list(container):
        if _local(el.tag) == "ButtonMapping":
            name = (el.attrib.get("name") or "").strip()
            if name:
                existing[name] = el
    for name, function in mapping.items():
        if name in existing:
            existing[name].text = function
        else:
            ns = ""
            if "}" in container.tag:
                ns = container.tag.split("}")[0] + "}"
            el = ET.SubElement(container, f"{ns}ButtonMapping", {"name": name})
            el.text = function
    _write_tree(tree, dest)


def read_bill_protocol(goldclub: Path) -> str | None:
    path = goldclub / _QUIXANT_REL
    if not path.is_file():
        return None
    root = _parse_xml(path).getroot()
    bill = _find_desc(root, "BillAcceptor")
    if bill is None:
        return None
    proto = _find_child(bill, "currentProtocol")
    if proto is None or not (proto.text or "").strip():
        return None
    return (proto.text or "").strip().upper()


def patch_quixant_bill_protocol(src: Path, dest: Path, protocol: str) -> None:
    protocol = protocol.upper()
    if protocol not in BILL_PROTOCOLS:
        raise ValueError(f"Unsupported bill protocol: {protocol}")
    tree = _parse_xml(src)
    root = tree.getroot()
    bill = _find_desc(root, "BillAcceptor")
    if bill is None:
        raise ValueError("QuixantHardware.xml has no BillAcceptor section")
    # Never touch comPortName.
    _set_text(bill, "currentProtocol", protocol)
    settings = _find_child(bill, "currentProtocolSettings")
    if settings is None:
        settings = _ensure_child(bill, "currentProtocolSettings")
    _set_text(settings, "Protocol", protocol)
    supported = _find_child(settings, "SupportedDevices")
    if supported is None:
        supported = _ensure_child(settings, "SupportedDevices")
    for child in list(supported):
        supported.remove(child)
    ns = ""
    if "}" in supported.tag:
        ns = supported.tag.split("}")[0] + "}"
    if protocol == "MEI":
        device = ET.SubElement(supported, f"{ns}BillAcceptorProtocolDevice")
        _set_text(device, "Id", "MEI")
    else:
        for device_id in ("JCM UBA10", "JCM IVizion"):
            device = ET.SubElement(supported, f"{ns}BillAcceptorProtocolDevice")
            _set_text(device, "Id", device_id)
    ticket = _find_child(settings, "TicketValue")
    if ticket is None:
        _set_text(settings, "TicketValue", "111")
    _write_tree(tree, dest)


def ticket_protocol_from_hw_driver(raw: str) -> str | None:
    """Map an HWSetup ``driverRawName`` to JCM (FutureLogic) or TRANSACT (Ithaca)."""
    text = (raw or "").casefold()
    if "ithaca" in text or "epic950" in text:
        return "TRANSACT"
    if "futurelogic" in text or "psa66" in text:
        return "JCM"
    return None


def _replace_ticket_driver_in_raw(raw: str, protocol: str) -> str:
    target = TICKET_HW_DRIVER[protocol]
    last = None
    for match in _BRACKET_RE.finditer(raw):
        if _TICKET_DRIVER_HINT_RE.search(match.group(1)):
            last = match
    if last is not None:
        return raw[: last.start(1)] + target + raw[last.end(1) :]
    if _TICKET_DRIVER_HINT_RE.search(raw):
        return target
    return raw


def _tito_alias_name(item: ET.Element) -> str:
    name = (item.attrib.get("aliasName") or "").strip()
    alias = _find_child(item, "aliasName")
    if alias is not None and (alias.text or "").strip():
        name = (alias.text or "").strip()
    return name


def _is_tito_alias(name: str) -> bool:
    return name.strip().casefold().startswith("tito")


def _find_tito_item(root: ET.Element) -> ET.Element | None:
    drivers = _find_desc(root, "drivers")
    if drivers is None:
        return None
    for item in drivers:
        if _is_tito_alias(_tito_alias_name(item)):
            return item
    return None


def _driver_raw_el(item: ET.Element) -> ET.Element | None:
    el = _find_child(item, "driverRawName")
    if el is not None:
        return el
    options = _find_child(item, "options")
    if options is None:
        return None
    return _find_child(options, "driverRawName")


def _driverssetup_rel(goldclub: Path) -> str | None:
    for rel in _DRIVERSSETUP_RELS:
        if (goldclub / rel).is_file():
            return rel
    return None


def read_ticket_hw_protocol(goldclub: Path) -> str | None:
    rel = _driverssetup_rel(goldclub)
    if not rel:
        return None
    root = _parse_xml(goldclub / rel).getroot()
    item = _find_tito_item(root)
    if item is None:
        return None
    raw_el = _driver_raw_el(item)
    if raw_el is None:
        return None
    return ticket_protocol_from_hw_driver((raw_el.text or "").strip())


def read_ticket_quixant_protocol(goldclub: Path) -> str | None:
    path = goldclub / _QUIXANT_REL
    if not path.is_file():
        return None
    root = _parse_xml(path).getroot()
    ticket = _find_desc(root, "TicketPrinter")
    if ticket is None:
        return None
    proto = _find_child(ticket, "currentProtocol")
    if proto is None:
        return None
    value = (proto.text or "").strip().upper()
    if value not in TICKET_PROTOCOLS:
        return None
    return value


def read_ticket_protocol(goldclub: Path) -> str | None:
    """HWSetup tito driver if present, else OneHand ``TicketPrinter/currentProtocol``."""
    hw = read_ticket_hw_protocol(goldclub)
    if hw:
        return hw
    return read_ticket_quixant_protocol(goldclub)


def patch_quixant_ticket_protocol(src: Path, dest: Path, protocol: str) -> None:
    protocol = protocol.upper()
    if protocol not in TICKET_PROTOCOLS:
        raise ValueError(f"Unsupported ticket protocol: {protocol}")
    tree = _parse_xml(src)
    root = tree.getroot()
    ticket = _find_desc(root, "TicketPrinter")
    if ticket is None:
        ticket = _ensure_child(root, "TicketPrinter")
    # Never touch comPortName.
    _set_text(ticket, "currentProtocol", protocol)
    settings = _find_child(ticket, "currentProtocolSettings")
    if settings is not None:
        _set_text(settings, "Protocol", protocol)
    _write_tree(tree, dest)


def patch_tito_ticket_driver(src: Path, dest: Path, protocol: str) -> None:
    """Swap the tito TicketPrinter class in driverssetup; keep the TCP endpoint."""
    protocol = protocol.upper()
    if protocol not in TICKET_PROTOCOLS:
        raise ValueError(f"Unsupported ticket protocol: {protocol}")
    text = src.read_text(encoding="utf-8")
    tree = _parse_xml(src)
    item = _find_tito_item(tree.getroot())
    dest.parent.mkdir(parents=True, exist_ok=True)
    if item is None:
        if src.resolve() != dest.resolve():
            dest.write_text(text, encoding="utf-8")
        return
    raw_el = _driver_raw_el(item)
    old_raw = (raw_el.text or "").strip() if raw_el is not None else ""
    if not old_raw:
        if src.resolve() != dest.resolve():
            dest.write_text(text, encoding="utf-8")
        return
    new_raw = _replace_ticket_driver_in_raw(old_raw, protocol)
    if new_raw == old_raw:
        if src.resolve() != dest.resolve():
            dest.write_text(text, encoding="utf-8")
        return
    if old_raw in text:
        dest.write_text(text.replace(old_raw, new_raw, 1), encoding="utf-8")
        return
    if raw_el is not None:
        raw_el.text = new_raw
    _write_tree(tree, dest)


def read_bill_tokens(goldclub: Path) -> list[BillToken]:
    path = goldclub / _HARDWARE_CONFIG_REL
    if not path.is_file():
        return []
    root = _parse_xml(path).getroot()
    bills = _find_desc(root, "Bills")
    if bills is None:
        return []
    out: list[BillToken] = []
    for el in bills:
        if _local(el.tag) != "TokenMapping":
            continue
        code = (el.attrib.get("Code") or "").strip()
        try:
            value = int((el.text or "0").strip())
        except ValueError:
            continue
        out.append(
            BillToken(
                code=code,
                value=value,
                can_accept=(el.attrib.get("CanAccept", "true").lower() == "true"),
                can_return=(el.attrib.get("CanReturn", "true").lower() == "true"),
            )
        )
    return out


def patch_hardware_config_bills(
    src: Path, dest: Path, tokens: list[BillToken]
) -> None:
    patch_hardware_config(src, dest, tokens=tokens)


def patch_hardware_config(
    src: Path,
    dest: Path,
    *,
    tokens: list[BillToken] | None = None,
    offline_enabled: bool | None = None,
    currency_name: str | None = None,
    dallas: DallasSettings | None = None,
    ticket_redeem_enabled: bool | None = None,
    ticket_use_currency_iso: bool | None = None,
    jackpot_receipt_layout: str | None = None,
    door_switches: DoorSwitchSettings | None = None,
) -> None:
    """Patch HardwareConfig bills, OfflineEnabled, currency, Dallas, ticket extras."""
    tree = _parse_xml(src)
    root = tree.getroot()

    if tokens is not None:
        bill_settings = _find_desc(root, "BillSettings")
        if bill_settings is None:
            bill_settings = _ensure_child(root, "BillSettings")
        bills = _find_child(bill_settings, "Bills")
        if bills is None:
            bills = _ensure_child(bill_settings, "Bills")
        for child in list(bills):
            bills.remove(child)
        ns = ""
        if "}" in bills.tag:
            ns = bills.tag.split("}")[0] + "}"
        for token in tokens:
            el = ET.SubElement(
                bills,
                f"{ns}TokenMapping",
                {
                    "Code": token.code,
                    "CanAccept": "true" if token.can_accept else "false",
                    "CanReturn": "true" if token.can_return else "false",
                    "AcceptingDelayBetweenTokenInMS": "0",
                },
            )
            el.text = str(token.value)

    if currency_name:
        # Prefer top-level CurrencyName under HardwareSettings.
        top = _find_child(root, "CurrencyName")
        if top is not None:
            top.text = currency_name
        else:
            _set_text(root, "CurrencyName", currency_name)

    need_ticket = (
        offline_enabled is not None
        or ticket_redeem_enabled is not None
        or ticket_use_currency_iso is not None
        or bool(jackpot_receipt_layout)
    )
    if need_ticket:
        ticket = _find_desc(root, "TicketPrinterSettings")
        if ticket is None:
            ticket = _ensure_child(root, "TicketPrinterSettings")
        if offline_enabled is not None:
            _set_text(ticket, "OfflineEnabled", _bool_xml(offline_enabled))
        if ticket_redeem_enabled is not None:
            _set_text(ticket, "RedeemEnabled", _bool_xml(ticket_redeem_enabled))
        if ticket_use_currency_iso is not None:
            _set_text(ticket, "UseCurrencyISO", _bool_xml(ticket_use_currency_iso))
        if jackpot_receipt_layout:
            _set_text(ticket, "LayoutJackpotReceiptTicket", jackpot_receipt_layout)

    if dallas is not None and dallas.code.strip():
        _patch_dallas_key(root, dallas)

    if door_switches is not None:
        _patch_door_switches(root, door_switches)

    _write_tree(tree, dest)


def _patch_dallas_key(root: ET.Element, dallas: DallasSettings) -> None:
    settings = _find_desc(root, "DallasKeySettings")
    if settings is None:
        settings = _ensure_child(root, "DallasKeySettings")
    perms = _find_child(settings, "Permissions")
    if perms is None:
        perms = _ensure_child(settings, "Permissions")
    target: ET.Element | None = None
    for el in perms:
        if _local(el.tag) != "DallasKey":
            continue
        code_el = _find_child(el, "Code")
        code = (code_el.text or "").strip() if code_el is not None else ""
        if code == dallas.code or (code and not _IGT_DALLAS_RE.match(code)):
            target = el
            if code == dallas.code:
                break
    ns = ""
    if "}" in perms.tag:
        ns = perms.tag.split("}")[0] + "}"
    if target is None:
        target = ET.SubElement(perms, f"{ns}DallasKey")
    _set_text(target, "Code", dallas.code.strip())
    _set_text(target, "Unlock", "true" if dallas.unlock else "false")
    if dallas.group:
        groups = _find_child(target, "Groups")
        if groups is None:
            groups = _ensure_child(target, "Groups")
        # Keep a single group string matching recipe.
        for child in list(groups):
            groups.remove(child)
        gns = ""
        if "}" in groups.tag:
            gns = groups.tag.split("}")[0] + "}"
        el = ET.SubElement(groups, f"{gns}string")
        el.text = dallas.group


def _patch_door_switches(root: ET.Element, settings: DoorSwitchSettings) -> None:
    bill = _find_desc(root, "BillSettings")
    if bill is None:
        bill = _ensure_child(root, "BillSettings")
    _set_text(
        bill,
        "StackerInstalledAutoUnlock",
        _bool_xml(settings.stacker_installed_auto_unlock),
    )
    sw = _find_desc(root, "SwitchesSettings")
    if sw is None:
        sw = _ensure_child(root, "SwitchesSettings")
    _set_text(sw, "Enabled", _bool_xml(settings.enabled))
    items = settings.items or default_door_switch_items()
    lst = _find_child(sw, "SwitchSettingsList")
    if lst is None:
        lst = _ensure_child(sw, "SwitchSettingsList")
    by_name: dict[str, ET.Element] = {}
    for child in list(lst):
        if _local(child.tag) != "SwitchSettings":
            continue
        name = _xml_attr(child, "SwitchName")
        if name:
            by_name[name] = child
    ns = ""
    if "}" in lst.tag:
        ns = lst.tag.split("}")[0] + "}"
    for row in items:
        name = (row.name or "").strip()
        if not name:
            continue
        el = by_name.get(name)
        if el is None:
            el = ET.SubElement(lst, f"{ns}SwitchSettings")
        el.set("SwitchName", name)
        el.set("AlertType", _normalize_switch_alert(row.alert_type))
        el.set("AutoUnlock", _bool_xml(row.auto_unlock))
        el.set("OfflineTriggerAutoUnlock", _bool_xml(row.offline_trigger))


def read_door_switches(goldclub: Path) -> DoorSwitchSettings:
    path = goldclub / _HARDWARE_CONFIG_REL
    out = DoorSwitchSettings()
    if not path.is_file():
        return out
    root = _parse_xml(path).getroot()
    bill = _find_desc(root, "BillSettings")
    if bill is not None:
        stacker = _find_child(bill, "StackerInstalledAutoUnlock")
        if stacker is not None and (stacker.text or "").strip():
            out.stacker_installed_auto_unlock = (
                (stacker.text or "").strip().lower() == "true"
            )
    sw = _find_desc(root, "SwitchesSettings")
    if sw is None:
        return out
    enabled = _find_child(sw, "Enabled")
    if enabled is not None and (enabled.text or "").strip():
        out.enabled = (enabled.text or "").strip().lower() == "true"
    lst = _find_child(sw, "SwitchSettingsList")
    if lst is None:
        return out
    items: list[DoorSwitchRow] = []
    for el in lst:
        if _local(el.tag) != "SwitchSettings":
            continue
        name = _xml_attr(el, "SwitchName")
        if not name:
            continue
        items.append(
            DoorSwitchRow(
                name=name,
                alert_type=_normalize_switch_alert(_xml_attr(el, "AlertType")),
                auto_unlock=_xml_attr(el, "AutoUnlock").lower() == "true",
                offline_trigger=_xml_attr(el, "OfflineTriggerAutoUnlock").lower()
                == "true",
            )
        )
    out.items = items or default_door_switch_items()
    return out


def read_offline_enabled(goldclub: Path) -> bool | None:
    path = goldclub / _HARDWARE_CONFIG_REL
    if not path.is_file():
        return None
    root = _parse_xml(path).getroot()
    el = _find_desc(root, "OfflineEnabled")
    if el is None or not (el.text or "").strip():
        return None
    return (el.text or "").strip().lower() == "true"


def read_ticket_printer_active(goldclub: Path) -> bool:
    """True when HardwareConfig has ticket printer + redeem enabled (TITO can work)."""
    path = goldclub / _HARDWARE_CONFIG_REL
    if not path.is_file():
        return False
    root = _parse_xml(path).getroot()
    tps = _find_desc(root, "TicketPrinterSettings")
    if tps is None:
        return False
    enabled = _find_desc(tps, "Enabled")
    redeem = _find_desc(tps, "RedeemEnabled")
    on = (enabled.text or "").strip().lower() == "true" if enabled is not None else False
    redeem_on = (redeem.text or "").strip().lower() == "true" if redeem is not None else False
    return on and redeem_on


def read_hardware_currency_name(goldclub: Path) -> str:
    path = goldclub / _HARDWARE_CONFIG_REL
    if not path.is_file():
        return ""
    root = _parse_xml(path).getroot()
    el = _find_child(root, "CurrencyName")
    if el is not None and (el.text or "").strip():
        return (el.text or "").strip()
    return ""


def read_dallas_settings(goldclub: Path) -> DallasSettings:
    path = goldclub / _HARDWARE_CONFIG_REL
    settings = DallasSettings()
    if not path.is_file():
        return settings
    root = _parse_xml(path).getroot()
    perms = None
    dks = _find_desc(root, "DallasKeySettings")
    if dks is not None:
        perms = _find_child(dks, "Permissions")
    if perms is None:
        return settings
    for el in perms:
        if _local(el.tag) != "DallasKey":
            continue
        code_el = _find_child(el, "Code")
        code = (code_el.text or "").strip() if code_el is not None else ""
        if not code or _IGT_DALLAS_RE.match(code):
            continue
        unlock_el = _find_child(el, "Unlock")
        group = "Service"
        groups = _find_child(el, "Groups")
        if groups is not None:
            for child in groups:
                if _local(child.tag) == "string" and (child.text or "").strip():
                    group = (child.text or "").strip()
                    break
        return DallasSettings(
            code=code,
            unlock=(
                (unlock_el.text or "true").strip().lower() == "true"
                if unlock_el is not None
                else True
            ),
            group=group,
        )
    return settings


def read_jurisdiction_settings(goldclub: Path) -> JurisdictionSettings:
    """Read jurisdiction/locale from mgconfig (GameStar CS packs) or optional jurisdiction_config.xml."""
    out = JurisdictionSettings()
    mg = goldclub / _MGCONFIG_REL
    if mg.is_file():
        root = _parse_xml(mg).getroot()
        market = _find_desc(root, "TargetMarket")
        if market is not None and (market.text or "").strip():
            out.tag = (market.text or "").strip()
        culture = _find_desc(root, "CultureName")
        if culture is not None:
            out.culture_name = (culture.text or "").strip()
        currency = _find_child(root, "CurrencyName")
        if currency is None:
            currency = _find_desc(root, "CurrencyName")
        if currency is not None:
            out.currency_name = (currency.text or "").strip()
        symbol = _find_child(root, "CurrencyShortSymbol")
        if symbol is not None:
            out.currency_symbol = (symbol.text or "").strip()
        lang = _find_child(root, "Language")
        if lang is not None and (lang.text or "").strip() and not out.tag:
            # Language alone is not a tag; keep tag from TargetMarket.
            pass

    # Optional legacy / BiOS jurisdiction_config.xml (rare on GameStar 2.0.1 CS packs).
    path = goldclub / _JURISDICTION_REL
    if path.is_file():
        root = _parse_xml(path).getroot()
        tag = _find_child(root, "Tag")
        if tag is not None and (tag.text or "").strip():
            out.tag = (tag.text or "").strip()
        culture = _find_desc(root, "CultureName")
        if culture is not None and (culture.text or "").strip():
            out.culture_name = (culture.text or "").strip()
        currency = _find_desc(root, "CurrencyName")
        if currency is not None and (currency.text or "").strip():
            out.currency_name = (currency.text or "").strip()
        symbol = _find_desc(root, "CurrencySymbol")
        if symbol is not None and (symbol.text or "").strip():
            out.currency_symbol = (symbol.text or "").strip()
        pack = _find_child(root, "MagicWheelPackSettings")
        if pack is not None:
            fields = _read_magicwheel_fields(pack)
            if fields["money_limit"] is not None:
                out.magic_wheel_money_limit = fields["money_limit"]
        else:
            limit = _find_desc(root, "MoneyLimit")
            if limit is not None and (limit.text or "").strip().isdigit():
                out.magic_wheel_money_limit = int((limit.text or "").strip())
    return out


def read_jurisdiction_single_denomination(goldclub: Path) -> int | None:
    """OneHand on-screen denom from jurisdiction_config SingleDenomination.

    mgconfig DenominationList is the play list. The game UI still reads this
    leftover CS field; a stale 5c here shows 5c after we already wrote 10c.
    """
    path = goldclub / _JURISDICTION_REL
    if not path.is_file():
        return None
    root = _parse_xml(path).getroot()
    el = _find_desc(root, "SingleDenomination")
    if el is None or not (el.text or "").strip():
        return None
    try:
        return int((el.text or "").strip())
    except ValueError:
        return None


def leftover_jurisdiction_single_denomination(
    goldclub: Path, denomination_list: list[int] | None
) -> int | None:
    """Stale SingleDenomination when it disagrees with mgconfig's first denom."""
    if not denomination_list:
        return None
    single = read_jurisdiction_single_denomination(goldclub)
    if single is None:
        return None
    if single != int(denomination_list[0]):
        return single
    return None


def sas_channel_flags_differ(goldclub: Path, sas: SasSettings) -> bool:
    """True when SAS channel OwnerHostId flags disagree with live AurumSetup."""
    live_flags = read_sas_channel_flags(goldclub)
    for field, _label, _cls in SAS_CHANNEL_FIELDS:
        if bool(getattr(sas, field, True)) != bool(live_flags.get(field, True)):
            return True
    return False


# Union of Market names seen across GameStar Country Selector SKUs.
# XmlSerializer only accepts the subset baked into *that* OneHand.exe:
# GameStar **2.0.1** TRI (``.111``) has ``PuertoRico`` and not ``Jamaica``.
# GameStar **3.x** may include ``Jamaica`` — live push probes the live exe.
# ``TT`` is a UI/jurisdiction shorthand only — never write it to TargetMarket.
ONEHAND_TARGET_MARKETS: frozenset[str] = frozenset(
    {
        "PuertoRico",
        "TrinidadTobago",
        "Trinidad&Tobago",
        "Panama",
        "Jamaica",
        "Colombia",
        "Guyana",
        "Mexico",
        "Peru",
        "Poland",
        "SA",
        "SouthAfrica",
    }
)
# ``TT`` may keep these (same TRI/TTD line). Never keep Jamaica/Panama/… here.
_TT_ALIAS_KEEP_MARKETS: frozenset[str] = frozenset(
    {"PuertoRico", "TrinidadTobago", "Trinidad&Tobago"}
)
_ONEHAND_EXE_RELS: tuple[str, ...] = ("slot/OneHand.exe", "OneHand.exe")
_DEBUG_VERSION_TOKEN = re.compile(r"(?:^|[^a-z0-9])debug(?:[^a-z0-9]|$)", re.IGNORECASE)


def is_debug_onehand_version(text: str | None) -> bool:
    """True when a PE ProductVersion / FileVersion / name is the Debug SKU."""
    folded = (text or "").strip().casefold()
    if not folded:
        return False
    if folded == "debug" or folded.startswith("debug ") or folded.startswith("debug-"):
        return True
    return bool(_DEBUG_VERSION_TOKEN.search(folded))


def _utf16_string_after(blob: bytes, key: str) -> str:
    """Value that follows a UTF-16LE VERSIONINFO key (ProductVersion, …)."""
    needle = (key + "\0").encode("utf-16le")
    idx = blob.find(needle)
    if idx < 0:
        needle = key.encode("utf-16le")
        idx = blob.find(needle)
        if idx < 0:
            return ""
        rest = blob[idx + len(needle) : idx + len(needle) + 96]
    else:
        rest = blob[idx + len(needle) : idx + len(needle) + 96]
    try:
        text = rest.decode("utf-16le", errors="ignore")
    except Exception:
        return ""
    return text.replace("\x00", "").strip().split("\n", 1)[0].strip()


def is_onehand_debug_build(goldclub: Path) -> bool:
    """True when live ``OneHand.exe`` is the Debug SKU (no production licence).

    Prefers VERSIONINFO ``Debug`` tokens, then the latest SlotLog
    ``OneHand.MainFrm - DB`` line. Numbered FileVersion/ProductVersion is
    Release when that log line is absent. A cabinet that has never booted
    still classifies from the exe alone.
    """
    try:
        from config_scanner.build_version import detect_onehand_build

        info = detect_onehand_build(goldclub)
    except Exception:
        info = None
    if info is not None:
        return (info.configuration or "").strip().casefold() == "debug"
    path = onehand_exe_path(goldclub)
    if path is None:
        return False
    try:
        if "debug" in path.name.casefold():
            return True
    except OSError:
        return False
    try:
        from config_scanner.build_version import onehand_exe_is_debug_sku

        return bool(onehand_exe_is_debug_sku(path))
    except Exception:
        return False


def licence_push_default_checked(
    *,
    needs_push: bool,
    can_mirror: bool,
    has_source: bool,
    debug_onehand: bool,
) -> bool:
    """Default for Live Push “Push missing licence files”.

    Debug OneHand SKUs stay off so we do not copy production XML onto a
    lab debug binary. The operator can still tick the box by hand.
    """
    if not needs_push or debug_onehand:
        return False
    return bool(can_mirror or has_source)


def pick_onehand_allowed_market(
    allowed: frozenset[str] | set[str] | tuple[str, ...],
    *,
    preferred: str = "",
) -> str:
    """Stable TargetMarket pick when the operator chose an enum this OneHand lacks."""
    allowed_set = {str(x).strip() for x in allowed if str(x).strip()}
    if not allowed_set:
        return (preferred or "").strip()
    pref = (preferred or "").strip()
    if pref in allowed_set:
        return pref
    for name in ("PuertoRico", "TrinidadTobago", "Trinidad&Tobago", "TT"):
        if name in allowed_set:
            return name
    return sorted(allowed_set)[0]


def resolve_target_market_for_mgconfig(
    tag: str, existing_market: str | None = None
) -> str:
    """Map jurisdiction tags to a schema-valid ``TargetMarket`` value."""
    want = (tag or "").strip()
    existing = (existing_market or "").strip()
    if want in ONEHAND_TARGET_MARKETS:
        return want
    folded = want.casefold()
    if folded in ("tt", "trinidad", "trinidad & tobago", "trinidad and tobago"):
        if existing in _TT_ALIAS_KEEP_MARKETS:
            return existing
        return "PuertoRico"
    if folded in ("south africa", "southafrica", "zar"):
        return "SA"
    if existing in ONEHAND_TARGET_MARKETS:
        return existing
    return want


def _ascii_ident_present(data: bytes, token: str) -> bool:
    raw = token.encode("ascii")
    start = 0
    while True:
        idx = data.find(raw, start)
        if idx < 0:
            return False
        before = data[idx - 1] if idx else 0
        after_i = idx + len(raw)
        after = data[after_i] if after_i < len(data) else 0
        if not (65 <= before <= 90 or 97 <= before <= 122) and not (
            65 <= after <= 90 or 97 <= after <= 122
        ):
            return True
        start = idx + 1


def onehand_exe_path(goldclub: Path) -> Path | None:
    root = goldclub_root_from_target(goldclub)
    for rel in _ONEHAND_EXE_RELS:
        path = root / rel
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def markets_accepted_by_onehand(goldclub: Path) -> frozenset[str] | None:
    """Market enum tokens present as ASCII in this cabinet's OneHand.exe.

    Returns None when the exe is missing or no known tokens are found, so
    callers can skip the live-binary check (authoring fixtures, other SKUs).
    """
    path = onehand_exe_path(goldclub)
    if path is None:
        return None
    data = read_exe_bytes_cached(path)
    if data is None:
        try:
            data = path.read_bytes()
        except OSError:
            return None
    found = {
        name for name in ONEHAND_TARGET_MARKETS if _ascii_ident_present(data, name)
    }
    return frozenset(found) if found else None


def read_mgconfig_target_market(goldclub: Path) -> str:
    path = goldclub_root_from_target(goldclub) / _MGCONFIG_REL
    if not path.is_file():
        return ""
    try:
        root = _parse_xml(path).getroot()
    except (ET.ParseError, OSError):
        return ""
    return _existing_target_market(root)


def validate_onehand_target_market(
    proposed_tag: str,
    goldclub: Path,
    *,
    existing_market: str | None = None,
) -> list[str]:
    """Reject TargetMarket values this live OneHand XmlSerializer will refuse."""
    allowed = markets_accepted_by_onehand(goldclub)
    if not allowed:
        return []
    want = (proposed_tag or "").strip()
    if not want:
        return []
    existing = (existing_market if existing_market is not None else "").strip()
    if not existing:
        existing = read_mgconfig_target_market(goldclub)
    resolved = resolve_target_market_for_mgconfig(want, existing)
    if resolved in allowed:
        return []
    listed = ", ".join(sorted(allowed))
    return [
        f"This OneHand build does not accept TargetMarket={resolved!r} "
        f"(Market enum has {listed}). Keep {listed}; "
        f"{resolved} needs that market's Country Selector / OneHand SKU, "
        "not a live locale write."
    ]


def _existing_target_market(root: ET.Element) -> str:
    market = _find_desc(root, "TargetMarket")
    if market is not None and (market.text or "").strip():
        return (market.text or "").strip()
    return ""


def patch_mgconfig_locale(
    src: Path,
    dest: Path,
    settings: JurisdictionSettings,
    *,
    language: str | None = None,
) -> None:
    """Write TargetMarket / CultureName / CurrencyName / Language into mgconfig.xml."""
    tree = _parse_xml(src)
    root = tree.getroot()
    existing_market = _existing_target_market(root)
    if settings.tag:
        market_value = resolve_target_market_for_mgconfig(
            settings.tag, existing_market
        )
        market = _find_desc(root, "TargetMarket")
        if market is None:
            ms = _find_child(root, "MarketSpecific")
            if ms is None:
                ms = _ensure_child(root, "MarketSpecific")
            _set_text(ms, "TargetMarket", market_value)
        else:
            market.text = market_value
    if settings.culture_name:
        culture = _find_desc(root, "CultureName")
        if culture is None:
            cid = _find_child(root, "CultureInfoData")
            if cid is None:
                cid = _ensure_child(root, "CultureInfoData")
            _set_text(cid, "CultureName", settings.culture_name)
        else:
            culture.text = settings.culture_name
    if settings.currency_name:
        top = _find_child(root, "CurrencyName")
        if top is not None:
            top.text = settings.currency_name
        else:
            _set_text(root, "CurrencyName", settings.currency_name)
        if settings.currency_symbol:
            fmt = _find_child(root, "CurrencyFormat")
            if fmt is not None:
                fmt.text = f"{{0}} {settings.currency_name}"
            sym = _find_child(root, "CurrencyShortSymbol")
            if sym is not None:
                sym.text = settings.currency_symbol
    if language:
        _set_text(root, "Language", language)
    _write_tree(tree, dest)


def patch_jurisdiction_config(
    src: Path,
    dest: Path,
    settings: JurisdictionSettings,
    *,
    single_denomination: int | None = None,
    play_limits: PlayLimitsSettings | None = None,
    create_pack_fields: bool = False,
) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()
    if settings.tag:
        _set_text(root, "Tag", settings.tag)
    if settings.culture_name:
        info = _find_child(root, "CultureInformation")
        if info is None:
            info = _ensure_child(root, "CultureInformation")
        _set_text(info, "CultureName", settings.culture_name)
    if settings.currency_name or settings.currency_symbol:
        cds = _find_child(root, "CurrencyDisplaySettings")
        if cds is None:
            cds = _ensure_child(root, "CurrencyDisplaySettings")
        if settings.currency_name:
            _set_text(cds, "CurrencyName", settings.currency_name)
            for el in cds.iter():
                local = _local(el.tag)
                if local in {"CurrencyLongFormat", "CurrencyFormat"} and el.text:
                    # Keep "{0} CODE" shape when the leaf already has a placeholder.
                    text = el.text
                    if "{0}" in text:
                        el.text = f"{{0}} {settings.currency_name}"
                    else:
                        el.text = settings.currency_name
        if settings.currency_symbol:
            _set_text(cds, "CurrencySymbol", settings.currency_symbol)
    want_limit = settings.magic_wheel_money_limit is not None
    want_play = play_limits is not None and play_limits.touches_magicwheel()
    if want_limit or want_play:
        mw = _find_child(root, "MagicWheelPackSettings")
        if mw is None:
            mw = _ensure_child(root, "MagicWheelPackSettings")
        if want_limit:
            _set_text(mw, "MoneyLimit", str(settings.magic_wheel_money_limit))
        if play_limits is not None:
            _write_magicwheel_pack_play(
                mw, play_limits, create_missing=create_pack_fields
            )
    if single_denomination is not None:
        display = _find_child(root, "DenominationDisplay")
        if display is None:
            display = _ensure_child(root, "DenominationDisplay")
        _set_text(display, "SingleDenomination", str(int(single_denomination)))
    _write_jurisdiction_config(tree, dest)


def read_mg_identity(goldclub: Path) -> MgIdentitySettings:
    path = goldclub / _MGCONFIG_REL
    out = MgIdentitySettings()
    if not path.is_file():
        return out
    root = _parse_xml(path).getroot()
    mid = _find_child(root, "MachineID")
    if mid is not None and (mid.text or "").strip():
        out.machine_id_template = (mid.text or "").strip()
    lang = _find_child(root, "Language")
    if lang is None:
        lang = _find_desc(root, "Language")
    if lang is not None:
        out.language = (lang.text or "").strip()
    inac = _find_child(root, "InactivitySecondsToGameSelector")
    if inac is not None and (inac.text or "").strip().lstrip("-").isdigit():
        out.inactivity_seconds_to_game_selector = int((inac.text or "").strip())
    jfile = _find_child(root, "JurisdictionSettingsFile")
    if jfile is not None and (jfile.text or "").strip():
        out.jurisdiction_settings_file = (jfile.text or "").strip()
    return out


def read_aurum_identity(goldclub: Path) -> AurumIdentitySettings:
    path = goldclub / _AURUM_SETUP_REL
    out = AurumIdentitySettings()
    if not path.is_file():
        return out
    root = _parse_xml(path).getroot()
    host = _find_desc(root, "NetworkHostName")
    if host is not None and (host.text or "").strip():
        out.network_hostname_template = (host.text or "").strip()
    return out


def read_aurum_currency_code(goldclub: Path) -> str:
    """CurrencyCode from AurumSetup CurrencyTable (what OneHand compares to jurisdiction)."""
    path = goldclub / _AURUM_SETUP_REL
    if not path.is_file():
        return ""
    root = _parse_xml(path).getroot()
    for el in root.iter():
        if _local(el.tag) == "CurrencyCode" and (el.text or "").strip():
            return (el.text or "").strip().upper()
    return ""


def _sas_host_id(root: ET.Element) -> int:
    """HostId of SASControler1 from AurumSetup Subscribers (usually 1)."""
    for el in root.iter():
        if _local(el.tag) != "Subscribers":
            continue
        name = ""
        hid = ""
        for child in el:
            local = _local(child.tag)
            if local == "HostName":
                name = (child.text or "").strip()
            elif local == "HostId":
                hid = (child.text or "").strip()
        if name in SAS_CHANNEL_HOST_NAMES and hid.isdigit():
            return int(hid)
    return 1


def _iter_egm_devices(root: ET.Element):
    for el in root.iter():
        if _local(el.tag) in ("EgmsDevices", "EgmDevice"):
            yield el


def _device_class_of(el: ET.Element) -> str:
    child = _find_child(el, "DeviceClass")
    return (child.text or "").strip() if child is not None else ""


def _owner_host_id_of(el: ET.Element) -> int | None:
    child = _find_child(el, "OwnerHostId")
    if child is None or not (child.text or "").strip().lstrip("-").isdigit():
        return None
    return int((child.text or "").strip())


def read_sas_channel_flags(goldclub: Path) -> dict[str, bool]:
    """True when that GSA device is owned by the SAS host (OwnerHostId)."""
    flags = {field: True for field, _label, _cls in SAS_CHANNEL_FIELDS}
    path = goldclub / _AURUM_SETUP_REL
    if not path.is_file():
        return flags
    root = _parse_xml(path).getroot()
    sas_id = _sas_host_id(root)
    for field, _label, classes in SAS_CHANNEL_FIELDS:
        seen = False
        owned = False
        for el in _iter_egm_devices(root):
            if _device_class_of(el) not in classes:
                continue
            seen = True
            if _owner_host_id_of(el) == sas_id:
                owned = True
        if seen:
            flags[field] = owned
    return flags


def _patch_sas_channel_owners(root: ET.Element, sas: SasSettings) -> None:
    sas_id = _sas_host_id(root)
    for field, _label, classes in SAS_CHANNEL_FIELDS:
        enabled = bool(getattr(sas, field, True))
        target = sas_id if enabled else 0
        for el in _iter_egm_devices(root):
            if _device_class_of(el) not in classes:
                continue
            owner = _find_child(el, "OwnerHostId")
            if owner is None:
                continue
            old = (owner.text or "").strip()
            if old == str(target):
                continue
            owner.text = str(target)
            lcc = _find_child(el, "LastConfigurationChange")
            if lcc is None:
                continue
            try:
                lcc.text = str(int((lcc.text or "0").strip() or "0") + 1)
            except ValueError:
                pass


def patch_aurum_setup_placeholders(
    src: Path,
    dest: Path,
    settings: AurumIdentitySettings,
    *,
    currency_code: str | None = None,
    sas: SasSettings | None = None,
) -> None:
    """Patch NetworkHostName/ServiceURI and/or CurrencyCode + CurrencyId.

    Missing CurrencyCode / CurrencyId leaves are created so jurisdiction and
    Aurum cannot diverge when Live Push changes currency on a thin AurumSetup.
    Optional ``sas`` writes SAS channel OwnerHostId flags on EgmsDevices.
    """
    template = (settings.network_hostname_template or "").strip()
    currency = (currency_code or "").strip().upper()
    if not template and not currency and sas is None:
        shutil.copy2(src, dest)
        return
    tree = _parse_xml(src)
    root = tree.getroot()
    if template:
        replacements: list[tuple[str, str]] = []
        for el in root.iter():
            if _local(el.tag) == "NetworkHostName":
                old_host = (el.text or "").strip()
                if old_host and old_host != template:
                    replacements.append((old_host, template))
                el.text = template
        if replacements:
            for el in root.iter():
                local = _local(el.tag)
                if local in ("ServiceURI", "MessengerURI") and el.text:
                    text = el.text
                    for old_host, new_host in replacements:
                        text = text.replace(old_host, new_host)
                    el.text = text
    if currency:
        updated_code = False
        updated_id = False
        for el in root.iter():
            local = _local(el.tag)
            if local == "CurrencyCode":
                el.text = currency
                updated_code = True
            elif local == "CurrencyId":
                el.text = currency
                updated_id = True
        if not updated_code:
            table = _find_child(root, "CurrencyTable")
            if table is None:
                table = _ensure_child(root, "CurrencyTable")
            _set_text(table, "CurrencyCode", currency)
        if not updated_id:
            # Prefer ProcessorConfig under the first EgmsDevices/processor block.
            proc = None
            for el in root.iter():
                if _local(el.tag) == "ProcessorConfig":
                    proc = el
                    break
            if proc is None:
                proc = _ensure_child(root, "ProcessorConfig")
            _set_text(proc, "CurrencyId", currency)
    if sas is not None:
        _patch_sas_channel_owners(root, sas)
    _write_tree(tree, dest)


def read_math_settings(goldclub: Path) -> list[MathDenomSettings]:
    themes = goldclub / "slot" / "themes"
    if not themes.is_dir():
        return []
    out: list[MathDenomSettings] = []
    for game_dir in sorted(themes.iterdir()):
        if not game_dir.is_dir() or not receives_live_push_bet_steps(game_dir.name):
            continue
        math_path = game_dir / "MathSettings.xml"
        if not math_path.is_file():
            continue
        root = _parse_xml(math_path).getroot()
        denom = _find_desc(root, "DenomConfigSettings")
        if denom is None:
            continue
        mult_el = _find_child(denom, "DenominationMultiplier")
        fixed_el = _find_child(denom, "FixedBet")
        rtp_el = _find_child(denom, "ReturnPercent")
        bets_el = _find_child(denom, "BetMultipliers")
        multipliers: list[int] = []
        if bets_el is not None:
            for child in bets_el:
                if _local(child.tag) == "int" and (child.text or "").strip():
                    try:
                        multipliers.append(int(child.text.strip()))
                    except ValueError:
                        continue
        fixed: float | None = None
        if fixed_el is not None and (fixed_el.text or "").strip():
            try:
                fixed = float(fixed_el.text.strip())
            except ValueError:
                fixed = None
        out.append(
            MathDenomSettings(
                theme=game_dir.name,
                denomination_multiplier=int(
                    (mult_el.text or "1").strip() if mult_el is not None else "1"
                ),
                fixed_bet=fixed,
                bet_multipliers=multipliers,
                return_percent=(
                    (rtp_el.text or "").strip() if rtp_el is not None else None
                )
                or None,
            )
        )
    return out


def patch_math_settings(src: Path, dest: Path, settings: MathDenomSettings) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()
    denom = _find_desc(root, "DenomConfigSettings")
    if denom is None:
        raise ValueError(f"No DenomConfigSettings in {src}")
    _set_text(denom, "DenominationMultiplier", str(settings.denomination_multiplier))
    if settings.fixed_bet is not None:
        _set_text(denom, "FixedBet", str(settings.fixed_bet))
        # Mirror top-level FixedBet when present.
        top_fixed = _find_child(root, "FixedBet")
        if top_fixed is not None:
            top_fixed.text = str(settings.fixed_bet)
    if settings.return_percent:
        _set_text(denom, "ReturnPercent", settings.return_percent)
        top_rtp = _find_child(root, "CurrentReturnPercent")
        if top_rtp is not None:
            top_rtp.text = settings.return_percent
    if settings.bet_multipliers:
        bets = _find_child(denom, "BetMultipliers")
        if bets is None:
            bets = _ensure_child(denom, "BetMultipliers")
        for child in list(bets):
            bets.remove(child)
        ns = ""
        if "}" in bets.tag:
            ns = bets.tag.split("}")[0] + "}"
        for value in settings.bet_multipliers:
            el = ET.SubElement(bets, f"{ns}int")
            el.text = str(value)
    _write_tree(tree, dest)


DISPLAY_MODE_CHOICES: tuple[str, ...] = ("2", "3")

DISPLAY_MODE_MGCONFIG_TAGS: tuple[str, ...] = (
    "EffectSettingsFile",
    "GameSelectorSettingsFile",
    "GameSelectorDefaultSettingsFile",
    "GameCatalogSettingsFile",
    "ResidualSpinPath",
    "MagicWheelPath",
    "InfoScreenSharedPath",
)

# Country Selector Gamestar 2 Screens vs 3 Screens leaves differ only here.
_DISPLAY_TO_3_SUBS: tuple[tuple[str, str], ...] = (
    ("gameselector_GSC_config_default.xml", "gameselector_GSC_3Screens_config_default.xml"),
    ("gameselector_GSC_config.xml", "gameselector_GSC_3Screens_config.xml"),
    ("gamecatalog_GSC_config.xml", "gamecatalog_GSC_3Screens_config.xml"),
    ("2_Screens_GSC_Settings.xml", "3_Screens_GSC_Settings.xml"),
    ("Effects.xml", "Effects_3Screens.xml"),
    ("ResidualSpin.xml", "ResidualSpin_3Screens.xml"),
    ("magicwheel.xml", "magicwheel_3Screens.xml"),
)
_DISPLAY_TO_2_SUBS: tuple[tuple[str, str], ...] = tuple(
    (new, old) for old, new in _DISPLAY_TO_3_SUBS
)


def _normalize_display_mode(value: object) -> str | None:
    mode = str(value or "").strip()
    if mode in DISPLAY_MODE_CHOICES:
        return mode
    return None


def _transform_display_path(path: str, mode: str) -> str:
    want = _normalize_display_mode(mode)
    if want is None:
        return path
    subs = _DISPLAY_TO_3_SUBS if want == "3" else _DISPLAY_TO_2_SUBS
    out = path
    for old, new in subs:
        if old in out:
            out = out.replace(old, new)
    return out


def read_display_mode_paths(goldclub: Path) -> dict[str, str]:
    """Read mgconfig path elements that distinguish 2-screen vs 3-screen UI."""
    path = goldclub / _MGCONFIG_REL
    if not path.is_file():
        return {}
    root = _parse_xml(path).getroot()
    out: dict[str, str] = {}
    for tag in DISPLAY_MODE_MGCONFIG_TAGS:
        el = _find_child(root, tag)
        if el is None:
            el = _find_desc(root, tag)
        if el is not None and (el.text or "").strip():
            out[tag] = (el.text or "").strip()
    return out


def read_display_mode(goldclub: Path) -> str | None:
    """``2``, ``3``, or ``None`` when mgconfig has no display path tags."""
    paths = read_display_mode_paths(goldclub)
    if not paths:
        return None
    joined = " ".join(paths.values())
    if "_3Screens" in joined or "3_Screens_GSC_Settings" in joined:
        return "3"
    return "2"


def _theme_file_from_mgconfig_path(goldclub: Path, rel: str) -> Path:
    norm = rel.replace("\\", "/").strip("/")
    parts = [bit for bit in norm.split("/") if bit]
    if parts and parts[0].casefold() == "themes":
        parts = parts[1:]
    return goldclub / "slot" / "themes" / Path(*parts)


def missing_display_mode_assets(goldclub: Path, mode: str) -> list[str]:
    """Theme files referenced after a display-mode switch that are absent on disk."""
    want = _normalize_display_mode(mode)
    if want is None:
        return []
    root = goldclub_root_from_target(goldclub)
    live_paths = read_display_mode_paths(root)
    if not live_paths:
        return []
    missing: list[str] = []
    seen: set[str] = set()
    for tag in DISPLAY_MODE_MGCONFIG_TAGS:
        raw = live_paths.get(tag)
        if not raw:
            continue
        transformed = _transform_display_path(raw, want)
        if transformed == raw:
            continue
        rel = _theme_file_from_mgconfig_path(root, transformed)
        key = normalize_rel_path(str(rel.relative_to(root)))
        if key in seen:
            continue
        seen.add(key)
        if not rel.is_file():
            missing.append(key)
    return missing


def patch_mgconfig_display_mode(src: Path, dest: Path, mode: str) -> None:
    """Swap GameStar 2-screen vs 3-screen UI paths in mgconfig.xml."""
    want = _normalize_display_mode(mode)
    if want is None:
        shutil.copy2(src, dest)
        return
    tree = _parse_xml(src)
    root = tree.getroot()
    for tag in DISPLAY_MODE_MGCONFIG_TAGS:
        el = _find_child(root, tag)
        if el is None:
            el = _find_desc(root, tag)
        if el is None or not (el.text or "").strip():
            continue
        el.text = _transform_display_path((el.text or "").strip(), want)
    _write_tree(tree, dest)


def display_mode_infoscreen_height(goldclub: Path) -> int | None:
    """Canvas height from the active ``InfoScreenSharedPath`` settings file."""
    paths = read_display_mode_paths(goldclub)
    info = paths.get("InfoScreenSharedPath")
    if not info:
        return None
    p = _theme_file_from_mgconfig_path(goldclub, info)
    if not p.is_file():
        return None
    root = _parse_xml(p).getroot()
    height = _find_desc(root, "Height")
    if height is None or not (height.text or "").strip().isdigit():
        return None
    return int((height.text or "").strip())


def display_mode_probe_lines(goldclub: Path) -> list[str]:
    """Human-readable probe report for live cabinets (assets + coords we leave alone)."""
    root = goldclub_root_from_target(goldclub)
    mode = read_display_mode(root)
    paths = read_display_mode_paths(root)
    lines = [
        f"Goldclub: {root}",
        f"Display mode: {mode or 'unknown'}",
        (
            "Missing assets for 2-screen: "
            + (", ".join(missing_display_mode_assets(root, "2")) or "none")
        ),
        (
            "Missing assets for 3-screen: "
            + (", ".join(missing_display_mode_assets(root, "3")) or "none")
        ),
    ]
    for tag in DISPLAY_MODE_MGCONFIG_TAGS:
        rel = paths.get(tag)
        if not rel:
            continue
        ok = _theme_file_from_mgconfig_path(root, rel).is_file()
        lines.append(f"  {tag}: {rel} ({'ok' if ok else 'MISSING'})")
    cd = root / "bios" / "etc" / "application" / "configuredisplays" / "config.xml"
    if cd.is_file():
        ys = [
            ln.strip()
            for ln in cd.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip().startswith("<Y>") and ln.strip().endswith("</Y>")
        ]
        lines.append(
            "configuredisplays Y (never touched by display switch): "
            + ", ".join(ys)
        )
    ohc = root / "slot" / "OneHand.exe.config"
    if ohc.is_file():
        picks = [
            ln.strip()
            for ln in ohc.read_text(encoding="utf-8", errors="replace").splitlines()
            if any(k in ln.casefold() for k in ("starty", "width", "height"))
        ]
        lines.append(f"OneHand.exe.config (unchanged): {'; '.join(picks)}")
    height = display_mode_infoscreen_height(root)
    if height is not None:
        lines.append(f"InfoScreen canvas height: {height}")
    return lines


def read_mgconfig_denoms(goldclub: Path) -> tuple[list[int], list[int]]:
    path = goldclub / _MGCONFIG_REL
    if not path.is_file():
        return [], []
    root = _parse_xml(path).getroot()

    def _ints(tag: str) -> list[int]:
        parent = _find_desc(root, tag)
        if parent is None:
            return []
        values: list[int] = []
        for child in parent:
            if _local(child.tag) == "int" and (child.text or "").strip():
                try:
                    values.append(int(child.text.strip()))
                except ValueError:
                    continue
        return values

    return _ints("DenominationList"), _ints("CreditRateValues")


def patch_mgconfig_denoms(
    src: Path,
    dest: Path,
    denomination_list: list[int],
    credit_rate_values: list[int],
    identity: MgIdentitySettings | None = None,
) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()

    def _replace_ints(tag: str, values: list[int]) -> None:
        parent = _find_desc(root, tag)
        if parent is None:
            parent = _ensure_child(root, tag)
        for child in list(parent):
            parent.remove(child)
        ns = ""
        if "}" in parent.tag:
            ns = parent.tag.split("}")[0] + "}"
        for value in values:
            el = ET.SubElement(parent, f"{ns}int")
            el.text = str(value)

    if denomination_list:
        _replace_ints("DenominationList", denomination_list)
    if credit_rate_values:
        _replace_ints("CreditRateValues", credit_rate_values)
    if identity is not None:
        if identity.machine_id_template:
            _set_text(root, "MachineID", identity.machine_id_template)
        if identity.language:
            _set_text(root, "Language", identity.language)
        if identity.inactivity_seconds_to_game_selector is not None:
            _set_text(
                root,
                "InactivitySecondsToGameSelector",
                str(identity.inactivity_seconds_to_game_selector),
            )
        if identity.jurisdiction_settings_file:
            _set_text(
                root,
                "JurisdictionSettingsFile",
                identity.jurisdiction_settings_file,
            )
    _write_tree(tree, dest)


def _bool_from_xml(root: ET.Element, name: str) -> bool | None:
    return _parse_opt_bool(_elem_text(root, name) or None)


def _int_from_xml(root: ET.Element, name: str) -> int | None:
    return _parse_opt_int(_elem_text(root, name) or None)


def _read_magicwheel_fields(root: ET.Element) -> dict[str, int | bool | None]:
    """Bet / limit / enabled from a magic-wheel settings element."""
    average = _int_from_xml(root, "MoneyWheelAverage")
    if average is None:
        average = _int_from_xml(root, "Average")
    return {
        "money_limit": _int_from_xml(root, "MoneyLimit"),
        "enabled": _bool_from_xml(root, "Enabled"),
        "bet": _int_from_xml(root, "Bet"),
        "max_spins": _int_from_xml(root, "MaxWheelSpins"),
        "average": average,
    }


def _merge_magicwheel_play(
    out: PlayLimitsSettings,
    fields: dict[str, int | bool | None],
    *,
    overwrite: bool,
) -> None:
    mapping = {
        "enabled": "magic_wheel_enabled",
        "bet": "magic_wheel_bet",
        "max_spins": "magic_wheel_max_spins",
        "average": "magic_wheel_average",
    }
    for src, dest in mapping.items():
        val = fields.get(src)
        if val is None:
            continue
        if overwrite or getattr(out, dest) is None:
            setattr(out, dest, val)


def _write_magicwheel_pack_play(
    pack: ET.Element,
    play_limits: PlayLimitsSettings,
    *,
    create_missing: bool,
) -> None:
    existing = {_local(child.tag).casefold() for child in pack}

    def write(tag: str, value: object, *, as_bool: bool = False) -> None:
        if value is None:
            return
        if not create_missing and tag.casefold() not in existing:
            return
        _set_text(pack, tag, _bool_xml(bool(value)) if as_bool else str(value))

    write("Enabled", play_limits.magic_wheel_enabled, as_bool=True)
    write("Bet", play_limits.magic_wheel_bet)
    write("MaxWheelSpins", play_limits.magic_wheel_max_spins)
    if play_limits.magic_wheel_average is None:
        return
    if create_missing or "moneywheelaverage" in existing:
        write("MoneyWheelAverage", play_limits.magic_wheel_average)
    elif "average" in existing:
        write("Average", play_limits.magic_wheel_average)


def theme_rel_from_mgconfig_path(raw: str) -> str:
    """``themes\\magicwheel.xml`` → ``slot/themes/magicwheel.xml``."""
    text = (raw or "").replace("\\", "/").strip().lstrip("/")
    if not text:
        return ""
    if text.casefold().startswith("slot/"):
        return text
    if text.casefold().startswith("themes/"):
        return f"slot/{text}"
    return f"slot/themes/{Path(text).name}"


def read_mgconfig_magicwheel_path(goldclub: Path) -> str:
    mg = goldclub / _MGCONFIG_REL
    if not mg.is_file():
        return ""
    return _elem_text(_parse_xml(mg).getroot(), "MagicWheelPath")


def iter_magicwheel_setting_rels(goldclub: Path) -> list[str]:
    """Cabinet-relative XMLs that actually hold magic-wheel knobs.

    Gamepacks on newer builds write ``jurisdiction_config``
    ``MagicWheelPackSettings`` (not mgconfig). Older images still use
    ``magicwheel_Config.xml``; display-mode leaves use MagicWheelPath.
    """
    root = goldclub_root_from_target(goldclub)
    ordered: list[str] = []
    seen: set[str] = set()

    def add(rel: str) -> None:
        norm = rel.replace("\\", "/").strip().lstrip("/")
        if not norm:
            return
        key = norm.casefold()
        if key in seen:
            return
        path = _resolve_goldclub_rel(root, norm)
        if path is None or not path.is_file():
            return
        seen.add(key)
        ordered.append(norm)

    add(_JURISDICTION_REL)
    add(_MAGICWHEEL_REL)
    path_text = read_mgconfig_magicwheel_path(root)
    if path_text:
        add(theme_rel_from_mgconfig_path(path_text))
    for rel in _MAGICWHEEL_THEME_RELS:
        add(rel)
    return ordered


def dedicated_magicwheel_file_exists(goldclub: Path) -> bool:
    """True when a magic-wheel XML exists besides jurisdiction_config."""
    return any(
        rel.casefold() != _JURISDICTION_REL.casefold()
        for rel in iter_magicwheel_setting_rels(goldclub)
    )


def looks_like_magicwheel_settings(path: Path) -> bool:
    try:
        root = _parse_xml(path).getroot()
    except (OSError, ET.ParseError, ValueError):
        return False
    fields = _read_magicwheel_fields(root)
    if any(value is not None for value in fields.values()):
        return True
    return _local(root.tag).casefold() in {
        "magicwheelsettingsconfig",
        "magicwheelpacksettings",
    }


def math_settings_rels(goldclub: Path) -> list[str]:
    """Theme MathSettings.xml files Live Push may rewrite for bet steps."""
    return [
        f"slot/themes/{name}/MathSettings.xml" for name in _math_theme_names(goldclub)
    ]


def read_play_limits(goldclub: Path) -> PlayLimitsSettings:
    """Read jackpot / magic-wheel / UI play knobs from live XML."""
    out = PlayLimitsSettings()
    mg = goldclub / _MGCONFIG_REL
    if mg.is_file():
        root = _parse_xml(mg).getroot()
        out.jackpot_counters = _int_from_xml(root, "NumberOfJackpotCounters")
        out.celebration_limit = _elem_text(root, "PayoutWhenCelebrationLimit")
        out.cashout_button_mode = _elem_text(root, "CashoutButtonMode")
        out.show_all_lines = _bool_from_xml(root, "ShowAllLines")
        out.show_denom_selector = _bool_from_xml(root, "ShowDenominationSelector")
        out.default_bet = _elem_text(root, "DefaultBet")
    hw = goldclub / _HARDWARE_CONFIG_REL
    if hw.is_file():
        root = _parse_xml(hw).getroot()
        out.jackpot_receipt_layout = _elem_text(root, "LayoutJackpotReceiptTicket")
        out.ticket_redeem_enabled = _bool_from_xml(root, "RedeemEnabled")
        out.ticket_use_currency_iso = _bool_from_xml(root, "UseCurrencyISO")
    mw = goldclub / _MAGICWHEEL_REL
    if mw.is_file():
        _merge_magicwheel_play(
            out,
            _read_magicwheel_fields(_parse_xml(mw).getroot()),
            overwrite=True,
        )
    root = goldclub_root_from_target(goldclub)
    for rel in iter_magicwheel_setting_rels(root):
        if rel.casefold() in {
            _JURISDICTION_REL.casefold(),
            _MAGICWHEEL_REL.casefold(),
        }:
            continue
        path = _resolve_goldclub_rel(root, rel)
        if path is None or not looks_like_magicwheel_settings(path):
            continue
        _merge_magicwheel_play(
            out,
            _read_magicwheel_fields(_parse_xml(path).getroot()),
            overwrite=False,
        )
    jur = root / _JURISDICTION_REL
    if jur.is_file():
        pack = _find_child(_parse_xml(jur).getroot(), "MagicWheelPackSettings")
        if pack is not None:
            _merge_magicwheel_play(
                out, _read_magicwheel_fields(pack), overwrite=True
            )
    return out


def patch_mgconfig_play(
    src: Path, dest: Path, settings: PlayLimitsSettings
) -> None:
    """Write jackpot counters, cashout, celebration, denom selector, default bet."""
    tree = _parse_xml(src)
    root = tree.getroot()
    if settings.jackpot_counters is not None:
        _set_text(root, "NumberOfJackpotCounters", str(settings.jackpot_counters))
    if settings.show_all_lines is not None:
        _set_text(root, "ShowAllLines", _bool_xml(settings.show_all_lines))
    if settings.show_denom_selector is not None:
        _set_text(root, "ShowDenominationSelector", _bool_xml(settings.show_denom_selector))
    if settings.default_bet:
        _set_text(root, "DefaultBet", settings.default_bet)
    if settings.cashout_button_mode or settings.celebration_limit:
        transfer = _find_desc(root, "TransferParameters")
        if transfer is None:
            transfer = _ensure_child(root, "TransferParameters")
        if settings.cashout_button_mode:
            _set_text(transfer, "CashoutButtonMode", settings.cashout_button_mode)
        if settings.celebration_limit:
            _set_text(transfer, "PayoutWhenCelebrationLimit", settings.celebration_limit)
    _write_tree(tree, dest)


def _parse_lock_flag(text: str | None) -> bool:
    return (text or "").strip().casefold() in ("1", "true", "yes", "on")


def _read_limit_setup_locks(
    limit_setup: ET.Element, spec: LimitSetupFieldSpec
) -> tuple[bool, bool]:
    """Read host/egm lock flags from LimitSetup XML when present."""
    host_locked = False
    egm_locked = False
    for child in limit_setup:
        tag = _local(child.tag)
        if tag == spec.xml_tag:
            for attr in ("hostLocked", "HostLocked", "host_locked"):
                if attr in child.attrib:
                    host_locked = _parse_lock_flag(child.attrib.get(attr))
            for attr in ("egmLocked", "EgmLocked", "egm_locked"):
                if attr in child.attrib:
                    egm_locked = _parse_lock_flag(child.attrib.get(attr))
        elif tag == f"{spec.xml_tag}HostLocked":
            host_locked = _parse_lock_flag(child.text)
        elif tag == f"{spec.xml_tag}EgmLocked":
            egm_locked = _parse_lock_flag(child.text)
    return host_locked, egm_locked


def read_limit_setup(goldclub: Path) -> LimitSetupSettings:
    """Read Limit Setup values/locks from mgconfig.xml (0 when LimitSetup is empty)."""
    out = LimitSetupSettings()
    path = goldclub / _MGCONFIG_REL
    if not path.is_file():
        return out
    root = _parse_xml(path).getroot()
    limit_setup = _find_desc(root, "LimitSetup")
    if limit_setup is None:
        return out
    values: dict[str, int] = {}
    for spec in LIMIT_SETUP_FIELDS:
        el = _find_child(limit_setup, spec.xml_tag)
        if el is not None and (el.text or "").strip():
            try:
                values[spec.key] = int((el.text or "0").strip())
            except ValueError:
                values[spec.key] = 0
        else:
            values[spec.key] = 0
        host_locked, egm_locked = _read_limit_setup_locks(limit_setup, spec)
        setattr(out, spec.key, values[spec.key])
        setattr(out, f"{spec.key}_host_locked", host_locked)
        setattr(out, f"{spec.key}_egm_locked", egm_locked)
    return out


def patch_limit_setup(
    src: Path, dest: Path, settings: LimitSetupSettings
) -> None:
    """Write editable Limit Setup fields under mgconfig LimitSetup."""
    tree = _parse_xml(src)
    root = tree.getroot()
    limit_setup = _find_desc(root, "LimitSetup")
    if limit_setup is None:
        host = root if _local(root.tag) == "Multigamer" else _find_desc(root, "Multigamer")
        if host is None:
            host = root
        limit_setup = _ensure_child(host, "LimitSetup")
    ns = ""
    if "}" in limit_setup.tag:
        ns = limit_setup.tag.split("}")[0] + "}"
    for spec in LIMIT_SETUP_FIELDS:
        want = settings.value_for(spec.key)
        if want is None:
            continue
        host_locked, egm_locked = _read_limit_setup_locks(limit_setup, spec)
        if host_locked or egm_locked:
            continue
        el = _find_child(limit_setup, spec.xml_tag)
        if el is None:
            el = ET.SubElement(limit_setup, f"{ns}{spec.xml_tag}")
        el.text = str(int(want))
    _write_tree(tree, dest)


def patch_magicwheel_config(
    src: Path,
    dest: Path,
    *,
    money_limit: int | None = None,
    enabled: bool | None = None,
    bet: int | None = None,
    max_spins: int | None = None,
    average: int | None = None,
) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()
    if money_limit is not None:
        _set_text(root, "MoneyLimit", str(money_limit))
    if enabled is not None:
        _set_text(root, "Enabled", _bool_xml(enabled))
    if bet is not None:
        _set_text(root, "Bet", str(bet))
    if max_spins is not None:
        _set_text(root, "MaxWheelSpins", str(max_spins))
    if average is not None:
        _set_text(root, "MoneyWheelAverage", str(average))
    _write_tree(tree, dest)


def patch_math_bet_multipliers(
    src: Path, dest: Path, multipliers: list[int]
) -> None:
    """Replace BetMultipliers only; leave denom multiplier / RTP alone."""
    tree = _parse_xml(src)
    root = tree.getroot()
    denom = _find_desc(root, "DenomConfigSettings")
    if denom is None:
        raise ValueError(f"No DenomConfigSettings in {src}")
    bets = _find_child(denom, "BetMultipliers")
    if bets is None:
        bets = _ensure_child(denom, "BetMultipliers")
    for child in list(bets):
        bets.remove(child)
    ns = ""
    if "}" in bets.tag:
        ns = bets.tag.split("}")[0] + "}"
    for value in multipliers:
        el = ET.SubElement(bets, f"{ns}int")
        el.text = str(value)
    _write_tree(tree, dest)


# Live Push writes BetMultipliers only into these themes' MathSettings.xml.
# RouletteGame keeps its own roulette math; Link2WinFeature is JSON packs;
# data/ is shared assets. Underscore-prefixed folders are disabled titles.
_MATH_THEME_SKIP = frozenset({"data", "RouletteGame", "Link2WinFeature"})


def receives_live_push_bet_steps(theme_name: str) -> bool:
    """False when Live Push must not overwrite this theme's bet steps."""
    name = (theme_name or "").strip()
    if not name or name.startswith("_"):
        return False
    return name.casefold() not in {n.casefold() for n in _MATH_THEME_SKIP}


def _math_theme_names(goldclub: Path) -> list[str]:
    themes = goldclub / "slot" / "themes"
    if not themes.is_dir():
        return []
    names: list[str] = []
    try:
        entries = list(themes.iterdir())
    except OSError:
        return []
    for game_dir in sorted(entries):
        try:
            if not game_dir.is_dir():
                continue
            theme_name = game_dir.name
            if not receives_live_push_bet_steps(theme_name):
                continue
            if (game_dir / "MathSettings.xml").is_file():
                names.append(theme_name)
        except OSError:
            continue
    return names


def _resolve_goldclub_rel(goldclub: Path, relative: str) -> Path | None:
    """Resolve a relative Goldclub path; try case variants for SMB / Linux-ish trees.

    Memoised per ``(root, relative)`` while a live-load read scope is open -
    the case-insensitive ``iterdir`` walk is several SMB round-trips.
    """
    return cached_resolve(Path(goldclub), relative, _resolve_goldclub_rel_uncached)


def _resolve_goldclub_rel_uncached(goldclub: Path, relative: str) -> Path | None:
    root = Path(goldclub)
    direct = root / relative
    try:
        if direct.is_file() or direct.is_dir():
            return direct
    except OSError:
        pass
    # Walk case-insensitively when the literal casing differs (services vs Services).
    parts = [p for p in relative.replace("\\", "/").split("/") if p]
    cur = root
    for part in parts:
        try:
            if not cur.is_dir():
                return None
            match = None
            for child in cur.iterdir():
                if child.name.casefold() == part.casefold():
                    match = child
                    break
            if match is None:
                return None
            cur = match
        except OSError:
            return None
    return cur


def read_sas_settings(goldclub: Path) -> SasSettings:
    settings = SasSettings()
    clients = _resolve_goldclub_rel(goldclub, _CLIENTS_SET_REL)
    if clients is not None and clients.is_file():
        root = _parse_xml(clients).getroot()
        addr = _find_desc(root, "SASAddress")
        if addr is not None and (addr.text or "").strip().isdigit():
            settings.address = int(addr.text.strip())
        aft = _find_desc(root, "AFT.anyAftEnabled")
        if aft is not None and (aft.text or "").strip():
            settings.aft_enabled = (aft.text or "").strip().lower() == "true"
    sas_setup = _resolve_goldclub_rel(goldclub, _SAS_SETUP_REL)
    if sas_setup is not None and sas_setup.is_file():
        root = _parse_xml(sas_setup).getroot()
        ftt = _find_desc(root, "FundsTransferType")
        if ftt is not None and (ftt.text or "").strip():
            settings.funds_transfer_type = (ftt.text or "").strip()
        lock = _find_desc(root, "LockGameWhenNoComms")
        if lock is not None and (lock.text or "").strip():
            settings.lock_game_when_no_comms = (
                (lock.text or "").strip().lower() == "true"
            )
        # Offline CS packs often leave SAS files present but FundsTransferType empty
        # or lock false — treat missing address file as disabled only via explicit flag.
    for field, value in read_sas_channel_flags(goldclub).items():
        setattr(settings, field, value)
    return settings


def patch_clients_set(src: Path, dest: Path, sas: SasSettings) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()
    for el in root.iter():
        local = _local(el.tag)
        if local == "SASAddress":
            el.text = str(sas.address)
        elif local == "AFT.anyAftEnabled":
            el.text = "true" if sas.aft_enabled else "false"
        elif local == "AFT.inHouseTransfersEnabled" and sas.aft_enabled:
            el.text = "true"
    _write_tree(tree, dest)


def patch_sas_setup_data(src: Path, dest: Path, sas: SasSettings) -> None:
    tree = _parse_xml(src)
    root = tree.getroot()
    for el in root.iter():
        local = _local(el.tag)
        if local == "FundsTransferType":
            el.text = sas.funds_transfer_type if sas.enabled else "NONE"
        elif local == "LockGameWhenNoComms":
            el.text = "true" if sas.lock_game_when_no_comms else "false"
    _write_tree(tree, dest)


def recipe_from_jurisdiction_profile(
    profile: object,
    *,
    denom: int | None = None,
    denomination_list: list[int] | None = None,
    offline_enabled: bool | None = None,
) -> SlotSetupRecipe:
    """Build a SlotSetupRecipe from a JurisdictionProfile (or duck-typed object)."""
    expected = dict(getattr(profile, "expected", {}) or {})
    currency = str(getattr(profile, "currency", "") or expected.get("locale.currency_name") or "")
    culture = str(getattr(profile, "culture", "") or expected.get("locale.culture_name") or "")
    language = str(getattr(profile, "language", "") or expected.get("locale.language") or "")
    market = str(
        getattr(profile, "target_market", "") or expected.get("locale.target_market") or ""
    )
    label = str(getattr(profile, "label", "") or getattr(profile, "id", "") or "")

    denoms = list(getattr(profile, "allowed_denoms", []) or [])
    if denomination_list is not None:
        denoms = [int(x) for x in denomination_list]
    elif denom is not None:
        denoms = [int(denom)]
    elif expected.get("denom.list"):
        try:
            denoms = [int(x) for x in expected["denom.list"]]
        except (TypeError, ValueError):
            pass

    credit = list(denoms)
    credit_explicit = False
    if expected.get("denom.credit_rate_values"):
        try:
            credit = [int(x) for x in expected["denom.credit_rate_values"]]
            credit_explicit = True
        except (TypeError, ValueError):
            pass
    elif getattr(profile, "allowed_denoms", None):
        try:
            credit = [int(x) for x in profile.allowed_denoms]
            credit_explicit = True
        except (TypeError, ValueError):
            pass
    # Preferred single denom stays first; do not shrink an explicit credit table.
    if denom is not None and denoms:
        preferred = int(denom)
        if preferred in denoms:
            denoms = [preferred] + [d for d in denoms if d != preferred]
        if credit_explicit and preferred in credit:
            credit = [preferred] + [c for c in credit if c != preferred]
        elif not credit_explicit:
            credit = list(denoms)

    bet_mults = list(getattr(profile, "allowed_bet_multipliers", []) or [])
    if expected.get("math.bet_multipliers"):
        try:
            bet_mults = [int(x) for x in expected["math.bet_multipliers"]]
        except (TypeError, ValueError):
            pass

    offline = offline_enabled
    if offline is None and "ticket.offline_enabled" in expected:
        offline = bool(expected["ticket.offline_enabled"])

    sas = SasSettings(
        enabled=True,
        address=int(expected.get("sas.address") or 1),
        aft_enabled=bool(expected.get("sas.aft_enabled", True)),
        funds_transfer_type=str(expected.get("sas.funds_transfer_type") or "AFT"),
        lock_game_when_no_comms=bool(expected.get("sas.lock_when_no_comms", False)),
    )
    protocol = str(expected.get("bill.protocol") or "MEI").upper()
    if protocol not in BILL_PROTOCOLS:
        protocol = "MEI"

    tokens: list[BillToken] = []
    raw_tokens = expected.get("bill.tokens")
    if isinstance(raw_tokens, dict):
        for code, value in raw_tokens.items():
            try:
                tokens.append(BillToken(code=str(code), value=int(value)))
            except (TypeError, ValueError):
                continue
    if not tokens:
        tokens = default_bill_tokens_for_currency(currency)

    math: list[MathDenomSettings] = []
    if bet_mults:
        math.append(
            MathDenomSettings(
                theme="*",
                denomination_multiplier=1,
                bet_multipliers=bet_mults,
            )
        )

    play_limits = PlayLimitsSettings(
        jackpot_receipt_layout=str(expected.get("ticket.layout_jackpot") or ""),
        celebration_limit=str(expected.get("ui.payout_celebration_limit") or ""),
        cashout_button_mode=str(expected.get("ui.cashout_button_mode") or ""),
        show_all_lines=_parse_opt_bool(expected.get("ui.show_all_lines")),
        show_denom_selector=_parse_opt_bool(expected.get("denom.show_selector")),
        ticket_redeem_enabled=_parse_opt_bool(expected.get("ticket.redeem_enabled")),
        ticket_use_currency_iso=_parse_opt_bool(expected.get("ticket.use_currency_iso")),
        default_bet=str(expected.get("ui.default_bet") or ""),
        bet_multipliers=list(bet_mults),
    )

    recipe = SlotSetupRecipe(
        label=label,
        sas=sas,
        bill_protocol=protocol,
        bill_tokens=tokens,
        math=math,
        denomination_list=denoms,
        credit_rate_values=credit,
        jurisdiction=JurisdictionSettings(
            tag=market,
            culture_name=culture,
            currency_name=currency,
            currency_symbol=str(expected.get("locale.currency_short_symbol") or ""),
            magic_wheel_money_limit=_parse_opt_int(
                expected.get("locale.jur_magic_wheel_limit")
            ),
        ),
        mg_identity=MgIdentitySettings(
            machine_id_template=str(
                expected.get("id.machine_id") or "GST!!MachineName!!"
            ),
            language=language,
        ),
        offline_enabled=offline,
        hardware_currency_name=currency
        or str(expected.get("locale.hw_currency_name") or ""),
        aurum_identity=AurumIdentitySettings(
            network_hostname_template=str(
                expected.get("id.network_hostname") or "GST!!MachineName!!"
            ),
        ),
        play_limits=play_limits,
        include_oticket=bool(offline),
    )
    inactivity = _parse_opt_int(expected.get("ui.inactivity_to_selector"))
    if inactivity is not None:
        recipe.mg_identity.inactivity_seconds_to_game_selector = inactivity
    return recipe


def load_recipe_from_goldclub(goldclub: Path, *, label: str = "") -> SlotSetupRecipe:
    """Read current EGM settings into a recipe (authoring starting point)."""
    from config_scanner.hw_drivers import detect_hw_driver_profile

    root = goldclub_root_from_target(goldclub)
    denoms, credit = read_mgconfig_denoms(root)
    protocol = read_bill_protocol(root) or ""
    ticket_protocol = read_ticket_protocol(root) or ""
    offline = read_offline_enabled(root)
    play_limits = read_play_limits(root)
    return SlotSetupRecipe(
        label=label,
        sas=read_sas_settings(root),
        bill_protocol=protocol,
        ticket_protocol=ticket_protocol,
        keyboard=read_keyboard_map(root),
        bill_tokens=read_bill_tokens(root),
        math=read_math_settings(root),
        denomination_list=denoms,
        credit_rate_values=credit,
        jurisdiction=read_jurisdiction_settings(root),
        mg_identity=read_mg_identity(root),
        offline_enabled=offline,
        hardware_currency_name=read_hardware_currency_name(root),
        dallas=read_dallas_settings(root),
        door_switches=read_door_switches(root),
        aurum_identity=read_aurum_identity(root),
        play_limits=play_limits,
        limit_setup=read_limit_setup(root),
        include_oticket=bool(offline) and (root / _OTICKET_REL).is_file(),
        display_mode=read_display_mode(root),
        hw_driver_profile=detect_hw_driver_profile(root),
    )


def recipe_summary_lines(recipe: SlotSetupRecipe) -> list[str]:
    offline = recipe.offline_enabled
    offline_s = "—" if offline is None else ("on" if offline else "off")
    lines = [
        f"Label: {recipe.label or '(unnamed)'}",
        (
            f"SAS: {'on' if recipe.sas.enabled else 'off'} "
            f"addr={recipe.sas.address} AFT={'on' if recipe.sas.aft_enabled else 'off'} "
            f"transfer={recipe.sas.funds_transfer_type}"
        ),
        f"Bill acceptor: {recipe.bill_protocol}",
        f"Ticket printer: {recipe.ticket_protocol or '—'}",
        f"Keyboard mappings: {len(recipe.keyboard)}",
        f"Bill tokens: {len(recipe.bill_tokens)}",
        f"Game math overrides: {len(recipe.math)}",
        f"DenominationList: {recipe.denomination_list or '—'}",
        f"CreditRateValues: {recipe.credit_rate_values or '—'}",
        (
            f"Jurisdiction: {recipe.jurisdiction.tag or '—'} "
            f"currency={recipe.jurisdiction.currency_name or '—'} "
            f"limit={recipe.jurisdiction.magic_wheel_money_limit}"
        ),
        (
            f"Jackpots: counters={recipe.play_limits.jackpot_counters} "
            f"layout={recipe.play_limits.jackpot_receipt_layout or '—'} "
            f"celebration={recipe.play_limits.celebration_limit or '—'}"
        ),
        (
            f"Magic wheel: bet={recipe.play_limits.magic_wheel_bet} "
            f"spins={recipe.play_limits.magic_wheel_max_spins} "
            f"enabled={recipe.play_limits.magic_wheel_enabled}"
        ),
        f"Offline ticket: {offline_s} (oticket={'yes' if recipe.include_oticket else 'no'})",
        (
            f"Dallas: {recipe.dallas.code or '—'} "
            f"group={recipe.dallas.group} unlock={recipe.dallas.unlock}"
        ),
        (
            f"Door switches: {'on' if recipe.door_switches.enabled else 'off'} "
            f"auto_unlock="
            + (
                ",".join(
                    row.name
                    for row in recipe.door_switches.items
                    if row.auto_unlock
                )
                or "off"
            )
        ),
        (
            f"MachineID template: {recipe.mg_identity.machine_id_template or '—'} "
            f"lang={recipe.mg_identity.language or '—'}"
        ),
        f"Aurum host template: {recipe.aurum_identity.network_hostname_template or '—'}",
        (
            f"Display layout: {recipe.display_mode or '—'} screens"
            if recipe.display_mode
            else "Display layout: —"
        ),
    ]
    return lines


def _safe_copy_with_identity(src: Path, dest: Path, relative: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes()
    if dest.is_file() and relative.casefold().endswith(".xml"):
        try:
            live = dest.read_bytes()
            if live.lstrip().startswith(b"<") and raw.lstrip().startswith(b"<"):
                raw = merge_xml_bytes_preserving_identity(
                    live, raw, relative_path=relative
                )
        except (ET.ParseError, OSError, ValueError):
            pass
    if is_jurisdiction_config_path(relative):
        raw = postprocess_jurisdiction_xml_bytes(raw)
    dest.write_bytes(raw)


def is_slot_setup_forbidden_path(relative_path: str) -> bool:
    """Paths the setup apply must never write."""
    norm = normalize_rel_path(relative_path)
    if not norm:
        return True
    if _SERIALPORT_DIR_RE.search(norm):
        return True
    low = norm.casefold()
    if "/licen" in f"/{low}/" or low.endswith("licence.dll") or low.endswith(
        "license.dll"
    ):
        return True
    if low.endswith("layout.json") or low.endswith("locations.json"):
        return True
    return False


def build_config_pack(
    recipe: SlotSetupRecipe,
    live_goldclub: Path,
    pack_dir: Path,
    *,
    sections: frozenset[str] | None = None,
) -> SlotSetupRecipe:
    """Materialize patched XML under ``pack_dir`` (Goldclub-relative) + recipe.json.

    When ``sections`` is set, only those Live Push sections are staged
    (``keyboard``, ``bill``, ``ticket``, ``hardware``, ``math``, ``mgconfig``,
    ``jurisdiction``, ``magicwheel``, ``aurum``, ``oticket``, ``sas``,
    ``link2win``, ``hw_drivers``). Licence files are not staged here — Live
    Push copies missing licences separately. ``None`` keeps the legacy
    full-pack behaviour.
    """
    live = goldclub_root_from_target(live_goldclub)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def _want(section: str) -> bool:
        return sections is None or section in sections

    def _stage(rel: str, patcher) -> None:  # noqa: ANN001
        src = _resolve_goldclub_rel(live, rel)
        if src is None or not src.is_file():
            return
        dest = pack_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        patcher(src, dest)
        written.append(normalize_rel_path(rel))

    # Keyboard — skip when a whole HW deck pack will replace Keyboard.xml
    if _want("keyboard") and recipe.keyboard and not recipe.hw_driver_profile:
        _stage(
            _KEYBOARD_REL,
            lambda s, d: patch_keyboard_xml(s, d, recipe.keyboard),
        )

    # Bill protocol
    if _want("bill") and recipe.bill_protocol:
        _stage(
            _QUIXANT_REL,
            lambda s, d: patch_quixant_bill_protocol(s, d, recipe.bill_protocol),
        )
        proto_src = live / _BILL_PROTO_DIR / f"BillAcceptor_{recipe.bill_protocol}.xml"
        if proto_src.is_file():
            dest = pack_dir / _BILL_PROTO_DIR / proto_src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(proto_src, dest)
            written.append(normalize_rel_path(str(Path(_BILL_PROTO_DIR) / proto_src.name)))

    if _want("ticket") and recipe.ticket_protocol in TICKET_PROTOCOLS:
        quixant_pack = pack_dir / _QUIXANT_REL
        quixant_src = quixant_pack if quixant_pack.is_file() else live / _QUIXANT_REL
        if quixant_src.is_file():
            patch_quixant_ticket_protocol(
                quixant_src, quixant_pack, recipe.ticket_protocol
            )
            written.append(normalize_rel_path(_QUIXANT_REL))
        ticket_proto_src = (
            live / _TICKET_PROTO_DIR / f"TicketPrinter_{recipe.ticket_protocol}.xml"
        )
        if ticket_proto_src.is_file():
            dest = pack_dir / _TICKET_PROTO_DIR / ticket_proto_src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ticket_proto_src, dest)
            written.append(
                normalize_rel_path(str(Path(_TICKET_PROTO_DIR) / ticket_proto_src.name))
            )
        for rel in _DRIVERSSETUP_RELS:
            if (live / rel).is_file():
                _stage(
                    rel,
                    lambda s, d, proto=recipe.ticket_protocol: patch_tito_ticket_driver(
                        s, d, proto
                    ),
                )

    # Bill tokens + offline ticket + Dallas + hardware currency (one HardwareConfig)
    pl = recipe.play_limits
    needs_hw = bool(
        recipe.bill_tokens
        or recipe.offline_enabled is not None
        or recipe.hardware_currency_name
        or (recipe.dallas and recipe.dallas.code)
        or pl.touches_hardware()
        or recipe.door_switches.touches()
    )
    if _want("hardware") and needs_hw:
        _stage(
            _HARDWARE_CONFIG_REL,
            lambda s, d: patch_hardware_config(
                s,
                d,
                tokens=recipe.bill_tokens or None,
                offline_enabled=recipe.offline_enabled,
                currency_name=recipe.hardware_currency_name or None,
                dallas=recipe.dallas if recipe.dallas.code else None,
                ticket_redeem_enabled=pl.ticket_redeem_enabled,
                ticket_use_currency_iso=pl.ticket_use_currency_iso,
                jackpot_receipt_layout=pl.jackpot_receipt_layout or None,
                door_switches=recipe.door_switches,
            ),
        )

    # Math per theme
    if _want("math"):
        for math in recipe.math:
            themes = (
                _math_theme_names(live)
                if math.theme in ("", "*")
                else [math.theme]
            )
            for theme in themes:
                if not receives_live_push_bet_steps(theme):
                    continue
                rel = f"slot/themes/{theme}/MathSettings.xml"
                src = live / rel
                if not src.is_file():
                    continue
                dest = pack_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                patch_math_settings(src, dest, math)
                written.append(normalize_rel_path(rel))
        if pl.bet_multipliers:
            for theme in _math_theme_names(live):
                rel = f"slot/themes/{theme}/MathSettings.xml"
                src = pack_dir / rel
                if not src.is_file():
                    src = live / rel
                if not src.is_file():
                    continue
                dest = pack_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                patch_math_bet_multipliers(src, dest, pl.bet_multipliers)
                written.append(normalize_rel_path(rel))

    # mgconfig denoms + identity + locale + play limits + display mode + limit setup
    needs_display = _normalize_display_mode(recipe.display_mode) is not None
    live_limits = read_limit_setup(live)
    needs_limit = limit_setup_changed(live_limits, recipe.limit_setup)
    needs_mg = bool(
        recipe.denomination_list
        or recipe.credit_rate_values
        or recipe.mg_identity.machine_id_template
        or recipe.mg_identity.language
        or recipe.mg_identity.inactivity_seconds_to_game_selector is not None
        or recipe.jurisdiction.tag
        or recipe.jurisdiction.currency_name
        or recipe.jurisdiction.culture_name
        or pl.touches_mgconfig()
        or needs_display
        or needs_limit
    )
    if _want("mgconfig") and needs_mg:
        src_mg = live / _MGCONFIG_REL
        if src_mg.is_file():
            dest_mg = pack_dir / _MGCONFIG_REL
            dest_mg.parent.mkdir(parents=True, exist_ok=True)
            # First denoms + identity
            patch_mgconfig_denoms(
                src_mg,
                dest_mg,
                recipe.denomination_list,
                recipe.credit_rate_values,
                identity=recipe.mg_identity,
            )
            # Then locale onto the staged copy (skip when only retargeting displays).
            locale_requested = bool(
                recipe.jurisdiction.currency_name
                or recipe.jurisdiction.culture_name
                or recipe.mg_identity.language
            )
            tag_requested = bool(recipe.jurisdiction.tag) and not (
                needs_display
                and not locale_requested
                and not recipe.denomination_list
                and not recipe.credit_rate_values
                and recipe.mg_identity.inactivity_seconds_to_game_selector is None
                and not pl.touches_mgconfig()
                and not needs_limit
            )
            if (
                tag_requested
                or locale_requested
            ):
                patch_mgconfig_locale(
                    dest_mg,
                    dest_mg,
                    recipe.jurisdiction,
                    language=recipe.mg_identity.language or None,
                )
            if pl.touches_mgconfig():
                patch_mgconfig_play(dest_mg, dest_mg, pl)
            if needs_limit:
                merged = LimitSetupSettings()
                for spec in LIMIT_SETUP_FIELDS:
                    merged.set_value(spec.key, live_limits.value_for(spec.key))
                    setattr(
                        merged,
                        f"{spec.key}_host_locked",
                        live_limits.host_locked_for(spec.key),
                    )
                    setattr(
                        merged,
                        f"{spec.key}_egm_locked",
                        live_limits.egm_locked_for(spec.key),
                    )
                    if live_limits.editable_for(spec.key):
                        val = recipe.limit_setup.value_for(spec.key)
                        if val is not None:
                            merged.set_value(spec.key, val)
                patch_limit_setup(dest_mg, dest_mg, merged)
            if needs_display:
                patch_mgconfig_display_mode(
                    dest_mg, dest_mg, str(recipe.display_mode)
                )
            written.append(normalize_rel_path(_MGCONFIG_REL))

    # Jurisdiction file: locale plus on-screen SingleDenomination (must
    # match mgconfig DenominationList or the game UI keeps the old 5c).
    single_denom = (
        int(recipe.denomination_list[0]) if recipe.denomination_list else None
    )
    want_jur_mw = (
        recipe.jurisdiction.magic_wheel_money_limit is not None
        or pl.touches_magicwheel()
    )
    if _want("jurisdiction") and (
        recipe.jurisdiction.tag
        or recipe.jurisdiction.currency_name
        or recipe.jurisdiction.culture_name
        or want_jur_mw
        or single_denom is not None
    ):
        jsrc = live / _JURISDICTION_REL
        create_pack = not dedicated_magicwheel_file_exists(live)
        if jsrc.is_file():
            create_pack = not dedicated_magicwheel_file_exists(live)
            _stage(
                _JURISDICTION_REL,
                lambda s, d, denom=single_denom, create=create_pack: (
                    patch_jurisdiction_config(
                        s,
                        d,
                        recipe.jurisdiction,
                        single_denomination=denom,
                        play_limits=pl,
                        create_pack_fields=create,
                    )
                ),
            )
        elif single_denom is not None or recipe.jurisdiction.tag:
            dest_j = pack_dir / _JURISDICTION_REL
            dest_j.parent.mkdir(parents=True, exist_ok=True)
            dest_j.write_bytes(
                b'<?xml version="1.0" encoding="utf-8"?>\n'
                b"<JurisdictionSettings>\n</JurisdictionSettings>\n"
            )
            patch_jurisdiction_config(
                dest_j,
                dest_j,
                recipe.jurisdiction,
                single_denomination=single_denom,
                play_limits=pl,
                create_pack_fields=create_pack,
            )
            written.append(normalize_rel_path(_JURISDICTION_REL))

    if _want("magicwheel") and want_jur_mw:
        for rel in iter_magicwheel_setting_rels(live):
            if rel.casefold() == _JURISDICTION_REL.casefold():
                continue
            src = _resolve_goldclub_rel(live, rel)
            if src is None:
                continue
            if (
                rel.casefold() != _MAGICWHEEL_REL.casefold()
                and not looks_like_magicwheel_settings(src)
            ):
                continue

            def _patch_mw(
                s: Path,
                d: Path,
                _rel: str = rel,
            ) -> None:
                patch_magicwheel_config(
                    s,
                    d,
                    money_limit=recipe.jurisdiction.magic_wheel_money_limit,
                    enabled=pl.magic_wheel_enabled,
                    bet=pl.magic_wheel_bet,
                    max_spins=pl.magic_wheel_max_spins,
                    average=pl.magic_wheel_average,
                )

            _stage(rel, _patch_mw)

    # Aurum hostname placeholders and/or currency (must match jurisdiction CurrencyName)
    currency = (
        recipe.jurisdiction.currency_name or recipe.hardware_currency_name or ""
    ).strip().upper()
    want_aurum = _want("aurum") and (
        recipe.aurum_identity.network_hostname_template or currency
    )
    # SAS address / AFT / lock live in ClientsSet + SASsetupData. Rewriting
    # AurumSetup.xml for those (ElementTree round-trip) drops the Windows
    # hostname Network block → AurumEGM..ctor NRE / SASControler1 NOT FOUND.
    want_sas_channels = _want("sas") and sas_channel_flags_differ(live, recipe.sas)
    if want_aurum or want_sas_channels:
        identity = (
            recipe.aurum_identity if want_aurum else AurumIdentitySettings()
        )
        _stage(
            _AURUM_SETUP_REL,
            lambda s, d: patch_aurum_setup_placeholders(
                s,
                d,
                identity,
                currency_code=currency or None if want_aurum else None,
                sas=recipe.sas if want_sas_channels else None,
            ),
        )

    # Offline ticket config file (optional companion to OfflineEnabled)
    if _want("oticket") and (recipe.include_oticket or recipe.offline_enabled):
        oticket_src = live / _OTICKET_REL
        if oticket_src.is_file() and (
            recipe.include_oticket or recipe.offline_enabled is True
        ):
            dest = pack_dir / _OTICKET_REL
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(oticket_src, dest)
            written.append(normalize_rel_path(_OTICKET_REL))

    # SAS
    if _want("sas"):
        clients = _resolve_goldclub_rel(live, _CLIENTS_SET_REL)
        if clients is not None and clients.is_file():
            dest = pack_dir / _CLIENTS_SET_REL
            dest.parent.mkdir(parents=True, exist_ok=True)
            patch_clients_set(clients, dest, recipe.sas)
            written.append(normalize_rel_path(_CLIENTS_SET_REL))
        sas_setup = _resolve_goldclub_rel(live, _SAS_SETUP_REL)
        if sas_setup is None or not sas_setup.is_file():
            raise FileNotFoundError(
                f"SAS setup missing under {live}: {_SAS_SETUP_REL} "
                "(LockGameWhenNoComms cannot be written)"
            )
        dest = pack_dir / _SAS_SETUP_REL
        dest.parent.mkdir(parents=True, exist_ok=True)
        patch_sas_setup_data(sas_setup, dest, recipe.sas)
        written.append(normalize_rel_path(_SAS_SETUP_REL))

    from config_scanner.denom_compat import (
        cabinet_has_link2win,
        denomination_lists_equal,
        live_link2win_math_mismatches,
        live_link2win_math_unknown,
        playable_denoms_from_recipe,
    )

    live_denoms, _ = read_mgconfig_denoms(live)
    listed = list(recipe.denomination_list or live_denoms)
    target_denoms = playable_denoms_from_recipe(recipe, listed=listed)
    live_math_stale = bool(
        target_denoms
        and cabinet_has_link2win(live)
        and live_link2win_math_mismatches(live, target_denoms)
    )
    live_math_unknown = bool(
        target_denoms
        and cabinet_has_link2win(live)
        and live_link2win_math_unknown(live)
    )
    denom_changed = bool(
        listed
        and not denomination_lists_equal(listed, live_denoms)
    )
    if (
        target_denoms
        and cabinet_has_link2win(live)
        and (live_math_stale or (denom_changed and live_math_unknown))
    ):
        raise ValueError(
            f"Cannot change denomination to {min(target_denoms)}c: "
            "live Link2WinBonusMath.json does not include that denom."
        )

    if _want("hw_drivers") and recipe.hw_driver_profile:
        from config_scanner.hw_drivers import stage_hw_driver_profile

        for rel in stage_hw_driver_profile(recipe.hw_driver_profile, pack_dir):
            written.append(normalize_rel_path(rel))

    recipe.files = sorted(set(written))
    save_recipe(recipe, pack_dir / "recipe.json")
    return recipe


def apply_config_pack(pack_dir: Path, dest_goldclub: Path) -> ApplyResult:
    """Write staged files from an apply pack onto a live Goldclub root."""
    dest_root = goldclub_root_from_target(dest_goldclub)
    recipe_path = pack_dir / "recipe.json"
    if not recipe_path.is_file():
        return ApplyResult((), (), ("recipe.json missing in config pack",))
    recipe = load_recipe(recipe_path)
    written: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    candidates = recipe.files or []
    if not candidates:
        # Fall back to every relative file under the pack except recipe.json.
        for path in pack_dir.rglob("*"):
            if not path.is_file() or path.name.casefold() == "recipe.json":
                continue
            try:
                candidates.append(path.relative_to(pack_dir).as_posix())
            except ValueError:
                continue

    for rel in candidates:
        norm = normalize_rel_path(rel)
        if is_slot_setup_forbidden_path(norm):
            skipped.append(f"{norm}: forbidden path")
            continue
        src = pack_dir / norm
        if not src.is_file():
            errors.append(f"{norm}: missing in pack")
            continue
        try:
            dest = safe_join_under(dest_root, norm)
        except ValueError as exc:
            errors.append(f"{norm}: {exc}")
            continue
        try:
            _safe_copy_with_identity(src, dest, norm)
            written.append(norm)
        except OSError as exc:
            errors.append(f"{norm}: {exc}")

    return ApplyResult(tuple(written), tuple(skipped), tuple(errors))
