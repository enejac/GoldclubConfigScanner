"""Full snapshot embeds the surgical Ruleta pack for one-click restore."""

from __future__ import annotations

import json
from pathlib import Path

from config_scanner.service import ConfigScannerService
from config_scanner.software_compat import (
    SNAPSHOT_SOFTWARE_SUBDIR,
    capture_ruleta_software_into_snapshot,
    capture_slot_software_into_snapshot,
    is_software_capture_info_note,
    resolve_software_pack_for_snapshot,
    scan_user_warnings,
    snapshot_embedded_software_dir,
    snapshot_has_embedded_software,
)
from network.software_version_swap import SOFTWARE_VERSION_FILES, preflight_source


def _minimal_pe(machine: int, payload: bytes = b"") -> bytes:
    dos = bytearray(64)
    dos[0:2] = b"MZ"
    dos[0x3C:0x40] = (64).to_bytes(4, "little")
    pe = bytearray(b"PE\x00\x00") + machine.to_bytes(2, "little") + bytes(20)
    return bytes(dos) + bytes(pe) + payload


def _write_ruleta_pack(root: Path, *, marker: bytes = b"pack") -> None:
    for _, rel in SOFTWARE_VERSION_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(marker + rel.encode("ascii", errors="ignore")[:12])


def _minimal_tool_root(tmp_path: Path) -> Path:
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    (tool_root / "config.json").write_text(
        json.dumps(
            {
                "gameDrive": None,
                "scanRoots": ["config"],
                "includePatterns": ["*.xml"],
                "parallelWorkers": 1,
                "snapshotsDir": "snapshots",
                "reportsDir": "reports",
            }
        ),
        encoding="utf-8",
    )
    (tool_root / "snapshots").mkdir()
    (tool_root / "reports").mkdir()
    (tool_root / "templates").mkdir()
    return tool_root


def _roulette_machine(tmp_path: Path) -> Path:
    root = tmp_path / "Goldclub"
    ruleta = root / "ruleta"
    _write_ruleta_pack(ruleta, marker=b"live")
    (ruleta / "BuildVersion.txt").write_text(
        "Source Version: 876\nBranch: Development\nBuild Number: 40119\n",
        encoding="utf-8",
    )
    config = root / "config"
    config.mkdir()
    (config / "setup.xml").write_text("<root/>", encoding="utf-8")
    return root


def test_capture_ruleta_software_copies_seven_files(tmp_path: Path) -> None:
    live = _roulette_machine(tmp_path)
    snap = tmp_path / "snap"
    snap.mkdir()
    result = capture_ruleta_software_into_snapshot(str(live), snap)
    assert result.captured is True
    assert result.file_count == 7
    dest = snapshot_embedded_software_dir(snap)
    assert dest is not None
    assert preflight_source(dest) == []
    exe = dest / "Ruleta.exe"
    assert exe.read_bytes().startswith(b"live")


def test_capture_includes_x64_libeay32(tmp_path: Path) -> None:
    live = _roulette_machine(tmp_path)
    (live / "ruleta" / "libeay32.dll").write_bytes(_minimal_pe(0x8664) + b"ok")
    (live / "ruleta" / "ssleay32.dll").write_bytes(_minimal_pe(0x8664) + b"ssl")
    snap = tmp_path / "snap"
    snap.mkdir()
    result = capture_ruleta_software_into_snapshot(str(live), snap)
    assert result.captured is True
    assert result.file_count == 9
    software = snap / SNAPSHOT_SOFTWARE_SUBDIR
    assert (software / "libeay32.dll").read_bytes().endswith(b"ok")
    assert (software / "ssleay32.dll").read_bytes().endswith(b"ssl")
    assert "64-bit libeay32.dll" in result.note


def test_capture_skips_x86_libeay32(tmp_path: Path) -> None:
    live = _roulette_machine(tmp_path)
    (live / "ruleta" / "libeay32.dll").write_bytes(_minimal_pe(0x14C) + b"ntp")
    snap = tmp_path / "snap"
    snap.mkdir()
    result = capture_ruleta_software_into_snapshot(str(live), snap)
    assert result.captured is True
    assert result.file_count == 7
    assert not (snap / SNAPSHOT_SOFTWARE_SUBDIR / "libeay32.dll").exists()


def test_capture_skips_licence_and_trial_files(tmp_path: Path) -> None:
    live = _roulette_machine(tmp_path)
    (live / "ruleta" / "licence.dll").write_bytes(b"dongle")
    persist = live / "ruleta" / "persistent"
    persist.mkdir()
    (persist / "RouletteActivate.dat").write_bytes(b"token")
    snap = tmp_path / "snap"
    snap.mkdir()
    capture_ruleta_software_into_snapshot(str(live), snap)
    software = snap / SNAPSHOT_SOFTWARE_SUBDIR
    assert not (software / "licence.dll").exists()
    assert not (software / "persistent" / "RouletteActivate.dat").exists()


def test_resolve_pack_prefers_embedded_over_software_versions(tmp_path: Path) -> None:
    from config_scanner.build_version import BuildInfo

    snap = tmp_path / "snap"
    embedded = snap / SNAPSHOT_SOFTWARE_SUBDIR
    _write_ruleta_pack(embedded, marker=b"snap")
    versions = tmp_path / "software_versions" / "Ruleta_v10.2.0.876_build40119"
    _write_ruleta_pack(versions, marker=b"usb")
    info = BuildInfo(
        source_version="876",
        branch="Development",
        product_version="10.2.0.876",
        build_number="40119",
        build_date=None,
        trigger=None,
        requested_by=None,
        scan_timestamp="t",
        game_drive=str(tmp_path),
        exe_product_version="10.2.0.876",
    )
    pack = resolve_software_pack_for_snapshot(
        info,
        str(tmp_path),
        snapshot_dir=snap,
        versions_dir=versions.parent,
    )
    assert pack == embedded
    assert (pack / "Ruleta.exe").read_bytes().startswith(b"snap")


def test_run_scan_include_software_embeds_pack(tmp_path: Path) -> None:
    machine = _roulette_machine(tmp_path)
    service = ConfigScannerService(_minimal_tool_root(tmp_path))
    result = service.run_scan(str(machine), include_software=True)
    assert result.software_captured is True
    assert result.software_file_count == 7
    assert snapshot_has_embedded_software(result.snapshot_path)
    listed = {row.name: row for row in service.list_snapshots()}
    assert listed[result.snapshot_name].has_software is True
    assert scan_user_warnings(result.warnings) == ()
    assert not any(
        is_software_capture_info_note(note) for note in result.warnings
    )


def test_scan_user_warnings_drop_successful_capture_note() -> None:
    notes = scan_user_warnings(
        (
            "Captured 7 Ruleta software files into the snapshot.",
            "Decrypt failed for setup.xml",
        )
    )
    assert notes == ("Decrypt failed for setup.xml",)


def test_scan_user_warnings_keep_missing_libeay_note() -> None:
    notes = scan_user_warnings(
        (
            "Captured 7 Ruleta software files into the snapshot. "
            "Ruleta.exe needs 64-bit libeay32.dll; none was next to the exe.",
        )
    )
    assert len(notes) == 1
    assert "libeay32" in notes[0]


def test_run_scan_without_software_stays_config_only(tmp_path: Path) -> None:
    machine = _roulette_machine(tmp_path)
    service = ConfigScannerService(_minimal_tool_root(tmp_path))
    result = service.run_scan(str(machine), include_software=False)
    assert result.software_captured is False
    assert snapshot_has_embedded_software(result.snapshot_path) is False


def _slot_goldclub(tmp_path: Path) -> Path:
    root = tmp_path / "Goldclub"
    slot = root / "slot"
    themes = slot / "themes" / "PR2_Foo"
    themes.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(b"MZ slot")
    (slot / "game-start.exe").write_bytes(b"MZ start")
    (slot / "GoldClub.Settings.dll").write_bytes(b"settings")
    (slot / "themes" / "mgconfig.xml").write_text(
        "<Multigamer><MachineID>GST22377</MachineID></Multigamer>\n",
        encoding="utf-8",
    )
    (themes / "game.xml").write_text("<game/>", encoding="utf-8")
    (themes / "MathSettings.xml").write_text("<math/>", encoding="utf-8")
    (themes / "PR2_FooMath.json").write_bytes(b"\x00math")
    (themes / "big.mp4").write_bytes(b"video")
    (slot / "themes" / "HardwareConfig.xml").write_text("<hwcfg/>", encoding="utf-8")
    gs = slot / "themes" / "data" / "GameStarColors" / "1080p" / "Red"
    gs.mkdir(parents=True)
    (gs / "gameselector_GSC_config.xml").write_text("<gs/>", encoding="utf-8")
    (gs / "flag.png").write_bytes(b"png")
    (slot / "hwdrivers").mkdir()
    (slot / "hwdrivers" / "device.xml").write_text("<dev/>", encoding="utf-8")
    (slot / "var").mkdir()
    (slot / "var" / "runtime.dat").write_bytes(b"runtime")
    cache = slot / "Cache"
    cache.mkdir()
    (cache / "blob.bin").write_bytes(b"cache")
    (slot / "licence.dll").write_bytes(b"wibu-slot")
    bios = root / "bios"
    (bios / "License").mkdir(parents=True)
    (bios / "etc" / "game-start").mkdir(parents=True)
    (bios / "BiOS2.exe").write_bytes(b"MZ bios")
    (bios / "License" / "License.lic").write_bytes(b"secret-lic")
    (bios / "etc" / "game-start" / "checksum.sha1").write_text("deadbeef", encoding="utf-8")
    (root / "Licenses").mkdir()
    (root / "Licenses" / "dongle.xml").write_text("<licence/>", encoding="utf-8")
    (root / "maintenance" / "config").mkdir(parents=True)
    (root / "maintenance" / "config" / "serialports.conf").write_text("COM4", encoding="utf-8")
    (root / "Bootstrap.exe").write_bytes(b"MZ boot")
    (root / "licence.dll").write_bytes(b"wibu")
    return root


def test_capture_slot_software_skips_gamepack_keeps_licence_and_hw(tmp_path: Path) -> None:
    live = _slot_goldclub(tmp_path)
    snap = tmp_path / "snap"
    snap.mkdir()
    result = capture_slot_software_into_snapshot(str(live), snap)
    assert result.captured is True
    software = snap / SNAPSHOT_SOFTWARE_SUBDIR
    assert (software / "slot" / "OneHand.exe").read_bytes().startswith(b"MZ")
    assert (software / "slot" / "hwdrivers" / "device.xml").is_file()
    assert (software / "bios" / "BiOS2.exe").is_file()
    assert (software / "Bootstrap.exe").is_file()
    assert (software / "licence.dll").read_bytes() == b"wibu"
    assert (software / "slot" / "licence.dll").read_bytes() == b"wibu-slot"
    assert (software / "Licenses" / "dongle.xml").is_file()
    assert (software / "bios" / "License" / "License.lic").is_file()
    assert (software / "slot" / "themes" / "mgconfig.xml").is_file()
    assert (software / "slot" / "themes" / "HardwareConfig.xml").is_file()
    assert (software / "slot" / "themes" / "PR2_Foo" / "MathSettings.xml").is_file()
    assert (software / "slot" / "themes" / "PR2_Foo" / "PR2_FooMath.json").is_file()
    assert (
        software
        / "slot"
        / "themes"
        / "data"
        / "GameStarColors"
        / "1080p"
        / "Red"
        / "gameselector_GSC_config.xml"
    ).is_file()
    assert (software / "bios" / "etc" / "game-start" / "checksum.sha1").is_file()
    assert (software / "maintenance" / "config" / "serialports.conf").is_file()
    assert not (software / "slot" / "themes" / "PR2_Foo" / "game.xml").exists()
    assert not (software / "slot" / "themes" / "PR2_Foo" / "big.mp4").exists()
    assert not (
        software / "slot" / "themes" / "data" / "GameStarColors" / "1080p" / "Red" / "flag.png"
    ).exists()
    assert not (software / "slot" / "var" / "runtime.dat").exists()
    assert not (software / "slot" / "Cache" / "blob.bin").exists()
    assert snapshot_has_embedded_software(snap) is True


def test_run_scan_slot_full_snapshot_prelicence_tag(tmp_path: Path) -> None:
    machine = _slot_goldclub(tmp_path)
    service = ConfigScannerService(
        _minimal_tool_root(tmp_path), profile_id="slot_lab_90"
    )
    result = service.run_scan(
        str(machine), include_software=True, snapshot_tag="prelicence"
    )
    assert result.software_captured is True
    assert result.software_file_count >= 4
    assert "prelicence" in result.snapshot_name.casefold()
    assert "GST22377" in result.snapshot_name
    assert snapshot_has_embedded_software(result.snapshot_path)
    listed = {row.name: row for row in service.list_snapshots()}
    assert listed[result.snapshot_name].has_software is True
    software = result.snapshot_path / SNAPSHOT_SOFTWARE_SUBDIR
    assert (software / "licence.dll").is_file()
    assert not (software / "slot" / "themes" / "PR2_Foo" / "game.xml").exists()
