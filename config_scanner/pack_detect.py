"""Detect which update pack type a folder is (for simple Restore flow)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PackKind(str, Enum):
    COUNTRY = "country"
    EGM_RECIPE = "egm_recipe"
    COMPANION = "companion"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DetectedPack:
    kind: PackKind
    root: Path
    detail: str


def detect_pack(path: Path) -> DetectedPack:
    """Classify a directory as country / EGM recipe / companion pack."""
    path = Path(path)
    if not path.exists():
        return DetectedPack(PackKind.UNKNOWN, path, "path not found")

    # Direct markers
    if (path / "companion.json").is_file():
        return DetectedPack(PackKind.COMPANION, path, "companion.json")
    if (path / "recipe.json").is_file():
        return DetectedPack(PackKind.EGM_RECIPE, path, "recipe.json")
    if (path / "data").is_dir() and any(path.rglob("install.json")):
        return DetectedPack(PackKind.COUNTRY, path, "CountrySelectorTool data/")

    # Nested BiOS layout: Content/tmp/...
    tmp = path / "Content" / "tmp"
    if tmp.is_dir():
        if (tmp / "companion-pack" / "companion.json").is_file():
            return DetectedPack(
                PackKind.COMPANION, tmp / "companion-pack", "Content/tmp/companion-pack"
            )
        if (tmp / "config-pack" / "recipe.json").is_file():
            return DetectedPack(
                PackKind.EGM_RECIPE, tmp / "config-pack", "Content/tmp/config-pack"
            )
        tool = tmp / "CountrySelectorTool"
        if (tool / "data").is_dir():
            return DetectedPack(PackKind.COUNTRY, tool, "Content/tmp/CountrySelectorTool")

    # CountrySelectorTool folder itself
    if path.name.casefold() == "countryselectortool" and (path / "data").is_dir():
        return DetectedPack(PackKind.COUNTRY, path, "CountrySelectorTool")

    # Walk one level
    if path.is_dir():
        for child in path.iterdir():
            if not child.is_dir():
                continue
            nested = detect_pack(child)
            if nested.kind != PackKind.UNKNOWN:
                return nested

    return DetectedPack(PackKind.UNKNOWN, path, "unrecognized pack folder")


def resolve_update_root(path: Path) -> Path:
    """Return a folder root for detect_pack; decrypt ``.b2u`` files first."""
    path = Path(path)
    if path.suffix.casefold() == ".b2u":
        from config_scanner.b2u_pack import extract_b2u_update

        return extract_b2u_update(path)
    return path


def detect_update_path(path: Path) -> DetectedPack:
    """Classify an update folder or raw ``.b2u`` file."""
    return detect_pack(resolve_update_root(path))


def auto_detect_beside_exe() -> DetectedPack | None:
    """Look next to the running exe / cwd for a bundled pack."""
    candidates: list[Path] = []
    import sys

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    candidates.append(Path.cwd())
    for base in candidates:
        for name in (
            "CountrySelectorTool",
            "config-pack",
            "companion-pack",
            "Content/tmp/CountrySelectorTool",
            "Content/tmp/config-pack",
            "Content/tmp/companion-pack",
        ):
            cand = base / name
            if cand.exists():
                detected = detect_pack(cand if cand.is_dir() else cand.parent)
                if detected.kind != PackKind.UNKNOWN:
                    return detected
        # Whole package folder next to exe
        detected = detect_pack(base)
        if detected.kind != PackKind.UNKNOWN:
            return detected
    return None
