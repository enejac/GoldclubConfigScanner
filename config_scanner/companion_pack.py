"""Companion Updates packs (GameStar ``Updates`` style, not full Country Selectors).

Kinds mirror ``\\\\10.0.0.249\\WinSystems_SLOT\\_B2U`` / ``GameStar 2.0.1\\Updates``:

| Kind | Typical source | Apply target |
|------|----------------|--------------|
| keyboards | CS-Keyboards-00 | C:\\Goldclub via install.json leaves |
| bills | BillsTTD-00 | C:\\Goldclub\\slot (+ optional OneHandConfigurer) |
| dallas | Dallas-B2 | Launch OneHandConfigurer only |
| licences | Licences_PR | C:\\Goldclub\\Licenses + slot (explicit opt-in) |
| onehand | OneHand_Update-00 | C:\\Goldclub\\slot |
| theme_overlay | Clovers_Disable-00 / Tuatankhamen_Config-00 | C:\\Goldclub\\slot (gameselector / theme XML) |
| oticket | OffLineTicket_* | C:\\Goldclub\\bios\\etc\\application\\slot\\oticket.xml |
| serial_mux | SerialInterface / OLD_MUX | **G:\\** only (explicit opt-in) |

Never writes serialport ``layout.json`` / ``locations.json``.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from config_scanner.cs_catalog import (
    apply_country_leaf,
    discover_leaves,
    filter_leaves,
    is_cs_forbidden_rel,
    resolve_country_selector_tool,
)

MANIFEST_VERSION = 1
MANIFEST_NAME = "companion.json"


class CompanionKind(str, Enum):
    KEYBOARDS = "keyboards"
    BILLS = "bills"
    DALLAS = "dallas"
    LICENCES = "licences"
    ONEHAND = "onehand"
    THEME_OVERLAY = "theme_overlay"
    OTICKET = "oticket"
    SERIAL_MUX = "serial_mux"


@dataclass
class CompanionManifest:
    version: int = MANIFEST_VERSION
    kind: CompanionKind = CompanionKind.ONEHAND
    label: str = ""
    source_name: str = ""
    run_onehand_configurer: bool = False
    reboot_after: bool = False
    # Relative payload paths inside the companion pack directory.
    payload_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "kind": self.kind.value,
            "label": self.label,
            "source_name": self.source_name,
            "run_onehand_configurer": self.run_onehand_configurer,
            "reboot_after": self.reboot_after,
            "payload_notes": list(self.payload_notes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompanionManifest:
        kind_raw = str(data.get("kind") or CompanionKind.ONEHAND.value)
        try:
            kind = CompanionKind(kind_raw)
        except ValueError:
            kind = CompanionKind.ONEHAND
        return cls(
            version=int(data.get("version") or MANIFEST_VERSION),
            kind=kind,
            label=str(data.get("label") or ""),
            source_name=str(data.get("source_name") or ""),
            run_onehand_configurer=bool(data.get("run_onehand_configurer", False)),
            reboot_after=bool(data.get("reboot_after", False)),
            payload_notes=[str(x) for x in (data.get("payload_notes") or [])],
        )


@dataclass(frozen=True)
class CompanionApplyResult:
    written: tuple[str, ...]
    skipped: tuple[str, ...]
    errors: tuple[str, ...]
    notes: tuple[str, ...]


def save_manifest(manifest: CompanionManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_manifest(path: Path) -> CompanionManifest:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("companion.json must be an object")
    return CompanionManifest.from_dict(data)


def detect_kind_from_source(source: Path) -> CompanionKind:
    """Best-effort classify an unpacked _B2U Updates folder."""
    source = Path(source)
    name = source.name.casefold()
    tmp = _find_tmp(source)
    if "keyboard" in name:
        return CompanionKind.KEYBOARDS
    if "bill" in name or name.startswith("ttd") or "billsttd" in name:
        return CompanionKind.BILLS
    if "dallas" in name:
        return CompanionKind.DALLAS
    if "licence" in name or "license" in name:
        return CompanionKind.LICENCES
    if "oticket" in name or "offlineticket" in name or "offline_ticket" in name:
        return CompanionKind.OTICKET
    if "clover" in name or "tuatank" in name or "tutankhamen" in name:
        return CompanionKind.THEME_OVERLAY
    if "trialreset" in name:
        return CompanionKind.ONEHAND
    if "onehand" in name:
        return CompanionKind.ONEHAND
    if "serial" in name or "mux" in name:
        return CompanionKind.SERIAL_MUX

    if tmp is not None:
        if (tmp / "CountrySelectorTool" / "data").is_dir():
            return CompanionKind.KEYBOARDS
        if (tmp / "Licenses").is_dir() or (tmp / "Licences").is_dir():
            return CompanionKind.LICENCES
        if (tmp / "OneHandConfigurer.exe").is_file() and not (tmp / "slot").is_dir():
            return CompanionKind.DALLAS
        if (tmp / "OneHandConfigurer.exe").is_file() and (tmp / "slot").is_dir():
            return CompanionKind.BILLS
        if (tmp / "slot" / "OneHand.exe").is_file():
            return CompanionKind.ONEHAND
        if (tmp / "oticket.xml").is_file() or (tmp / "bios").is_dir():
            return CompanionKind.OTICKET
        if (tmp / "slot").is_dir() and not (tmp / "OneHandConfigurer.exe").is_file():
            return CompanionKind.THEME_OVERLAY
        if (tmp / "maintenance").is_dir() or (tmp / "platform").is_dir():
            return CompanionKind.SERIAL_MUX
    return CompanionKind.ONEHAND


def _find_tmp(source: Path) -> Path | None:
    for cand in (
        source / "Content" / "tmp",
        source / "tmp",
        source,
    ):
        if cand.is_dir():
            return cand
    return None


def _copy_tree_filtered(src: Path, dest_root: Path) -> tuple[list[str], list[str], list[str]]:
    written: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    if not src.exists():
        errors.append(f"missing source {src}")
        return written, skipped, errors
    if src.is_file():
        rel = src.name
        if is_cs_forbidden_rel(rel):
            skipped.append(f"{rel}: forbidden")
            return written, skipped, errors
        dest_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_root)
        written.append(str(dest_root))
        return written, skipped, errors
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        if is_cs_forbidden_rel(rel):
            skipped.append(f"{rel}: forbidden serialport map")
            continue
        dest = dest_root / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            written.append(dest.as_posix())
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
    return written, skipped, errors


def stage_companion_from_source(
    source: Path,
    pack_dir: Path,
    *,
    kind: CompanionKind | None = None,
    label: str = "",
) -> CompanionManifest:
    """Copy payload from an unpacked Updates/_B2U folder into ``pack_dir``."""
    source = Path(source)
    kind = kind or detect_kind_from_source(source)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    tmp = _find_tmp(source)
    notes: list[str] = []

    if kind == CompanionKind.KEYBOARDS:
        tool = resolve_country_selector_tool(source)
        dest_tool = pack_dir / "CountrySelectorTool"
        shutil.copytree(tool / "data", dest_tool / "data")
        notes.append("CountrySelectorTool/data")
    elif kind == CompanionKind.SERIAL_MUX:
        if tmp is None:
            raise FileNotFoundError(f"no tmp payload in {source}")
        payload = pack_dir / "g_payload"
        shutil.copytree(tmp, payload)
        notes.append("g_payload/")
        reboot = source / "Content" / "ReBoot.exe"
        if not reboot.is_file():
            reboot = source / "ReBoot.exe"
        if reboot.is_file():
            shutil.copy2(reboot, pack_dir / "ReBoot.exe")
            notes.append("ReBoot.exe")
    elif kind == CompanionKind.LICENCES:
        if tmp is None:
            raise FileNotFoundError(f"no tmp payload in {source}")
        for name in ("Licenses", "Licences"):
            src = tmp / name
            if src.is_dir():
                shutil.copytree(src, pack_dir / "Licenses")
                notes.append("Licenses/")
                break
        slot = tmp / "slot"
        if slot.is_dir():
            shutil.copytree(slot, pack_dir / "slot")
            notes.append("slot/")
    elif kind == CompanionKind.DALLAS:
        if tmp is None:
            raise FileNotFoundError(f"no tmp payload in {source}")
        cfg = pack_dir / "configurer"
        cfg.mkdir()
        for name in ("OneHandConfigurer.exe", "OneHandConfigurer.exe.config"):
            src = tmp / name
            if src.is_file():
                shutil.copy2(src, cfg / name)
                notes.append(f"configurer/{name}")
        lib = tmp / "lib"
        if lib.is_dir():
            shutil.copytree(lib, cfg / "lib")
            notes.append("configurer/lib/")
    elif kind in (CompanionKind.BILLS, CompanionKind.ONEHAND, CompanionKind.THEME_OVERLAY):
        if tmp is None:
            raise FileNotFoundError(f"no tmp payload in {source}")
        slot = tmp / "slot"
        if slot.is_dir():
            shutil.copytree(slot, pack_dir / "slot")
            notes.append("slot/")
        if kind == CompanionKind.BILLS:
            cfg = pack_dir / "configurer"
            if (tmp / "OneHandConfigurer.exe").is_file():
                cfg.mkdir(exist_ok=True)
                shutil.copy2(tmp / "OneHandConfigurer.exe", cfg / "OneHandConfigurer.exe")
                notes.append("configurer/OneHandConfigurer.exe")
                conf = tmp / "OneHandConfigurer.exe.config"
                if conf.is_file():
                    shutil.copy2(conf, cfg / "OneHandConfigurer.exe.config")
                lib = tmp / "lib"
                if lib.is_dir():
                    shutil.copytree(lib, cfg / "lib")
                    notes.append("configurer/lib/")
    elif kind == CompanionKind.OTICKET:
        if tmp is None:
            raise FileNotFoundError(f"no tmp payload in {source}")
        dest_ticket = pack_dir / "oticket"
        dest_ticket.mkdir(parents=True, exist_ok=True)
        for src in tmp.rglob("oticket.xml"):
            shutil.copy2(src, dest_ticket / "oticket.xml")
            notes.append("oticket/oticket.xml")
            break
        conf = tmp / "configure-aurum.conf"
        if not conf.is_file():
            hits = list(tmp.rglob("configure-aurum.conf"))
            conf = hits[0] if hits else conf
        if conf.is_file():
            shutil.copy2(conf, dest_ticket / "configure-aurum.conf")
            notes.append("oticket/configure-aurum.conf")
    else:
        raise ValueError(f"unsupported kind {kind}")

    manifest = CompanionManifest(
        kind=kind,
        label=label or source.name,
        source_name=source.name,
        run_onehand_configurer=kind in (CompanionKind.BILLS, CompanionKind.DALLAS),
        reboot_after=kind == CompanionKind.SERIAL_MUX,
        payload_notes=notes,
    )
    save_manifest(manifest, pack_dir / MANIFEST_NAME)
    return manifest


def apply_companion_pack(
    pack_dir: Path,
    *,
    goldclub_root: Path | None = None,
    g_drive_root: Path | None = None,
    keyboard_leaf: Path | None = None,
    allow_licences: bool = False,
    allow_g_drive: bool = False,
    dry_run: bool = False,
) -> CompanionApplyResult:
    """Apply a staged companion pack. Licence and G: writes require explicit flags."""
    pack_dir = Path(pack_dir)
    manifest_path = pack_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return CompanionApplyResult((), (), ("companion.json missing",), ())
    manifest = load_manifest(manifest_path)
    goldclub_root = Path(goldclub_root or r"C:\Goldclub")
    g_drive_root = Path(g_drive_root or r"G:\\")
    written: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    notes: list[str] = []

    if manifest.kind == CompanionKind.KEYBOARDS:
        tool = pack_dir / "CountrySelectorTool"
        if keyboard_leaf is None:
            leaves = discover_leaves(tool)
            if not leaves:
                return CompanionApplyResult((), (), ("no keyboard leaves",), ())
            keyboard_leaf = leaves[0].path
        if dry_run:
            notes.append(f"would apply keyboard leaf {keyboard_leaf}")
            return CompanionApplyResult((), (), (), tuple(notes))
        result = apply_country_leaf(keyboard_leaf, goldclub_root)
        return CompanionApplyResult(
            result.copied,
            result.skipped,
            result.errors,
            (f"keyboard leaf {keyboard_leaf}",),
        )

    if manifest.kind == CompanionKind.SERIAL_MUX:
        if not allow_g_drive:
            return CompanionApplyResult(
                (),
                (),
                ("G: drive apply blocked — set allow_g_drive=True after Unlocker is mounted",),
                (),
            )
        payload = pack_dir / "g_payload"
        if dry_run:
            notes.append(f"would xcopy {payload} -> {g_drive_root}")
            return CompanionApplyResult((), (), (), tuple(notes))
        w, s, e = _copy_tree_filtered(payload, g_drive_root)
        written.extend(w)
        skipped.extend(s)
        errors.extend(e)
        if manifest.reboot_after:
            notes.append("Reboot recommended (ReBoot.exe present in pack; not auto-started)")
        return CompanionApplyResult(
            tuple(written), tuple(skipped), tuple(errors), tuple(notes)
        )

    if manifest.kind == CompanionKind.LICENCES:
        if not allow_licences:
            return CompanionApplyResult(
                (),
                (),
                ("Licence apply blocked — set allow_licences=True after confirming the set",),
                (),
            )
        if dry_run:
            notes.append("would copy Licenses/ and slot/licence.dll")
            return CompanionApplyResult((), (), (), tuple(notes))
        lic = pack_dir / "Licenses"
        if lic.is_dir():
            w, s, e = _copy_tree_filtered(lic, goldclub_root / "Licenses")
            written.extend(w)
            skipped.extend(s)
            errors.extend(e)
        slot = pack_dir / "slot"
        if slot.is_dir():
            w, s, e = _copy_tree_filtered(slot, goldclub_root / "slot")
            written.extend(w)
            skipped.extend(s)
            errors.extend(e)
        return CompanionApplyResult(
            tuple(written), tuple(skipped), tuple(errors), ("licences applied",)
        )

    if manifest.kind in (
        CompanionKind.BILLS,
        CompanionKind.ONEHAND,
        CompanionKind.THEME_OVERLAY,
    ):
        slot = pack_dir / "slot"
        if dry_run:
            notes.append(f"would copy slot/ -> {goldclub_root / 'slot'}")
            if manifest.run_onehand_configurer:
                notes.append("would launch OneHandConfigurer.exe (manual)")
            return CompanionApplyResult((), (), (), tuple(notes))
        if slot.is_dir():
            w, s, e = _copy_tree_filtered(slot, goldclub_root / "slot")
            written.extend(w)
            skipped.extend(s)
            errors.extend(e)
        if manifest.run_onehand_configurer:
            cfg = pack_dir / "configurer" / "OneHandConfigurer.exe"
            if cfg.is_file():
                notes.append(f"OneHandConfigurer available at {cfg} (launch manually)")
            else:
                notes.append("OneHandConfigurer not bundled")
        return CompanionApplyResult(
            tuple(written), tuple(skipped), tuple(errors), tuple(notes)
        )

    if manifest.kind == CompanionKind.OTICKET:
        dest = goldclub_root / "bios" / "etc" / "application" / "slot" / "oticket.xml"
        src = pack_dir / "oticket" / "oticket.xml"
        if dry_run:
            notes.append(f"would copy {src} -> {dest}")
            return CompanionApplyResult((), (), (), tuple(notes))
        if not src.is_file():
            return CompanionApplyResult((), (), ("oticket.xml missing in pack",), ())
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            written.append(dest.as_posix())
        except OSError as exc:
            errors.append(str(exc))
        conf_src = pack_dir / "oticket" / "configure-aurum.conf"
        if conf_src.is_file():
            conf_dest = goldclub_root / "maintenance" / "config" / "configure-aurum.conf"
            try:
                conf_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(conf_src, conf_dest)
                written.append(conf_dest.as_posix())
            except OSError as exc:
                errors.append(str(exc))
        return CompanionApplyResult(
            tuple(written), tuple(skipped), tuple(errors), ("oticket applied",)
        )

    if manifest.kind == CompanionKind.DALLAS:
        cfg = pack_dir / "configurer" / "OneHandConfigurer.exe"
        if dry_run:
            notes.append(f"would launch {cfg}")
            return CompanionApplyResult((), (), (), tuple(notes))
        if cfg.is_file():
            notes.append(f"OneHandConfigurer available at {cfg} (launch manually)")
        else:
            errors.append("OneHandConfigurer.exe missing in dallas pack")
        return CompanionApplyResult((), (), tuple(errors), tuple(notes))

    return CompanionApplyResult((), (), (f"unhandled kind {manifest.kind}",), ())


def companion_summary_lines(manifest: CompanionManifest) -> list[str]:
    return [
        f"Kind: {manifest.kind.value}",
        f"Label: {manifest.label or '(unnamed)'}",
        f"Source: {manifest.source_name or '—'}",
        f"OneHandConfigurer: {'yes' if manifest.run_onehand_configurer else 'no'}",
        f"Reboot after: {'yes' if manifest.reboot_after else 'no'}",
        f"Payload: {', '.join(manifest.payload_notes) or '—'}",
        "",
        "Ship under GameStar Updates (not Country Selectors), except keyboards"
        " which use a mini CountrySelector data tree.",
    ]


def list_keyboard_variants(pack_dir: Path) -> list[str]:
    tool = Path(pack_dir) / "CountrySelectorTool"
    if not (tool / "data").is_dir():
        return []
    return [leaf.label for leaf in discover_leaves(tool)]


def find_keyboard_leaf(pack_dir: Path, label: str) -> Path | None:
    tool = Path(pack_dir) / "CountrySelectorTool"
    for leaf in discover_leaves(tool):
        if leaf.label == label or "/".join(leaf.rel_parts) == label:
            return leaf.path
    # Also try last path segment match
    matched = filter_leaves(discover_leaves(tool))
    for leaf in matched:
        if leaf.rel_parts and leaf.rel_parts[-1] == label:
            return leaf.path
    return None
