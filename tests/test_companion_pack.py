"""Tests for companion Updates packs (keyboards, bills, licences, G: mux)."""

from __future__ import annotations

from pathlib import Path

from config_scanner.b2u_pack import build_companion_b2u_folder, pack_companion_update
from config_scanner.companion_pack import (
    CompanionKind,
    apply_companion_pack,
    detect_kind_from_source,
    list_keyboard_variants,
    load_manifest,
    stage_companion_from_source,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _keyboard_source(tmp_path: Path) -> Path:
    root = tmp_path / "CS-Keyboards-00"
    leaf = (
        root
        / "Content"
        / "tmp"
        / "CountrySelectorTool"
        / "data"
        / "Gamestar2"
        / "Axiomtek"
        / "Rhapsody"
    )
    leaf.mkdir(parents=True)
    _write(
        leaf / "install.json",
        """{
  "Readme": "Gamestar2 Rhapsody Keyboard",
  "Delete": [],
  "Copy": [{"From": "slot", "To": "c:/Goldclub/Slot/"}],
  "Data": [{"Path": [], "Variables": []}]
}
""",
    )
    _write(
        leaf / "slot" / "hwdrivers" / "Keyboard.xml",
        """<?xml version="1.0"?>
<config><mapping><ButtonMapping name="270">Spin</ButtonMapping></mapping></config>
""",
    )
    # Forbidden map must be skipped
    bad = leaf / "slot" / "system" / "hardware" / "serialport"
    bad.mkdir(parents=True)
    _write(bad / "layout.json", '{"bad":true}')
    return root


def _bills_source(tmp_path: Path) -> Path:
    root = tmp_path / "BillsTTD-00"
    tmp = root / "Content" / "tmp"
    _write(
        tmp / "slot" / "themes" / "HardwareConfig.xml",
        "<HardwareSettings><CurrencyName>TTD</CurrencyName></HardwareSettings>\n",
    )
    (tmp / "OneHandConfigurer.exe").write_bytes(b"MZ cfg")
    return root


def _licences_source(tmp_path: Path) -> Path:
    root = tmp_path / "Licences_PR"
    tmp = root / "Content" / "tmp"
    _write(tmp / "Licenses" / "Licence12-test.xml", "<Licence/>\n")
    (tmp / "slot" / "licence.dll").parent.mkdir(parents=True, exist_ok=True)
    (tmp / "slot" / "licence.dll").write_bytes(b"MZ lic")
    return root


def _serial_source(tmp_path: Path) -> Path:
    root = tmp_path / "SerialInterface"
    tmp = root / "Content" / "tmp"
    _write(tmp / "maintenance" / "config" / "serialports.conf", "COM1=ok\n")
    (root / "Content" / "ReBoot.exe").write_bytes(b"MZ reboot")
    return root


def _theme_overlay_source(tmp_path: Path) -> Path:
    root = tmp_path / "Clovers_Disable-00"
    tmp = root / "Content" / "tmp"
    _write(
        tmp / "slot" / "themes" / "data" / "gameselector_GSC_config.xml",
        "<GameSelector><Enabled>false</Enabled></GameSelector>\n",
    )
    return root


def _oticket_source(tmp_path: Path) -> Path:
    root = tmp_path / "OffLineTicket_GS_OticketSetup"
    tmp = root / "Content" / "tmp"
    _write(tmp / "oticket.xml", "<config><location>Gold Club</location></config>\n")
    _write(tmp / "configure-aurum.conf", "[AurumConfigurer]\nCurrency=TTD\n")
    return root


def test_detect_kinds(tmp_path: Path) -> None:
    assert detect_kind_from_source(_keyboard_source(tmp_path)) == CompanionKind.KEYBOARDS
    assert detect_kind_from_source(_bills_source(tmp_path)) == CompanionKind.BILLS
    assert detect_kind_from_source(_licences_source(tmp_path)) == CompanionKind.LICENCES
    assert detect_kind_from_source(_serial_source(tmp_path)) == CompanionKind.SERIAL_MUX
    assert detect_kind_from_source(_theme_overlay_source(tmp_path)) == CompanionKind.THEME_OVERLAY
    assert detect_kind_from_source(_oticket_source(tmp_path)) == CompanionKind.OTICKET
    trial = tmp_path / "TrialReset.b2u"
    trial.write_bytes(b"x")
    assert detect_kind_from_source(trial) == CompanionKind.ONEHAND


def test_stage_and_apply_keyboards(tmp_path: Path) -> None:
    src = _keyboard_source(tmp_path)
    pack = tmp_path / "kb_pack"
    manifest = stage_companion_from_source(src, pack, kind=CompanionKind.KEYBOARDS)
    assert manifest.kind == CompanionKind.KEYBOARDS
    assert (pack / "companion.json").is_file()
    variants = list_keyboard_variants(pack)
    assert any("Rhapsody" in v for v in variants)

    gold = tmp_path / "Goldclub"
    gold.mkdir()
    leaf = pack / "CountrySelectorTool" / "data" / "Gamestar2" / "Axiomtek" / "Rhapsody"
    result = apply_companion_pack(pack, goldclub_root=gold, keyboard_leaf=leaf)
    assert not result.errors
    assert (gold / "slot" / "hwdrivers" / "Keyboard.xml").is_file()
    assert not (
        gold / "slot" / "system" / "hardware" / "serialport" / "layout.json"
    ).exists()


def test_licences_require_flag(tmp_path: Path) -> None:
    src = _licences_source(tmp_path)
    pack = tmp_path / "lic_pack"
    stage_companion_from_source(src, pack, kind=CompanionKind.LICENCES)
    gold = tmp_path / "Goldclub"
    gold.mkdir()
    blocked = apply_companion_pack(pack, goldclub_root=gold, allow_licences=False)
    assert blocked.errors
    assert "Licence" in blocked.errors[0] or "licence" in blocked.errors[0].casefold()

    ok = apply_companion_pack(pack, goldclub_root=gold, allow_licences=True)
    assert not ok.errors
    assert (gold / "Licenses" / "Licence12-test.xml").is_file()
    assert (gold / "slot" / "licence.dll").is_file()


def test_serial_mux_requires_g_flag(tmp_path: Path) -> None:
    src = _serial_source(tmp_path)
    pack = tmp_path / "mux_pack"
    stage_companion_from_source(src, pack, kind=CompanionKind.SERIAL_MUX)
    assert (pack / "ReBoot.exe").is_file()
    blocked = apply_companion_pack(pack, allow_g_drive=False)
    assert blocked.errors
    assert "G:" in blocked.errors[0] or "g_drive" in blocked.errors[0].casefold()

    gdrive = tmp_path / "Gdrive"
    gdrive.mkdir()
    ok = apply_companion_pack(pack, g_drive_root=gdrive, allow_g_drive=True)
    assert not ok.errors
    assert (gdrive / "maintenance" / "config" / "serialports.conf").is_file()


def test_bills_stage_and_apply(tmp_path: Path) -> None:
    src = _bills_source(tmp_path)
    pack = tmp_path / "bills_pack"
    manifest = stage_companion_from_source(src, pack, kind=CompanionKind.BILLS)
    assert manifest.run_onehand_configurer
    gold = tmp_path / "Goldclub"
    gold.mkdir()
    result = apply_companion_pack(pack, goldclub_root=gold)
    assert not result.errors
    hw = (gold / "slot" / "themes" / "HardwareConfig.xml").read_text(encoding="utf-8")
    assert "TTD" in hw
    assert any("OneHandConfigurer" in n for n in result.notes)


def test_build_companion_b2u(tmp_path: Path) -> None:
    src = _bills_source(tmp_path)
    pack = tmp_path / "bills_pack"
    stage_companion_from_source(src, pack, kind=CompanionKind.BILLS, label="BillsTTD")
    exe = tmp_path / "ConfigScanner.exe"
    exe.write_bytes(b"MZ")
    package = build_companion_b2u_folder(
        tmp_path / "out", pack, exe_path=exe, package_name="Comp_Test"
    )
    init = (package / "Content" / "init.cmd").read_text(encoding="ascii")
    assert "--companion-pack" in init
    assert (
        package / "Content" / "tmp" / "companion-pack" / "companion.json"
    ).is_file()
    result = pack_companion_update(
        tmp_path / "dist", pack, exe_path=exe, package_name="Comp_X", encrypt=False
    )
    assert result.b2u_path is None
    assert load_manifest(
        result.package_dir / "Content" / "tmp" / "companion-pack" / "companion.json"
    ).kind == CompanionKind.BILLS


def test_theme_overlay_and_oticket_apply(tmp_path: Path) -> None:
    overlay_src = _theme_overlay_source(tmp_path)
    overlay_pack = tmp_path / "clovers_pack"
    manifest = stage_companion_from_source(overlay_src, overlay_pack)
    assert manifest.kind == CompanionKind.THEME_OVERLAY
    gold = tmp_path / "Goldclub"
    gold.mkdir()
    result = apply_companion_pack(overlay_pack, goldclub_root=gold)
    assert not result.errors
    assert (
        gold / "slot" / "themes" / "data" / "gameselector_GSC_config.xml"
    ).is_file()

    ticket_src = _oticket_source(tmp_path)
    ticket_pack = tmp_path / "oticket_pack"
    ticket_manifest = stage_companion_from_source(ticket_src, ticket_pack)
    assert ticket_manifest.kind == CompanionKind.OTICKET
    applied = apply_companion_pack(ticket_pack, goldclub_root=gold)
    assert not applied.errors
    dest = gold / "bios" / "etc" / "application" / "slot" / "oticket.xml"
    assert dest.is_file()
    assert "Gold Club" in dest.read_text(encoding="utf-8")
    conf = gold / "maintenance" / "config" / "configure-aurum.conf"
    assert conf.is_file()
    assert "TTD" in conf.read_text(encoding="utf-8")


def test_gui_kind_labels_cover_all_kinds() -> None:
    from gui.companion_pack_panel import _KIND_LABELS

    assert set(CompanionKind) <= set(_KIND_LABELS)

