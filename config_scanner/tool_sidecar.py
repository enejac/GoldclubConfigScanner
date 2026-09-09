"""Single ``tools`` folder next to ConfigScanner.exe.

Encryptor / BiOS cryptors and BiOS2_PackageGenerator live together here.
Country Selector packages still receive a nested ``CRYPT_TOOLS`` copy — that is
the official CS layout, not the ConfigScanner sidecar.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app_paths import app_install_dir

TOOLS_FOLDER = "tools"
LEGACY_CRYPT_FOLDER = "CRYPT_TOOLS"

# One of each — never nest a second copy of these next to the exe.
SHIP_TOOL_FILES: tuple[str, ...] = (
    "Encryptor.exe",
    "BiOSCrypt.exe",
    "BiOS Encryptor.exe",
    "JPCrypt.exe",
    "ReadMe.txt",
    "BiOS2_PackageGenerator.exe",
    "BiOS2_PackageGenerator.exe.config",
    "log4net.dll",
    "ICSharpCode.SharpZipLib.dll",
)


def sidecar_tools_dir() -> Path:
    """``<exe or repo>\\tools`` — the only sidecar folder next to the program."""
    return app_install_dir() / TOOLS_FOLDER


def collect_ship_tool_sources(root: Path) -> dict[str, Path]:
    """Map basename → first existing file (flat ``tools``, then legacy nests)."""
    base = Path(root)
    found: dict[str, Path] = {}
    search = (
        base / TOOLS_FOLDER,
        base / TOOLS_FOLDER / LEGACY_CRYPT_FOLDER,
        base / TOOLS_FOLDER / "BiOS2_PackageGenerator",
        base,
        base / LEGACY_CRYPT_FOLDER,
        base / "BiOS2_PackageGenerator",
    )
    for folder in search:
        try:
            if not folder.is_dir():
                continue
        except OSError:
            continue
        for name in SHIP_TOOL_FILES:
            if name in found:
                continue
            path = folder / name
            try:
                if path.is_file():
                    found[name] = path
            except OSError:
                continue
    return found


def stage_sidecar_tools(dest_tools: Path, *, source_root: Path | None = None) -> Path:
    """Copy one of each needed tool into *dest_tools* (no nested duplicates)."""
    src = collect_ship_tool_sources(source_root or app_install_dir())
    dest = Path(dest_tools)
    dest.mkdir(parents=True, exist_ok=True)
    for name in SHIP_TOOL_FILES:
        origin = src.get(name)
        if origin is None:
            continue
        target = dest / name
        if origin.resolve() == target.resolve():
            continue
        shutil.copy2(origin, target)
    return dest


def embedded_updates_assets_root(source_root: Path | None = None) -> Path:
    root = Path(source_root) if source_root is not None else app_install_dir()
    return root / "config_scanner" / "assets" / "embedded_updates"


def stage_embedded_updates(dest: Path, *, source_root: Path | None = None) -> Path | None:
    """Copy catalog + b2u + staged CS trees beside the exe (USB / zip layout)."""
    src = embedded_updates_assets_root(source_root)
    try:
        if not src.is_dir() or not (src / "catalog.json").is_file():
            return None
    except OSError:
        return None
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("_sync_cache", "__pycache__"))
    return dest


PACK_README = (
    "Config Scanner portable pack\r\n"
    "\r\n"
    "  ConfigScanner.exe\r\n"
    "  tools\\              Encryptor, BiOSCrypt, BiOS Encryptor, JPCrypt,\r\n"
    "                      BiOS2_PackageGenerator + log4net + SharpZipLib\r\n"
    "\r\n"
    "Keep tools next to the exe.\r\n"
    "First run creates config-scanner\\ beside it.\r\n"
    "Country Selector packs: use the lab share or copy embedded_updates beside the exe.\r\n"
)


def build_portable_zip(
    exe: Path,
    dest_zip: Path,
    *,
    folder_name: str,
    source_root: Path | None = None,
) -> Path:
    """Zip exe + ``tools`` only (no embedded Country Selector trees)."""
    import tempfile
    import zipfile

    exe = Path(exe)
    dest_zip = Path(dest_zip)
    if not exe.is_file():
        raise FileNotFoundError(exe)
    tmp = Path(tempfile.mkdtemp(prefix="gcs-pack-"))
    try:
        pack = tmp / folder_name
        pack.mkdir()
        shutil.copy2(exe, pack / "ConfigScanner.exe")
        stage_sidecar_tools(pack / TOOLS_FOLDER, source_root=source_root)
        (pack / "README.txt").write_text(PACK_README, encoding="ascii")
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        if dest_zip.exists():
            dest_zip.unlink()
        with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in pack.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(tmp).as_posix())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest_zip
