"""Denom configuration guards for Live Push."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from config_scanner.denom_compat import (
    STANDARD_CONFIG_DENOMS,
    allowed_denoms_for,
    denom_combo_choices,
    expected_magic_wheel_for_denom,
    find_staged_leaf_for_denom,
    inspect_link2win_math,
    list_link2win_math_replace_targets,
    parse_link2win_pairs,
    replace_cabinet_math_file,
    validate_denom_configuration,
    validate_math_replacement_source,
)
from config_scanner.jurisdiction import find_jurisdiction
from config_scanner.live_push import (
    dallas_read_diagnostics,
    read_latest_dallas_from_hardware,
    wait_for_dallas_from_hardware,
)
from config_scanner.slot_setup import (
    PlayLimitsSettings,
    SlotSetupRecipe,
    build_config_pack,
    load_recipe_from_goldclub,
    recipe_from_jurisdiction_profile,
)
from tests.test_slot_setup import _fake_goldclub


def test_allowed_denoms_include_standard_config_set() -> None:
    allowed = allowed_denoms_for("TTD", "TrinidadTobago")
    assert STANDARD_CONFIG_DENOMS <= allowed
    assert {2, 5, 10} <= allowed
    choices = denom_combo_choices("TTD", "TrinidadTobago")
    assert "100" in choices
    assert "2" in choices
    assert "5000" in choices
    jam = allowed_denoms_for("JMD", "Jamaica")
    assert 100 in jam
    assert "100" in denom_combo_choices("JMD", "Jamaica")
    zar = allowed_denoms_for("ZAR", "South Africa")
    assert 1 in zar
    assert "1" in denom_combo_choices("ZAR", "SA")


def test_high_denoms_available_for_colombia_cop() -> None:
    allowed = allowed_denoms_for("COP", "Colombia")
    assert {100, 500, 1000, 5000} <= allowed
    choices = denom_combo_choices("COP", "Colombia")
    assert choices[-1] == "5000"
    assert expected_magic_wheel_for_denom(5000) == (5000, 25000)


def test_expected_magic_wheel_scales_with_denom() -> None:
    assert expected_magic_wheel_for_denom(2) == (2, 10)
    assert expected_magic_wheel_for_denom(10) == (10, 50)
    assert expected_magic_wheel_for_denom(100) == (100, 500)


def test_rejects_disallowed_denom(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.jurisdiction.currency_name = "TTD"
    proposed.jurisdiction.tag = "TrinidadTobago"
    proposed.denomination_list = [7]
    proposed.credit_rate_values = [7]
    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert any("not allowed" in err for err in result.errors)


def test_rejects_denom_change_without_magic_wheel_sync(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "Link2WinBonusMath.json").write_bytes(b"\x00" * 16)

    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [10]
    live.credit_rate_values = [10]
    live.play_limits.magic_wheel_bet = 10
    live.play_limits.magic_wheel_average = 50

    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [5]
    proposed.credit_rate_values = [5]
    proposed.play_limits.magic_wheel_bet = 10
    proposed.play_limits.magic_wheel_average = 50

    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert any("Magic wheel" in err for err in result.errors)


def test_finds_staged_leaf_for_ttd_10c() -> None:
    leaf = find_staged_leaf_for_denom(
        10,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert leaf is not None
    assert "10c" in leaf.as_posix()


def test_finds_5c_leaf_when_cabinet_tag_is_puerto_rico() -> None:
    leaf = find_staged_leaf_for_denom(
        5,
        currency="USD",
        market="PuertoRico",
        screens="3",
    )
    assert leaf is not None
    assert "5c" in leaf.as_posix()


def test_rejects_denom_change_when_live_math_is_unidentified(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "Link2WinBonusMath.json").write_bytes(b"\x00" * 16)

    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [10]
    live.credit_rate_values = [10]
    live.jurisdiction.currency_name = "TTD"
    live.jurisdiction.tag = "TrinidadTobago"
    live.play_limits = PlayLimitsSettings(
        magic_wheel_bet=10,
        magic_wheel_average=50,
    )

    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [5]
    proposed.credit_rate_values = [5]
    proposed.play_limits.magic_wheel_bet = 5
    proposed.play_limits.magic_wheel_average = 25

    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert any("cannot be verified" in err or "does not include" in err for err in result.errors)


def test_jamaica_100c_blocked_without_link2win_math(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "Link2WinBonusMath.json").write_bytes(b"\x00" * 16)

    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [5]
    live.credit_rate_values = [5]
    live.jurisdiction.currency_name = "JMD"
    live.jurisdiction.tag = "Jamaica"
    live.play_limits = PlayLimitsSettings(
        magic_wheel_bet=5,
        magic_wheel_average=25,
    )

    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [100]
    proposed.credit_rate_values = [100]
    proposed.play_limits.magic_wheel_bet = 100
    proposed.play_limits.magic_wheel_average = 500

    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert result.leaf_dir is None
    assert any("Link2Win" in err or "math" in err.casefold() for err in result.errors)

    pack = tmp_path / "pack"
    try:
        build_config_pack(proposed, gold, pack)
    except ValueError as exc:
        assert "Link2WinBonusMath" in str(exc)
    else:
        raise AssertionError("expected build_config_pack to refuse 100c without math")


def _write_link2win_json(gold: Path, pairs: list[tuple[int, int]]) -> Path:
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    path = link_dir / "Link2WinBonusMath.json"
    path.write_text(
        json.dumps([{"Bet": bet, "Denom": denom} for bet, denom in pairs]),
        encoding="utf-8",
    )
    return path


def test_parse_link2win_pairs_from_plain_json(tmp_path: Path) -> None:
    path = tmp_path / "Link2WinBonusMath.json"
    path.write_text(
        '[{"Bet": 30, "Denom": 5}, {"Bet": 30, "Denom": 10}]',
        encoding="utf-8",
    )
    assert parse_link2win_pairs(path) == frozenset({(30, 5), (30, 10)})


def test_inspect_embedded_5c_math_is_not_10c() -> None:
    leaf = find_staged_leaf_for_denom(
        5,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert leaf is not None
    support = inspect_link2win_math(
        leaf / "slot/themes/Link2WinFeature/Link2WinBonusMath.json"
    )
    assert support is not None
    assert 5 in support.denoms
    assert 10 not in support.denoms


def test_rejects_bet_denom_missing_from_live_math_json(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write_link2win_json(gold, [(30, 5)])
    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [5]
    live.credit_rate_values = [5]
    live.jurisdiction.currency_name = "JMD"
    live.jurisdiction.tag = "Jamaica"
    live.play_limits = PlayLimitsSettings(
        magic_wheel_bet=5,
        magic_wheel_average=25,
        bet_multipliers=[30],
    )
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [25]
    proposed.credit_rate_values = [25]
    proposed.play_limits.magic_wheel_bet = 25
    proposed.play_limits.magic_wheel_average = 125
    proposed.play_limits.bet_multipliers = [30]
    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert any(
        ("Bet: 30" in err and "Denom: 25" in err) or "does not include 25c" in err
        for err in result.errors
    )


def test_accepts_live_math_that_already_has_bet_denom(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    _write_link2win_json(gold, [(30, 10)])
    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [5]
    live.credit_rate_values = [5]
    live.jurisdiction.currency_name = "JMD"
    live.jurisdiction.tag = "Jamaica"
    live.play_limits = PlayLimitsSettings(
        magic_wheel_bet=5,
        magic_wheel_average=25,
        bet_multipliers=[30],
    )
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [10]
    proposed.credit_rate_values = [10]
    proposed.play_limits.magic_wheel_bet = 10
    proposed.play_limits.magic_wheel_average = 50
    proposed.play_limits.bet_multipliers = [30]
    result = validate_denom_configuration(live, proposed, gold)
    assert result.ok
    assert not result.errors


def test_puerto_rico_can_push_5c_when_live_math_is_already_5c(tmp_path: Path) -> None:
    """Live .111 case: jurisdiction still PuertoRico/USD, math is the 5c pack."""
    gold = _fake_goldclub(tmp_path)
    src_leaf = find_staged_leaf_for_denom(
        5,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert src_leaf is not None
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        src_leaf / "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        link_dir / "Link2WinBonusMath.json",
    )
    mg = gold / "slot/themes/mgconfig.xml"
    mg.write_text(
        mg.read_text(encoding="utf-8")
        .replace("<int>5</int>", "<int>10</int>"),
        encoding="utf-8",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [10]
    live.credit_rate_values = [10]
    live.jurisdiction.currency_name = "USD"
    live.jurisdiction.tag = "PuertoRico"
    live.play_limits = PlayLimitsSettings(
        magic_wheel_bet=10,
        magic_wheel_average=50,
    )
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [5]
    proposed.credit_rate_values = [5]
    proposed.play_limits.magic_wheel_bet = 5
    proposed.play_limits.magic_wheel_average = 25
    result = validate_denom_configuration(live, proposed, gold)
    assert result.ok, result.errors
    pack = tmp_path / "pack"
    built = build_config_pack(proposed, gold, pack)
    assert built.files
    assert not any("Cannot change denomination" in f for f in built.files)


def test_ttd_10c_stages_country_pack_math_when_live_is_5c(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    src_leaf = find_staged_leaf_for_denom(
        5,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert src_leaf is not None
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        src_leaf / "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        link_dir / "Link2WinBonusMath.json",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [5]
    live.credit_rate_values = [5]
    live.jurisdiction.currency_name = "TTD"
    live.jurisdiction.tag = "TrinidadTobago"
    live.play_limits = PlayLimitsSettings(
        magic_wheel_bet=5,
        magic_wheel_average=25,
    )
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [10]
    proposed.credit_rate_values = [10]
    proposed.play_limits.magic_wheel_bet = 10
    proposed.play_limits.magic_wheel_average = 50
    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert any("does not include 10c" in err for err in result.errors)
    pack = tmp_path / "pack"
    try:
        build_config_pack(proposed, gold, pack)
    except ValueError as exc:
        assert "does not include" in str(exc)
    else:
        raise AssertionError("expected build_config_pack to refuse 10c on 5c live math")


def test_rejects_custom_bet_multipliers_for_market(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    live.jurisdiction.currency_name = "TTD"
    live.play_limits.bet_multipliers = [1, 2, 3, 4, 5, 8, 10, 12, 15]

    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.play_limits.bet_multipliers = [1, 5, 10, 20]

    result = validate_denom_configuration(live, proposed, gold)
    assert not result.ok
    assert any("Bet multipliers" in err for err in result.errors)


def test_market_preset_denoms_are_allowed() -> None:
    prof = find_jurisdiction("trinidad_ttd")
    assert prof is not None
    recipe = recipe_from_jurisdiction_profile(prof, denom=5)
    assert recipe.denomination_list == [5, 2, 10] or recipe.denomination_list[0] == 5


def test_read_latest_dallas_from_slotlog(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    log_dir = gold / "var" / "log" / "SlotLog"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "2026-09-03.log").write_text(
        "noise\n"
        "2026-09-03T10:00:00.000+01:00 INFO Dallas code received: 0100000000000282\n"
        "2026-09-03T10:01:00.000+01:00 INFO Dallas code received: 01D68A721B000019\n",
        encoding="utf-8",
    )
    hit = read_latest_dallas_from_hardware(gold)
    assert hit.code == "01D68A721B000019"
    assert hit.via == "onehand"


def test_read_dallas_from_bios2_multihardware_without_onehand(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    log_dir = gold / "var" / "log" / "BiOS2 MultiHardware EVENTS"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "2026-09-03.log").write_text(
        "2026-09-03T11:09:46.560+01:00 INFO [:1] DALLASKEY CONTROLLER - "
        "Dallas code received: 01AABBCCDDEEFF01\n",
        encoding="utf-8",
    )
    hit = read_latest_dallas_from_hardware(gold)
    assert hit.code == "01AABBCCDDEEFF01"
    assert hit.via == "hardware"
    assert "BiOS2" in hit.source


def test_wait_for_dallas_returns_existing_fresh_code(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    log_dir = gold / "var" / "log" / "HardwareSetup MultiHardware EVENTS"
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    line_ts = now.strftime("%Y-%m-%dT%H:%M:%S.000%z")
    if len(line_ts) >= 5 and line_ts[-5] != ":":
        line_ts = line_ts[:-2] + ":" + line_ts[-2:]
    (log_dir / "live.log").write_text(
        f"{line_ts} INFO DALLASKEY CONTROLLER - Dallas code received: 01FEEDFACE000001\n",
        encoding="utf-8",
    )
    sleeps: list[float] = []

    def _sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("time.sleep", _sleep)
    hit = wait_for_dallas_from_hardware(gold, timeout_sec=5.0, poll_sec=2.5)
    assert hit.code == "01FEEDFACE000001"
    assert hit.via == "hardware"
    assert sleeps == []  # found on first read, no poll loop


def test_dallas_pins_bios2_log_with_slotlog_backlog(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    slot_dir = gold / "var" / "log" / "SlotLog"
    slot_dir.mkdir(parents=True, exist_ok=True)
    for day in range(1, 16):
        (slot_dir / f"2026-09-{day:02d}.log").write_text("noise\n", encoding="utf-8")
    bios2_dir = gold / "var" / "log" / "BiOS2"
    bios2_dir.mkdir(parents=True, exist_ok=True)
    (bios2_dir / "BiOS2.log").write_text(
        "2026-09-01 09:00:00 INFO [Buttons driver] "
        "MultiHardware.Controllers.Axiomtek.DallasKeyController - "
        "Dallas code received: 01AABBCCDDEEFF01\n",
        encoding="utf-8",
    )
    hit = read_latest_dallas_from_hardware(gold)
    assert hit.code == "01AABBCCDDEEFF01"
    assert hit.via == "hardware"
    assert "BiOS2" in hit.source


def test_wait_for_dallas_accepts_stale_bios2_without_poll(tmp_path: Path, monkeypatch) -> None:
    gold = _fake_goldclub(tmp_path)
    bios2_dir = gold / "var" / "log" / "BiOS2"
    bios2_dir.mkdir(parents=True, exist_ok=True)
    (bios2_dir / "BiOS2.log").write_text(
        "2020-01-01 09:00:00 INFO [Buttons driver] "
        "Dallas code received: 01DEADBEEF000001\n",
        encoding="utf-8",
    )
    sleeps: list[float] = []

    def _sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("time.sleep", _sleep)
    hit = wait_for_dallas_from_hardware(gold, timeout_sec=5.0, poll_sec=2.5)
    assert hit.code == "01DEADBEEF000001"
    assert hit.via == "hardware"
    assert sleeps == []


def test_dallas_hot_prefers_today_onehand_over_stale_bios2(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    bios2_dir = gold / "var" / "log" / "BiOS2"
    bios2_dir.mkdir(parents=True, exist_ok=True)
    (bios2_dir / "BiOS2.log").write_text(
        "2020-01-01 09:00:00 INFO Dallas code received: 01OLDKEY000000001\n",
        encoding="utf-8",
    )
    oh_dir = gold / "var" / "log" / "OneHand MultiHardware EVENTS"
    oh_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().astimezone()
    line_ts = today.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(
        timespec="milliseconds"
    )
    (oh_dir / f"{today.strftime('%Y-%m-%d')}.log").write_text(
        f"{line_ts} INFO Dallas code received: 01FEEDFACE000001\n",
        encoding="utf-8",
    )
    hit = read_latest_dallas_from_hardware(
        gold, hot_only=True, ignore_not_before=True
    )
    assert hit.code == "01FEEDFACE000001"
    assert hit.via == "onehand"


def test_dallas_read_diagnostics_lists_folders(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    mh = gold / "var" / "log" / "BiOS2 MultiHardware EVENTS"
    mh.mkdir(parents=True, exist_ok=True)
    (mh / "2026-09-03.log").write_text(
        "2026-09-03T11:00:00.000+01:00 INFO Dallas code received: 01AABBCCDDEEFF01\n",
        encoding="utf-8",
    )
    text = dallas_read_diagnostics(gold)
    assert "BiOS2 MultiHardware" in text
    assert "01AABBCCDDEEFF01" in text


def test_inspect_uses_hash_before_decrypt(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "Link2WinBonusMath.json"
    blob = b"\x00encrypted-math"
    path.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(
        "config_scanner.denom_compat._link2win_hash_to_denom",
        lambda: {digest: 5},
    )
    launched: list[int] = []

    def _no_decrypt(_path, **_kwargs):
        launched.append(1)
        return None

    monkeypatch.setattr(
        "config_scanner.math_decrypt.decrypt_math_file",
        _no_decrypt,
    )
    support = inspect_link2win_math(path)
    assert support is not None
    assert 5 in support.denoms
    assert launched == []


def test_inspect_allow_decrypt_false_skips_encryptor(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "Link2WinBonusMath.json"
    path.write_bytes(b"\x00encrypted-math")
    monkeypatch.setattr(
        "config_scanner.denom_compat._link2win_hash_to_denom",
        lambda: {},
    )
    launched: list[int] = []
    monkeypatch.setattr(
        "config_scanner.math_decrypt.decrypt_math_file",
        lambda _path, **kwargs: launched.append(kwargs.get("spawn", True)) or None,
    )
    assert inspect_link2win_math(path, allow_decrypt=False) is None
    assert launched == [False]


def test_link2win_hash_manifest_includes_cabinet_111_5c() -> None:
    from config_scanner.denom_compat import _link2win_hash_manifest

    live_sha = "497b2e144a04a95ecd9a75a33ddf8ed3eb15bc340c91db965c353b6ad669bc56"
    manifest = _link2win_hash_manifest()
    assert manifest.get(live_sha) == 5
    config2_sha = "2b14d791139d23ac531e1d8e12d72733debff70b5175ef1829c014a2a59d9738"
    assert manifest.get(config2_sha) == 5


def test_list_math_replace_targets_when_live_missing_denom(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    src_leaf = find_staged_leaf_for_denom(
        5,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert src_leaf is not None
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        src_leaf / "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        link_dir / "Link2WinBonusMath.json",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [5]
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [10]
    proposed.play_limits.magic_wheel_bet = 10
    proposed.play_limits.magic_wheel_average = 50
    targets = list_link2win_math_replace_targets(live, proposed, gold)
    assert len(targets) == 1
    assert targets[0].label == "Link2WinBonusMath.json"
    assert targets[0].denoms == (10,)


def test_replace_cabinet_math_clears_validation(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    src_5c = find_staged_leaf_for_denom(
        5,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    src_10c = find_staged_leaf_for_denom(
        10,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert src_5c is not None and src_10c is not None
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        src_5c / "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        link_dir / "Link2WinBonusMath.json",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    live.denomination_list = [5]
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [10]
    proposed.play_limits.magic_wheel_bet = 10
    proposed.play_limits.magic_wheel_average = 50
    targets = list_link2win_math_replace_targets(live, proposed, gold)
    assert targets
    good_src = src_10c / "slot/themes/Link2WinFeature/Link2WinBonusMath.json"
    assert validate_math_replacement_source(good_src, targets[0]) is None
    replace_cabinet_math_file(gold, targets[0], good_src)
    after_replace = validate_denom_configuration(live, proposed, gold)
    assert after_replace.ok, after_replace.errors
    assert not list_link2win_math_replace_targets(live, proposed, gold)


def test_validate_math_replacement_rejects_wrong_denom(tmp_path: Path) -> None:
    gold = _fake_goldclub(tmp_path)
    src_5c = find_staged_leaf_for_denom(
        5,
        currency="TTD",
        market="TrinidadTobago",
        screens="3",
    )
    assert src_5c is not None
    link_dir = gold / "slot/themes/Link2WinFeature"
    link_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        src_5c / "slot/themes/Link2WinFeature/Link2WinBonusMath.json",
        link_dir / "Link2WinBonusMath.json",
    )
    live = load_recipe_from_goldclub(gold, label="live")
    proposed = SlotSetupRecipe.from_dict(live.to_dict())
    proposed.denomination_list = [10]
    targets = list_link2win_math_replace_targets(live, proposed, gold)
    assert targets
    bad_src = src_5c / "slot/themes/Link2WinFeature/Link2WinBonusMath.json"
    err = validate_math_replacement_source(bad_src, targets[0])
    assert err is not None
    assert "10c" in err or "does not include" in err

