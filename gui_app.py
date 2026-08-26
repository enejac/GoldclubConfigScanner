#!/usr/bin/env python3
"""Launch the Config Scanner desktop UI (no log-triage tabs)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gui.config_scanner_window import run_config_scanner_app  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_config_scanner_app())
