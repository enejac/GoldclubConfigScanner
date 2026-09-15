"""Slot licence rollback capture, compare, and explicit restore."""

from __future__ import annotations

import json
from pathlib import Path

from config_scanner.scanner import FileEntry, Manifest, archive_manifest_files, save_json
from config_scanner.service import ConfigScannerService
from config_scanner.slot_licence import (
    ROLLBACK_LICENCE_MANIFEST,
    capture_licence_state_for_rollback,
    compare_slot_licence_between_snapshots,
    has_rollback_licence_state,
    restore_slot_licence_from_snapshot,
    rollback_licence_dir,
)


def _write_slot_licence(root: Path, *, dll_size: int = 4096, xml_suffix: str = "A") -> None:
    lic_dir = root / "Licenses"
    lic_dir.mkdir(parents=True)
    (lic_dir / f"Licence12-12262688_447_24234_{xml_suffix}.xml").write_text(
        "<Licence><SerialNumber>20664</SerialNumber>"
        "<LicenseeId>12-12262688</LicenseeId></Licence>",
        encoding="utf-8",
    )
    slot = root / "slot"
    slot.mkdir(parents=True)
    (slot / "licence.dll").write_bytes(b"x" * dll_size)


def _write_build_info(snap_dir: Path, *, serial: str = "GST20664") -> None:
    (snap_dir / "build-info.json").write_text(
        json.dumps(
            {
                "buildNumber": "98170458",
                "scanTimestamp": "2026-08-27T09:07:40",
                "gameDrive": str(snap_dir),
                "profileId": "slot_lab_90",
                "profileLabel": "Slot",
                "machineSerial": serial,
            }
        ),
        encoding="utf-8",
    )


def test_capture_rollback_licence_on_scan(tmp_path: Path) -> None:
    root = tmp_path / "goldclub"
    _write_slot_licence(root)
    snap_dir = tmp_path / "snap"
    notes = capture_licence_state_for_rollback(root, snap_dir)
    assert has_rollback_licence_state(snap_dir)
    assert any("captured licence" in n for n in notes)
    manifest = json.loads(
        (rollback_licence_dir(snap_dir) / ROLLBACK_LICENCE_MANIFEST).read_text(
            encoding="utf-8"
        )
    )
    rels = {str(item["rel"]) for item in manifest["paths"]}
    assert "slot/licence.dll" in rels
    assert any(r.startswith("Licenses/") for r in rels)


def test_capture_rollback_licence_keeps_one_xml_location(tmp_path: Path) -> None:
    root = tmp_path / "goldclub"
    _write_slot_licence(root)
    name = "Licence12-12262688_447_24234_A.xml"
    body = (root / "Licenses" / name).read_text(encoding="utf-8")
    (root / name).write_text(body, encoding="utf-8")
    (root / "slot" / name).write_text(body, encoding="utf-8")
    (root / "licence.dll").write_bytes(b"y" * 4096)
    snap_dir = tmp_path / "snap-one"
    capture_licence_state_for_rollback(root, snap_dir)
    manifest = json.loads(
        (rollback_licence_dir(snap_dir) / ROLLBACK_LICENCE_MANIFEST).read_text(
            encoding="utf-8"
        )
    )
    rels = {str(item["rel"]) for item in manifest["paths"]}
    assert f"Licenses/{name}" in rels
    assert name not in rels
    assert f"slot/{name}" not in rels
    assert "slot/licence.dll" in rels
    assert "licence.dll" not in rels


def test_compare_detects_licence_dll_change(tmp_path: Path) -> None:
    baseline_gc = tmp_path / "baseline_gc"
    target_gc = tmp_path / "target_gc"
    _write_slot_licence(baseline_gc, dll_size=4096, xml_suffix="good")
    _write_slot_licence(target_gc, dll_size=12288, xml_suffix="bad")
    baseline = tmp_path / "baseline"
    target = tmp_path / "target"
    xml_rel = "Licenses/Licence12-12262688_447_24234_good.xml"
    for snap_dir, gc, dll_size in (
        (baseline, baseline_gc, 4096),
        (target, target_gc, 12288),
    ):
        capture_licence_state_for_rollback(gc, snap_dir)
        _write_build_info(snap_dir)
        manifest = Manifest(
            scanned_at="t",
            file_count=2,
            elapsed_seconds=0.1,
            files=[
                FileEntry("slot/licence.dll", "a", dll_size, "t"),
                FileEntry(xml_rel, "b", 100, "t"),
            ],
        )
        archive_manifest_files(
            str(gc),
            manifest,
            snap_dir,
            content_overrides={
                "slot/licence.dll": (gc / "slot" / "licence.dll").read_bytes(),
                xml_rel: next(gc.glob("Licenses/*.xml")).read_bytes(),
            },
        )

    result = compare_slot_licence_between_snapshots(baseline, target)
    assert result.changed
    assert any(c.relative_path == "slot/licence.dll" for c in result.changes)
    assert any("Slot licence changed" in w for w in result.warnings)


def test_restore_overwrites_live_licence(tmp_path: Path) -> None:
    live = tmp_path / "live"
    _write_slot_licence(live, dll_size=12288, xml_suffix="wrong")
    snap = tmp_path / "snap"
    _write_slot_licence(snap, dll_size=4096, xml_suffix="good")
    capture_licence_state_for_rollback(snap, snap)
    _write_build_info(snap)

    notes = restore_slot_licence_from_snapshot(
        live,
        snap,
        live_serial="GST20664",
        snapshot_serial="GST20664",
    )
    assert any(n.startswith("restored slot/licence.dll") for n in notes)
    assert (live / "slot" / "licence.dll").stat().st_size == 4096


def test_service_run_scan_captures_rollback_licence(tmp_path: Path) -> None:
    slot_root = tmp_path / "slot"
    slot_root.mkdir()
    (slot_root / "OneHand.exe").write_bytes(b"MZ")
    (slot_root / "game-start.exe").write_bytes(b"start")
    (slot_root / "GoldClub.Settings.dll").write_bytes(b"dll")
    _write_slot_licence(slot_root)
    (slot_root / "mgconfig.xml").write_text("<m/>", encoding="utf-8")

    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    (tool_root / "config.json").write_text(
        json.dumps(
            {
                "gameDrive": str(slot_root),
                "buildVersionRelativePath": "ruleta/BuildVersion.txt",
                "scanRoots": ["."],
                "includePatterns": ["*.xml"],
                "parallelWorkers": 1,
                "snapshotsDir": "snapshots",
                "reportsDir": "reports",
            }
        ),
        encoding="utf-8",
    )
    service = ConfigScannerService(tool_root, profile_id="slot_lab_90")
    result = service.run_scan(str(slot_root), snapshot_tag="prelicence")
    assert has_rollback_licence_state(result.snapshot_path)


def test_compare_warnings_includes_licence_change(tmp_path: Path) -> None:
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    (tool_root / "config.json").write_text(
        json.dumps(
            {
                "gameDrive": "C:\\Goldclub",
                "scanRoots": ["."],
                "includePatterns": ["*.xml"],
                "parallelWorkers": 1,
                "snapshotsDir": "snapshots",
                "reportsDir": "reports",
            }
        ),
        encoding="utf-8",
    )
    snap_root = tool_root / "snapshots"
    base = snap_root / "base_snap"
    tgt = snap_root / "tgt_snap"
    for name, snap_dir, dll_size in (
        ("base_snap", base, 4096),
        ("tgt_snap", tgt, 8192),
    ):
        gc = tmp_path / name
        _write_slot_licence(gc, dll_size=dll_size)
        capture_licence_state_for_rollback(gc, snap_dir)
        _write_build_info(snap_dir)
        manifest = Manifest(
            scanned_at="t",
            file_count=1,
            elapsed_seconds=0.1,
            files=[FileEntry("slot/licence.dll", "a", dll_size, "t")],
        )
        archive_manifest_files(
            str(gc),
            manifest,
            snap_dir,
            content_overrides={
                "slot/licence.dll": (gc / "slot" / "licence.dll").read_bytes(),
            },
        )
        from config_scanner.scanner import manifest_to_dict

        save_json(snap_dir / "manifest.json", manifest_to_dict(manifest))

    service = ConfigScannerService(tool_root, profile_id="slot_lab_90")
    warnings = service.compare_warnings("base_snap", "tgt_snap")
    assert any("Slot licence changed" in w for w in warnings)


def test_inspect_live_licences_detects_licenses_dir_only(tmp_path: Path) -> None:
    from config_scanner.slot_licence import inspect_live_licences

    root = tmp_path / "goldclub"
    (root / "slot").mkdir(parents=True)
    (root / "Licenses").mkdir()
    (root / "Licenses" / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence><SerialNumber>20664</SerialNumber></Licence>",
        encoding="utf-8",
    )
    status = inspect_live_licences(root)
    assert status.playable is False
    assert status.needs_push is True
    assert status.can_mirror is True
    assert any("Licence12" in name for name in status.licenses_dir_xml)


def test_inspect_live_licences_playable_next_to_onehand(tmp_path: Path) -> None:
    from config_scanner.slot_licence import inspect_live_licences

    root = tmp_path / "goldclub"
    slot = root / "slot"
    slot.mkdir(parents=True)
    (slot / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence/>", encoding="utf-8"
    )
    (slot / "licence.dll").write_bytes(b"x" * 64)
    status = inspect_live_licences(root)
    assert status.playable is True
    assert status.needs_push is False
    assert "slot/Licence12-12262688_447_24234.xml" in status.playable_xml


def test_push_missing_licences_mirrors_into_slot(tmp_path: Path) -> None:
    from config_scanner.slot_licence import inspect_live_licences, push_missing_licences

    root = tmp_path / "goldclub"
    (root / "slot").mkdir(parents=True)
    (root / "Licenses").mkdir()
    xml = root / "Licenses" / "Licence12-12262688_447_24234.xml"
    xml.write_text("<Licence><SerialNumber>20664</SerialNumber></Licence>", encoding="utf-8")
    (root / "licence.dll").write_bytes(b"x" * 128)
    written, skipped, errors = push_missing_licences(root)
    assert not errors
    assert "slot/Licence12-12262688_447_24234.xml" in written
    assert "slot/licence.dll" in written
    assert (root / "slot" / "Licence12-12262688_447_24234.xml").is_file()
    assert (root / "slot" / "licence.dll").read_bytes() == b"x" * 128
    assert inspect_live_licences(root).playable is True
    again, skipped2, errors2 = push_missing_licences(root)
    assert not errors2
    assert not again
    assert any("already present" in s for s in skipped2)


def test_push_missing_licences_from_pack_does_not_overwrite(tmp_path: Path) -> None:
    from config_scanner.slot_licence import push_missing_licences

    dest = tmp_path / "goldclub"
    (dest / "slot").mkdir(parents=True)
    (dest / "slot" / "Licence12-keep.xml").write_text("<live/>", encoding="utf-8")
    (dest / "slot" / "licence.dll").write_bytes(b"live-dll")
    pack = tmp_path / "Licences_SlotQA" / "Content" / "tmp"
    (pack / "Licenses").mkdir(parents=True)
    (pack / "Licenses" / "Licence12-keep.xml").write_text("<pack/>", encoding="utf-8")
    (pack / "Licenses" / "Licence12-new.xml").write_text("<new/>", encoding="utf-8")
    (pack / "slot").mkdir()
    (pack / "slot" / "licence.dll").write_bytes(b"pack-dll")
    written, skipped, errors = push_missing_licences(dest, source=pack.parent.parent)
    assert not errors
    # playable already — helper no-ops rather than adding a second XML
    assert not written
    assert (dest / "slot" / "Licence12-keep.xml").read_text(encoding="utf-8") == "<live/>"
    assert (dest / "slot" / "licence.dll").read_bytes() == b"live-dll"


def test_push_missing_licences_from_pack_when_dest_empty(tmp_path: Path) -> None:
    from config_scanner.slot_licence import push_missing_licences

    dest = tmp_path / "goldclub"
    (dest / "slot").mkdir(parents=True)
    pack = tmp_path / "pack" / "Content" / "tmp"
    (pack / "Licenses").mkdir(parents=True)
    (pack / "Licenses" / "Licence12-12262688_447_24234.xml").write_text(
        "<Licence><SerialNumber>20664</SerialNumber></Licence>",
        encoding="utf-8",
    )
    (pack / "slot").mkdir()
    (pack / "slot" / "licence.dll").write_bytes(b"pack-dll")
    written, _skipped, errors = push_missing_licences(dest, source=pack.parent.parent)
    assert not errors
    assert "slot/Licence12-12262688_447_24234.xml" in written
    assert "slot/licence.dll" in written
    assert (dest / "slot" / "licence.dll").read_bytes() == b"pack-dll"
    assert not (dest / "licence.dll").exists()


def _write_pack_xml(folder: Path, name: str = "Licence12-12262688_447_24234.xml") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(
        "<Licence><SerialNumber>20664</SerialNumber></Licence>",
        encoding="utf-8",
    )
    return path


def test_discover_preferred_licence_pack_prefers_usb_over_embedded(
    tmp_path: Path,
) -> None:
    from config_scanner.slot_licence import discover_preferred_licence_pack

    usb = tmp_path / "usb" / "Licences_PR"
    _write_pack_xml(usb / "Licenses")
    (usb / "slot").mkdir(parents=True)
    (usb / "slot" / "licence.dll").write_bytes(b"usb-dll")
    embedded = tmp_path / "exe" / "Licenses"
    _write_pack_xml(embedded, "Licence12-embedded.xml")
    dest = tmp_path / "goldclub"
    dest.mkdir()
    hit = discover_preferred_licence_pack(
        skip_roots=(dest,),
        usb_roots=(usb,),
        embedded_roots=(embedded,),
    )
    assert hit is not None
    assert hit.origin == "usb"
    assert hit.root == usb
    assert any(name.endswith(".xml") for name in hit.files)


def test_discover_preferred_licence_pack_falls_back_to_embedded(
    tmp_path: Path,
) -> None:
    from config_scanner.slot_licence import discover_preferred_licence_pack

    empty_usb = tmp_path / "usb"
    empty_usb.mkdir()
    embedded = tmp_path / "ConfigScanner" / "Licenses"
    _write_pack_xml(embedded)
    (embedded.parent / "licence.dll").write_bytes(b"tool-dll")
    hit = discover_preferred_licence_pack(
        skip_roots=(),
        usb_roots=(empty_usb,),
        embedded_roots=(embedded.parent,),
    )
    assert hit is not None
    assert hit.origin == "usb"
    assert "Licence12-12262688_447_24234.xml" in hit.files


def test_discover_preferred_licence_pack_skips_live_cabinet(
    tmp_path: Path,
) -> None:
    from config_scanner.slot_licence import discover_preferred_licence_pack

    dest = tmp_path / "goldclub"
    _write_pack_xml(dest / "Licenses")
    hit = discover_preferred_licence_pack(
        skip_roots=(dest,),
        usb_roots=(dest, dest / "Licenses"),
        embedded_roots=(),
    )
    assert hit is None


def test_is_licence_folder_name_accepts_misspellings() -> None:
    from config_scanner.slot_licence import is_licence_folder_name

    assert is_licence_folder_name("Licenses")
    assert is_licence_folder_name("Licences")
    assert is_licence_folder_name("licence")
    assert is_licence_folder_name("Lisence")
    assert is_licence_folder_name("liscence")
    assert is_licence_folder_name("Licences_PR")
    assert not is_licence_folder_name("slot")
    assert not is_licence_folder_name("themes")


def test_inspect_live_licences_finds_misspelled_licence_folder(tmp_path: Path) -> None:
    from config_scanner.slot_licence import inspect_live_licences

    root = tmp_path / "goldclub"
    (root / "slot").mkdir(parents=True)
    _write_pack_xml(root / "licence")
    status = inspect_live_licences(root)
    assert status.playable is False
    assert status.needs_push is True
    assert status.can_mirror is True
    assert any("licence/" in name.replace("\\", "/") for name in status.licenses_dir_xml)


def test_discover_preferred_licence_pack_finds_misspelled_usb_folder(
    tmp_path: Path,
) -> None:
    from config_scanner.slot_licence import (
        discover_preferred_licence_pack,
        licence_layout_candidates,
    )

    stick = tmp_path / "stick"
    _write_pack_xml(stick / "Lisence")
    hit = discover_preferred_licence_pack(
        skip_roots=(),
        usb_roots=licence_layout_candidates(stick),
        embedded_roots=(),
    )
    assert hit is not None
    assert hit.root in (stick / "Lisence", stick)
    assert any(name.endswith(".xml") for name in hit.files)


def test_usb_share_licence_roots_lists_usb_and_named_pack() -> None:
    from config_scanner.slot_licence import (
        DEFAULT_LICENCE_USB_HOST,
        usb_share_licence_roots,
    )

    roots = usb_share_licence_roots(DEFAULT_LICENCE_USB_HOST)
    texts = [str(p).replace("/", "\\").rstrip("\\") for p in roots]
    assert any(t.endswith(r"10.0.0.111\USB") for t in texts)
    assert any(t.endswith(r"10.0.0.111\USB\Licences_SlotQA_01") for t in texts)
    assert any(r"10.0.0.111\USB_Remote" in t for t in texts)
    assert usb_share_licence_roots("") == []
    assert usb_share_licence_roots(r"10.0.0.111\USB") == []


def test_default_usb_licence_roots_includes_lab_and_extra_hosts() -> None:
    from config_scanner.slot_licence import default_usb_licence_roots

    roots = default_usb_licence_roots(extra_hosts=("10.0.0.171",))
    texts = [str(p).replace("/", "\\") for p in roots]
    assert any("10.0.0.111" in t and "Licences_SlotQA_01" in t for t in texts)
    assert any("10.0.0.171" in t and "Licenses" in t for t in texts)


def test_discover_preferred_licence_pack_from_cabinet_usb_share(
    tmp_path: Path,
) -> None:
    from config_scanner.slot_licence import discover_preferred_licence_pack

    stick = tmp_path / "USB" / "Licences_SlotQA_01"
    _write_pack_xml(stick / "Licenses")
    (stick / "slot").mkdir(parents=True)
    (stick / "slot" / "licence.dll").write_bytes(b"usb-dll")
    dest = tmp_path / "goldclub"
    dest.mkdir()
    hit = discover_preferred_licence_pack(
        skip_roots=(dest,),
        usb_roots=[stick, stick / "Licenses", stick / "slot"],
        embedded_roots=(),
    )
    assert hit is not None
    assert hit.root in (stick, stick / "Licenses")
    assert "Licence12-12262688_447_24234.xml" in hit.files
    assert "licence.dll" in hit.files


def test_push_missing_licences_from_usb_when_egm_empty(tmp_path: Path) -> None:
    from config_scanner.slot_licence import (
        inspect_live_licences,
        push_missing_licences,
    )

    dest = tmp_path / "goldclub"
    (dest / "slot").mkdir(parents=True)
    pack = tmp_path / "Licences_SlotQA_01"
    _write_pack_xml(pack / "Licenses")
    (pack / "slot").mkdir(parents=True)
    (pack / "slot" / "licence.dll").write_bytes(b"from-usb")
    status = inspect_live_licences(dest)
    assert status.needs_push is True
    assert status.playable is False
    written, _skipped, errors = push_missing_licences(dest, source=pack)
    assert not errors
    assert "slot/Licence12-12262688_447_24234.xml" in written
    assert "slot/licence.dll" in written
    assert (dest / "slot" / "licence.dll").read_bytes() == b"from-usb"
    assert inspect_live_licences(dest).needs_push is False

