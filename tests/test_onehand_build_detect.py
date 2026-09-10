"""OneHand version + Debug/Release detection for Live Push header."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from config_scanner.build_version import (
    OneHandBuildInfo,
    _all_utf16_values_after,
    _configuration_from_strings,
    _find_onehand_exe,
    _pdb_path_is_debug_output,
    _read_pe_debug_flag,
    _read_version_resource,
    _sniff_build_configuration,
    detect_onehand_build,
    format_onehand_build_label,
    onehand_exe_is_debug_sku,
)


def _utf16_pair(key: str, value: str) -> bytes:
    return (key + "\0").encode("utf-16le") + value.encode("utf-16le") + b"\x00\x00"


def _version_info_blob(**strings: str) -> bytes:
    """Loose VS_VERSIONINFO window the resource parser accepts."""
    body = b"".join(_utf16_pair(key, value) for key, value in strings.items())
    payload = (
        "VS_VERSION_INFO".encode("utf-16le")
        + b"\x00\x00"
        + b"\xbd\x04\xef\xfe"
        + (0x00010000).to_bytes(4, "little")
        + (0x00020000).to_bytes(4, "little")  # 2.0
        + (0x00010000).to_bytes(4, "little")  # 1.0
        + b"\x00" * 8
        + (0x3F).to_bytes(4, "little")
        + (0x00).to_bytes(4, "little")  # FileFlags: no VS_FF_DEBUG
        + body
    )
    header = (len(payload) + 6).to_bytes(2, "little") + b"\x00\x00\x00\x00"
    return header + payload


def test_onehand_build_info_label() -> None:
    info = OneHandBuildInfo(version="2.0.1+RC2", configuration="Release")
    assert info.label == "OneHand 2.0.1+RC2 · Release"
    assert format_onehand_build_label(info) == info.label
    assert format_onehand_build_label(None) == ""


def test_configuration_from_strings() -> None:
    assert _configuration_from_strings("SpecialBuild: Debug") == "Debug"
    assert _configuration_from_strings("Release build") == "Release"
    assert _configuration_from_strings("Debugger helpers") is None


def test_sniff_prefers_assembly_configuration(tmp_path: Path) -> None:
    exe = tmp_path / "OneHand.exe"
    payload = "junk Debugger junk AssemblyConfiguration\x00Release more Debug"
    exe.write_bytes(b"\x00" * 64 + payload.encode("utf-16le"))
    assert _sniff_build_configuration(exe) == "Release"


def test_sniff_assembly_debug_wins_over_dependency_release(tmp_path: Path) -> None:
    exe = tmp_path / "OneHand.exe"
    payload = (
        "mscorlib Release AssemblyConfiguration\x00Debug "
        "Newtonsoft.Json Release"
    )
    exe.write_bytes(b"\x00" * 64 + payload.encode("utf-16le"))
    assert _sniff_build_configuration(exe) == "Debug"


def test_sniff_ignores_stray_release_word(tmp_path: Path) -> None:
    exe = tmp_path / "OneHand.exe"
    payload = "Debug path and Release config"
    exe.write_bytes(b"\x00" * 32 + payload.encode("utf-16le"))
    assert _sniff_build_configuration(exe) is None


def test_read_pe_debug_flag_true() -> None:
    win32 = SimpleNamespace(
        GetFileVersionInfo=lambda _path, _key: {
            "FileFlags": 0x1,
            "FileFlagsMask": 0x3F,
        }
    )
    assert _read_pe_debug_flag(win32, r"C:\fake\OneHand.exe") is True


def test_read_pe_debug_flag_unset_is_unknown() -> None:
    win32 = SimpleNamespace(
        GetFileVersionInfo=lambda _path, _key: {
            "FileFlags": 0x0,
            "FileFlagsMask": 0x3F,
        }
    )
    assert _read_pe_debug_flag(win32, r"C:\fake\OneHand.exe") is None


def test_detect_onehand_build_uses_sniff_and_version(tmp_path: Path, monkeypatch) -> None:
    gold = tmp_path / "Goldclub"
    gold.mkdir()
    exe = gold / "OneHand.exe"
    exe.write_bytes(
        b"\x00" * 100
        + "2.0.1+RC2".encode("utf-16le")
        + "AssemblyConfiguration".encode("utf-16le")
        + "\x00\x00".encode("utf-16le")
        + "Debug".encode("utf-16le")
    )

    # Force PE path off so sniff + version sniff drive the result.
    monkeypatch.setattr(
        "config_scanner.build_version._extract_version_from_onehand_exe",
        lambda _path: SimpleNamespace(
            product_version="2.0.1+RC2",
            display_version="v2.0.1-rc2",
            file_version=None,
            product_name="OneHand",
            is_debug=None,
        ),
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.version == "2.0.1+RC2"
    # AssemblyConfiguration alone is not a compile signal (Release SKUs contain it).
    assert info.configuration == "Release"
    assert "OneHand" in info.label


def test_detect_onehand_build_debug_when_pe_flag_clear(tmp_path: Path, monkeypatch) -> None:
    gold = tmp_path / "Goldclub"
    gold.mkdir()
    exe = gold / "OneHand.exe"
    exe.write_bytes(b"MZ" + "ProductVersion\0Debug\0".encode("utf-16le"))

    monkeypatch.setattr(
        "config_scanner.build_version._extract_version_from_onehand_exe",
        lambda _path: SimpleNamespace(
            product_version="Debug",
            display_version=None,
            file_version="2.0.1.0",
            product_name="OneHand",
            is_debug=False,
        ),
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"
    assert info.version == "2.0.1.0"


def test_detect_onehand_build_debug_from_sku_bytes(tmp_path: Path, monkeypatch) -> None:
    gold = tmp_path / "Goldclub"
    (gold / "slot").mkdir(parents=True)
    exe = gold / "slot" / "OneHand.exe"
    exe.write_bytes(b"MZ" + "ProductVersion\0Debug\0".encode("utf-16le"))

    monkeypatch.setattr(
        "config_scanner.build_version._extract_version_from_onehand_exe",
        lambda _path: SimpleNamespace(
            product_version="2.0.1+RC2",
            display_version="v2.0.1-rc2",
            file_version="2.0.1.0",
            product_name="OneHand",
            is_debug=None,
        ),
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"
    assert "2.0.1" in info.version


def test_all_utf16_values_after_skips_earlier_numeric_product_version() -> None:
    blob = (
        _utf16_pair("ProductVersion", "3.0.0.0+RC2+2667F2")
        + b"\x00" * 16
        + _utf16_pair("ProductVersion", "Debug")
    )
    assert _all_utf16_values_after(blob, "ProductVersion") == (
        "3.0.0.0+RC2+2667F2",
        "Debug",
    )


def test_debug_sku_from_versioninfo_past_first_4mb(tmp_path: Path) -> None:
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    exe = slot / "OneHand.exe"
    prefix = (
        b"MZ"
        + _utf16_pair("ProductVersion", "3.0.0.0+RC2+2667F2")
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + b"\x00" * (5 * 1024 * 1024)
    )
    exe.write_bytes(prefix + _version_info_blob(ProductVersion="Debug", FileVersion="3.0.0.0"))
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"
    assert info.exe_path.endswith("OneHand.exe")
    assert "slot" in info.exe_path.replace("\\", "/")


def test_debug_sku_from_fileversion_string_when_productversion_is_rc(tmp_path: Path) -> None:
    """10.0.0.76 / 10.0.0.98 Debug SKU: RC ProductVersion, FileVersion=Debug, VS_FF_DEBUG unset."""
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    exe = slot / "OneHand.exe"
    exe.write_bytes(
        b"MZ"
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + _version_info_blob(
            ProductVersion="3.0.0.0+RC2+2667F2",
            FileVersion="Debug",
            FileDescription="OneHand",
        )
    )
    assert onehand_exe_is_debug_sku(exe) is True
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"
    assert "3.0.0.0+RC2+2667F2" in (info.version or "")
    assert "Release" not in info.label
    assert info.label.endswith("Debug")


def test_cabinet_76_fileversion_debug_is_debug(tmp_path: Path) -> None:
    """10.0.0.76 lab Debug OneHand: FileVersion=Debug must label Debug and use Bootstrap.

    Same VERSIONINFO SKU rule as 10.0.0.98. AssemblyConfiguration=Release and a
    numeric ProductVersion must not flip the cabinet to Release.
    """
    from config_scanner.live_push import slot_start_launcher
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(
        b"MZ"
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + _version_info_blob(
            ProductVersion="3.0.0.0+RC2+2667F2",
            FileVersion="Debug",
            FileDescription="OneHand",
            Comments="lab debug cabinet 10.0.0.76",
        )
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"
    assert "3.0.0.0+RC2+2667F2" in (info.version or "")
    assert info.label.endswith("Debug")
    assert "Release" not in info.label
    assert is_onehand_debug_build(gold) is True
    assert slot_start_launcher(str(gold), dest=gold) == "bootstrap"


def test_prefers_slot_onehand_over_root_release_copy(tmp_path: Path) -> None:
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (gold / "OneHand.exe").write_bytes(
        b"MZ" + _version_info_blob(ProductVersion="3.0.0.0+RC2+2667F2", FileDescription="OneHand Release")
    )
    (slot / "OneHand.exe").write_bytes(
        b"MZ" + _version_info_blob(ProductVersion="Debug", FileVersion="3.0.0.0")
    )
    assert _find_onehand_exe(gold) == slot / "OneHand.exe"
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"
    assert Path(info.exe_path) == slot / "OneHand.exe"


def test_release_versioninfo_stays_release_when_assembly_is_release(tmp_path: Path) -> None:
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(
        b"MZ"
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + _version_info_blob(ProductVersion="2.1.0", FileDescription="OneHand")
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Release"


def test_read_version_resource_finds_debug_sku(tmp_path: Path) -> None:
    exe = tmp_path / "OneHand.exe"
    exe.write_bytes(b"MZ" + _version_info_blob(ProductVersion="Debug", ProductName="OneHand"))
    res = _read_version_resource(exe)
    assert res is not None
    assert "Debug" in res.fields.get("ProductVersion", ())


def test_version_number_and_slotlog_strings_are_not_debug(tmp_path: Path) -> None:
    """3.0.0.0+RC2+hex and SlotLog banners appear on Release OneHand too."""
    from config_scanner.live_push import slot_start_launcher
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(
        b"MZ"
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + "SlotMachine v3.0.0.0".encode("utf-16le")
        + "Static initialization (i0)".encode("ascii")
        + _version_info_blob(
            ProductVersion="3.0.0.0+RC2+2667F2",
            FileVersion="3.0.0.0",
            FileDescription="OneHand",
        )
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Release"
    assert "3.0.0.0+RC2+2667F2" in (info.version or "")
    assert info.label.endswith("Release")
    assert is_onehand_debug_build(gold) is False
    assert slot_start_launcher(str(gold), dest=gold) == "game-start"


def test_release_exe_ignores_dependency_debug_version_bytes(tmp_path: Path) -> None:
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(
        b"MZ"
        + "3.0.0.0+RC2+DEADBE".encode("utf-16le")
        + "DebuggableAttribute".encode("ascii")
        + bytes([0x06, 0x01, 0x00, 0x07, 0x01, 0x00, 0x00])
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + _version_info_blob(ProductVersion="2.1.0", FileDescription="OneHand")
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Release"
    assert info.version == "2.1.0"


def test_pdb_path_debug_folder_does_not_override_numeric_release(tmp_path: Path, monkeypatch) -> None:
    """10.0.0.111-style numbered VERSIONINFO stays Release even with a Debug PDB path."""
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    exe = slot / "OneHand.exe"
    exe.write_bytes(
        b"MZ"
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + _version_info_blob(ProductVersion="3.0.0.0+RC2+2667F2", FileDescription="OneHand")
    )
    monkeypatch.setattr(
        "config_scanner.build_version._pe_codeview_is_debug_build",
        lambda _p: True,
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Release"


def test_codeview_debug_when_versioninfo_missing(tmp_path: Path, monkeypatch) -> None:
    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    exe = slot / "OneHand.exe"
    exe.write_bytes(b"MZ\x00\x00")
    monkeypatch.setattr(
        "config_scanner.build_version._pe_codeview_is_debug_build",
        lambda _p: True,
    )
    monkeypatch.setattr(
        "config_scanner.build_version._extract_version_from_onehand_exe",
        lambda _path: SimpleNamespace(
            product_version=None,
            display_version=None,
            file_version=None,
            product_name="OneHand",
            is_debug=None,
            file_version_string=None,
        ),
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Debug"


def test_cabinet_111_numeric_versioninfo_is_release(tmp_path: Path, monkeypatch) -> None:
    """GST22377 / 10.0.0.111: FileVersion 2.0.1.0, ProductVersion 2.0.1+RC2+51df6aa.

    Live dump of \\\\10.0.0.111\\slot\\slot\\OneHand.exe. A dependency
    ProductVersion=Debug in the head, DebuggableAttribute, and a Debug
    CodeView path must not paint this cabinet Debug.
    """
    from config_scanner.live_push import slot_start_launcher
    from config_scanner.slot_setup import is_onehand_debug_build

    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(
        b"MZ"
        + _utf16_pair("ProductVersion", "Debug")
        + _utf16_pair("FileVersion", "Debug")
        + "DebuggableAttribute".encode("ascii")
        + bytes([0x06, 0x01, 0x00, 0x07, 0x01, 0x00, 0x00])
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Debug".encode("utf-16le")
        + _version_info_blob(
            ProductVersion="2.0.1+RC2+51df6aa",
            FileVersion="2.0.1.0",
            FileDescription="OneHand",
            Comments="built with debugger helpers",
        )
    )
    monkeypatch.setattr(
        "config_scanner.build_version._pe_codeview_is_debug_build",
        lambda _p: True,
    )
    monkeypatch.setattr(
        "config_scanner.build_version._dotnet_assembly_is_debug",
        lambda _p: True,
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Release"
    assert "2.0.1+RC2+51df6aa" in (info.version or "")
    assert info.label.endswith("Release")
    assert "Debug" not in info.label
    assert is_onehand_debug_build(gold) is False
    assert slot_start_launcher(str(gold), dest=gold) == "game-start"


def test_lab_cabinets_76_debug_and_111_release(tmp_path: Path) -> None:
    """Paired lab expectation: 10.0.0.76 → Debug, 10.0.0.111 → Release."""
    from config_scanner.live_push import slot_start_launcher
    from config_scanner.slot_setup import is_onehand_debug_build

    cases = (
        (
            "10.0.0.76",
            {"ProductVersion": "3.0.0.0+RC2+2667F2", "FileVersion": "Debug"},
            "Debug",
            "bootstrap",
            True,
        ),
        (
            "10.0.0.111",
            {"ProductVersion": "2.0.1+RC2+51df6aa", "FileVersion": "2.0.1.0"},
            "Release",
            "game-start",
            False,
        ),
    )
    for host, version_fields, expect_cfg, expect_launcher, expect_debug in cases:
        gold = tmp_path / host.replace(".", "_")
        slot = gold / "slot"
        slot.mkdir(parents=True)
        (slot / "OneHand.exe").write_bytes(
            b"MZ"
            + "AssemblyConfiguration".encode("utf-16le")
            + b"\x00\x00"
            + "Release".encode("utf-16le")
            + _version_info_blob(FileDescription="OneHand", **version_fields)
        )
        info = detect_onehand_build(gold)
        assert info is not None, host
        assert info.configuration == expect_cfg, host
        assert info.label.endswith(expect_cfg), host
        assert is_onehand_debug_build(gold) is expect_debug, host
        assert slot_start_launcher(str(gold), dest=gold) == expect_launcher, host


def test_pdb_path_is_debug_output_uses_folder_not_filename() -> None:
    assert _pdb_path_is_debug_output(r"C:\src\bin\Debug\OneHand.pdb") is True
    assert _pdb_path_is_debug_output(r"C:\src\bin\Release\OneHand.pdb") is False
    assert _pdb_path_is_debug_output(r"C:\src\OneHand-Debug.pdb") is False
    assert _pdb_path_is_debug_output("OneHand.pdb") is False


def test_slot_start_launcher_uses_bootstrap_for_rc_debug_sku(tmp_path: Path) -> None:
    from config_scanner.live_push import slot_start_launcher

    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    (slot / "OneHand.exe").write_bytes(
        b"MZ"
        + "AssemblyConfiguration".encode("utf-16le")
        + b"\x00\x00"
        + "Release".encode("utf-16le")
        + _version_info_blob(
            ProductVersion="3.0.0.0+RC2+2667F2",
            FileVersion="Debug",
        )
    )
    assert slot_start_launcher(str(gold), dest=gold) == "bootstrap"


def test_detect_onehand_build_release_from_pe_flag(tmp_path: Path, monkeypatch) -> None:
    gold = tmp_path / "Goldclub"
    (gold / "slot").mkdir(parents=True)
    exe = gold / "slot" / "OneHand.exe"
    exe.write_bytes(b"MZ")

    monkeypatch.setattr(
        "config_scanner.build_version._extract_version_from_onehand_exe",
        lambda _path: SimpleNamespace(
            product_version="2.1.0",
            display_version="v2.1.0",
            file_version="2.1.0.0",
            product_name="OneHand",
            is_debug=False,
        ),
    )
    info = detect_onehand_build(gold)
    assert info is not None
    assert info.configuration == "Release"
    assert info.version == "2.1.0"


def test_load_live_cabinet_attaches_onehand_build(tmp_path: Path, monkeypatch) -> None:
    from config_scanner.live_push import load_live_cabinet

    gold = tmp_path / "Goldclub"
    themes = gold / "slot" / "themes"
    themes.mkdir(parents=True)
    (gold / "OneHand.exe").write_bytes(b"MZ")

    fake_recipe = SimpleNamespace(
        display_mode=1,
        jurisdiction=SimpleNamespace(tag="PR"),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.prepare_live_goldclub",
        lambda _t: (gold, ""),
    )
    monkeypatch.setattr(
        "config_scanner.live_push.load_recipe_from_goldclub",
        lambda *_a, **_k: fake_recipe,
    )
    monkeypatch.setattr(
        "config_scanner.live_push.inspect_live_licences",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "config_scanner.live_push.goldclub_stack_kind",
        lambda *_a, **_k: "slot",
    )
    monkeypatch.setattr(
        "config_scanner.live_push.prefetch_link2win_math",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "config_scanner.live_push.read_display_mode",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        "config_scanner.live_push.live_display_corruption_errors",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "config_scanner.live_push.detect_onehand_build",
        lambda *_a, **_k: OneHandBuildInfo(
            version="2.0.1+RC2",
            configuration="Release",
            exe_path=str(gold / "OneHand.exe"),
        ),
    )

    outcome = load_live_cabinet(str(gold))
    assert outcome.error == ""
    assert outcome.onehand_build is not None
    assert outcome.onehand_build.label == "OneHand 2.0.1+RC2 · Release"
    assert outcome.recipe is fake_recipe
