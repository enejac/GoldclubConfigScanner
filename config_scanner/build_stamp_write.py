"""Write ``_build_stamp.py`` with the current local clock (minute).

Called from ``build_exe.ps1`` only. Do not invent a time by hand.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

STAMP_FORMAT = "%Y-%m-%d %H:%M"
STAMP_PATH = Path(__file__).resolve().parent / "_build_stamp.py"


def current_build_stamp(now: datetime | None = None) -> str:
    """Exact calendar minute of *now* (local), or ``datetime.now()``."""
    return (now or datetime.now()).strftime(STAMP_FORMAT)


def write_build_stamp(
    *,
    now: datetime | None = None,
    dest: Path | None = None,
) -> str:
    """Overwrite the baked stamp file. *now* is for tests; builds pass nothing."""
    stamp = current_build_stamp(now)
    path = Path(dest) if dest is not None else STAMP_PATH
    path.write_text(
        "# Written by build_stamp_write.py at exe build time.\n"
        "# Do not edit this time by hand.\n"
        f"BUILD_STAMP = {stamp!r}\n",
        encoding="utf-8",
    )
    return stamp


if __name__ == "__main__":
    print("Build stamp: " + write_build_stamp())
