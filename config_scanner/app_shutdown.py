"""Stop leftover work when the Config Scanner window is closed with X.

Fleet SMB scans and WinRM/watchdog PowerShell keep the exe in Task Manager
as a background process after the window is gone. The real app session
requests shutdown on close so those workers abort, then
``shutdown_runtime`` drains the Qt pool and stops helpers we started.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_SHUTDOWN = threading.Event()
_REAL_APP = False
_REAL_LOCK = threading.Lock()

# Command-line fragments of processes this app starts and must not leave behind.
HELPER_CMDLINE_MARKERS: tuple[str, ...] = (
    "GoldClub-LivePush-Watchdog",
    "glci_winrm_inline_",
    "glci_winrm_probe_",
)

WATCHDOG_SCRIPT_NAME = "GoldClub-LivePush-Watchdog.ps1"


def reset_shutdown_for_tests() -> None:
    """Clear process-wide flags so pytest cases stay isolated."""
    _SHUTDOWN.clear()
    global _REAL_APP
    with _REAL_LOCK:
        _REAL_APP = False


def mark_real_app_session() -> None:
    """Enable close-to-exit behavior for ``run_config_scanner_app`` only."""
    global _REAL_APP
    with _REAL_LOCK:
        _REAL_APP = True


def clear_real_app_session() -> None:
    global _REAL_APP
    with _REAL_LOCK:
        _REAL_APP = False


def is_real_app_session() -> bool:
    with _REAL_LOCK:
        return _REAL_APP


def notify_window_closing() -> None:
    """X on the real app window: stop fleet scans so the process can exit."""
    if is_real_app_session():
        request_shutdown()


def request_shutdown() -> None:
    _SHUTDOWN.set()


def is_shutting_down() -> bool:
    return _SHUTDOWN.is_set()


def in_automated_test() -> bool:
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def helper_process_matches(command_line: str | None) -> bool:
    folded = str(command_line or "").casefold()
    if not folded:
        return False
    return any(marker.casefold() in folded for marker in HELPER_CMDLINE_MARKERS)


def pids_matching_helpers(rows: list[tuple[int, str]]) -> list[int]:
    me = os.getpid()
    return [
        int(pid)
        for pid, command_line in rows
        if int(pid) != me and helper_process_matches(command_line)
    ]


def watchdog_script_path() -> Path:
    return Path(os.environ.get("TEMP") or tempfile.gettempdir()) / WATCHDOG_SCRIPT_NAME


def _remove_watchdog_script() -> None:
    path = watchdog_script_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _query_win32_process_cmdlines() -> list[tuple[int, str]]:
    if os.name != "nt":
        return []
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    script = (
        "Get-CimInstance Win32_Process | "
        "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=8,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[tuple[int, str]] = []
    for line in (completed.stdout or "").splitlines():
        pid_text, sep, command_line = line.partition("\t")
        if not sep:
            continue
        try:
            rows.append((int(pid_text.strip()), command_line))
        except ValueError:
            continue
    return rows


def _terminate_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(int(pid))],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5,
                creationflags=flags,
            )
            return int(completed.returncode or 0) == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.kill(int(pid), 9)
        return True
    except OSError:
        return False


def stop_owned_helper_processes(
    *,
    rows: list[tuple[int, str]] | None = None,
) -> int:
    """Kill watchdog / WinRM wrapper PowerShell this app started. Returns count."""
    snapshot = rows if rows is not None else _query_win32_process_cmdlines()
    killed = 0
    for pid in pids_matching_helpers(snapshot):
        if _terminate_pid(pid):
            killed += 1
    _remove_watchdog_script()
    return killed


def drain_qt_thread_pool(*, wait_ms: int = 1500) -> None:
    try:
        from PySide6.QtCore import QThreadPool
    except ImportError:
        return
    pool = QThreadPool.globalInstance()
    pool.clear()
    pool.waitForDone(max(0, int(wait_ms)))


def release_instance_lock(lock: object | None) -> None:
    detach = getattr(lock, "detach", None)
    if detach is None:
        return
    try:
        detach()
    except Exception:
        pass


def process_still_busy() -> bool:
    try:
        from PySide6.QtCore import QThreadPool

        if QThreadPool.globalInstance().activeThreadCount() > 0:
            return True
    except ImportError:
        pass
    me = threading.current_thread()
    for thread in threading.enumerate():
        if thread is me or not thread.is_alive() or thread.daemon:
            continue
        name = thread.name or ""
        if name == "MainThread":
            continue
        return True
    return False


def shutdown_runtime(
    *,
    wait_ms: int = 1500,
    instance_lock: object | None = None,
    force_exit: bool | None = None,
) -> None:
    """Abort workers, drop helpers, then exit if the process would otherwise linger."""
    request_shutdown()
    stop_owned_helper_processes()
    drain_qt_thread_pool(wait_ms=wait_ms)
    release_instance_lock(instance_lock)
    if force_exit is None:
        force_exit = not in_automated_test()
    if force_exit and process_still_busy():
        os._exit(0)
