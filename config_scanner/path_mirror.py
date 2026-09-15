"""GoldClub mirrors ``config/etc`` and ``bios/etc`` as the same settings tree.

Scans that include both roots would report every change twice. Prefer the
lexicographically highest full relative path (``config/etc/...`` over
``bios/etc/...``).

Slot licence XML is also copied to Goldclub root, ``Licenses\\``, and
``slot\\``. Snapshots keep ``Licenses\\`` (or ``Licences\\``) and
``slot\\licence.dll`` only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def normalize_rel(relative_path: str) -> str:
    return (relative_path or "").replace("\\", "/").strip("/")


def etc_mirror_key(relative_path: str) -> str | None:
    """Shared key for ``config/etc/X`` and ``bios/etc/X``; else None."""
    low = normalize_rel(relative_path).lower()
    if low.startswith("bios/etc/"):
        return "etc/" + low[len("bios/etc/") :]
    if low.startswith("config/etc/"):
        return "etc/" + low[len("config/etc/") :]
    return None


def highest_full_path(paths: Iterable[str]) -> str:
    """Return the lexicographically highest normalized relative path."""
    items = list(paths)
    if not items:
        raise ValueError("highest_full_path requires at least one path")
    return max(items, key=lambda p: normalize_rel(p).lower())


def select_highest_etc_mirror_paths(relative_paths: Iterable[str]) -> list[str]:
    """Keep non-mirrors as-is; for each etc mirror pair keep the highest path."""
    by_key: dict[str, list[str]] = {}
    others: list[str] = []
    for rel in relative_paths:
        key = etc_mirror_key(rel)
        if key is None:
            others.append(rel)
            continue
        by_key.setdefault(key, []).append(rel)

    kept = list(others)
    for paths in by_key.values():
        kept.append(highest_full_path(paths))
    return sorted(kept, key=lambda p: normalize_rel(p).lower())


def dedupe_etc_mirror_items(
    items: Iterable[T],
    *,
    path_of,
    fingerprint_of=None,
) -> list[T]:
    """Collapse bios/etc ↔ config/etc duplicates, keeping the highest path.

    When mirror siblings share the same fingerprint (or fingerprint_of is None),
    only the highest full path is kept. Divergent fingerprints are all kept
    (each group's highest path).
    """
    by_key: dict[str, list[T]] = {}
    others: list[T] = []
    for item in items:
        rel = path_of(item)
        key = etc_mirror_key(rel)
        if key is None:
            others.append(item)
            continue
        by_key.setdefault(key, []).append(item)

    out = list(others)
    for group in by_key.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        if fingerprint_of is None:
            out.append(max(group, key=lambda item: normalize_rel(path_of(item)).lower()))
            continue
        by_fp: dict[object, list[T]] = {}
        for item in group:
            by_fp.setdefault(fingerprint_of(item), []).append(item)
        for siblings in by_fp.values():
            out.append(
                max(siblings, key=lambda item: normalize_rel(path_of(item)).lower())
            )
    return sorted(out, key=lambda item: normalize_rel(path_of(item)).lower())


# Same WIBU XML / dll is often copied to Goldclub root, Licenses\\, and slot\\.
# Snapshots keep one path: Licenses\\ (or Licences\\) for XML, slot\\licence.dll.
_LICENCE_XML_NAME_RE = re.compile(
    r"^(licence|license).+\.xml$|^[0-9A-Fa-f]{64}\.xml$",
    re.IGNORECASE,
)
_LICENCE_DLL_NAMES = frozenset({"licence.dll", "license.dll"})
_LICENCE_STORE_DIRS = frozenset({"licenses", "licences"})


def licence_mirror_key(relative_path: str) -> str | None:
    """Shared key for the same licence file in root / Licenses / slot; else None."""
    norm = normalize_rel(relative_path)
    if not norm:
        return None
    low = norm.casefold()
    if low.startswith("bios/license/") or "/licensing/" in f"/{low}/":
        return None
    name = Path(norm).name
    namelow = name.casefold()
    if namelow in _LICENCE_DLL_NAMES:
        return "dll:licence.dll"
    if _LICENCE_XML_NAME_RE.match(name):
        return f"xml:{namelow}"
    return None


def _licence_location_rank(relative_path: str) -> int:
    """Lower is better: Licenses\\, then slot\\, then Goldclub root."""
    parent = str(Path(normalize_rel(relative_path)).parent).replace("\\", "/").casefold()
    if parent in {".", ""}:
        return 2
    first = parent.split("/", 1)[0]
    if first in _LICENCE_STORE_DIRS:
        return 0
    if first == "slot":
        return 1
    return 3


def select_canonical_licence_paths(relative_paths: Iterable[str]) -> list[str]:
    """Keep one copy of each licence XML / dll (Licenses\\ XML, slot\\licence.dll)."""
    by_key: dict[str, list[str]] = {}
    others: list[str] = []
    for rel in relative_paths:
        key = licence_mirror_key(rel)
        if key is None:
            others.append(rel)
            continue
        by_key.setdefault(key, []).append(rel)

    kept = list(others)
    for paths in by_key.values():
        kept.append(
            min(
                paths,
                key=lambda p: (
                    _licence_location_rank(p),
                    normalize_rel(p).casefold(),
                ),
            )
        )
    return sorted(kept, key=lambda p: normalize_rel(p).lower())


def existing_mirrored_licence_rels(root: Path) -> list[str]:
    """Licence XML / dll paths that snapshots collapse to one location."""
    root = Path(root)
    found: dict[str, str] = {}
    for pattern in (
        "Licenses/*.xml",
        "Licences/*.xml",
        "slot/Licence*.xml",
        "slot/License*.xml",
        "Licence*.xml",
        "License*.xml",
        "slot/licence.dll",
        "slot/license.dll",
        "licence.dll",
        "license.dll",
    ):
        try:
            matches = root.glob(pattern)
        except (OSError, ValueError):
            continue
        for path in matches:
            try:
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if licence_mirror_key(rel):
                found[normalize_rel(rel).casefold()] = rel
    return list(found.values())


def canonical_licence_rels_on_disk(root: Path) -> frozenset[str]:
    """Casefolded rels that should be stored in a snapshot."""
    return frozenset(
        normalize_rel(rel).casefold()
        for rel in select_canonical_licence_paths(existing_mirrored_licence_rels(root))
    )
