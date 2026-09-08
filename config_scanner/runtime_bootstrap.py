"""Early frozen-exe bootstrap: logging before the GUI imports heavy stacks."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def bootstrap_frozen_app(*, log_name: str | None = None) -> Path:
    """Configure file logging and log install / embedded-update layout."""
    from gui.app_logging import configure_app_logging, default_app_log_filename

    path = configure_app_logging(filename=log_name or default_app_log_filename())
    log = logging.getLogger("config_scanner.bootstrap")
    log.info("executable=%s frozen=%s argv=%s", sys.executable, getattr(sys, "frozen", False), sys.argv)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        install = Path(sys.executable).resolve().parent
        beside = install / "embedded_updates"
        log.info("_MEIPASS=%s install=%s beside_embedded=%s", meipass, install, beside)
        if beside.is_dir():
            log.info(
                "beside embedded_updates: catalog=%s staged=%s b2u=%s",
                (beside / "catalog.json").is_file(),
                (beside / "staged").is_dir(),
                (beside / "b2u").is_dir(),
            )
    return path
