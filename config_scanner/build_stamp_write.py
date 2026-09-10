"""Bake the current local clock into ``_build_stamp.py`` for one exe build.

Called from ``build_exe.ps1`` / ``ConfigScanner.spec``. Never commit a real
minute — ``clear_build_stamp()`` restores the empty placeholder.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

STAMP_FORMAT = "%Y-%m-%d %H:%M"
STAMP_PATH = Path(__file__).resolve().parent / "_build_stamp.py"
PLACEHOLDER = (
    "# Placeholder only. build_stamp_write.py fills this with datetime.now()\n"
    "# at exe build time, then build_exe.ps1 clears it again so git stays empty.\n"
    'BUILD_STAMP = ""\n'
)


def current_build_stamp(now: datetime | None = None) -> str:
    """Exact calendar minute of *now* (local), or ``datetime.now()``."""
    return (now or datetime.now()).strftime(STAMP_FORMAT)


def write_build_stamp(
    *,
    now: datetime | None = None,
    dest: Path | None = None,
) -> str:
    """Overwrite the bake file with the system clock. *now* is for tests."""
    stamp = current_build_stamp(now)
    path = Path(dest) if dest is not None else STAMP_PATH
    path.write_text(
        "# Written by build_stamp_write.py at exe build time from datetime.now().\n"
        "# Do not commit a real minute — run: python -m config_scanner.build_stamp_write --clear\n"
        f"BUILD_STAMP = {stamp!r}\n",
        encoding="utf-8",
    )
    return stamp


def clear_build_stamp(*, dest: Path | None = None) -> None:
    """Restore the empty git placeholder (no hardcoded time)."""
    path = Path(dest) if dest is not None else STAMP_PATH
    path.write_text(PLACEHOLDER, encoding="utf-8")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear_build_stamp()
        print("Build stamp: cleared")
    else:
        print("Build stamp: " + write_build_stamp())
