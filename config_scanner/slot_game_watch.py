"""Escape / Bootstrap GameBinRun helper for Slot cabinets.

Bootstrap treats game-start exit 11 (operator Escape) as
``Unexpected game stop! >> Restart the machine``. Point GameBinRun at
``Start-SlotGameWatch.exe`` so that process stays alive across Escape,
bounces HWSubsys, then starts BiOS2.
"""

from __future__ import annotations

GAMEBINRUN_WATCH = "%:/slot/Start-SlotGameWatch.exe"
STOCK_GAMEBINRUN = "%:/slot/game-start.exe"
WATCH_EXE_NAME = "Start-SlotGameWatch.exe"

HW_SERVICE_NAMES: tuple[str, ...] = (
    "GoldClub.Logging.LogDaemon",
    "GoldClub Serial Communication Gateway",
    "GoldClub Serial Communication Gateway SAS",
    "GoldClub Hardware Subsystem",
    "GoldClub.Aurum.Services",
)


def rewrite_bootstrap_gamebinrun(
    text: str, gamebinrun: str = GAMEBINRUN_WATCH
) -> str:
    """Replace the GameBinRun line. Keeps GameBin / ConfigBin untouched."""
    found = False
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        raw = line.lstrip()
        if raw.startswith("GameBinRun"):
            nl = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
            out.append(f"GameBinRun {gamebinrun}{nl}")
            found = True
        else:
            out.append(line)
    if not found:
        raise ValueError("bootstrap.ini has no GameBinRun line")
    return "".join(out)
