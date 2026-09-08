"""One Config Scanner process at a time.

Windows uses a named mutex so a crash does not leave a stuck lock
(QSharedMemory orphans often do). Non-Windows falls back to QSharedMemory.
"""

from __future__ import annotations

import os
import sys

CONFIG_SCANNER_SINGLE_INSTANCE_KEY = "GoldClub.ConfigScanner.v1"
ALLOW_MULTI_ENV = "CONFIG_SCANNER_ALLOW_MULTI"

ALREADY_RUNNING_TITLE = "Config Scanner already running"
ALREADY_RUNNING_TEXT = (
    "Another Config Scanner window is already open.\n\n"
    "Close that window, then start the program again."
)

_ERROR_ALREADY_EXISTS = 183


class _WinMutexLock:
    """Keeps a Win32 mutex handle open for the process lifetime."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    def detach(self) -> None:
        if not self._handle:
            return
        import ctypes

        ctypes.windll.kernel32.CloseHandle(self._handle)
        self._handle = 0

    def __del__(self) -> None:
        try:
            self.detach()
        except Exception:
            pass


def _env_allows_multi() -> bool:
    return os.environ.get(ALLOW_MULTI_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _try_acquire_win_mutex(name: str) -> object | None:
    """CreateMutex — OS releases it when the holding process dies."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return _WinMutexLock(int(handle))


def try_acquire_config_scanner_lock(*, key: str | None = None) -> object | None:
    """Return a process-lifetime lock, or None when another instance holds it.

    Set ``CONFIG_SCANNER_ALLOW_MULTI=1`` to bypass (dev / automated UI tests).
    """
    if _env_allows_multi():
        return object()

    lock_key = (key or CONFIG_SCANNER_SINGLE_INSTANCE_KEY).strip() or (
        CONFIG_SCANNER_SINGLE_INSTANCE_KEY
    )
    if sys.platform == "win32":
        return _try_acquire_win_mutex(f"Local\\{lock_key}")

    from PySide6.QtCore import QSharedMemory

    mem = QSharedMemory(lock_key)
    if mem.create(1):
        return mem
    if mem.attach():
        mem.detach()
    mem = QSharedMemory(lock_key)
    if mem.create(1):
        return mem
    return None


def show_already_running_warning(parent=None) -> None:
    """Modal warning with an OK button. Caller must have a QApplication."""
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.warning(parent, ALREADY_RUNNING_TITLE, ALREADY_RUNNING_TEXT)
