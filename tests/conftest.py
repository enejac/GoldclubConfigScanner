"""Ensure project root is on sys.path for package imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolate_qsettings(tmp_path_factory: pytest.TempPathFactory):
    """Keep every test out of the operator's real QSettings store.

    A GUI test that loads a cabinet persists that path as the remembered
    Live Push target. Without this, a tmp_path fixture ends up in the
    Cabinet field of the installed app.
    """
    try:
        from PySide6.QtCore import QSettings

        from config_manager import SettingsManager
    except ImportError:
        yield
        return

    ini = str(tmp_path_factory.mktemp("qsettings") / "settings.ini")
    original = SettingsManager.__dict__["_s"]
    SettingsManager._s = staticmethod(
        lambda: QSettings(ini, QSettings.Format.IniFormat)
    )
    try:
        yield
    finally:
        SettingsManager._s = original
