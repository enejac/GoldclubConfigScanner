"""Build BiOS2-style update folders (.b2u) that launch ConfigScanner.

Always writes an unpacked package tree matching CS layouts on
``\\\\10.0.0.249\\WinSystems_SLOT\\_B2U``. When BiOS2_PackageGenerator.exe is
available, optionally encrypts to a real ``.b2u``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from config_scanner.tool_sidecar import sidecar_tools_dir

PACKAGE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<package version="1.0.2">
  <command>
    <type>external</type>
    <cmd>init.cmd</cmd>
    <confirmation>true</confirmation>
    <async>false</async>
  </command>
  <platform>all</platform>
  <permissions>
    <role id="0">true</role>
    <role id="1">true</role>
    <role id="2">true</role>
  </permissions>
</package>
"""

TOOL_INIT_CMD = """\
@echo off
cd /d "%~dp0"
start /wait "" "%~dp0tmp\\ConfigScanner.exe" --snapshots
"""

EGM_INIT_CMD = """\
@echo off
cd /d "%~dp0"
start /wait "" "%~dp0tmp\\ConfigScanner.exe" --apply-pack "%~dp0tmp\\config-pack"
"""

COUNTRY_INIT_CMD = """\
@echo off
cd /d "%~dp0"
start /wait "" "%~dp0tmp\\ConfigScanner.exe" --country-pack "%~dp0tmp\\CountrySelectorTool"
"""

COMPANION_INIT_CMD = """\
@echo off
cd /d "%~dp0"
start /wait "" "%~dp0tmp\\ConfigScanner.exe" --companion-pack "%~dp0tmp\\companion-pack"
"""


@dataclass(frozen=True)
class B2uPackResult:
    package_dir: Path
    b2u_path: Path | None
    note: str


def launched_from_tool_b2u() -> bool:
    """True when the frozen exe runs from Content\\tmp\\ beside a tool init.cmd."""
    if not getattr(sys, "frozen", False):
        return False
    exe = Path(sys.executable).resolve()
    if exe.name.casefold() != "configscanner.exe":
        return False
    if exe.parent.name.casefold() != "tmp":
        return False
    return (exe.parent.parent / "init.cmd").is_file()


# Bare BiOS2_PackageGenerator.exe without these DLLs raises FileNotFoundException
# for log4net (exit 3762504530) — common when only the .exe is copied beside USB tools.
_GENERATOR_DEPS: tuple[str, ...] = (
    "log4net.dll",
    "ICSharpCode.SharpZipLib.dll",
)


def package_generator_ready(path: Path | None) -> bool:
    """True when *path* is an exe that has its managed dependencies beside it."""
    if path is None or not Path(path).is_file():
        return False
    parent = Path(path).resolve().parent
    return all((parent / name).is_file() for name in _GENERATOR_DEPS)


def _package_generator_candidates() -> list[Path]:
    candidates: list[Path] = []
    tools = sidecar_tools_dir()
    candidates.extend(
        [
            tools / "BiOS2_PackageGenerator.exe",
            tools / "BiOS2_PackageGenerator" / "BiOS2_PackageGenerator.exe",
        ]
    )
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "tools" / "BiOS2_PackageGenerator.exe",
                exe_dir / "BiOS2_PackageGenerator.exe",
            ]
        )
    repo = Path(__file__).resolve().parents[1]
    candidates.append(repo / "tools" / "BiOS2_PackageGenerator.exe")
    for letter in "DEFGHI":
        root = Path(f"{letter}:/")
        if not root.exists():
            continue
        candidates.extend(
            [
                root / "tools" / "BiOS2_PackageGenerator.exe",
                root / "tools" / "BiOS2_PackageGenerator" / "BiOS2_PackageGenerator.exe",
                root / "BiOS2_PackageGenerator.exe",
            ]
        )
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def ensure_package_generator_deps(gen: Path) -> Path:
    """Copy missing DLLs next to *gen* from another complete install when possible."""
    gen = Path(gen)
    if package_generator_ready(gen):
        return gen
    donor: Path | None = None
    for cand in _package_generator_candidates():
        if cand.resolve() == gen.resolve():
            continue
        if package_generator_ready(cand):
            donor = cand
            break
    if donor is None:
        missing = [
            name
            for name in _GENERATOR_DEPS
            if not (gen.parent / name).is_file()
        ]
        raise FileNotFoundError(
            f"{gen.name} is missing {', '.join(missing)}. "
            "Place BiOS2_PackageGenerator.exe with log4net.dll and "
            "ICSharpCode.SharpZipLib.dll in the tools folder next to "
            "ConfigScanner.exe."
        )
    for name in _GENERATOR_DEPS:
        dest = gen.parent / name
        if dest.is_file():
            continue
        src = donor.parent / name
        if src.is_file():
            shutil.copy2(src, dest)
    if not package_generator_ready(gen):
        raise FileNotFoundError(
            f"Could not repair dependencies for {gen} from {donor.parent}"
        )
    return gen


def default_package_generator() -> Path | None:
    """Locate a usable BiOS2_PackageGenerator.exe (complete install preferred).

    Skips bare .exe copies that lack log4net.dll (those crash on updateDecrypt).
    Incomplete installs are repaired in place when a complete donor is available.
    """
    incomplete: list[Path] = []
    for path in _package_generator_candidates():
        if not path.is_file():
            continue
        if package_generator_ready(path):
            return path
        incomplete.append(path)
    for path in incomplete:
        try:
            return ensure_package_generator_deps(path)
        except (OSError, FileNotFoundError):
            continue
    return None


def run_package_generator(
    args: list[str],
    *,
    generator: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run PackageGenerator with cwd=its folder so .NET finds log4net.dll."""
    gen = generator or default_package_generator()
    if gen is None:
        raise FileNotFoundError(
            "BiOS2_PackageGenerator.exe not found (needed to decrypt/encrypt .b2u). "
            "Install BiOS2_PackageGenerator or place the full folder beside ConfigScanner.exe."
        )
    gen = ensure_package_generator_deps(Path(gen))
    cmd = [str(gen), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(gen.parent),
    )


def is_b2u_file(path: Path) -> bool:
    return Path(path).is_file() and Path(path).suffix.casefold() == ".b2u"


def is_game_update_file(path: Path) -> bool:
    """GameStar+30 ``GameUpdate.Slot.CountrySelector_*.zip`` (gameDecrypt, not .b2u)."""
    p = Path(path)
    name = p.name.casefold()
    return name.startswith("gameupdate.slot.countryselector") and p.suffix.casefold() == ".zip"


def game_update_authoring_note(path: Path) -> str:
    return (
        f"{Path(path).name} is a GameStar+30 game update package.\n\n"
        "BiOS2 gameDecrypt succeeds but the payload is Meta/meta.xml only — "
        "there is no CountrySelectorTool/data tree for leaf probing or export.\n\n"
        "For Create / jurisdiction matrix use a GameStar 2.0.1 CS .b2u from "
        r"\\10.0.0.249\WinSystems_SLOT\GameStar 2.0.1\Country Selectors\ "
        "or an unpacked _B2U\\CS-Gamestar-* folder.\n\n"
        "Apply this GS+30 zip on the cabinet via BiOS game update, or copy it "
        "to the client USB for Restore."
    )


def decrypt_game_update(
    archive_path: Path,
    output_dir: Path,
    *,
    generator: Path | None = None,
) -> Path:
    """Decrypt a GameStar+30 ``GameUpdate.Slot.CountrySelector_*.zip`` via gameDecrypt."""
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise FileNotFoundError(f"game update not found: {archive_path}")
    if not is_game_update_file(archive_path):
        raise ValueError(f"not a GameUpdate CountrySelector archive: {archive_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = run_package_generator(
        [
            "gameDecrypt",
            "--sourcePath",
            str(archive_path),
            "--outputPath",
            str(output_dir),
            "--nowait",
        ],
        generator=generator,
    )
    detail = (proc.stderr or proc.stdout or "").strip()
    package_dir = output_dir / archive_path.stem
    if not package_dir.is_dir():
        dirs = [p for p in output_dir.iterdir() if p.is_dir()]
        if len(dirs) == 1:
            package_dir = dirs[0]
        else:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise RuntimeError(
                f"gameDecrypt failed (exit {proc.returncode}): "
                f"{detail or 'no unpacked folder'}"
            )
    meta = package_dir / "Meta" / "meta.xml"
    if not meta.is_file():
        raise RuntimeError(
            f"gameDecrypt produced unexpected layout under {package_dir}: {detail}"
        )
    return package_dir


def extract_game_update(
    archive_path: Path,
    *,
    work_parent: Path | None = None,
    generator: Path | None = None,
    reuse_cache: bool = True,
) -> Path:
    """Decrypt GameUpdate zip; returns package root (Meta/meta.xml)."""
    archive_path = Path(archive_path)
    if work_parent is None:
        work_parent = Path(r"C:\tmp\cs_gameupdate") if sys.platform == "win32" else Path("/tmp/cs_gameupdate")
    package_dir = work_parent / archive_path.stem
    if reuse_cache and package_dir.is_dir() and (package_dir / "Meta" / "meta.xml").is_file():
        return package_dir
    if package_dir.exists():
        shutil.rmtree(package_dir, ignore_errors=True)
    return decrypt_game_update(archive_path, work_parent, generator=generator)


def decrypt_b2u(
    b2u_path: Path,
    output_dir: Path,
    *,
    generator: Path | None = None,
) -> Path:
    """Decrypt an official ``.b2u`` update to an unpacked package folder."""
    b2u_path = Path(b2u_path)
    if not b2u_path.is_file():
        raise FileNotFoundError(f".b2u not found: {b2u_path}")
    if b2u_path.suffix.casefold() != ".b2u":
        raise ValueError(f"not a .b2u file: {b2u_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = run_package_generator(
        [
            "updateDecrypt",
            "--sourcePath",
            str(b2u_path),
            "--outputPath",
            str(output_dir),
            "--nowait",
        ],
        generator=generator,
    )
    detail = (proc.stderr or proc.stdout or "").strip()
    package_dir = output_dir / b2u_path.stem
    if not package_dir.is_dir():
        dirs = [p for p in output_dir.iterdir() if p.is_dir()]
        if len(dirs) == 1:
            package_dir = dirs[0]
        else:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise RuntimeError(
                f"updateDecrypt failed (exit {proc.returncode}): "
                f"{detail or 'no unpacked folder'}"
            )
    if not ((package_dir / "Content").is_dir() or (package_dir / "package.xml").is_file()):
        raise RuntimeError(
            f"updateDecrypt produced no package tree under {package_dir}: {detail}"
        )
    if proc.returncode != 0:
        # Generator sometimes exits non-zero after successful extract; trust tree.
        pass
    return package_dir


def b2u_extract_dir(b2u_path: Path) -> Path:
    """Short working directory for decrypt (avoids MAX_PATH on deep CS trees)."""
    stem = Path(b2u_path).stem
    if sys.platform == "win32":
        return Path(r"C:\tmp\cs_b2u") / stem
    return Path("/tmp") / "cs_b2u" / stem


def extract_b2u_update(
    b2u_path: Path,
    *,
    work_parent: Path | None = None,
    generator: Path | None = None,
    reuse_cache: bool = True,
) -> Path:
    """Decrypt ``.b2u`` and return the unpacked package root (``Content/``, ``package.xml``)."""
    b2u_path = Path(b2u_path)
    if work_parent is None:
        work_parent = b2u_extract_dir(b2u_path).parent
    package_dir = work_parent / b2u_path.stem
    if reuse_cache and package_dir.is_dir() and (package_dir / "Content").is_dir():
        return package_dir
    if package_dir.exists():
        shutil.rmtree(package_dir, ignore_errors=True)
    return decrypt_b2u(b2u_path, work_parent, generator=generator)


def resolve_config_scanner_exe(*, prefer_dist: bool = True) -> Path:
    root = Path(__file__).resolve().parents[1]
    candidates: list[Path] = []
    if prefer_dist:
        candidates.append(root / "dist" / "ConfigScanner.exe")
    candidates.append(root / "ConfigScanner.exe")
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "ConfigScanner.exe not found. Run .\\build_exe.ps1 first "
        f"(looked under {root / 'dist'})."
    )


def _write_package_shell(package_dir: Path, init_cmd: str) -> None:
    if package_dir.exists():
        shutil.rmtree(package_dir)
    content = package_dir / "Content"
    meta = package_dir / "Meta"
    tmp = content / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    (package_dir / "package.xml").write_text(PACKAGE_XML, encoding="utf-8")
    (meta / "package.xml").write_text(PACKAGE_XML, encoding="utf-8")
    (content / "init.cmd").write_text(init_cmd.replace("\n", "\r\n"), encoding="ascii")


def build_tool_b2u_folder(
    output_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_Tool",
) -> Path:
    """Unpacked tool B2U that launches the full Config Scanner GUI."""
    exe = exe_path or resolve_config_scanner_exe()
    package_dir = output_dir / package_name
    _write_package_shell(package_dir, TOOL_INIT_CMD)
    tmp = package_dir / "Content" / "tmp"
    shutil.copy2(exe, tmp / "ConfigScanner.exe")
    _bundle_embedded_updates(tmp)
    return package_dir


def _bundle_embedded_updates(tmp_dir: Path) -> None:
    from config_scanner.embedded_updates import embedded_updates_root

    src = embedded_updates_root()
    if not src.is_dir() or not (src / "catalog.json").is_file():
        return
    dest = tmp_dir / "embedded_updates"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def build_egm_b2u_folder(
    output_dir: Path,
    config_pack_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_EGM",
) -> Path:
    """Unpacked EGM B2U that launches apply-only GUI with a bundled config pack."""
    if not (config_pack_dir / "recipe.json").is_file():
        raise FileNotFoundError(f"config pack missing recipe.json: {config_pack_dir}")
    exe = exe_path or resolve_config_scanner_exe()
    package_dir = output_dir / package_name
    _write_package_shell(package_dir, EGM_INIT_CMD)
    tmp = package_dir / "Content" / "tmp"
    shutil.copy2(exe, tmp / "ConfigScanner.exe")
    dest_pack = tmp / "config-pack"
    if dest_pack.exists():
        shutil.rmtree(dest_pack)
    shutil.copytree(config_pack_dir, dest_pack)
    return package_dir


def build_country_b2u_folder(
    output_dir: Path,
    country_tool_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_Country",
) -> Path:
    """Unpacked B2U that launches the CS field wizard with bundled data leaves."""
    tool = Path(country_tool_dir)
    if not (tool / "data").is_dir():
        raise FileNotFoundError(f"country pack missing data/: {tool}")
    exe = exe_path or resolve_config_scanner_exe()
    package_dir = Path(output_dir) / package_name
    _write_package_shell(package_dir, COUNTRY_INIT_CMD)
    tmp = package_dir / "Content" / "tmp"
    shutil.copy2(exe, tmp / "ConfigScanner.exe")
    dest_tool = tmp / "CountrySelectorTool"
    if dest_tool.exists():
        shutil.rmtree(dest_tool)
    shutil.copytree(tool, dest_tool)
    return package_dir


def encrypt_b2u(
    package_dir: Path,
    output_b2u: Path,
    *,
    generator: Path | None = None,
) -> Path:
    """Encrypt an unpacked package folder to ``.b2u`` via BiOS2_PackageGenerator.

    PackageGenerator treats ``--outputPath`` as a directory and writes
    ``<packageName>.b2u`` inside it. We stage that output, then move the
    produced file to ``output_b2u``.
    """
    output_b2u = Path(output_b2u)
    output_b2u.parent.mkdir(parents=True, exist_ok=True)
    if output_b2u.is_file():
        output_b2u.unlink()
    elif output_b2u.is_dir():
        shutil.rmtree(output_b2u)

    stage = output_b2u.parent / f".b2u_stage_{package_dir.name}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    proc = run_package_generator(
        [
            "updateEncrypt",
            "--sourcePath",
            str(package_dir),
            "--outputPath",
            str(stage),
            "--nowait",
        ],
        generator=generator,
    )
    detail = (proc.stderr or proc.stdout or "").strip()
    produced = _find_produced_b2u(stage, package_dir.name)
    if proc.returncode != 0 or produced is None:
        shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError(
            f"updateEncrypt failed (exit {proc.returncode}): {detail or 'no .b2u produced'}"
        )
    shutil.move(str(produced), str(output_b2u))
    shutil.rmtree(stage, ignore_errors=True)
    if not output_b2u.is_file():
        raise RuntimeError(f"updateEncrypt produced no file at {output_b2u}")
    return output_b2u


def _find_produced_b2u(stage: Path, package_name: str) -> Path | None:
    """Locate the encrypted ``.b2u`` file written under a generator output dir."""
    preferred = stage / f"{package_name}.b2u"
    if preferred.is_file():
        return preferred
    candidates = sorted(
        p for p in stage.rglob("*.b2u") if p.is_file() and p.stat().st_size > 0
    )
    return candidates[0] if candidates else None


def pack_tool_update(
    output_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_Tool",
    encrypt: bool = True,
) -> B2uPackResult:
    package_dir = build_tool_b2u_folder(
        output_dir, exe_path=exe_path, package_name=package_name
    )
    b2u_path: Path | None = None
    note = f"Unpacked tool package: {package_dir}"
    if encrypt:
        gen = default_package_generator()
        if gen is None:
            note += " (BiOS2_PackageGenerator.exe missing — skipped .b2u encrypt)"
        else:
            try:
                b2u_path = encrypt_b2u(package_dir, output_dir / f"{package_name}.b2u")
                note = f"Tool package + .b2u: {b2u_path}"
            except (OSError, RuntimeError) as exc:
                note += f" (encrypt failed: {exc})"
    return B2uPackResult(package_dir=package_dir, b2u_path=b2u_path, note=note)


def pack_egm_update(
    output_dir: Path,
    config_pack_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_EGM",
    encrypt: bool = True,
) -> B2uPackResult:
    package_dir = build_egm_b2u_folder(
        output_dir,
        config_pack_dir,
        exe_path=exe_path,
        package_name=package_name,
    )
    b2u_path: Path | None = None
    note = f"Unpacked EGM package: {package_dir}"
    if encrypt:
        gen = default_package_generator()
        if gen is None:
            note += " (BiOS2_PackageGenerator.exe missing — skipped .b2u encrypt)"
        else:
            try:
                b2u_path = encrypt_b2u(package_dir, output_dir / f"{package_name}.b2u")
                note = f"EGM package + .b2u: {b2u_path}"
            except (OSError, RuntimeError) as exc:
                note += f" (encrypt failed: {exc})"
    return B2uPackResult(package_dir=package_dir, b2u_path=b2u_path, note=note)


def pack_country_update(
    output_dir: Path,
    country_tool_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_Country",
    encrypt: bool = True,
) -> B2uPackResult:
    """Bundle CountrySelectorTool data + exe for the field CS wizard."""
    package_dir = build_country_b2u_folder(
        output_dir,
        country_tool_dir,
        exe_path=exe_path,
        package_name=package_name,
    )
    b2u_path: Path | None = None
    note = f"Unpacked country package: {package_dir}"
    if encrypt:
        gen = default_package_generator()
        if gen is None:
            note += " (BiOS2_PackageGenerator.exe missing — skipped .b2u encrypt)"
        else:
            try:
                b2u_path = encrypt_b2u(package_dir, output_dir / f"{package_name}.b2u")
                note = f"Country package + .b2u: {b2u_path}"
            except (OSError, RuntimeError) as exc:
                note += f" (encrypt failed: {exc})"
    return B2uPackResult(package_dir=package_dir, b2u_path=b2u_path, note=note)


def build_companion_b2u_folder(
    output_dir: Path,
    companion_pack_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_Companion",
) -> Path:
    """Unpacked B2U that launches companion apply UI with bundled payload."""
    pack = Path(companion_pack_dir)
    if not (pack / "companion.json").is_file():
        raise FileNotFoundError(f"companion pack missing companion.json: {pack}")
    exe = exe_path or resolve_config_scanner_exe()
    package_dir = Path(output_dir) / package_name
    _write_package_shell(package_dir, COMPANION_INIT_CMD)
    tmp = package_dir / "Content" / "tmp"
    shutil.copy2(exe, tmp / "ConfigScanner.exe")
    dest = tmp / "companion-pack"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(pack, dest)
    return package_dir


def pack_companion_update(
    output_dir: Path,
    companion_pack_dir: Path,
    *,
    exe_path: Path | None = None,
    package_name: str = "ConfigScanner_Companion",
    encrypt: bool = True,
) -> B2uPackResult:
    package_dir = build_companion_b2u_folder(
        output_dir,
        companion_pack_dir,
        exe_path=exe_path,
        package_name=package_name,
    )
    b2u_path: Path | None = None
    note = f"Unpacked companion package: {package_dir}"
    if encrypt:
        gen = default_package_generator()
        if gen is None:
            note += " (BiOS2_PackageGenerator.exe missing — skipped .b2u encrypt)"
        else:
            try:
                b2u_path = encrypt_b2u(package_dir, output_dir / f"{package_name}.b2u")
                note = f"Companion package + .b2u: {b2u_path}"
            except (OSError, RuntimeError) as exc:
                note += f" (encrypt failed: {exc})"
    return B2uPackResult(package_dir=package_dir, b2u_path=b2u_path, note=note)
