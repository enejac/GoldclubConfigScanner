"""Country Selector config inventory + Slot scan coverage checks.

Used to keep the Slot profile broad enough that CS overlays (hwdrivers,
mgconfig, Aurum/SAS, bios, Confirmation.txt, MathSettings, …) show up in
before/after SHA1 compares — not just two headline XML files.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from config_scanner.cs_catalog import CountryLeaf, load_install_json
from config_scanner.profiles import GameProfile, ScanRootSpec

# Config-like suffixes shipped inside CS leaves (exclude game assets).
_CONFIG_SUFFIXES = frozenset(
    {
        ".xml",
        ".json",
        ".config",
        ".conf",
        ".txt",
        ".ini",
        ".dat",
        ".lic",
        ".sha1",
        ".md5",
        ".xsd",
        ".ps1",
        ".cmd",
    }
)


def is_config_like(path: Path) -> bool:
    return path.suffix.casefold() in _CONFIG_SUFFIXES


def inventory_leaf_config_files(leaf: Path | CountryLeaf) -> list[Path]:
    """Config-like files under a CS leaf (absolute paths)."""
    leaf_dir = leaf.path if isinstance(leaf, CountryLeaf) else Path(leaf)
    out: list[Path] = []
    for path in leaf_dir.rglob("*"):
        if not path.is_file():
            continue
        if not is_config_like(path):
            continue
        # Skip install.json itself (not on live Goldclub after apply)
        if path.name.casefold() == "install.json":
            continue
        out.append(path)
    return sorted(out, key=lambda p: p.as_posix().casefold())


def goldclub_rel_from_leaf_file(leaf_dir: Path, file_path: Path) -> str | None:
    """Map a file inside a leaf to the Goldclub-relative path after apply.

    ``slot/themes/mgconfig.xml`` → ``slot/themes/mgconfig.xml``
    ``Services/aurum/...`` → ``Services/aurum/...``
    ``hello.txt`` at leaf root → ``hello.txt``
    """
    leaf_dir = Path(leaf_dir)
    file_path = Path(file_path)
    try:
        rel = file_path.relative_to(leaf_dir).as_posix()
    except ValueError:
        return None
    return rel


def applied_goldclub_rels(leaf: Path | CountryLeaf) -> list[str]:
    """Goldclub-relative config paths a leaf would write (best-effort)."""
    leaf_dir = leaf.path if isinstance(leaf, CountryLeaf) else Path(leaf)
    rels: list[str] = []
    for path in inventory_leaf_config_files(leaf_dir):
        rel = goldclub_rel_from_leaf_file(leaf_dir, path)
        if rel:
            rels.append(rel)
    # Also honor install.json Copy From roots (covers dest casing Slot vs slot)
    install = leaf_dir / "install.json"
    if install.is_file():
        try:
            recipe = load_install_json(install)
        except (OSError, ValueError):
            recipe = None
        if recipe is not None:
            for frm, _to in recipe.copy_ops:
                src = leaf_dir / frm
                if not src.exists():
                    continue
                if src.is_file() and is_config_like(src):
                    rels.append(frm.replace("\\", "/"))
                elif src.is_dir():
                    for path in src.rglob("*"):
                        if path.is_file() and is_config_like(path):
                            rels.append(path.relative_to(leaf_dir).as_posix())
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for rel in rels:
        key = rel.replace("\\", "/").casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(rel.replace("\\", "/"))
    return out


def _matches_scan_root(rel: str, spec: ScanRootSpec) -> bool:
    rel_n = rel.replace("\\", "/").lstrip("/")
    root = spec.path.strip().replace("\\", "/").strip("/")
    if root in (".", ""):
        # non-recursive "." → only files directly under Goldclub root
        return ("/" not in rel_n) if not spec.recursive else True
    root_cf = root.casefold()
    rel_cf = rel_n.casefold()
    if rel_cf == root_cf:
        return True
    if not rel_cf.startswith(root_cf + "/"):
        return False
    rest = rel_n[len(root) + 1 :]
    if spec.recursive:
        return True
    # non-recursive: only immediate children of the root
    return "/" not in rest.replace("\\", "/")


def _matches_include(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def profile_covers_rel(profile: GameProfile, rel: str) -> bool:
    """True if Slot (or other) profile would include this Goldclub-relative path."""
    from config_scanner.theme_math import is_theme_math_rel

    candidates = [rel.replace("\\", "/").lstrip("/")]
    # Try common Goldclub casing variants CS packs use
    first, _, rest = candidates[0].partition("/")
    swaps = {
        "slot": "Slot",
        "Slot": "slot",
        "services": "Services",
        "Services": "services",
    }
    if first in swaps:
        alt = swaps[first] + (f"/{rest}" if rest else "")
        candidates.append(alt)

    for rel_n in candidates:
        # Same walk collect_scan_files uses — any theme *Math.json / ProgressiveSetup.
        if is_theme_math_rel(rel_n):
            return True
        name = Path(rel_n).name
        for glob_pat in profile.extra_file_globs:
            pat = glob_pat.replace("\\", "/")
            if fnmatch.fnmatch(rel_n, pat) or fnmatch.fnmatch(rel_n.casefold(), pat.casefold()):
                return True
        if not _matches_include(name, profile.include_patterns):
            continue
        for spec in profile.scan_roots:
            if _matches_scan_root(rel_n, spec):
                return True
    return False


def snapshot_include_check(
    rels: list[str] | tuple[str, ...],
    *,
    profile_id: str = "slot_lab_90",
) -> dict[str, bool]:
    """Map Goldclub-relative paths to whether a snapshot scan would include them."""
    from config_scanner.profiles import get_profile

    profile = get_profile(profile_id)
    return {rel: profile_covers_rel(profile, rel) for rel in rels}


def coverage_gaps(profile: GameProfile, leaf: Path | CountryLeaf) -> list[str]:
    """Return Goldclub-relative paths from *leaf* that the profile would miss."""
    gaps: list[str] = []
    for rel in applied_goldclub_rels(leaf):
        if not profile_covers_rel(profile, rel):
            gaps.append(rel)
    return gaps
