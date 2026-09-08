"""Country Selector catalog: discover leaves, load install.json, apply overlays.

Mirrors CS packs under ``\\\\10.0.0.249\\WinSystems_SLOT\\_B2U\\CS-Gamestar-*``:
``CountrySelectorTool\\data\\<country>\\<screens>\\<mode>\\install.json``.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Trailing commas appear in real CS install.json files.
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

_SERIALPORT_FORBIDDEN = re.compile(
    r"(^|/)system/hardware/serialport/(layout|locations)\.json$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InstallVariable:
    title: str
    pattern: str


@dataclass(frozen=True)
class InstallRecipe:
    readme: str
    delete_paths: tuple[str, ...]
    copy_ops: tuple[tuple[str, str], ...]  # (from_rel, to_abs)
    variable_files: tuple[str, ...]
    variables: tuple[InstallVariable, ...]
    raw: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CountryLeaf:
    """One selectable overlay under CountrySelectorTool/data."""

    path: Path
    rel_parts: tuple[str, ...]
    country: str
    screens: str
    mode: str
    readme: str

    @property
    def label(self) -> str:
        bits = [p for p in (self.country, self.screens, self.mode) if p]
        return " / ".join(bits) if bits else self.path.name


@dataclass(frozen=True)
class CsApplyResult:
    deleted: tuple[str, ...]
    copied: tuple[str, ...]
    substituted: tuple[str, ...]
    skipped: tuple[str, ...]
    errors: tuple[str, ...]


def load_install_json(path: Path) -> InstallRecipe:
    """Parse a CS ``install.json`` (tolerates trailing commas)."""
    text = path.read_text(encoding="utf-8-sig")
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
    data = json.loads(cleaned)
    delete_paths = tuple(
        str(item.get("Path", "")).replace("\\", "/")
        for item in data.get("Delete") or []
        if item.get("Path")
    )
    copy_ops: list[tuple[str, str]] = []
    for item in data.get("Copy") or []:
        frm = str(item.get("From", "")).strip().replace("\\", "/")
        to = str(item.get("To", "")).strip().replace("\\", "/")
        if frm and to:
            copy_ops.append((frm, to))
    var_files: list[str] = []
    variables: list[InstallVariable] = []
    for block in data.get("Data") or []:
        for p in block.get("Path") or []:
            var_files.append(str(p).replace("\\", "/"))
        for var in block.get("Variables") or []:
            pattern = str(var.get("Pattern", "")).strip()
            if not pattern:
                continue
            variables.append(
                InstallVariable(
                    title=str(var.get("Title", "Value")).strip() or "Value",
                    pattern=pattern,
                )
            )
    return InstallRecipe(
        readme=str(data.get("Readme", "")).strip(),
        delete_paths=delete_paths,
        copy_ops=tuple(copy_ops),
        variable_files=tuple(dict.fromkeys(var_files)),
        variables=tuple(variables),
        raw=data,
    )


def resolve_country_selector_tool(root: Path) -> Path:
    """Locate ``CountrySelectorTool`` (or a folder that contains ``data/``).

    Accepts a tool folder, package root, ``.b2u``, or nested BiOS
    ``Content/tmp`` layout. Walks a few levels so decrypt caches still resolve.
    """
    root = Path(root)
    if root.is_file() and root.suffix.casefold() == ".b2u":
        from config_scanner.b2u_pack import extract_b2u_update
        from config_scanner.pack_detect import detect_pack

        package = extract_b2u_update(root, reuse_cache=True)
        detected = detect_pack(package)
        if (detected.root / "data").is_dir():
            return detected.root
        root = package

    if not root.exists():
        raise FileNotFoundError(f"country pack path not found: {root}")

    candidates = [
        root,
        root / "CountrySelectorTool",
        root / "tmp" / "CountrySelectorTool",
        root / "Content" / "tmp" / "CountrySelectorTool",
        root / "Content" / "CountrySelectorTool",
    ]
    for cand in candidates:
        try:
            if (cand / "data").is_dir():
                return cand
            if cand.name.casefold() == "data" and cand.is_dir():
                return cand.parent
        except OSError:
            continue

    queue: list[tuple[Path, int]] = [(root, 0)]
    seen: set[str] = set()
    while queue:
        cur, depth = queue.pop(0)
        key = str(cur).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            data = cur / "data"
            if data.is_dir() and (
                cur.name.casefold() == "countryselectortool"
                or any(data.rglob("install.json"))
            ):
                return cur
        except OSError:
            continue
        if depth >= 4:
            continue
        try:
            children = list(cur.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                queue.append((child, depth + 1))

    raise FileNotFoundError(f"No CountrySelectorTool/data under {root}")


def discover_leaves(tool_or_pack: Path) -> list[CountryLeaf]:
    """Find every ``install.json`` leaf under the CS data tree."""
    tool = resolve_country_selector_tool(tool_or_pack)
    data_root = tool / "data"
    leaves: list[CountryLeaf] = []
    for install in sorted(data_root.rglob("install.json")):
        leaf_dir = install.parent
        try:
            rel = leaf_dir.relative_to(data_root)
        except ValueError:
            continue
        parts = tuple(rel.parts)
        country = parts[0] if len(parts) >= 1 else leaf_dir.name
        screens = parts[1] if len(parts) >= 2 else ""
        mode = parts[2] if len(parts) >= 3 else ""
        try:
            recipe = load_install_json(install)
            readme = recipe.readme
        except (OSError, json.JSONDecodeError, ValueError):
            readme = ""
        leaves.append(
            CountryLeaf(
                path=leaf_dir,
                rel_parts=parts,
                country=country,
                screens=screens,
                mode=mode,
                readme=readme,
            )
        )
    return leaves


def unique_axis_values(leaves: list[CountryLeaf]) -> tuple[list[str], list[str], list[str]]:
    countries = sorted({leaf.country for leaf in leaves if leaf.country})
    screens = sorted({leaf.screens for leaf in leaves if leaf.screens})
    modes = sorted({leaf.mode for leaf in leaves if leaf.mode})
    return countries, screens, modes


def filter_leaves(
    leaves: list[CountryLeaf],
    *,
    country: str | None = None,
    screens: str | None = None,
    mode: str | None = None,
) -> list[CountryLeaf]:
    out = leaves
    if country:
        out = [leaf for leaf in out if leaf.country == country]
    if screens:
        out = [leaf for leaf in out if leaf.screens == screens]
    if mode:
        out = [leaf for leaf in out if leaf.mode == mode]
    return out


def is_cs_forbidden_rel(rel_posix: str) -> bool:
    """Paths we never write even if present in a CS overlay."""
    return bool(_SERIALPORT_FORBIDDEN.search(rel_posix.replace("\\", "/")))


def _prefer_existing_case(goldclub_root: Path, rest: str) -> Path:
    """Join *rest* onto *goldclub_root*, preserving on-disk folder casing."""
    parts = [p for p in rest.replace("\\", "/").split("/") if p]
    cur = Path(goldclub_root)
    for part in parts:
        if cur.is_dir():
            match = None
            try:
                for child in cur.iterdir():
                    if child.name.casefold() == part.casefold():
                        match = child.name
                        break
            except OSError:
                match = None
            cur = cur / (match or part)
        else:
            cur = cur / part
    return cur


def _normalize_goldclub_path(path_str: str, goldclub_root: Path) -> Path:
    """Map ``c:/Goldclub/...`` (any casing) onto ``goldclub_root``."""
    text = path_str.replace("\\", "/").strip()
    goldclub_root = Path(goldclub_root)
    m = re.match(r"^[a-zA-Z]:/Goldclub/(.*)$", text, re.IGNORECASE)
    if m:
        rest = m.group(1).rstrip("/")
        return _prefer_existing_case(goldclub_root, rest) if rest else goldclub_root
    m = re.match(r"^[a-zA-Z]:/Goldclub/?$", text, re.IGNORECASE)
    if m:
        return goldclub_root
    if text.lower().startswith("goldclub/"):
        return _prefer_existing_case(goldclub_root, text.split("/", 1)[1])
    if re.match(r"^(slot|services|bios|var|platform|maintenance)(/|$)", text, re.I):
        return _prefer_existing_case(goldclub_root, text)
    return Path(text)


def apply_country_leaf(
    leaf: Path | CountryLeaf,
    goldclub_root: Path,
    *,
    substitutions: dict[str, str] | None = None,
    dry_run: bool = False,
) -> CsApplyResult:
    """Apply one CS overlay leaf to a Goldclub root using its install.json."""
    leaf_dir = leaf.path if isinstance(leaf, CountryLeaf) else Path(leaf)
    install_path = leaf_dir / "install.json"
    if not install_path.is_file():
        return CsApplyResult((), (), (), (), (f"missing install.json under {leaf_dir}",))

    recipe = load_install_json(install_path)
    goldclub_root = Path(goldclub_root)
    subs = dict(substitutions or {})
    deleted: list[str] = []
    copied: list[str] = []
    substituted: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for del_path in recipe.delete_paths:
        target = _normalize_goldclub_path(del_path, goldclub_root)
        rel_note = str(target)
        if dry_run:
            deleted.append(rel_note)
            continue
        try:
            if target.is_file():
                target.unlink()
                deleted.append(rel_note)
            elif target.is_dir():
                shutil.rmtree(target)
                deleted.append(rel_note)
            else:
                skipped.append(f"{rel_note}: not present")
        except OSError as exc:
            errors.append(f"delete {rel_note}: {exc}")

    for frm, to in recipe.copy_ops:
        src = leaf_dir / frm
        dest_root = _normalize_goldclub_path(to, goldclub_root)
        if not src.exists():
            skipped.append(f"copy {frm}: source missing in leaf")
            continue
        if dry_run:
            copied.append(f"{frm} -> {dest_root}")
            continue
        try:
            _copy_tree_filtered(src, dest_root, copied, skipped, errors)
        except OSError as exc:
            errors.append(f"copy {frm} -> {dest_root}: {exc}")

    if subs:
        for file_path in recipe.variable_files:
            target = _normalize_goldclub_path(file_path, goldclub_root)
            if dry_run:
                substituted.append(str(target))
                continue
            if not target.is_file():
                skipped.append(f"subst {target}: missing after copy")
                continue
            try:
                raw = target.read_text(encoding="utf-8", errors="surrogateescape")
                new = raw
                for pattern, value in subs.items():
                    new = new.replace(pattern, value)
                if new != raw:
                    target.write_text(new, encoding="utf-8", errors="surrogateescape")
                    substituted.append(str(target))
                else:
                    skipped.append(f"subst {target}: no pattern match")
            except OSError as exc:
                errors.append(f"subst {target}: {exc}")

    return CsApplyResult(
        tuple(deleted),
        tuple(copied),
        tuple(substituted),
        tuple(skipped),
        tuple(errors),
    )


def _copy_file_retry(src: Path, dest: Path, *, attempts: int = 3) -> None:
    """Copy one file; retry briefly on Windows sharing violations."""
    import time

    last: OSError | None = None
    for i in range(attempts):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return
        except OSError as exc:
            last = exc
            # WinError 32 sharing violation / 5 access denied — brief backoff
            if i + 1 < attempts and getattr(exc, "winerror", None) in (5, 32, 33):
                time.sleep(0.35 * (i + 1))
                continue
            raise
    if last:
        raise last


def _copy_tree_filtered(
    src: Path,
    dest_root: Path,
    copied: list[str],
    skipped: list[str],
    errors: list[str],
) -> None:
    if src.is_file():
        rel = src.name
        if is_cs_forbidden_rel(rel):
            skipped.append(f"{rel}: forbidden")
            return
        try:
            _copy_file_retry(src, dest_root)
            copied.append(str(dest_root))
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
        return

    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        if is_cs_forbidden_rel(rel):
            skipped.append(f"{rel}: forbidden serialport map")
            continue
        dest = dest_root / rel
        try:
            _copy_file_retry(path, dest)
            copied.append(dest.as_posix())
        except OSError as exc:
            errors.append(f"{rel}: {exc}")


def stage_country_pack(
    tool_or_pack: Path,
    output_dir: Path,
    *,
    package_label: str = "ConfigScanner_Country",
) -> Path:
    """Copy CountrySelectorTool (data + optional exe) into a staging folder.

    Returns the staged ``CountrySelectorTool`` directory path.
    """
    tool = resolve_country_selector_tool(tool_or_pack)
    dest = Path(output_dir) / package_label / "CountrySelectorTool"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    # Always need data/
    shutil.copytree(tool / "data", dest / "data")
    # Optional binaries (field can use our wizard instead)
    for name in (
        "CountrySelector.exe",
        "CountrySelector.exe.config",
        "log4net.config",
        "log4net.dll",
        "Newtonsoft.Json.dll",
    ):
        src = tool / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    from config_scanner.math_decrypt import stage_crypt_tools

    stage_crypt_tools(dest)
    return dest


def substitutions_from_machine_number(
    recipe: InstallRecipe,
    machine_number: str,
) -> dict[str, str]:
    """Build pattern→value map; machine number replaces ``!!MachineName!!``."""
    number = machine_number.strip()
    out: dict[str, str] = {}
    for var in recipe.variables:
        if var.pattern == "!!MachineName!!" or "MachineName" in var.pattern:
            out[var.pattern] = number
        else:
            # Unknown patterns: leave unset unless caller adds them
            continue
    if "!!MachineName!!" not in out and any(
        v.pattern == "!!MachineName!!" for v in recipe.variables
    ):
        out["!!MachineName!!"] = number
    if not out and number:
        out["!!MachineName!!"] = number
    return out
