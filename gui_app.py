#!/usr/bin/env python3
"""Launch the Config Scanner desktop UI (no log-triage tabs)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gui.config_scanner_window import run_config_scanner_app  # noqa: E402
from config_scanner.b2u_pack import launched_from_tool_b2u  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GoldClub Config Scanner")
    parser.add_argument(
        "--apply-pack",
        metavar="DIR",
        help="Open apply-only UI for a bundled EGM config-pack directory",
    )
    parser.add_argument(
        "--country-pack",
        metavar="DIR",
        help="Open Country Selector wizard for a bundled CountrySelectorTool directory",
    )
    parser.add_argument(
        "--companion-pack",
        metavar="DIR",
        help="Open companion Updates apply UI (keyboards/bills/licences/OneHand/serial)",
    )
    parser.add_argument(
        "--snapshots",
        action="store_true",
        help="Open Snapshots tab directly (create full snapshot, restore)",
    )
    parser.add_argument(
        "--restore-b2u",
        metavar="PATH",
        help="Open Restore flow for a raw .b2u update (GameStar country selector, etc.)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        from config_scanner.runtime_bootstrap import bootstrap_frozen_app

        bootstrap_frozen_app()
    except Exception:
        pass
    args = _parse_args()
    snapshots = bool(args.snapshots) or (
        not args.apply_pack
        and not args.country_pack
        and not args.companion_pack
        and not args.restore_b2u
        and launched_from_tool_b2u()
    )
    raise SystemExit(
        run_config_scanner_app(
            apply_pack=args.apply_pack,
            country_pack=args.country_pack,
            companion_pack=args.companion_pack,
            restore_b2u=args.restore_b2u,
            snapshots=snapshots,
        )
    )
