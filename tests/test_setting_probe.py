"""Probe settings against staged Trinidad CS leaves."""

from __future__ import annotations

from pathlib import Path

import pytest

from config_scanner.embedded_updates import load_catalog, materialize_country_tool
from config_scanner.setting_probe import SettingState, probe_setting, read_setting_value
from config_scanner.setting_spec import specs_by_id


def _leaf(pack_id: str, *path_parts: str) -> Path:
    entries = load_catalog()
    entry = next(e for e in entries if e.id == pack_id)
    tool = materialize_country_tool(entry)
    leaf = tool / "data"
    for part in path_parts:
        leaf = leaf / part
    assert leaf.is_dir(), leaf
    assert (leaf / "install.json").is_file()
    return leaf


@pytest.fixture(scope="module")
def leaf_10c() -> Path:
    return _leaf(
        "CS-Gamestar-TRI-00_OL+SAS",
        "Trinidad&Tobago",
        "Gamestar OL+SAS 10c",
        "Gamestar 2 Screens",
    )


@pytest.fixture(scope="module")
def leaf_2c() -> Path:
    return _leaf(
        "CS-Gamestar-TRI-00_OL+SAS",
        "Trinidad&Tobago",
        "Gamestar OL+SAS 2c",
        "Gamestar 2 Screens",
    )


def test_denom_list_10c(leaf_10c: Path) -> None:
    spec = specs_by_id()["denom.list"]
    present, value, _note = read_setting_value(leaf_10c, spec)
    assert present
    assert value == [10]


def test_denom_list_2c(leaf_2c: Path) -> None:
    spec = specs_by_id()["denom.list"]
    present, value, _note = read_setting_value(leaf_2c, spec)
    assert present
    assert value == [2]


def test_offline_enabled_ol_sas(leaf_10c: Path) -> None:
    spec = specs_by_id()["ticket.offline_enabled"]
    present, value, _note = read_setting_value(leaf_10c, spec)
    assert present
    assert value is True


def test_keyboard_not_supplied_on_cs_leaf(leaf_10c: Path) -> None:
    spec = specs_by_id()["buttons.keyboard_map"]
    reading = probe_setting(
        leaf_10c,
        spec,
        expected={"Spin": "Space"},
        source_is_cs_leaf=True,
    )
    assert reading.state == SettingState.NOT_SUPPLIED


def test_absent_when_expected_and_missing(leaf_10c: Path, tmp_path: Path) -> None:
    # Empty goldclub-shaped root → denom.list ABSENT when expected.
    empty = tmp_path / "goldclub"
    empty.mkdir()
    spec = specs_by_id()["denom.list"]
    reading = probe_setting(empty, spec, expected=[10], source_is_cs_leaf=True)
    assert reading.state == SettingState.ABSENT


def test_new_b2u_settings_on_trinidad_leaf(leaf_10c: Path) -> None:
    specs = specs_by_id()
    present, value, _note = read_setting_value(leaf_10c, specs["ui.inactivity_to_selector"])
    assert present
    assert str(value) == "0"
    present, value, _note = read_setting_value(leaf_10c, specs["sas.chirping_enabled"])
    assert present is True
    assert value is True
    present, value, _note = read_setting_value(leaf_10c, specs["id.aurum_currency_code"])
    assert present
    assert value == "TTD"
    present, value, _note = read_setting_value(leaf_10c, specs["aurum.conf_currency"])
    assert present
    assert value == "USD"
    present, value, _note = read_setting_value(leaf_10c, specs["hw.tower_enabled"])
    assert present
    assert value is True
    present, value, _note = read_setting_value(leaf_10c, specs["dallas.nfc_enable"])
    assert present
    assert value is False
    present, value, _note = read_setting_value(leaf_10c, specs["ticket.layout_jackpot"])
    assert present
    assert value == "jackpotreceipt0"
    present, value, _note = read_setting_value(leaf_10c, specs["aurum.svc_tubo"])
    assert present is True
    assert value is True
    present, value, _note = read_setting_value(leaf_10c, specs["aurum.svc_progressive"])
    assert present is True
    assert value is False
    present, value, _note = read_setting_value(leaf_10c, specs["ui.cashout_button_mode"])
    assert present
    assert value == "Ticket"
    present, value, _note = read_setting_value(leaf_10c, specs["id.processor_locale"])
    assert present
    assert value == "sl_SI"

    spec = specs_by_id()["denom.list"]
    match = probe_setting(leaf_10c, spec, expected=[10], source_is_cs_leaf=True)
    assert match.state == SettingState.MATCH
    differs = probe_setting(leaf_10c, spec, expected=[5], source_is_cs_leaf=True)
    assert differs.state == SettingState.DIFFERS
    assert differs.value == [10]


def test_optional_cs_file_probed_when_present(tmp_path: Path) -> None:
    gold = tmp_path / "leaf"
    kb = gold / "slot" / "hwdrivers"
    kb.mkdir(parents=True)
    (kb / "Keyboard.xml").write_text(
        '<?xml version="1.0"?><config><mapping>'
        '<ButtonMapping name="Spin">Space</ButtonMapping>'
        "</mapping></config>\n",
        encoding="utf-8",
    )
    spec = specs_by_id()["buttons.keyboard_map"]
    reading = probe_setting(
        gold, spec, expected={"Spin": "Space"}, source_is_cs_leaf=True
    )
    assert reading.state == SettingState.MATCH
    assert reading.value == {"Spin": "Space"}
