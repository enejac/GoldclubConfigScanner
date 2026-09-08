"""Window / home title, including a temporary build date+time stamp."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


def build_stamp_text() -> str:
    """Date and clock of this exe build (local), or ``dev`` from source."""
    baked = ""
    try:
        from config_scanner._build_stamp import BUILD_STAMP

        baked = str(BUILD_STAMP or "").strip()
    except Exception:  # noqa: BLE001
        baked = ""
    if baked:
        return baked
    if getattr(sys, "frozen", False):
        try:
            ts = Path(sys.executable).stat().st_mtime
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except OSError:
            return "dev"
    return "dev"


def program_title(mode: str = "") -> str:
    """Top-of-window name with the build stamp appended."""
    stamp = build_stamp_text()
    if mode:
        return f"Config Scanner — {mode}  {stamp}"
    return f"Config Scanner  {stamp}"
