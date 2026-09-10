"""Regression tests for the edge-case audit (fail-closed restore / match / paths)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config_scanner.cabinet_trial_prep import prepare_cabinet_for_seamless_transfer
from config_scanner.cs_catalog import _normalize_goldclub_path
from config_scanner.dest_preflight import target_ok_for_snapshot_restore
from config_scanner.jurisdiction import (
    JurisdictionProfile,
    leaf_matches_profile_country,
    load_jurisdictions,
)
from config_scanner.machine_identity import is_licence_filename, live_has_licence
from config_scanner.scanner import (
    FileEntry,
    Manifest,
    save_json,
)
from config_scanner.service import ConfigScannerService
from config_scanner.setting_probe import SettingState, probe_tree
from config_scanner.slot_setup import recipe_from_jurisdiction_profile
from config_scanner.write_scope import WriteScope, path_matches_write_scope
from config_scanner.write_verify import (
    PreWriteCapture,
    capture_pre_write_state,
    rollback_pre_write_state,
)
from network.ruleta_stack_probe import (
    BlockingProcessProbe,
    probe_blocking_processes_remote_result,
    verify_stack_clear_for_swap,
)


def test_snapshot_apply_refuses_missing_snapshot(tmp_path: Path) -> None:
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "config.json").write_text("{}", encoding="utf-8")
    service = ConfigScannerService(tool)
    refuses = service.snapshot_apply_refuses("no_such", str(tmp_path / "gc"))
    assert refuses
    assert "not found" in refuses[0].casefold()


def test_snapshot_apply_refuses_fail_closed_on_exception(
    monkeypatch, tmp_path: Path
) -> None:
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "config.json").write_text("{}", encoding="utf-8")
    snap = tool / "snapshots" / "s1"
    snap.mkdir(parents=True)
    (snap / "build-info.json").write_text("{}", encoding="utf-8")
    (snap / "manifest.json").write_text('{"files":[]}', encoding="utf-8")
    service = ConfigScannerService(tool)

    def _boom(*_a, **_k):
        raise OSError("smb down")

    monkeypatch.setattr(
        "config_scanner.service.load_build_info",
        _boom,
    )
    refuses = service.snapshot_apply_refuses("s1", str(tmp_path / "gc"))
    assert refuses
    assert "preflight failed" in refuses[0].casefold()


def test_target_ok_fails_closed_when_live_serial_unreadable(
    monkeypatch, tmp_path: Path
) -> None:
    dest = tmp_path / "goldclub"
    (dest / "ruleta").mkdir(parents=True)
    monkeypatch.setattr(
        "config_scanner.build_version.read_machine_serial_from_target",
        lambda _t: None,
    )
    assert (
        target_ok_for_snapshot_restore(str(dest), snapshot_serial="GRT330106")
        is False
    )


def test_target_ok_allows_when_snapshot_has_no_serial(tmp_path: Path) -> None:
    dest = tmp_path / "goldclub"
    (dest / "ruleta").mkdir(parents=True)
    assert target_ok_for_snapshot_restore(str(dest), snapshot_serial=None) is True


def test_stack_clear_fails_closed_on_probe_error(monkeypatch, tmp_path: Path) -> None:
    dest = tmp_path / "ruleta"
    dest.mkdir()
    monkeypatch.setattr(
        "network.ruleta_stack_probe.probe_blocking_processes_result",
        lambda _host: BlockingProcessProbe(error="winrm timed out"),
    )
    ok, detail = verify_stack_clear_for_swap("10.0.0.111", dest)
    assert ok is False
    assert "could not check" in detail.casefold()


def test_remote_process_probe_empty_host_is_error() -> None:
    result = probe_blocking_processes_remote_result("")
    assert result.error
    assert result.names == ()


def test_winrm_script_wrapper_propagates_exit_code() -> None:
    from automation.remote_exec import winrm_run_script
    import inspect

    src = inspect.getsource(winrm_run_script)
    assert "exit $LASTEXITCODE" in src
    assert "winrm script timed out" in src


def test_trial_prep_does_not_succeed_when_clock_fails(monkeypatch, tmp_path: Path) -> None:
    from config_scanner.stack_restart import StackRestartPlan

    dest = tmp_path / "goldclub"
    dest.mkdir()
    monkeypatch.setattr(
        "config_scanner.cabinet_trial_prep.plan_stack_restart",
        lambda _t: StackRestartPlan(mode="local", host=None, kill_ps1="k", run_ps1="r"),
    )
    monkeypatch.setattr(
        "config_scanner.cabinet_trial_prep._run_powershell_file",
        lambda *_a, **_k: (False, "Set-Date access denied"),
    )
    monkeypatch.setattr(
        "roulette_trial.clear_stale_llave_after_software_swap",
        lambda _d: ["RouletteActivate.dat"],
    )
    monkeypatch.setattr(
        "roulette_trial.clear_auto_llave_password_files",
        lambda _t: [],
    )
    ok, detail = prepare_cabinet_for_seamless_transfer(
        str(dest),
        sync_password=False,
        tool_root=tmp_path,
    )
    assert ok is False
    assert "clock script failed" in detail.casefold()


def test_restore_archived_bytes_refuses_plain_ruleta_setup(tmp_path: Path) -> None:
    from config_scanner.scanner import (
        _looks_like_live_ruleta_setup,
        _looks_like_plain_xml,
    )

    dest = tmp_path / "application" / "ruleta" / "setup.xml"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"\x00encrypted")
    assert _looks_like_live_ruleta_setup(dest)
    assert _looks_like_plain_xml(b"<settings/>")
    assert not _looks_like_live_ruleta_setup(tmp_path / "slot" / "themes" / "mgconfig.xml")


def test_probe_reads_flat_mgconfig_locale(tmp_path: Path) -> None:
    mg = tmp_path / "slot" / "themes" / "mgconfig.xml"
    mg.parent.mkdir(parents=True)
    mg.write_text(
        "<Multigamer><TargetMarket>Jamaica</TargetMarket>"
        "<CultureName>en-JM</CultureName></Multigamer>",
        encoding="utf-8",
    )
    readings = probe_tree(tmp_path, expected=None)
    assert readings["locale.target_market"].present
    assert readings["locale.target_market"].value == "Jamaica"
    assert readings["locale.culture_name"].present
    assert readings["locale.culture_name"].value == "en-JM"
    assert readings["locale.target_market"].state != SettingState.ABSENT


def test_leaf_country_match_is_not_substring() -> None:
    mexico = JurisdictionProfile(id="mx", label="Mexico", country="Mexico")
    assert leaf_matches_profile_country("Mexico", mexico) is True
    assert leaf_matches_profile_country("NewMexico", mexico) is False
    us = JurisdictionProfile(id="us", label="US", country="US")
    assert leaf_matches_profile_country("Australia", us) is False
    assert leaf_matches_profile_country("", mexico) is False
    tri = next(p for p in load_jurisdictions() if p.id == "trinidad_ttd")
    assert leaf_matches_profile_country("Trinidad", tri) is True
    assert leaf_matches_profile_country("Trinidad 92-94", tri) is True
    sa = next(p for p in load_jurisdictions() if p.id == "south_africa_zar")
    assert leaf_matches_profile_country("South Africa 94", sa) is True


def test_recipe_keeps_full_credit_table_when_denom_subset() -> None:
    tri = next(p for p in load_jurisdictions() if p.id == "trinidad_ttd")
    recipe = recipe_from_jurisdiction_profile(
        tri, denom=10, denomination_list=[2, 5, 10]
    )
    assert recipe.denomination_list == [10, 2, 5]
    assert recipe.credit_rate_values[0] == 10
    assert set(tri.allowed_denoms).issubset(set(recipe.credit_rate_values))
    assert len(recipe.credit_rate_values) == len(tri.allowed_denoms)


def test_normalize_goldclub_path_rejects_escape(tmp_path: Path) -> None:
    (tmp_path / "slot").mkdir()
    with pytest.raises(ValueError):
        _normalize_goldclub_path("c:/Goldclub/../Windows/System32", tmp_path)
    with pytest.raises(ValueError):
        _normalize_goldclub_path("C:/Windows/System32/foo.xml", tmp_path)


def test_invalid_write_scope_raises() -> None:
    with pytest.raises(ValueError):
        path_matches_write_scope("config/setup.xml", "not_a_scope")
    assert path_matches_write_scope("config/setup.xml", WriteScope.FULL) is True


def test_save_json_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    save_json(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    assert not path.with_name("manifest.json.tmp").exists()


def test_live_licence_ignores_junk_files(tmp_path: Path) -> None:
    licenses = tmp_path / "Licenses"
    licenses.mkdir()
    (licenses / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")
    (licenses / "readme.txt").write_text("no", encoding="utf-8")
    assert live_has_licence(tmp_path) is False
    assert is_licence_filename("desktop.ini") is False
    assert is_licence_filename("Licence12-12262688.xml") is True
    assert is_licence_filename("37A55022DCBEF351AE27471D181B1EF5.xml") is True


def test_rollback_pre_write_restores_bytes(tmp_path: Path) -> None:
    dest = tmp_path / "goldclub"
    live = dest / "slot" / "themes" / "mgconfig.xml"
    live.parent.mkdir(parents=True)
    live.write_text("<live/>", encoding="utf-8")
    manifest = Manifest(
        scanned_at="t",
        file_count=1,
        elapsed_seconds=0,
        files=[
            FileEntry(
                relative_path="slot/themes/mgconfig.xml",
                sha1="A" * 40,
                size_bytes=7,
                last_write_utc="t",
            ),
        ],
    )
    pre = capture_pre_write_state(
        dest, manifest, allowed_paths={"slot/themes/mgconfig.xml"}
    )
    live.write_text("<new/>", encoding="utf-8")
    errors = rollback_pre_write_state(
        dest, ("slot/themes/mgconfig.xml",), pre
    )
    assert errors == []
    assert live.read_text(encoding="utf-8") == "<live/>"


def test_finance_stamp_remote_without_clock_is_not_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    from roulette_trial import finance_stamp_mismatches_clock

    monkeypatch.setattr(
        "roulette_trial.finance_stamp_unix",
        lambda _d: 1_754_784_000,
    )
    monkeypatch.setattr(
        "roulette_trial._clock_for_dest",
        lambda _d: None,
    )
    assert finance_stamp_mismatches_clock(tmp_path) is False


def test_patch_aurum_rewrites_every_host_block(tmp_path: Path) -> None:
    from config_scanner.slot_setup import (
        AurumIdentitySettings,
        patch_aurum_setup_placeholders,
    )

    src = tmp_path / "AurumSetup.xml"
    src.write_text(
        """<AurumSetup>
  <Network><NetworkHostName>GST20664</NetworkHostName>
  <ServiceURI>net.tcp://GST20664:50011</ServiceURI>
  <MessengerURI>net.tcp://GST20664:50010</MessengerURI></Network>
  <Network><NetworkHostName>GST22377</NetworkHostName>
  <ServiceURI>net.tcp://GST22377:50011</ServiceURI>
  <MessengerURI>net.tcp://GST22377:50010</MessengerURI></Network>
</AurumSetup>""",
        encoding="utf-8",
    )
    dest = tmp_path / "out.xml"
    patch_aurum_setup_placeholders(
        src, dest, AurumIdentitySettings(network_hostname_template="GST22377")
    )
    text = dest.read_text(encoding="utf-8")
    assert "GST20664" not in text
    assert text.count("GST22377") >= 4
