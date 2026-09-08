"""Build an official-style Country Selector .b2u from a tuned live cabinet.

After Live Push / Create, operators need more than a ConfigScanner client
wrapper: list the live settings that were applied, overlay those files into a
CS leaf, and encrypt a BiOS2 package that runs CountrySelector.exe (same shape
as GameStar CS-Gamestar-*.b2u).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config_scanner.b2u_pack import (
    PACKAGE_XML,
    B2uPackResult,
    default_package_generator,
    encrypt_b2u,
)
from config_scanner.cs_catalog import (
    CountryLeaf,
    discover_leaves,
    is_cs_forbidden_rel,
    resolve_country_selector_tool,
    stage_country_pack,
)
from config_scanner.cs_coverage import (
    goldclub_rel_from_leaf_file,
    inventory_leaf_config_files,
)
from config_scanner.setting_probe import format_value, probe_tree
from config_scanner.setting_spec import all_specs

# Stock GameStar Country Selector init (matches CS-Gamestar-TRI-01 / JAM / TT).
OFFICIAL_CS_INIT_CMD = """\
@echo off

net stop "GoldClub.Aurum.Services"

cd tmp\\

del s:\\etc\\game-start\\checksum.md5
del s:\\etc\\game-start\\checksum.sha1
del s:\\etc\\game-start\\list-game.sha1
if exist checksum.sha1 copy "checksum.sha1" "s:\\etc\\game-start\\checksum.sha1" /Y

cd CountrySelectorTool

start /wait CountrySelector.exe

cd..

if exist GCTicketConfig.exe start /wait GCTicketConfig.exe

net start "GoldClub.Aurum.Services"

start C:\\Goldclub\\maintenance\\begin-RamClearWithSetup.cmd
"""

_TOOL_EXTRAS = (
    "CountrySelector.exe",
    "CountrySelector.exe.config",
    "CountrySelector.pdb",
    "log4net.config",
    "log4net.dll",
    "Newtonsoft.Json.dll",
)

_TMP_EXTRAS = (
    "checksum.sha1",
    "checksum.md5",
    "GCTicketConfig.exe",
    "GCTicketConfig.exe.config",
)


@dataclass
class LiveCsExportResult:
    package_dir: Path
    b2u_path: Path | None
    settings_report: Path
    overlay_files: list[str] = field(default_factory=list)
    settings_rows: list[dict[str, str]] = field(default_factory=list)
    note: str = ""


def list_live_settings(goldclub: Path) -> list[dict[str, str]]:
    """Probe live Goldclub and return rows for the settings report / UI."""
    goldclub = Path(goldclub)
    readings = probe_tree(goldclub, expected=None, source_is_cs_leaf=False)
    rows: list[dict[str, str]] = []
    for spec in all_specs():
        reading = readings.get(spec.id)
        if reading is None:
            continue
        if not reading.present and reading.value is None:
            continue
        rows.append(
            {
                "id": spec.id,
                "group": spec.group,
                "label": spec.label,
                "value": format_value(reading.value),
                "state": reading.state.value,
                "file": spec.file_rel,
            }
        )
    return rows


def write_settings_report(
    rows: list[dict[str, str]],
    path: Path,
    *,
    goldclub: Path | None = None,
    leaf_label: str | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "goldclub": str(goldclub) if goldclub else None,
        "leaf": leaf_label,
        "settings": rows,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    txt = path.with_suffix(".txt")
    lines = [
        "Config Scanner — live cabinet settings",
        f"Generated: {payload['generated_utc']}",
        f"Goldclub: {payload['goldclub'] or '—'}",
        f"Leaf: {leaf_label or '—'}",
        "",
        f"{'Group':<16} {'Setting':<36} Value",
        "-" * 80,
    ]
    for row in rows:
        lines.append(
            f"{row['group']:<16} {row['label']:<36} {row['value']}"
        )
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _resolve_live_file(live_root: Path, rel: str) -> Path | None:
    """Find *rel* under live_root with Slot/slot and Services/services casing."""
    live_root = Path(live_root)
    rel_n = rel.replace("\\", "/").lstrip("/")
    variants = [rel_n]
    first, sep, rest = rel_n.partition("/")
    swaps = {
        "slot": "Slot",
        "Slot": "slot",
        "services": "Services",
        "Services": "services",
    }
    if first in swaps:
        variants.append(swaps[first] + (f"/{rest}" if rest else ""))
    for variant in variants:
        parts = [p for p in variant.split("/") if p]
        cur = live_root
        ok = True
        for part in parts:
            if not cur.is_dir():
                ok = False
                break
            match = None
            try:
                for child in cur.iterdir():
                    if child.name.casefold() == part.casefold():
                        match = child
                        break
            except OSError:
                ok = False
                break
            if match is None:
                ok = False
                break
            cur = match
        if ok and cur.is_file():
            return cur
    return None


def overlay_live_onto_leaf(leaf_dir: Path, live_root: Path) -> list[str]:
    """Replace leaf config files with matching live Goldclub files.

    Only paths already present in the leaf are updated (keeps CS shape). Serialport
    layout/locations maps are never copied.
    """
    leaf_dir = Path(leaf_dir)
    live_root = Path(live_root)
    written: list[str] = []
    for leaf_file in inventory_leaf_config_files(leaf_dir):
        rel = goldclub_rel_from_leaf_file(leaf_dir, leaf_file)
        if not rel or is_cs_forbidden_rel(rel):
            continue
        live_file = _resolve_live_file(live_root, rel)
        if live_file is None:
            continue
        shutil.copy2(live_file, leaf_file)
        written.append(rel.replace("\\", "/"))
    return written


def _tmp_dir_from_tool(tool: Path) -> Path | None:
    """If *tool* is Content/tmp/CountrySelectorTool, return the tmp parent."""
    tool = Path(tool).resolve()
    if tool.name.casefold() != "countryselectortool":
        return None
    parent = tool.parent
    if parent.name.casefold() == "tmp":
        return parent
    return None


def _copy_tmp_extras(tmp_dest: Path, tool_src: Path, reference_package: Path | None) -> None:
    sources: list[Path] = []
    tmp_from_tool = _tmp_dir_from_tool(tool_src)
    if tmp_from_tool is not None:
        sources.append(tmp_from_tool)
    if reference_package is not None:
        ref_tmp = Path(reference_package) / "Content" / "tmp"
        if ref_tmp.is_dir():
            sources.append(ref_tmp)
    for name in _TMP_EXTRAS:
        dest = tmp_dest / name
        if dest.is_file():
            continue
        for src_root in sources:
            src = src_root / name
            if src.is_file():
                shutil.copy2(src, dest)
                break


def build_official_cs_package(
    output_dir: Path,
    country_tool_dir: Path,
    *,
    package_name: str,
    reference_package: Path | None = None,
) -> Path:
    """Unpacked BiOS2 package that runs CountrySelector.exe (not ConfigScanner)."""
    tool_src = resolve_country_selector_tool(country_tool_dir)
    if not (tool_src / "CountrySelector.exe").is_file():
        # Staged packs sometimes omit the exe; try reference package tool.
        if reference_package is not None:
            ref_tool = (
                Path(reference_package) / "Content" / "tmp" / "CountrySelectorTool"
            )
            if (ref_tool / "CountrySelector.exe").is_file():
                # Copy binaries from reference onto a staged tool copy below.
                pass
            else:
                raise FileNotFoundError(
                    f"CountrySelector.exe missing under {tool_src} "
                    "(need a full CS pack, not data-only)."
                )
        else:
            raise FileNotFoundError(
                f"CountrySelector.exe missing under {tool_src} "
                "(need a full CS pack, not data-only)."
            )

    package_dir = Path(output_dir) / package_name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    content = package_dir / "Content"
    meta = package_dir / "Meta"
    tmp = content / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    (package_dir / "package.xml").write_text(PACKAGE_XML, encoding="utf-8")
    (meta / "package.xml").write_text(PACKAGE_XML, encoding="utf-8")
    (content / "init.cmd").write_text(
        OFFICIAL_CS_INIT_CMD.replace("\n", "\r\n"), encoding="ascii"
    )

    dest_tool = tmp / "CountrySelectorTool"
    shutil.copytree(tool_src, dest_tool)
    # Ensure binaries exist (data-only staged trees).
    if not (dest_tool / "CountrySelector.exe").is_file() and reference_package is not None:
        ref_tool = Path(reference_package) / "Content" / "tmp" / "CountrySelectorTool"
        for name in _TOOL_EXTRAS:
            src = ref_tool / name
            if src.is_file() and not (dest_tool / name).is_file():
                shutil.copy2(src, dest_tool / name)
    if not (dest_tool / "CountrySelector.exe").is_file():
        raise FileNotFoundError(
            f"CountrySelector.exe still missing after staging {dest_tool}"
        )

    from config_scanner.math_decrypt import stage_crypt_tools

    stage_crypt_tools(dest_tool)
    _copy_tmp_extras(tmp, tool_src, reference_package)
    return package_dir


def export_full_country_selector(
    output_dir: Path,
    *,
    live_goldclub: Path,
    country_tool_dir: Path,
    leaf: Path | CountryLeaf,
    package_name: str | None = None,
    encrypt: bool = True,
    reference_package: Path | None = None,
) -> LiveCsExportResult:
    """List live settings, overlay them onto *leaf*, build + encrypt official CS .b2u."""
    live_goldclub = Path(live_goldclub)
    if not live_goldclub.is_dir():
        raise FileNotFoundError(f"live Goldclub not found: {live_goldclub}")

    tool_src = resolve_country_selector_tool(country_tool_dir)
    leaf_obj = leaf if isinstance(leaf, CountryLeaf) else None
    leaf_dir = leaf.path if isinstance(leaf, CountryLeaf) else Path(leaf)
    if not (leaf_dir / "install.json").is_file():
        raise FileNotFoundError(f"leaf missing install.json: {leaf_dir}")

    # Stage a private CountrySelectorTool so we do not mutate the share/cache.
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_root = output_dir / "_stage_live_cs"
    staged_tool = stage_country_pack(tool_src, stage_root, package_label="live")

    # Map leaf path into the staged tree (same relative path under data/).
    try:
        rel_leaf = leaf_dir.resolve().relative_to(tool_src.resolve())
    except ValueError:
        # Leaf may already be under a different tool copy — match by country/mode.
        rel_leaf = None
        if leaf_obj is not None:
            for cand in discover_leaves(staged_tool):
                if (
                    cand.country == leaf_obj.country
                    and cand.screens == leaf_obj.screens
                    and cand.mode == leaf_obj.mode
                ):
                    leaf_dir = cand.path
                    break
            else:
                raise FileNotFoundError(
                    f"could not map leaf {leaf_obj.country}/{leaf_obj.mode} into staged tool"
                )
        else:
            raise FileNotFoundError(
                f"leaf {leaf_dir} is not under tool {tool_src}"
            )
    if rel_leaf is not None:
        leaf_dir = staged_tool / rel_leaf

    overlay_files = overlay_live_onto_leaf(leaf_dir, live_goldclub)
    settings_rows = list_live_settings(live_goldclub)

    leaf_label = None
    if leaf_obj is not None:
        leaf_label = f"{leaf_obj.country} / {leaf_obj.screens} / {leaf_obj.mode}"
    else:
        leaf_label = str(leaf_dir.relative_to(staged_tool)).replace("\\", "/")

    if not package_name:
        safe_country = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in (leaf_obj.country if leaf_obj else "Live")
        )[:24]
        package_name = f"CS-Gamestar-{safe_country}-Live"

    package_dir = build_official_cs_package(
        output_dir,
        staged_tool,
        package_name=package_name,
        reference_package=reference_package,
    )

    report = write_settings_report(
        settings_rows,
        package_dir / "Content" / "tmp" / "settings-from-live.json",
        goldclub=live_goldclub,
        leaf_label=leaf_label,
    )
    # Also drop a copy next to the package for easy review before encrypt.
    write_settings_report(
        settings_rows,
        output_dir / f"{package_name}_settings.json",
        goldclub=live_goldclub,
        leaf_label=leaf_label,
    )

    # Overlay inventory inside the package for the field tech.
    inv = package_dir / "Content" / "tmp" / "live-overlay-files.txt"
    inv.write_text(
        "\n".join(overlay_files) + ("\n" if overlay_files else "(no matching leaf files)\n"),
        encoding="utf-8",
    )

    b2u_path: Path | None = None
    note = (
        f"Official CS package: {package_dir} "
        f"({len(overlay_files)} live file(s) overlaid, "
        f"{len(settings_rows)} setting(s) listed)."
    )
    if encrypt:
        gen = default_package_generator()
        if gen is None:
            note += " BiOS2_PackageGenerator.exe missing — skipped .b2u encrypt."
        else:
            try:
                b2u_path = encrypt_b2u(package_dir, output_dir / f"{package_name}.b2u")
                note = (
                    f"Full Country Selector .b2u: {b2u_path} "
                    f"({len(overlay_files)} live file(s), "
                    f"{len(settings_rows)} setting(s))."
                )
            except (OSError, RuntimeError, FileNotFoundError) as exc:
                note += f" Encrypt failed: {exc}"

    shutil.rmtree(stage_root, ignore_errors=True)

    return LiveCsExportResult(
        package_dir=package_dir,
        b2u_path=b2u_path,
        settings_report=report,
        overlay_files=overlay_files,
        settings_rows=settings_rows,
        note=note,
    )


def pack_result_from_live_export(result: LiveCsExportResult) -> B2uPackResult:
    return B2uPackResult(
        package_dir=result.package_dir,
        b2u_path=result.b2u_path,
        note=result.note,
    )
