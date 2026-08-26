"""Read cabinet MachineName from ProductSerialNumber.json over SMB."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_CABINET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,63}$")
_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _normalize_cabinet_name(raw: str | None) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    first = s.split(".", 1)[0].strip()
    if not first or not _CABINET_NAME_RE.fullmatch(first):
        return None
    return first.upper()


def read_cabinet_machine_name_from_state(ip: str) -> str | None:
    """Authoritative post-rebuild identity (e.g. GRT330106) from GoldClub state."""
    ip = (ip or "").strip()
    if not ip or not _IPV4_RE.match(ip):
        return None
    candidates = (
        Path(rf"\\{ip}\c$\Goldclub\var\state\maintenance\ProductSerialNumber.json"),
        Path(rf"\\{ip}\g$\var\state\maintenance\ProductSerialNumber.json"),
        Path(rf"\\{ip}\c$\Goldclub\slot\var\state\maintenance\ProductSerialNumber.json"),
    )
    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug("ProductSerialNumber read %s: %s", path, e)
            continue
        if not isinstance(data, dict):
            continue
        name = _normalize_cabinet_name(str(data.get("MachineName") or ""))
        if name:
            return name
    return None
