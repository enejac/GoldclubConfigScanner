"""Probe and optionally round-trip 2<->3 display mode on a live slot cabinet."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from config_scanner.live_push import commit_live_push, load_live_cabinet
from config_scanner.slot_setup import (
    _MGCONFIG_REL,
    display_mode_infoscreen_height,
    display_mode_probe_lines,
    read_display_mode,
)


def _backup_mgconfig(goldclub: Path) -> Path:
    src = goldclub / _MGCONFIG_REL
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = src.with_name(f"{src.name}.bak-display-switch-{stamp}")
    shutil.copy2(src, dest)
    return dest


def round_trip(goldclub: Path, *, target: str, restart: bool) -> int:
    outcome = load_live_cabinet(target)
    if outcome.error or outcome.recipe is None or outcome.root is None:
        print(outcome.error or "load failed", file=sys.stderr)
        return 1
    root = outcome.root
    start = read_display_mode(root)
    print(f"Start mode: {start}")
    if start not in ("2", "3"):
        print("Cabinet display mode unknown; aborting round-trip.", file=sys.stderr)
        return 1

    other = "2" if start == "3" else "3"
    for want in (other, start):
        recipe = type(outcome.recipe).from_dict(outcome.recipe.to_dict())
        recipe.display_mode = want
        print(f"Switching to {want}-screen…")
        result = commit_live_push(
            recipe,
            root,
            scan_target=target,
            restart_stack=restart,
        )
        if result.errors:
            print("ERROR:", *result.errors, sep="\n", file=sys.stderr)
            return 1
        got = read_display_mode(root)
        print(f"  now {got}-screen, stack_started={result.stack_started}")
        if got != want:
            print(f"Expected {want} but read {got}", file=sys.stderr)
            return 1
        height = display_mode_infoscreen_height(root)
        print(f"  InfoScreen canvas height: {height}")
    print("Round-trip OK.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=r"\\10.0.0.111\slot",
        help="Goldclub UNC path (default: .111 slot share)",
    )
    parser.add_argument(
        "--round-trip",
        action="store_true",
        help="Switch to the other mode and back (stops/restarts OneHand)",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Write mgconfig only (no game restart)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Backup mgconfig.xml before --round-trip",
    )
    args = parser.parse_args()
    outcome = load_live_cabinet(args.target)
    if outcome.error or outcome.root is None:
        print(outcome.error or "cannot load", file=sys.stderr)
        return 1
    for line in display_mode_probe_lines(outcome.root):
        print(line)
    if args.round_trip:
        if args.backup:
            bak = _backup_mgconfig(outcome.root)
            print(f"Backup: {bak}")
        return round_trip(
            outcome.root,
            target=args.target,
            restart=not args.no_restart,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
