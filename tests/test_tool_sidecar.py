"""Single tools/ sidecar next to the exe — no CRYPT_TOOLS twin."""

from __future__ import annotations

from pathlib import Path
import zipfile

from config_scanner.tool_sidecar import (
    SHIP_TOOL_FILES,
    TOOLS_FOLDER,
    build_portable_zip,
    collect_ship_tool_sources,
    sidecar_tools_dir,
    stage_sidecar_tools,
)


def _write_nested_dupes(root: Path) -> None:
    crypt = root / "CRYPT_TOOLS"
    crypt.mkdir()
    nest = root / "tools" / "BiOS2_PackageGenerator"
    nest.mkdir(parents=True)
    (crypt / "Encryptor.exe").write_bytes(b"MZ-enc")
    (crypt / "ReadMe.txt").write_text("Encryptor.exe => JSON\n", encoding="ascii")
    (crypt / "BiOSCrypt.exe").write_bytes(b"MZ-bios")
    (crypt / "BiOS Encryptor.exe").write_bytes(b"MZ-ws")
    (crypt / "JPCrypt.exe").write_bytes(b"MZ-jp")
    (nest / "BiOS2_PackageGenerator.exe").write_bytes(b"MZ-gen")
    (nest / "BiOS2_PackageGenerator.exe.config").write_text("<c/>", encoding="ascii")
    (nest / "log4net.dll").write_bytes(b"l4")
    (nest / "ICSharpCode.SharpZipLib.dll").write_bytes(b"zip")
    (root / "BiOS2_PackageGenerator.exe").write_bytes(b"MZ-loose")
    (root / "log4net.dll").write_bytes(b"loose-l4")


def test_collect_prefers_flat_tools_over_loose_root(tmp_path: Path) -> None:
    _write_nested_dupes(tmp_path)
    flat = tmp_path / "tools"
    (flat / "Encryptor.exe").write_bytes(b"MZ-flat")
    (flat / "ReadMe.txt").write_text("flat\n", encoding="ascii")
    found = collect_ship_tool_sources(tmp_path)
    assert found["Encryptor.exe"] == flat / "Encryptor.exe"
    assert found["BiOS2_PackageGenerator.exe"] == (
        tmp_path / "tools" / "BiOS2_PackageGenerator" / "BiOS2_PackageGenerator.exe"
    )
    dest = tmp_path / "out" / "tools"
    stage_sidecar_tools(dest, source_root=tmp_path)
    assert (dest / "Encryptor.exe").read_bytes() == b"MZ-flat"
    assert (dest / "BiOS2_PackageGenerator.exe").is_file()
    assert not (dest / "CRYPT_TOOLS").exists()
    assert not (dest / "BiOS2_PackageGenerator").exists()
    names = {p.name for p in dest.iterdir() if p.is_file()}
    assert "Encryptor.exe" in names
    assert names <= set(SHIP_TOOL_FILES)


def test_sidecar_tools_dir_is_tools_under_install() -> None:
    assert sidecar_tools_dir().name == TOOLS_FOLDER


def test_build_portable_zip_single_nest(tmp_path: Path) -> None:
    _write_nested_dupes(tmp_path)
    exe = tmp_path / "ConfigScanner.exe"
    exe.write_bytes(b"MZ-exe")
    zpath = tmp_path / "ConfigScanner-2026-09-04.zip"
    build_portable_zip(
        exe, zpath, folder_name="ConfigScanner-2026-09-04", source_root=tmp_path
    )
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
    assert "ConfigScanner-2026-09-04/ConfigScanner.exe" in names
    assert "ConfigScanner-2026-09-04/tools/Encryptor.exe" in names
    assert "ConfigScanner-2026-09-04/tools/BiOS2_PackageGenerator.exe" in names
    assert "ConfigScanner-2026-09-04/README.txt" in names
    assert not any("/CRYPT_TOOLS/" in n for n in names)
    assert not any(n.endswith("/BiOS2_PackageGenerator/BiOS2_PackageGenerator.exe") for n in names)
    assert not any(n.count("ConfigScanner-2026-09-04") > 1 for n in names)
