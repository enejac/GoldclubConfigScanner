"""Slot licence capture, compare, and explicit restore (like roulette trial rollback).

Slot cabinets store WIBU licence XML under ``Licenses/`` and ``slot/licence.dll``.
Normal config restore never overwrites a live licence; this module archives licence
bytes at scan time and supports an explicit restore when a B2U or licence pack
replaced the dongle files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import string
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config_scanner.build_version import scan_target_path
from config_scanner.machine_identity import (
    egm_serials_match,
    is_foreign_licence_xml,
    is_licence_path,
    licensee_id_from_licence_bytes,
    serial_from_licence_bytes,
)
from config_scanner.scanner import (
    SNAPSHOT_FILES_SUBDIR,
    load_build_info,
    load_manifest,
    snapshot_content_root,
)
from config_scanner.slot_setup import goldclub_root_from_target
from config_scanner.software_compat import SNAPSHOT_SOFTWARE_SUBDIR
from network.lab_access import safe_join_under

ROLLBACK_LICENCE_SUBDIR = "rollback_licence"
ROLLBACK_LICENCE_FILES = "files"
ROLLBACK_LICENCE_MANIFEST = "manifest.json"

# BiOS accept bind files — never archived or restored (see Apply-CsRestore.ps1).
_BIOS_BIND_NAMES = frozenset(
    {
        "License.lic",
        "License_BACKUP.lic",
        "Session.lic",
    }
)

_HASH_LICENCE_RE = re.compile(r"^[0-9A-Fa-f]{64}\.xml$")
_DLL_NAMES = ("licence.dll", "license.dll")
_GENERIC_LICENCE_DIRS = (
    "Licenses",
    "Licences",
    "licence",
    "Licence",
    "license",
    "License",
)
_PACK_LICENCE_DIRS = (
    "Licences_PR",
    "Licences_SlotQA",
    "Licences_SlotQA_01",
)
_USB_SHARE_NAMES = ("USB", "USB_Remote")
# Lab stick that holds the Slot QA pack for Live Push (same host as the
# default live cabinet). Not a drive letter — UNC so the workstation exe
# still sees the pack when the USB is plugged into that EGM.
DEFAULT_LICENCE_USB_HOST = "10.0.0.111"
_LICENCE_FOLDER_RE = re.compile(
    r"li[cs]+en[cs]*e?s?",
    re.IGNORECASE,
)

_SLOT_LICENCE_GLOBS: tuple[str, ...] = (
    "Licenses/*.xml",
    "Licences/*.xml",
    "config/licences/**/*.xml",
    "config/licenses/**/*.xml",
    "slot/Licence*.xml",
    "slot/License*.xml",
    "Licence*.xml",
    "License*.xml",
    "slot/licence.dll",
    "slot/license.dll",
    "licence.dll",
    "license.dll",
)


def rollback_licence_dir(snapshot_dir: Path) -> Path:
    return Path(snapshot_dir) / ROLLBACK_LICENCE_SUBDIR


def has_rollback_licence_state(snapshot_dir: Path) -> bool:
    manifest = rollback_licence_dir(snapshot_dir) / ROLLBACK_LICENCE_MANIFEST
    return manifest.is_file()


def _normalize_rel(relative_path: str) -> str:
    return (relative_path or "").replace("\\", "/").strip("/")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_slot_licence_rel(relative_path: str) -> bool:
    norm = _normalize_rel(relative_path)
    if not norm:
        return False
    if norm.casefold().startswith("bios/license/"):
        return False
    name = Path(norm).name
    if name in _BIOS_BIND_NAMES:
        return False
    if is_licence_path(norm):
        return True
    from config_scanner.path_mirror import licence_mirror_key

    return licence_mirror_key(norm) is not None


def _collect_live_licence_paths(root: Path) -> list[Path]:
    found: dict[str, Path] = {}
    root = Path(root)
    for pattern in _SLOT_LICENCE_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = _normalize_rel(str(path.relative_to(root)))
            if _is_slot_licence_rel(rel):
                found[rel] = path
    return [found[key] for key in sorted(found)]


def _archive_name(rel: str) -> str:
    return rel.replace("/", "__")


def _rel_from_archive_name(name: str) -> str:
    return name.replace("__", "/")


def capture_licence_state_for_rollback(dest_root: Path, snapshot_dir: Path) -> list[str]:
    """Archive live slot licence files into a snapshot (presave / compare baseline)."""
    dest = goldclub_root_from_target(dest_root)
    out_root = rollback_licence_dir(snapshot_dir)
    files_root = out_root / ROLLBACK_LICENCE_FILES
    files_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    notes: list[str] = []

    from config_scanner.path_mirror import select_canonical_licence_paths

    live_paths = _collect_live_licence_paths(dest)
    keep = {
        _normalize_rel(rel).casefold()
        for rel in select_canonical_licence_paths(
            _normalize_rel(str(path.relative_to(dest))) for path in live_paths
        )
    }
    for path in live_paths:
        rel = _normalize_rel(str(path.relative_to(dest)))
        if rel.casefold() not in keep:
            continue
        archived = _archive_name(rel)
        entry: dict[str, object] = {"rel": rel, "present": True}
        try:
            data = path.read_bytes()
        except OSError as exc:
            entry["present"] = False
            entry["error"] = str(exc)
            notes.append(f"rollback licence: could not read {rel}")
        else:
            archive_path = files_root / archived
            archive_path.write_bytes(data)
            entry["archived"] = archived
            entry["size"] = len(data)
            entry["sha256"] = _sha256(data)
            if rel.casefold().endswith(".xml"):
                entry["serial"] = serial_from_licence_bytes(data)
                entry["licenseeId"] = licensee_id_from_licence_bytes(data)
            notes.append(f"captured licence {rel} ({len(data)} B)")
        entries.append(entry)

    if not entries:
        notes.append("rollback licence: no slot licence files on machine")

    manifest = {
        "version": 1,
        "paths": entries,
        "capturedAt": datetime.now().isoformat(),
    }
    (out_root / ROLLBACK_LICENCE_MANIFEST).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return notes


def _file_state_from_bytes(rel: str, data: bytes | None) -> dict[str, object]:
    if data is None:
        return {"relativePath": rel, "present": False}
    state: dict[str, object] = {
        "relativePath": rel,
        "present": True,
        "size": len(data),
        "sha256": _sha256(data),
    }
    if rel.casefold().endswith(".xml"):
        state["serial"] = serial_from_licence_bytes(data)
        state["licenseeId"] = licensee_id_from_licence_bytes(data)
    return state


def _read_archived_bytes(snapshot_dir: Path, rel: str) -> bytes | None:
    content_root = snapshot_content_root(snapshot_dir)
    if content_root is not None:
        path = content_root / Path(rel.replace("\\", "/"))
        try:
            if path.is_file():
                return path.read_bytes()
        except OSError:
            pass
    software = snapshot_dir / SNAPSHOT_SOFTWARE_SUBDIR
    if software.is_dir():
        for candidate in (rel, f"slot/{Path(rel).name}" if "/" not in rel else None):
            if not candidate:
                continue
            path = software / Path(candidate.replace("\\", "/"))
            try:
                if path.is_file():
                    return path.read_bytes()
            except OSError:
                continue
    rollback = rollback_licence_dir(snapshot_dir) / ROLLBACK_LICENCE_FILES
    archived = rollback / _archive_name(rel)
    try:
        if archived.is_file():
            return archived.read_bytes()
    except OSError:
        pass
    return None


def _licence_states_from_snapshot(snapshot_dir: Path) -> dict[str, dict[str, object]]:
    states: dict[str, dict[str, object]] = {}

    if has_rollback_licence_state(snapshot_dir):
        manifest_path = rollback_licence_dir(snapshot_dir) / ROLLBACK_LICENCE_MANIFEST
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            paths = manifest.get("paths")
            if isinstance(paths, list):
                for item in paths:
                    if not isinstance(item, dict):
                        continue
                    rel = _normalize_rel(str(item.get("rel") or ""))
                    if not rel or not _is_slot_licence_rel(rel):
                        continue
                    if not item.get("present"):
                        states[rel] = {"relativePath": rel, "present": False}
                        continue
                    archived = str(item.get("archived") or "").strip()
                    data = None
                    if archived:
                        src = (
                            rollback_licence_dir(snapshot_dir)
                            / ROLLBACK_LICENCE_FILES
                            / archived
                        )
                        try:
                            if src.is_file():
                                data = src.read_bytes()
                        except OSError:
                            pass
                    states[rel] = _file_state_from_bytes(rel, data)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    try:
        manifest = load_manifest(snapshot_dir)
    except (OSError, ValueError, TypeError, KeyError):
        manifest = None
    if manifest is not None:
        for entry in manifest.files:
            rel = _normalize_rel(entry.relative_path)
            if not _is_slot_licence_rel(rel):
                continue
            data = _read_archived_bytes(snapshot_dir, rel)
            current = states.get(rel)
            if current and current.get("present") and data is None:
                continue
            states[rel] = _file_state_from_bytes(rel, data)

    for rel in ("slot/licence.dll", "licence.dll"):
        if rel in states and states[rel].get("present"):
            continue
        data = _read_archived_bytes(snapshot_dir, rel)
        if data is not None:
            states[rel] = _file_state_from_bytes(rel, data)

    return states


@dataclass(frozen=True)
class SlotLicenceChange:
    relative_path: str
    status: str  # added | removed | modified | unchanged
    baseline_size: int | None = None
    target_size: int | None = None
    baseline_licensee: str | None = None
    target_licensee: str | None = None


@dataclass(frozen=True)
class SlotLicenceCompareResult:
    changed: bool
    changes: tuple[SlotLicenceChange, ...]
    warnings: tuple[str, ...]
    baseline_has_rollback: bool
    target_has_rollback: bool


def compare_slot_licence_between_snapshots(
    baseline_dir: Path,
    target_dir: Path,
) -> SlotLicenceCompareResult:
    """Diff slot licence files between two snapshots (manifest + rollback + software)."""
    baseline_dir = Path(baseline_dir)
    target_dir = Path(target_dir)
    base_states = _licence_states_from_snapshot(baseline_dir)
    tgt_states = _licence_states_from_snapshot(target_dir)
    all_rels = sorted(set(base_states) | set(tgt_states))

    changes: list[SlotLicenceChange] = []
    warnings: list[str] = []

    for rel in all_rels:
        base = base_states.get(rel, {"relativePath": rel, "present": False})
        tgt = tgt_states.get(rel, {"relativePath": rel, "present": False})
        base_present = bool(base.get("present"))
        tgt_present = bool(tgt.get("present"))
        if base_present and tgt_present:
            same = base.get("sha256") == tgt.get("sha256")
            status = "unchanged" if same else "modified"
        elif base_present:
            status = "removed"
        elif tgt_present:
            status = "added"
        else:
            status = "unchanged"
        if status == "unchanged":
            continue
        changes.append(
            SlotLicenceChange(
                relative_path=rel,
                status=status,
                baseline_size=int(base["size"]) if base.get("size") is not None else None,
                target_size=int(tgt["size"]) if tgt.get("size") is not None else None,
                baseline_licensee=str(base["licenseeId"]) if base.get("licenseeId") else None,
                target_licensee=str(tgt["licenseeId"]) if tgt.get("licenseeId") else None,
            )
        )

    changed = bool(changes)
    if changed:
        parts: list[str] = []
        for item in changes[:6]:
            detail = item.relative_path
            if item.status == "modified":
                detail += f" ({item.baseline_size} B → {item.target_size} B"
                if item.baseline_licensee or item.target_licensee:
                    detail += f"; WIBU {item.baseline_licensee or '?'} → {item.target_licensee or '?'}"
                detail += ")"
            elif item.status == "added":
                detail += f" (added, {item.target_size or '?'} B)"
            else:
                detail += " (removed in target)"
            parts.append(detail)
        extra = f" (+{len(changes) - 6} more)" if len(changes) > 6 else ""
        warnings.append(
            "Slot licence changed between snapshots: " + "; ".join(parts) + extra
        )

    baseline_info = load_build_info(baseline_dir)
    target_info = load_build_info(target_dir)
    base_serial = (baseline_info.machine_serial or "").strip() or None
    tgt_serial = (target_info.machine_serial or "").strip() or None
    if base_serial and tgt_serial and not egm_serials_match(base_serial, tgt_serial):
        warnings.append(
            f"Snapshots are from different EGMs ({base_serial} vs {tgt_serial}) — "
            "licence restore only when serials match."
        )

    return SlotLicenceCompareResult(
        changed=changed,
        changes=tuple(changes),
        warnings=tuple(warnings),
        baseline_has_rollback=has_rollback_licence_state(baseline_dir),
        target_has_rollback=has_rollback_licence_state(target_dir),
    )


def _licence_sources_for_restore(snapshot_dir: Path) -> list[tuple[str, Path]]:
    """Ordered (rel, src_path) pairs to write onto the live machine."""
    sources: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def _add(rel: str, path: Path) -> None:
        norm = _normalize_rel(rel)
        if not norm or norm in seen or not _is_slot_licence_rel(norm):
            return
        if not path.is_file():
            return
        seen.add(norm)
        sources.append((norm, path))

    if has_rollback_licence_state(snapshot_dir):
        manifest_path = rollback_licence_dir(snapshot_dir) / ROLLBACK_LICENCE_MANIFEST
        files_root = rollback_licence_dir(snapshot_dir) / ROLLBACK_LICENCE_FILES
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            paths = manifest.get("paths")
            if isinstance(paths, list):
                for item in paths:
                    if not isinstance(item, dict) or not item.get("present"):
                        continue
                    rel = _normalize_rel(str(item.get("rel") or ""))
                    archived = str(item.get("archived") or "").strip()
                    if rel and archived:
                        _add(rel, files_root / archived)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    content_root = snapshot_content_root(snapshot_dir)
    if content_root is not None:
        try:
            manifest = load_manifest(snapshot_dir)
        except (OSError, ValueError, TypeError, KeyError):
            manifest = None
        if manifest is not None:
            for entry in manifest.files:
                rel = _normalize_rel(entry.relative_path)
                if not _is_slot_licence_rel(rel):
                    continue
                _add(rel, content_root / Path(rel.replace("\\", "/")))

    software = snapshot_dir / SNAPSHOT_SOFTWARE_SUBDIR
    if software.is_dir():
        for rel in ("slot/licence.dll", "licence.dll"):
            path = software / Path(rel.replace("\\", "/"))
            _add(rel, path)

    return sources


def restore_slot_licence_from_snapshot(
    dest_root: Path,
    snapshot_dir: Path,
    *,
    live_serial: str | None = None,
    snapshot_serial: str | None = None,
) -> list[str]:
    """Overwrite live slot licence files from a snapshot (explicit user action)."""
    if live_serial and snapshot_serial and not egm_serials_match(
        live_serial, snapshot_serial
    ):
        return [
            f"Blocked: snapshot serial {snapshot_serial!r} does not match "
            f"live EGM {live_serial!r}."
        ]

    dest = goldclub_root_from_target(dest_root)
    notes: list[str] = []
    sources = _licence_sources_for_restore(snapshot_dir)
    if not sources:
        return ["No slot licence files in snapshot to restore."]

    for rel, src in sources:
        try:
            dest_path = safe_join_under(dest, rel)
        except ValueError as exc:
            notes.append(f"{rel}: {exc}")
            continue
        try:
            data = src.read_bytes()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(data)
            notes.append(f"restored {rel} ({len(data)} B)")
        except OSError as exc:
            notes.append(f"{rel}: {exc}")
    return notes


def restore_slot_licence_to_target(
    snapshot_dir: Path,
    scan_target: str,
    *,
    snapshot_serial: str | None = None,
) -> list[str]:
    """Restore slot licence from snapshot onto a scan target path."""
    from config_scanner.build_version import read_machine_serial_from_target

    dest_root = scan_target_path(scan_target)
    live_serial = read_machine_serial_from_target(scan_target)
    return restore_slot_licence_from_snapshot(
        dest_root,
        snapshot_dir,
        live_serial=live_serial,
        snapshot_serial=snapshot_serial,
    )


def is_slot_licence_xml_name(name: str) -> bool:
    """True for Licence*.xml / License*.xml and 64-hex WIBU dump names."""
    lowered = (name or "").casefold()
    if not lowered.endswith(".xml"):
        return False
    if lowered.startswith("licence") or lowered.startswith("license"):
        return True
    return bool(_HASH_LICENCE_RE.match(name or ""))


def _list_licence_xml(directory: Path) -> list[Path]:
    out: list[Path] = []
    try:
        if not directory.is_dir():
            return out
        entries = list(directory.iterdir())
    except OSError:
        return out
    for path in entries:
        try:
            if path.is_file() and is_slot_licence_xml_name(path.name):
                out.append(path)
        except OSError:
            continue
    return out


def _find_licence_dll(directory: Path) -> Path | None:
    try:
        if not directory.is_dir():
            return None
    except OSError:
        return None
    for name in _DLL_NAMES:
        candidate = directory / name
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


@dataclass(frozen=True)
class LiveLicenceStatus:
    """What OneHand can see vs what is only in Licenses/."""

    playable_xml: tuple[str, ...]
    licenses_dir_xml: tuple[str, ...]
    dll_rel: str
    playable: bool
    needs_push: bool
    can_mirror: bool
    detail: str


def is_licence_folder_name(name: str) -> bool:
    """True for Licenses / Licences / licence and common misspellings (Lisence, liscence)."""
    letters = re.sub(r"[^a-z]", "", (name or "").casefold())
    if not letters or letters in {"lic", "licensekey"}:
        return False
    if letters in {"license", "licence", "licenses", "licences", "lisence", "liscence"}:
        return True
    return bool(_LICENCE_FOLDER_RE.search(letters))


def _goldclub_licence_store_dirs(root: Path) -> list[Path]:
    """Immediate licence/licenses folders on a Goldclub root (misspellings included)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path).replace("/", "\\").casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    for name in _GENERIC_LICENCE_DIRS:
        add(root / name)
    try:
        for child in root.iterdir():
            try:
                if child.is_dir() and is_licence_folder_name(child.name):
                    add(child)
            except OSError:
                continue
    except OSError:
        pass
    return out


def inspect_live_licences(goldclub: Path) -> LiveLicenceStatus:
    """Detect licence XML / dll on a Goldclub root (no BIOS License.lic)."""
    root = goldclub_root_from_target(goldclub)
    playable: list[str] = []
    for path in _list_licence_xml(root / "slot"):
        playable.append(f"slot/{path.name}")
    licenses_dir: list[str] = []
    for folder in _goldclub_licence_store_dirs(root):
        try:
            rel_dir = str(folder.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel_dir = folder.name
        for path in _list_licence_xml(folder):
            licenses_dir.append(f"{rel_dir}/{path.name}")
    root_xml = _list_licence_xml(root)
    dll_rel = ""
    dll = _find_licence_dll(root / "slot") or _find_licence_dll(root)
    if dll is not None:
        try:
            dll_rel = str(dll.relative_to(root)).replace("\\", "/")
        except ValueError:
            dll_rel = dll.name
    playable_ok = bool(playable)
    has_any = playable_ok or bool(licenses_dir) or bool(root_xml) or bool(dll_rel)
    needs_push = not playable_ok
    can_mirror = needs_push and has_any
    if playable_ok:
        detail = (
            f"Licence XML next to OneHand ({len(playable)} file(s)). "
            "Live push will not overwrite it."
        )
    elif can_mirror:
        n = len(licenses_dir) or (1 if dll_rel else 0)
        detail = (
            f"No licence next to OneHand. {n} file(s) are in a licence/licenses "
            "folder (or licence.dll) — Apply copies them into slot\\."
        )
    else:
        detail = (
            "No licence next to OneHand. Apply can push from a USB "
            "licence/licenses folder if one is found."
        )
    return LiveLicenceStatus(
        playable_xml=tuple(playable),
        licenses_dir_xml=tuple(licenses_dir),
        dll_rel=dll_rel,
        playable=playable_ok,
        needs_push=needs_push,
        can_mirror=can_mirror,
        detail=detail,
    )


def _licence_source_dirs(source: Path) -> list[Path]:
    dirs: list[Path] = []
    for base in (source, source / "Content" / "tmp", source / "tmp"):
        try:
            if not base.is_dir():
                continue
        except OSError:
            continue
        dirs.append(base)
        dirs.append(base / "slot")
        dirs.extend(_goldclub_licence_store_dirs(base))
    return dirs


def discover_licence_source_files(
    source: Path,
    *,
    skip_foreign: bool = True,
) -> dict[str, Path]:
    """Map file name → source path (Licenses XML first, then slot, then root)."""
    found: dict[str, Path] = {}
    xml_dirs = []
    dll_dirs = []
    for directory in _licence_source_dirs(source):
        name = directory.name.casefold()
        if is_licence_folder_name(directory.name) and directory.name.casefold() != "slot":
            xml_dirs.append(directory)
        elif name == "slot":
            xml_dirs.append(directory)
            dll_dirs.append(directory)
        else:
            xml_dirs.append(directory)
            dll_dirs.append(directory)
    # Prefer Licenses/ over slot/ over root so a pack-in-Licenses is the source
    # when mirroring onto a machine that only has that folder.
    ordered_xml = []
    seen: set[str] = set()
    for directory in xml_dirs:
        key = str(directory).casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered_xml.append(directory)
    ordered_xml.sort(
        key=lambda p: (
            0
            if is_licence_folder_name(p.name) and p.name.casefold() != "slot"
            else 1
            if p.name.casefold() == "slot"
            else 2
        )
    )
    for directory in ordered_xml:
        for path in _list_licence_xml(directory):
            if path.name in found:
                continue
            if skip_foreign:
                try:
                    if is_foreign_licence_xml(path):
                        continue
                except OSError:
                    continue
            found[path.name] = path
    for directory in dll_dirs:
        dll = _find_licence_dll(directory)
        if dll is None:
            continue
        found.setdefault("licence.dll", dll)
        break
    return found


@dataclass(frozen=True)
class LicencePackHit:
    """A folder of licence XML / licence.dll suitable as a live-push source."""

    root: Path
    files: tuple[str, ...]
    origin: str  # usb

    @property
    def file_count(self) -> int:
        return len(self.files)


_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3


def _path_key(path: Path) -> str:
    return str(path).replace("/", "\\").casefold().rstrip("\\")


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        a = left.resolve()
        b = right.resolve()
    except OSError:
        a, b = Path(left), Path(right)
    ka, kb = _path_key(a), _path_key(b)
    return ka == kb or ka.startswith(kb + "\\") or kb.startswith(ka + "\\")


def _is_windows_drive_root(path: Path) -> bool:
    text = str(path).replace("/", "\\").rstrip("\\")
    return len(text) == 2 and text[1] == ":"


def _is_os_drive_root(path: Path) -> bool:
    return _is_windows_drive_root(path) and path.drive.upper() == "C:"


def _drive_type(root: str) -> int:
    if os.name != "nt":
        return 0
    try:
        import ctypes

        drive = root if root.endswith("\\") else root + "\\"
        return int(ctypes.windll.kernel32.GetDriveTypeW(drive))
    except (AttributeError, OSError, ValueError, TypeError):
        return 0


def _looks_like_licence_pack_folder(name: str) -> bool:
    if not is_licence_folder_name(name):
        return False
    return name.casefold() not in {n.casefold() for n in _GENERIC_LICENCE_DIRS}


def _iter_named_licence_children(base: Path) -> list[Path]:
    found: list[Path] = []
    if _is_os_drive_root(base):
        return found
    try:
        if not base.is_dir():
            return found
        for child in base.iterdir():
            try:
                if child.is_dir() and is_licence_folder_name(child.name):
                    found.append(child)
            except OSError:
                continue
    except OSError:
        return found
    return found


def licence_layout_candidates(
    base: Path, *, include_goldclub: bool = True
) -> list[Path]:
    """Shallow GoldClub / companion-pack folders under *base* (no deep walk)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = _path_key(path)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(path)

    add(Path(base))
    for name in (*_GENERIC_LICENCE_DIRS, *_PACK_LICENCE_DIRS):
        add(Path(base) / name)
    if include_goldclub:
        add(Path(base) / "GoldClub")
        add(Path(base) / "Goldclub")
        add(Path(base) / "ConfigScanner")
        add(Path(base) / "Content" / "tmp")
    for child in _iter_named_licence_children(Path(base)):
        add(child)
    return out


def _unc_host(path: Path | str | None) -> str | None:
    text = str(path or "").strip().replace("/", "\\")
    match = re.match(r"^\\\\([^\\]+)\\", text, re.IGNORECASE)
    return match.group(1) if match else None


def usb_share_licence_roots(host: str) -> list[Path]:
    """Shallow licence folders on ``\\\\host\\USB`` and ``USB_Remote``."""
    name = (host or "").strip().strip("\\")
    if not name or "\\" in name or "/" in name:
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for share in _USB_SHARE_NAMES:
        for path in licence_layout_candidates(Path(rf"\\{name}\{share}")):
            key = _path_key(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def default_usb_licence_roots(
    *,
    extra_hosts: Iterable[str] | None = None,
) -> list[Path]:
    """Usual licence / licenses folders on USB sticks (and the drive this exe is on).

    Also includes ``\\\\<host>\\USB`` for the loaded cabinet, the exe UNC host,
    and the lab licence stick (``DEFAULT_LICENCE_USB_HOST``) so a workstation
    run still finds a pack left on the EGM USB.
    """
    out: list[Path] = []
    seen: set[str] = set()

    def add_many(paths: Iterable[Path]) -> None:
        for path in paths:
            key = _path_key(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            dtype = _drive_type(f"{letter}:\\")
            if dtype == _DRIVE_REMOVABLE:
                add_many(licence_layout_candidates(root))
                continue
            if dtype == _DRIVE_FIXED and letter != "C":
                for name in (*_GENERIC_LICENCE_DIRS, *_PACK_LICENCE_DIRS):
                    add_many([root / name])
                add_many(
                    child
                    for child in _iter_named_licence_children(root)
                    if is_licence_folder_name(child.name)
                )
    try:
        from app_paths import app_install_dir

        install = app_install_dir()
    except OSError:
        install = None
    if install is not None:
        add_many(licence_layout_candidates(install))
        parent = install.parent
        if not _is_os_drive_root(parent):
            add_many(licence_layout_candidates(parent))
    hosts: list[str] = []
    if extra_hosts is not None:
        hosts.extend(str(h).strip() for h in extra_hosts if str(h).strip())
    if install is not None:
        inst_host = _unc_host(install)
        if inst_host:
            hosts.append(inst_host)
    hosts.append(DEFAULT_LICENCE_USB_HOST)
    seen_hosts: set[str] = set()
    for host in hosts:
        key = host.casefold()
        if key in seen_hosts:
            continue
        seen_hosts.add(key)
        add_many(usb_share_licence_roots(host))
    return out


def default_embedded_licence_roots() -> list[Path]:
    """Same as the portable exe-dir scan (kept for tests)."""
    return default_usb_licence_roots()


def _best_licence_pack(
    candidates: Iterable[Path],
    *,
    skip_roots: Iterable[Path],
    origin: str,
) -> LicencePackHit | None:
    skip = [Path(p) for p in skip_roots]
    best: LicencePackHit | None = None
    best_rank: tuple[int, int, int] | None = None
    for raw in candidates:
        path = Path(raw)
        try:
            if not path.exists():
                continue
        except OSError:
            continue
        if any(_paths_overlap(path, skipped) for skipped in skip):
            continue
        files = discover_licence_source_files(path)
        if not files:
            continue
        xml_n = sum(1 for name in files if name.casefold().endswith(".xml"))
        dll_n = 1 if any(name.casefold() in _DLL_NAMES for name in files) else 0
        if xml_n == 0 and dll_n == 0:
            continue
        dedicated = 0 if is_licence_folder_name(path.name) else 1
        rank = (dedicated, -xml_n, -dll_n)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = LicencePackHit(path, tuple(sorted(files)), origin)
    return best


def discover_preferred_licence_pack(
    *,
    skip_roots: Iterable[Path] = (),
    usb_roots: Iterable[Path] | None = None,
    embedded_roots: Iterable[Path] | None = None,
    extra_hosts: Iterable[str] | None = None,
) -> LicencePackHit | None:
    """USB licence / licenses folders first (misspellings included).

    Never walks the live cabinet tree passed in ``skip_roots``. BIOS ``License.lic``
    is not a source.
    """
    usb = (
        list(usb_roots)
        if usb_roots is not None
        else default_usb_licence_roots(extra_hosts=extra_hosts)
    )
    hit = _best_licence_pack(usb, skip_roots=skip_roots, origin="usb")
    if hit is not None:
        return hit
    extra = list(embedded_roots) if embedded_roots is not None else []
    return _best_licence_pack(extra, skip_roots=skip_roots, origin="usb")


def push_missing_licences(
    dest_goldclub: Path,
    *,
    source: Path | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Copy licence XML + dll only where the dest file is missing.

    Never overwrites a live licence. ``source=None`` mirrors from the dest
    tree (Licenses/ → slot/). BIOS ``License.lic`` is never copied.
    """
    dest = goldclub_root_from_target(dest_goldclub)
    status = inspect_live_licences(dest)
    if status.playable and _find_licence_dll(dest / "slot") is not None:
        return (), ("licences already present next to OneHand",), ()
    src_root = Path(source) if source is not None else dest
    try:
        skip_foreign = src_root.resolve() != dest.resolve()
    except OSError:
        skip_foreign = source is not None
    files = discover_licence_source_files(src_root, skip_foreign=skip_foreign)
    if not files:
        return (), (), ("No licence XML or licence.dll in the source folder",)

    dest_dirs = [dest / "slot", dest, dest / "Licenses"]
    written: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    def _copy_one(src: Path, dest_path: Path, rel: str) -> None:
        try:
            safe_join_under(dest, rel)
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")
            return
        try:
            if dest_path.is_file():
                skipped.append(f"{rel} already present")
                return
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
            return
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_path)
            written.append(rel)
        except OSError as exc:
            errors.append(f"{rel}: {exc}")

    for name, src in sorted(files.items()):
        if name.casefold() in _DLL_NAMES:
            _copy_one(src, dest / "slot" / "licence.dll", "slot/licence.dll")
            continue
        for dest_dir in dest_dirs:
            rel = str((dest_dir / name).relative_to(dest)).replace("\\", "/")
            _copy_one(src, dest_dir / name, rel)
    return tuple(written), tuple(skipped), tuple(errors)

