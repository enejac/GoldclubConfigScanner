"""Slot full-snapshot restore must ignore leftover roulette artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from config_scanner.build_version import BuildInfo, match_profile_for_target
from config_scanner.dest_preflight import goldclub_dest_writable
from config_scanner.egm_ui_labels import game_kind_from_target
from config_scanner.live_push import goldclub_stack_kind
from config_scanner.profiles import load_profiles
from config_scanner.service import ConfigScannerService
from config_scanner.software_compat import (
    SNAPSHOT_SOFTWARE_SUBDIR,
    push_matching_slot_software,
    restore_uses_slot_software,
)


def _build_info(**kwargs: object) -> BuildInfo:
    base: dict[str, object] = dict(
        source_version=None,
        branch=None,
        product_version="2.1.0",
        build_number="1",
        build_date=None,
        trigger=None,
        requested_by=None,
        scan_timestamp="t",
        game_drive=r"\\10.0.0.76\slot",
        profile_id="slot_lab_90",
        profile_label="Slot lab",
        exe_product_version="2.1.0",
        exe_file_version=None,
        exe_product_name="OneHand",
        machine_serial="GST22377",
    )
    base.update(kwargs)
    return BuildInfo(**base)  # type: ignore[arg-type]


def _slot_dest_with_leftover_ruleta(tmp_path: Path) -> Path:
    dest = tmp_path / "Goldclub"
    slot = dest / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(b"MZ-old")
    (slot / "game-start.exe").write_bytes(b"MZ-start")
    (slot / "GoldClub.Settings.dll").write_bytes(b"dll")
    (slot / "themes").mkdir()
    (slot / "themes" / "mgconfig.xml").write_text("<live/>", encoding="utf-8")
    (slot / "themes" / "HardwareConfig.xml").write_text("<hw-live/>", encoding="utf-8")
    leftover = dest / "ruleta"
    leftover.mkdir()
    (leftover / "Ruleta.exe").write_bytes(b"MZ-ruleta-leftover")
    (leftover / "lib").mkdir()
    return dest


def _write_slot_full_snapshot(
    tool_root: Path,
    dest: Path,
    *,
    name: str = "s_snap",
    onehand: bytes = b"MZ-new",
    include_software: bool = True,
) -> Path:
    (tool_root / "config.json").write_text(
        json.dumps(
            {
                "gameDrive": None,
                "scanRoots": ["slot"],
                "includePatterns": ["*.xml"],
                "parallelWorkers": 1,
                "snapshotsDir": "snapshots",
                "reportsDir": "reports",
                "profileId": "slot_lab_90",
            }
        ),
        encoding="utf-8",
    )
    (tool_root / "snapshots").mkdir(exist_ok=True)
    (tool_root / "reports").mkdir(exist_ok=True)
    (tool_root / "templates").mkdir(exist_ok=True)
    snap = tool_root / "snapshots" / name
    snap.mkdir(parents=True, exist_ok=True)
    rel = "slot/themes/mgconfig.xml"
    text = "<snap/>"
    archived = snap / "files" / Path(rel)
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text(text, encoding="utf-8")
    (snap / "build-info.json").write_text(
        json.dumps(
            {
                "buildNumber": "1",
                "productVersion": "2.1.0",
                "scanTimestamp": "t",
                "gameDrive": str(dest),
                "profileId": "slot_lab_90",
                "profileLabel": "Slot lab",
                "machineSerial": "GST22377",
                "exeProductVersion": "2.1.0",
            }
        ),
        encoding="utf-8",
    )
    (snap / "manifest.json").write_text(
        json.dumps(
            {
                "fileCount": 1,
                "elapsedSeconds": 0.1,
                "files": [
                    {
                        "relativePath": rel,
                        "sha1": "AAA",
                        "sizeBytes": len(text.encode("utf-8")),
                        "lastWriteUtc": "t",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    if include_software:
        software = snap / SNAPSHOT_SOFTWARE_SUBDIR / "slot"
        software.mkdir(parents=True)
        (software / "OneHand.exe").write_bytes(onehand)
        themes = software / "themes"
        themes.mkdir()
        (themes / "mgconfig.xml").write_text("<sw-mg/>", encoding="utf-8")
        (themes / "HardwareConfig.xml").write_text("<sw-hw/>", encoding="utf-8")
    serial = dest / "var" / "state" / "maintenance" / "ProductSerialNumber.json"
    serial.parent.mkdir(parents=True, exist_ok=True)
    serial.write_text('{"MachineName":"GST22377"}', encoding="utf-8")
    return snap


def test_restore_uses_slot_software_with_leftover_ruleta(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    info = _build_info()
    assert restore_uses_slot_software(info, str(dest)) is True
    roulette = _build_info(profile_id="roulette_usb")
    assert restore_uses_slot_software(roulette, str(dest)) is True


def test_goldclub_stack_kind_onehand_wins_over_leftover_ruleta(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    assert goldclub_stack_kind(dest) == "slot"
    assert game_kind_from_target(str(dest)) == "slot"


def test_match_profile_prefers_slot_when_onehand_and_ruleta(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    profile = match_profile_for_target(str(dest), load_profiles())
    assert profile is not None
    assert profile.id == "slot_lab_90"


def test_goldclub_dest_writable_probes_slot_not_leftover_ruleta(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    ok, msg = goldclub_dest_writable(dest)
    assert ok is True
    assert msg is None
    assert not (dest / "ruleta" / ".gci_write_probe").exists()


def test_snapshot_apply_refuses_slot_full_with_leftover_ruleta(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    _write_slot_full_snapshot(tool_root, dest)
    service = ConfigScannerService(tool_root)
    refuses = service.snapshot_apply_refuses(
        "s_snap", str(dest), write_scope="full_software"
    )
    assert refuses == []


def test_snapshot_apply_refuses_slot_unc_76_skips_fleet_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    _write_slot_full_snapshot(tool_root, dest)

    from config_scanner import build_version as bv

    monkeypatch.setattr(bv, "scan_target_path", lambda _t: dest)
    monkeypatch.setattr(
        "config_scanner.dest_preflight.goldclub_dest_writable",
        lambda _root: (True, None),
    )
    monkeypatch.setattr(bv, "read_machine_serial_from_target", lambda _t: "GST22377")

    called: list[str] = []

    def _boom(host: str, dest_ruleta: Path, **_kwargs: object) -> tuple[str, ...]:
        called.append(host)
        return (f"Refusing non-fleet IP: {host}",)

    monkeypatch.setattr(
        "network.ruleta_stack_probe.preflight_remote_software_swap",
        _boom,
    )
    service = ConfigScannerService(tool_root)
    refuses = service.snapshot_apply_refuses(
        "s_snap",
        r"\\10.0.0.76\slot",
        write_scope="full_software",
    )
    assert called == []
    assert refuses == []
    assert not any("lab fleet" in item.casefold() for item in refuses)
    assert not any("Ruleta software pack" in item for item in refuses)


def test_apply_slot_full_software_does_not_write_ruleta(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    _write_slot_full_snapshot(tool_root, dest, onehand=b"MZ-restored")
    service = ConfigScannerService(tool_root)
    result = service.apply_snapshot_to_target(
        "s_snap", str(dest), write_scope="full_software"
    )
    assert result.written_count >= 1
    assert (dest / "slot" / "OneHand.exe").read_bytes() == b"MZ-restored"
    assert (dest / "ruleta" / "Ruleta.exe").read_bytes() == b"MZ-ruleta-leftover"
    assert any("slot" in note.casefold() for note in result.notes)
    assert not any("Pushed Ruleta" in note for note in result.notes)


def test_push_slot_binaries_only_keeps_hardwareconfig(tmp_path: Path) -> None:
    dest = _slot_dest_with_leftover_ruleta(tmp_path)
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    snap = _write_slot_full_snapshot(tool_root, dest, onehand=b"MZ-bin")
    note = push_matching_slot_software(
        _build_info(),
        str(dest),
        snapshot_dir=snap,
        keep_profile=True,
    )
    assert "cabinet profile kept" in note
    assert (dest / "slot" / "OneHand.exe").read_bytes() == b"MZ-bin"
    assert (dest / "slot" / "themes" / "HardwareConfig.xml").read_text(
        encoding="utf-8"
    ) == "<hw-live/>"
    assert (dest / "slot" / "themes" / "mgconfig.xml").read_text(
        encoding="utf-8"
    ) == "<live/>"


def test_roulette_dest_still_refuses_missing_ruleta_pack(tmp_path: Path) -> None:
    dest = tmp_path / "Goldclub"
    ruleta = dest / "ruleta"
    ruleta.mkdir(parents=True)
    (ruleta / "Ruleta.exe").write_bytes(b"MZ")
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    (tool_root / "config.json").write_text(
        json.dumps({"gameDrive": None, "profileId": "roulette_usb"}),
        encoding="utf-8",
    )
    snap = tool_root / "snapshots" / "r_snap"
    snap.mkdir(parents=True)
    (snap / "files" / "config").mkdir(parents=True)
    (snap / "files" / "config" / "setup.xml").write_text("<x/>", encoding="utf-8")
    (snap / "build-info.json").write_text(
        json.dumps(
            {
                "productVersion": "10.2.0.876",
                "exeProductVersion": "10.2.0.876",
                "scanTimestamp": "t",
                "gameDrive": str(dest),
                "profileId": "roulette_usb",
            }
        ),
        encoding="utf-8",
    )
    (snap / "manifest.json").write_text(
        json.dumps({"files": []}),
        encoding="utf-8",
    )
    service = ConfigScannerService(tool_root)
    refuses = service.snapshot_apply_refuses(
        "r_snap", str(dest), write_scope="full_software"
    )
    assert any("Ruleta software pack" in item for item in refuses)
