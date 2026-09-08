"""Install directory and app-local writable paths (dev tree + frozen exe)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_install_dir() -> Path:
    """Folder containing LogInvestigator.exe, or repository root when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_network_path(path: Path | str) -> bool:
    """True for UNC paths (``\\\\server\\share\\…``) that keep SMB file locks open.

    Writing logs / temp next to an exe on ``\\\\10.0.0.90\\USB_Remote\\…`` holds the
    share open for the whole session, so Explorer reports "Folder In Use" when
    the operator tries to delete or rename the stick share.
    """
    s = str(path or "").strip().replace("/", "\\")
    if not s:
        return False
    if s.startswith("\\\\"):
        # \\?\C:\… is local; \\?\UNC\server\… is not.
        if s.startswith("\\\\?\\UNC\\") or s.startswith("\\\\.\\UNC\\"):
            return True
        if len(s) >= 4 and s[2] == "?" and s[3] == "\\":
            return False
        return True
    return False


def dir_is_writable(path: Path | str) -> bool:
    """True when a new file can be created and deleted in *path*.

    ``Path.mkdir(exist_ok=True)`` succeeds on a USB folder that already exists even
    when the volume is write-protected or Group Policy denies writes to removable
    disks. Opening ``ConfigScanner.log`` then raises ``PermissionError``.
    """
    try:
        folder = Path(path)
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".cs_write_probe_{os.getpid()}.tmp"
        probe.write_bytes(b"ok")
        try:
            probe.unlink()
        except OSError:
            pass
        return True
    except OSError:
        return False


def app_local_data_dir(*, mkdir: bool = True) -> Path:
    """Per-user local folder for writables when the install tree is on a share."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    path = Path(base) / "LogInvestigator"
    if mkdir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def app_writable_dir(*, mkdir: bool = True) -> Path:
    """Directory for logs, run packs and scratch files.

    Beside the exe when that folder is actually writable. Under
    ``%LOCALAPPDATA%\\LogInvestigator`` when the exe lives on a UNC share, a
    write-protected USB, or any other tree that refuses a probe file — so a
    removable stick can still launch even when Windows denies writes to it.
    """
    install = app_install_dir()
    if is_network_path(install) or not dir_is_writable(install):
        return app_local_data_dir(mkdir=mkdir)
    if mkdir:
        try:
            install.mkdir(parents=True, exist_ok=True)
        except OSError:
            return app_local_data_dir(mkdir=mkdir)
    return install


def _subdir_or_local(rel: str, *, mkdir: bool) -> Path:
    path = app_writable_dir(mkdir=mkdir) / rel
    if not mkdir:
        return path
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = app_local_data_dir() / rel
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def app_tmp_logs_dir(*, mkdir: bool = True) -> Path:
    """``_tmp_logs`` next to the writable root (Bug Detector, scratch logs)."""
    return _subdir_or_local("_tmp_logs", mkdir=mkdir)


def app_runs_dir(*, mkdir: bool = True) -> Path:
    """``automation_runs`` next to the writable root, never the current directory.

    A run pack has to end up somewhere the operator can find again. Resolved from
    the working directory it would land wherever the exe happened to be started
    from, which for a shortcut is ``C:\\Windows\\System32``.
    """
    return _subdir_or_local("automation_runs", mkdir=mkdir)


def bug_detector_output_base(*, mkdir: bool = True) -> Path:
    path = app_tmp_logs_dir(mkdir=mkdir) / "bug-detector"
    if mkdir:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            path = app_local_data_dir() / "_tmp_logs" / "bug-detector"
            path.mkdir(parents=True, exist_ok=True)
    return path
