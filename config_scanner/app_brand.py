"""Window / home title, including a temporary build date+time stamp."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


def _baked_stamp() -> str:
    try:
        from config_scanner._build_stamp import BUILD_STAMP

        return str(BUILD_STAMP or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def build_stamp_text() -> str:
    """Date and clock of this exe build (local), or ``dev`` from source.

    The git copy of ``_build_stamp.py`` stays empty. Source runs show ``dev``.
    The frozen exe uses the minute baked from ``datetime.now()`` at that build,
    or the exe file time if the bake file was empty.
    """
    if not getattr(sys, "frozen", False):
        return "dev"
    baked = _baked_stamp()
    if baked:
        return baked
    try:
        ts = Path(sys.executable).stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "dev"


def program_title(mode: str = "") -> str:
    """Top-of-window name with the build stamp appended."""
    stamp = build_stamp_text()
    if mode:
        return f"Config Scanner — {mode}  {stamp}"
    return f"Config Scanner  {stamp}"
