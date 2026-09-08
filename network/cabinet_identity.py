"""Read cabinet MachineName from ProductSerialNumber.json / .conf over SMB."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_CABINET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,63}$")
_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")

_SERIAL_FILE_NAMES: tuple[str, ...] = (
    "ProductSerialNumber.json",
    "ProductSerialNumber.conf",
)

_SERIAL_REL_DIRS: tuple[str, ...] = (
    r"var\state\maintenance",
    r"slot\var\state\maintenance",
)


def _normalize_cabinet_name(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    first = s.split(".", 1)[0].strip()
    if not first or not _CABINET_NAME_RE.fullmatch(first):
        return None
    return first.upper()


def _machine_name_from_serial_fields(data: dict[str, str]) -> str | None:
    name = _normalize_cabinet_name(data.get("MachineName") or "")
    if name:
        return name
    kind = (data.get("ProductKind") or "").strip().upper()
    serial = (data.get("ProductSerialNumber") or "").strip()
    if kind and serial and serial.isdigit():
        return _normalize_cabinet_name(f"G{kind}{serial}")
    return _normalize_cabinet_name(serial)


def _read_serial_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.debug("ProductSerialNumber read %s: %s", path, e)
        return None
    if not data:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeError:
            return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        try:
            return data.decode("utf-16")
        except UnicodeError:
            return None


def _machine_name_from_serial_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        text = _read_serial_text(path)
    except OSError as e:
        logger.debug("ProductSerialNumber read %s: %s", path, e)
        return None
    if text is None:
        return None
    raw = text.strip()
    if not raw:
        return None
    if path.suffix.casefold() == ".json" or raw[:1] in "{[":
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            fields = {str(k): "" if v is None else str(v) for k, v in data.items()}
            return _machine_name_from_serial_fields(fields)
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        fields[key.strip()] = val.strip()
    return _machine_name_from_serial_fields(fields)


def _ensure_smb_for_cabinet_ip(ip: str) -> None:
    host = (ip or "").strip()
    if not host or not _IPV4_RE.match(host):
        return
    try:
        from network.lab_access import ensure_lab_smb_credential

        ensure_lab_smb_credential(host)
    except Exception:
        logger.debug("ensure_lab_smb_credential failed for %s", host, exc_info=True)


def _serial_paths_for_ip(ip: str, *, scan_root: str = "") -> tuple[Path, ...]:
    ordered: list[Path] = []
    seen: set[str] = set()
    roots: list[Path] = []
    root_text = (scan_root or "").strip()
    if root_text:
        try:
            roots.append(Path(root_text))
            name = Path(root_text).name.casefold()
            if name in {"log", "state", "var"}:
                roots.append(Path(root_text).parent)
        except OSError:
            pass
    for base in roots:
        for rel in (Path("state") / "maintenance", Path("var") / "state" / "maintenance"):
            for fname in _SERIAL_FILE_NAMES:
                cand = base / rel / fname
                key = str(cand).casefold()
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(cand)
    ip = (ip or "").strip()
    if ip and _IPV4_RE.match(ip):
        for base in (
            Path(rf"\\{ip}\c$\Goldclub"),
            Path(rf"\\{ip}\slot"),
            Path(rf"\\{ip}\g$"),
        ):
            for rel in _SERIAL_REL_DIRS:
                if base.name.casefold() == "slot" and rel.casefold().startswith("slot"):
                    continue
                for fname in _SERIAL_FILE_NAMES:
                    cand = base / rel / fname
                    key = str(cand).casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    ordered.append(cand)
    return tuple(ordered)


def read_cabinet_machine_name_from_state(ip: str, *, scan_root: str = "") -> str | None:
    """Live MachineName from ProductSerialNumber.json / .conf (scan root, then UNC)."""
    ip = (ip or "").strip()
    if not ip or not _IPV4_RE.match(ip):
        return None
    _ensure_smb_for_cabinet_ip(ip)
    for path in _serial_paths_for_ip(ip, scan_root=scan_root):
        name = _machine_name_from_serial_file(path)
        if name:
            return name
    return None
