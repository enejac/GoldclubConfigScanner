"""Cabinet repair registry: diagnose, repair, gating and script contracts.

Faults documented in docs/cabinet-repairs.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_scanner import cabinet_repairs as cr

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_SECURITY = REPO_ROOT / "cabinet_tools" / "shared" / "platform-security"


# ---------------------------------------------------------------- fixtures


def _slot_tree(tmp_path: Path) -> Path:
    """Minimal Goldclub tree: OneHand in slot\\, licence pack only in Licenses\\."""
    root = tmp_path / "Goldclub"
    (root / "slot").mkdir(parents=True)
    (root / "Licenses").mkdir(parents=True)
    (root / "slot" / "OneHand.exe").write_bytes(b"MZ")
    (root / "Licenses" / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence/>", encoding="utf-8"
    )
    return root


def _ctx(root: Path, *, game_kind: str = "slot", host: str | None = None) -> cr.RepairContext:
    return cr.RepairContext(
        scan_target=str(root),
        goldclub_root=root,
        game_kind=game_kind,
        host=host,
    )


# ---------------------------------------------------------- licence placement


def test_licence_diagnose_flags_pack_installed_only_in_licenses_dir(tmp_path):
    root = _slot_tree(tmp_path)
    finding = cr._diagnose_slot_licence(_ctx(root))
    assert finding.status == cr.STATUS_BROKEN
    # The whole point: OneHand.exe reads licences next to itself.
    assert "slot/" in finding.detail


def test_licence_repair_mirrors_into_slot_and_root(tmp_path):
    root = _slot_tree(tmp_path)
    outcome = cr._repair_slot_licence(_ctx(root))
    assert outcome.ok, outcome.detail
    name = "Licence12-12262688_447_24234.xml"
    assert (root / "slot" / name).is_file()
    assert (root / name).is_file()
    # Idempotent: a second pass has nothing left to do.
    assert cr._diagnose_slot_licence(_ctx(root)).status == cr.STATUS_OK


def test_licence_repair_copies_licence_dll_next_to_onehand(tmp_path):
    root = _slot_tree(tmp_path)
    (root / "licence.dll").write_bytes(b"\x00" * 4096)
    cr._repair_slot_licence(_ctx(root))
    assert (root / "slot" / "licence.dll").is_file()


def test_licence_dll_is_not_wanted_at_the_game_root(tmp_path):
    # A healthy cabinet keeps the WIBU stub only beside OneHand.exe; demanding a
    # root copy made the check fire on a machine that was already correct.
    root = _slot_tree(tmp_path)
    (root / "slot" / "licence.dll").write_bytes(b"\x00" * 4096)
    cr._repair_slot_licence(_ctx(root))
    assert not (root / "licence.dll").exists()
    assert cr._diagnose_slot_licence(_ctx(root)).status == cr.STATUS_OK


def test_licence_repair_prefers_slot_over_stale_root(tmp_path):
    root = _slot_tree(tmp_path)
    name = "Licence12-12262688_447_24234.xml"
    (root / name).write_text("<Licence>stale-root</Licence>", encoding="utf-8")
    (root / "slot" / name).write_text("<Licence>slot-good</Licence>", encoding="utf-8")
    outcome = cr._repair_slot_licence(_ctx(root))
    assert outcome.ok, outcome.detail
    assert (root / "slot" / name).read_text(encoding="utf-8") == "<Licence>slot-good</Licence>"
    assert (root / name).read_text(encoding="utf-8") == "<Licence>slot-good</Licence>"


def test_licence_repair_never_deletes_the_original(tmp_path):
    root = _slot_tree(tmp_path)
    src = root / "Licenses" / "Licence12-12262688_447_24234.xml"
    cr._repair_slot_licence(_ctx(root))
    assert src.is_file()


def test_licence_diagnose_is_unknown_when_no_licence_exists(tmp_path):
    root = tmp_path / "Goldclub"
    (root / "slot").mkdir(parents=True)
    assert cr._diagnose_slot_licence(_ctx(root)).status == cr.STATUS_UNKNOWN


def test_hash_named_aurum_licence_is_treated_as_a_licence():
    assert cr._is_licence_xml("8" * 63 + "A.xml")
    assert cr._is_licence_xml("Licence12-12262688_447_24234.xml")
    assert not cr._is_licence_xml("mgconfig.xml")


# ------------------------------------------------------------ aurum hostname


_AURUM_XML = """<?xml version="1.0"?>
<AurumSetup>
  <Network>
    <NetworkHostName>GST20664</NetworkHostName>
    <ServiceURI>net.tcp://GST20664:50011/aurum</ServiceURI>
    <MessengerURI>net.tcp://GST20664:50010/msg</MessengerURI>
  </Network>
  <EGM id="GCC_ST_20664_01" CabinetSerialNumber="20664" />
</AurumSetup>
"""


def _aurum_tree(tmp_path: Path) -> Path:
    root = tmp_path / "Goldclub"
    cfg = root / "services" / "aurum" / "config"
    cfg.mkdir(parents=True)
    (cfg / "AurumSetup.xml").write_text(_AURUM_XML, encoding="utf-8")
    return root


def test_aurum_diagnose_flags_hostname_mismatch(tmp_path, monkeypatch):
    root = _aurum_tree(tmp_path)
    monkeypatch.setattr(cr, "_cabinet_machine_name", lambda ctx: "GST22377")
    finding = cr._diagnose_aurum_hostname(_ctx(root))
    assert finding.status == cr.STATUS_BROKEN
    assert "GST22377" in finding.detail and "GST20664" in finding.detail


def test_aurum_diagnose_ok_when_block_matches(tmp_path, monkeypatch):
    root = _aurum_tree(tmp_path)
    monkeypatch.setattr(cr, "_cabinet_machine_name", lambda ctx: "GST20664")
    assert cr._diagnose_aurum_hostname(_ctx(root)).status == cr.STATUS_OK


def test_aurum_repair_rewrites_hosts_but_keeps_egm_identity(tmp_path, monkeypatch):
    root = _aurum_tree(tmp_path)
    monkeypatch.setattr(cr, "_cabinet_machine_name", lambda ctx: "GST22377")
    outcome = cr._repair_aurum_hostname(_ctx(root))
    assert outcome.ok, outcome.detail

    text = (root / "services" / "aurum" / "config" / "AurumSetup.xml").read_text(
        encoding="utf-8"
    )
    assert "<NetworkHostName>GST22377</NetworkHostName>" in text
    assert "net.tcp://GST22377:50011/aurum" in text
    # Licensing identity must survive: it is not a networking token.
    assert 'id="GCC_ST_20664_01"' in text
    assert 'CabinetSerialNumber="20664"' in text


def test_aurum_repair_writes_a_backup(tmp_path, monkeypatch):
    root = _aurum_tree(tmp_path)
    monkeypatch.setattr(cr, "_cabinet_machine_name", lambda ctx: "GST22377")
    cr._repair_aurum_hostname(_ctx(root))
    backup = root / "services" / "aurum" / "config" / "AurumSetup.xml.bak-host-GST20664"
    assert backup.is_file()
    assert "GST20664" in backup.read_text(encoding="utf-8")


def test_find_aurum_setup_xml_accepts_services_casing(tmp_path):
    root = tmp_path / "Goldclub"
    cfg = root / "Services" / "aurum" / "config"
    cfg.mkdir(parents=True)
    (cfg / "AurumSetup.xml").write_text(_AURUM_XML, encoding="utf-8")
    found = cr.find_aurum_setup_xml(root)
    assert found is not None
    assert found.is_file()
    changed, detail = cr.rewrite_aurum_host_tokens(found, "GST22377")
    assert changed, detail
    assert "GST22377" in found.read_text(encoding="utf-8")


def test_aurum_diagnose_not_applicable_without_config(tmp_path):
    root = tmp_path / "Goldclub"
    root.mkdir()
    finding = cr._diagnose_aurum_hostname(_ctx(root))
    assert finding.status == cr.STATUS_NOT_APPLICABLE


# ------------------------------------------------------------------ MUX / SAS


def _mux_probe_values(**overrides) -> dict[str, str]:
    values = {
        "NODES": "6",
        "GHOSTS": "5",
        "LIVE_PORT": "COM14",
        "LIVE_NAME": "USB Serial Device (COM14)",
        "ACTIVE_PORT": "COM14",
        "SAS_LISTENING": "False",
    }
    values.update({k: str(v) for k, v in overrides.items()})
    return values


def test_mux_diagnose_flags_ghosts_and_wrong_port(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "run_probe", lambda ctx, script, **kw: _mux_probe_values())
    finding = cr._diagnose_mux_sas(_ctx(tmp_path, host="10.0.0.111"))
    assert finding.status == cr.STATUS_BROKEN
    assert "COM14" in finding.detail
    assert "31100" in finding.detail


def test_mux_diagnose_ok_when_on_com11_and_listening(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cr,
        "run_probe",
        lambda ctx, script, **kw: _mux_probe_values(
            GHOSTS=0, ACTIVE_PORT="COM11", SAS_LISTENING="True"
        ),
    )
    assert cr._diagnose_mux_sas(_ctx(tmp_path, host="10.0.0.111")).status == cr.STATUS_OK


def test_mux_diagnose_not_applicable_without_the_board(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cr, "run_probe", lambda ctx, script, **kw: _mux_probe_values(NODES=0, GHOSTS=0)
    )
    finding = cr._diagnose_mux_sas(_ctx(tmp_path, host="10.0.0.111"))
    assert finding.status == cr.STATUS_NOT_APPLICABLE


def test_mux_repair_stages_scripts_then_runs_the_repair(tmp_path, monkeypatch):
    staged: list[tuple] = []
    monkeypatch.setattr(
        cr,
        "stage_platform_security_scripts",
        lambda ctx, names=None: staged.append(tuple(names or ())) or list(names or []),
    )
    monkeypatch.setattr(
        cr,
        "run_cabinet_script",
        lambda ctx, name, **kw: (
            0,
            "ACTIVE_PORT=COM11\nSAS_LISTENING=True\nRESULT=OK\n",
        ),
    )
    outcome = cr._repair_mux_sas(_ctx(tmp_path, host="10.0.0.111"))
    assert outcome.ok, outcome.detail
    assert "Repair-MuxSasPort.ps1" in staged[0]
    # The ghost cleaner must ship alongside; the repair calls it.
    assert "Clear-MuxGhostPorts.ps1" in staged[0]


def test_mux_repair_reports_when_a_reboot_is_still_needed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cr, "stage_platform_security_scripts", lambda ctx, names=None: list(names or [])
    )
    monkeypatch.setattr(
        cr,
        "run_cabinet_script",
        lambda ctx, name, **kw: (6, "ACTIVE_PORT=COM14\nRESULT=PORT_NOT_APPLIED\n"),
    )
    outcome = cr._repair_mux_sas(_ctx(tmp_path, host="10.0.0.111"))
    assert not outcome.ok
    assert "reboot" in outcome.detail.casefold()


# ---------------------------------------------------------------- boot tasks


def test_boot_tasks_diagnose_flags_missing_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cr,
        "run_probe",
        lambda ctx, script, **kw: {
            "UNLOCK_TASK": "False",
            "MUX_TASK": "False",
            "DEVCON": "False",
        },
    )
    finding = cr._diagnose_boot_tasks(_ctx(tmp_path, host="10.0.0.111"))
    assert finding.status == cr.STATUS_BROKEN
    assert "GoldClub-Unlock-Volume" in finding.detail


def test_boot_tasks_diagnose_ok_when_both_registered_and_devcon_staged(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        cr,
        "run_probe",
        lambda ctx, script, **kw: {
            "UNLOCK_TASK": "True",
            "MUX_TASK": "True",
            "DEVCON": "True",
        },
    )
    finding = cr._diagnose_boot_tasks(_ctx(tmp_path, host="10.0.0.111"))
    assert finding.status == cr.STATUS_OK


def test_boot_tasks_diagnose_flags_missing_devcon_even_with_tasks(tmp_path, monkeypatch):
    # G: is BitLocker-locked when the MUX task runs, so devcon must be on C:.
    monkeypatch.setattr(
        cr,
        "run_probe",
        lambda ctx, script, **kw: {
            "UNLOCK_TASK": "True",
            "MUX_TASK": "True",
            "DEVCON": "False",
        },
    )
    finding = cr._diagnose_boot_tasks(_ctx(tmp_path, host="10.0.0.111"))
    assert finding.status == cr.STATUS_BROKEN
    assert "devcon" in finding.detail.casefold()


def test_boot_tasks_repair_reports_success_from_installer_output(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cr, "stage_platform_security_scripts", lambda ctx, names=None: ["x"]
    )
    monkeypatch.setattr(
        cr,
        "run_cabinet_script",
        lambda ctx, name, **kw: (0, "result: unlock=True muxGhosts=True"),
    )
    outcome = cr._repair_boot_tasks(_ctx(tmp_path, host="10.0.0.111"))
    assert outcome.ok, outcome.detail


# ------------------------------------------------------------------ ramclear


def test_ramclear_diagnose_flags_marker(tmp_path):
    root = tmp_path / "Goldclub"
    marker = root / "var" / "state" / "maintenance" / "invoke-task-ramclear"
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    finding = cr._diagnose_ramclear(_ctx(root))
    assert finding.status == cr.STATUS_BROKEN
    assert finding.destructive


def test_ramclear_diagnose_flags_trial_error_in_slot_log(tmp_path):
    root = tmp_path / "Goldclub"
    log_dir = root / "var" / "log" / "SlotLog"
    log_dir.mkdir(parents=True)
    (log_dir / "2026-08-31.log").write_text(
        "INFO something\nERRO Trial expired with trial type ErrorRegistryDataNotFound\n",
        encoding="utf-8",
    )
    assert cr._diagnose_ramclear(_ctx(root)).status == cr.STATUS_BROKEN


def test_ramclear_diagnose_ok_on_a_clean_cabinet(tmp_path):
    root = tmp_path / "Goldclub"
    (root / "var" / "log" / "SlotLog").mkdir(parents=True)
    assert cr._diagnose_ramclear(_ctx(root)).status == cr.STATUS_OK


# ------------------------------------------------------------------- registry


def test_roulette_profile_does_not_see_slot_only_repairs():
    ids = {r.id for r in cr.repairs_for("roulette")}
    assert "slot_licence_placement" not in ids
    assert "slot_ramclear_pending" not in ids
    assert "aurum_setup_hostname" not in ids
    # MUX/SAS and boot unlock are cabinet-wide, not slot-specific.
    assert "mux_sas_com_port" in ids
    assert "goldclub_boot_tasks" in ids


def test_slot_profile_sees_every_repair():
    assert {r.id for r in cr.repairs_for("slot")} == {r.id for r in cr.REPAIRS}


def test_only_ramclear_is_marked_destructive():
    destructive = {r.id for r in cr.REPAIRS if r.destructive}
    assert destructive == {"slot_ramclear_pending"}


def test_every_repair_id_is_unique_and_resolvable():
    ids = [r.id for r in cr.REPAIRS]
    assert len(ids) == len(set(ids))
    for repair_id in ids:
        assert cr.repair_by_id(repair_id) is not None


def test_apply_repairs_runs_only_what_was_asked_for(tmp_path, monkeypatch):
    called: list[str] = []

    def _fake_repair(ctx):
        called.append("licence")
        return cr.RepairOutcome("slot_licence_placement", "t", True, "done")

    monkeypatch.setattr(
        cr,
        "REPAIRS",
        (
            cr.CabinetRepair(
                id="slot_licence_placement",
                title="t",
                summary="s",
                diagnose=lambda ctx: cr.RepairFinding("slot_licence_placement", "t", cr.STATUS_OK, ""),
                repair=_fake_repair,
                game_kinds=("slot",),
            ),
            cr.CabinetRepair(
                id="other",
                title="o",
                summary="s",
                diagnose=lambda ctx: cr.RepairFinding("other", "o", cr.STATUS_OK, ""),
                repair=lambda ctx: called.append("other"),
            ),
        ),
    )
    outcomes = cr.apply_repairs(_ctx(tmp_path), ["slot_licence_placement"])
    assert called == ["licence"]
    assert len(outcomes) == 1


def test_diagnose_survives_a_check_that_raises(tmp_path, monkeypatch):
    def _boom(ctx):
        raise RuntimeError("winrm exploded")

    monkeypatch.setattr(
        cr,
        "REPAIRS",
        (
            cr.CabinetRepair(
                id="boom", title="b", summary="s", diagnose=_boom, repair=lambda ctx: None
            ),
        ),
    )
    findings = cr.diagnose_cabinet(_ctx(tmp_path))
    assert len(findings) == 1
    assert findings[0].status == cr.STATUS_UNKNOWN
    assert "winrm exploded" in findings[0].detail


def test_build_context_extracts_the_unc_host(monkeypatch):
    monkeypatch.setattr(cr, "ensure_lab_smb_credential", lambda ip: True)
    ctx = cr.build_context(r"\\10.0.0.111\slot", "slot")
    assert ctx.host == "10.0.0.111"
    assert ctx.is_remote


def test_build_context_rejects_an_empty_target():
    with pytest.raises(cr.RepairError):
        cr.build_context("", "slot")


def test_parse_kv_ignores_prose_lines():
    values = cr._parse_kv("noise = here\nACTIVE_PORT=COM11\nRESULT=OK\nrandom text")
    assert values == {"ACTIVE_PORT": "COM11", "RESULT": "OK"}


# ------------------------------------------------------- PowerShell contracts


def test_repair_script_exists_and_is_ascii_for_powershell_51():
    # No BOM, so PowerShell 5.1 reads these as ANSI: one em dash breaks the parse.
    script = PLATFORM_SECURITY / "Repair-MuxSasPort.ps1"
    assert script.is_file()
    raw = script.read_bytes()
    assert not raw.startswith(b"\xff\xfe") and not raw.startswith(b"\xfe\xff")
    bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, f"non-ASCII bytes at {bad[:5]}"


def test_repair_script_releases_the_port_before_bouncing_the_device():
    # devcon can only answer "requires reboot" while CommCtrl holds the handle.
    text = (PLATFORM_SECURITY / "Repair-MuxSasPort.ps1").read_text(encoding="ascii")
    stop_at = text.index("Stop-Service")
    disable_at = text.index("'disable'")
    assert stop_at < disable_at
    # ...and the gateways must come back up afterwards.
    assert "Start-Service" in text[disable_at:]


def test_repair_script_never_touches_the_board_port_maps():
    text = (PLATFORM_SECURITY / "Repair-MuxSasPort.ps1").read_text(encoding="ascii")
    lowered = text.casefold()
    for forbidden in ("layout.json", "locations.json", "bcdedit", "bcdboot"):
        # Only the safety comment may name them.
        code = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        ).casefold()
        assert forbidden not in code, f"{forbidden} appears in executable code"
    assert "layout.json" in lowered  # the safety note is still documented


def test_repair_script_only_targets_the_mux_hardware_id():
    text = (PLATFORM_SECURITY / "Repair-MuxSasPort.ps1").read_text(encoding="ascii")
    assert "VID_0483&PID_5740" in text


def test_bundled_scripts_are_listed_in_the_spec():
    spec = (REPO_ROOT / "ConfigScanner.spec").read_text(encoding="utf-8")
    for name in cr._PLATFORM_SECURITY_SCRIPTS:
        assert name in spec, f"{name} must ship in the exe"
        assert (PLATFORM_SECURITY / name).is_file()


def test_repair_menu_action_is_wired_in_the_tab():
    text = (REPO_ROOT / "gui" / "config_scanner_tab.py").read_text(encoding="utf-8")
    assert "_repair_cabinet_action" in text
    assert "_on_repair_cabinet_clicked" in text
    assert "CabinetRepairDialog" in text


def test_documentation_covers_every_repair_id():
    doc = (REPO_ROOT / "docs" / "cabinet-repairs.md").read_text(encoding="utf-8")
    for repair in cr.REPAIRS:
        assert repair.id in doc, f"{repair.id} is undocumented"
