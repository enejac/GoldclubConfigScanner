"""Lab LAN access and silent SMB login (test/test).

The lab password is the documented throwaway ``test`` account. ``cmdkey``
alone is not enough: Windows keeps a per-server SMB session, so a first
attempt with this PC's login (or ``GOLD-CLUB\\test`` on workgroup ``.111``)
sticks as WinError 1326 until we cancel that session and connect with the
host-specific user (``10.0.0.111\\test``, not the domain account).

SMB, WinRM, PsExec, and Live Push apply to every host on the lab LAN
``10.0.0.0/24`` (not a hardcoded cabinet list). ``LAB_FLEET_IPS`` is only
the named shortcut / cmdkey bootstrap set.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LAB_FLEET_IPS: frozenset[str] = frozenset(
    {
        "10.0.0.83",
        "10.0.0.90",
        "10.0.0.100",
        "10.0.0.110",
        "10.0.0.111",
        "10.0.0.112",
        "10.0.0.171",
    }
)

LAB_USERNAME_HINT = r"GOLD-CLUB\test"

# Workgroup cabinets have no GOLD-CLUB domain account. WinRM/SMB must use
# the local ``test`` user (IP\test or machine\test), not GOLD-CLUB\test.
LAB_WORKGROUP_USERS: dict[str, tuple[str, ...]] = {
    # Workgroup GRT330106 / GST22377 — never GOLD-CLUB\test (that account
    # does not exist here; it yields WinError 1326).
    "10.0.0.111": (
        r"10.0.0.111\test",
        r"GST22377\test",
        r"GRT330106\test",
    ),
}

# Win32 SMB logon failures that mean "retry with the lab user", not "offline".
_SMB_LOGON_WINERRORS = frozenset(
    {
        86,  # ERROR_INVALID_PASSWORD
        1326,  # ERROR_LOGON_FAILURE
        1327,  # ERROR_ACCOUNT_RESTRICTION
        1219,  # ERROR_SESSION_CREDENTIAL_CONFLICT
    }
)
_SMB_ALREADY_CONNECTED = frozenset(
    {
        85,  # ERROR_ALREADY_ASSIGNED
        1202,  # ERROR_DEVICE_ALREADY_REMEMBERED
    }
)
_SMB_SHARES_TO_DROP = ("IPC$", "slot", "c$", "C$", "USB", "USB_Remote")

# CONNECT_COMMANDLINE: WNetAddConnection2 must not show CredUI. Combined
# with explicit user/password this is a silent SMB logon (no popup).
_WNET_CONNECT_COMMANDLINE = 0x00000800

# Lab-only fallback credential. Cabinets use a single throwaway login
# (test / test — GOLD-CLUB\test on domain, IP\test on workgroup). Windows
# will NOT return a ``cmdkey``-stored domain password via ``CredRead`` (fails
# with error 87). SMB is opened with WNetAddConnection2 so Load does not
# need a prior Credential Manager popup. WinRM still uses this password
# for any 10.0.0.0/24 host. Override with GOLDCLUB_LAB_PASSWORD.
_LAB_PASSWORD_ENV = "GOLDCLUB_LAB_PASSWORD"
_LAB_DEFAULT_PASSWORD = "test"

_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


class LabCredentialError(RuntimeError):
    """Raised when lab credentials are missing from Windows Credential Manager."""


class FleetAllowlistError(ValueError):
    """Raised when a remote IP is outside the lab LAN (10.0.0.0/24)."""


def is_lab_fleet_ip(ip: str) -> bool:
    """True for a named shortcut cabinet (UI / cmdkey bootstrap list)."""
    host = (ip or "").strip()
    return host in LAB_FLEET_IPS


def is_lab_lan_ip(ip: str) -> bool:
    """True for any IPv4 on the lab subnet (10.0.0.0/24).

    Live Push, SMB auto-login, and WinRM use this so a cabinet like
    ``10.0.0.98`` is allowed without adding it to ``LAB_FLEET_IPS``.
    """
    host = (ip or "").strip()
    if not host or not _IPV4_RE.fullmatch(host):
        return False
    octets = [int(p) for p in host.split(".")]
    if any(o > 255 for o in octets):
        return False
    return octets[0] == 10 and octets[1] == 0 and octets[2] == 0


def require_lab_fleet_ip(ip: str) -> str:
    """Allow any 10.0.0.0/24 cabinet for Live Push / WinRM / PsExec."""
    host = (ip or "").strip()
    if is_lab_lan_ip(host):
        return host
    if not host or not _IPV4_RE.fullmatch(host):
        raise FleetAllowlistError(f"Invalid cabinet IP: {ip!r}")
    octets = [int(p) for p in host.split(".")]
    if any(o > 255 for o in octets):
        raise FleetAllowlistError(f"Invalid cabinet IP: {ip!r}")
    raise FleetAllowlistError(
        f"Remote operations are limited to the lab LAN (10.0.0.0/24). "
        f"Refusing: {host}"
    )


def _decode_cred_blob(blob: object) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob.rstrip("\x00")
    if isinstance(blob, (bytes, bytearray)):
        raw = bytes(blob)
        try:
            return raw.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="ignore").rstrip("\x00")
    return str(blob).rstrip("\x00")


def _lab_credential_from_manager(ip: str | None) -> tuple[str, str] | None:
    """Best-effort read of a *readable* lab credential from Credential Manager.

    Returns ``(user, password)`` only when Windows actually hands back a password
    blob (generic credentials). Domain (``cmdkey``) entries never expose their
    password, so this usually returns ``None`` and the caller falls back.
    """
    if sys.platform != "win32":
        return None
    try:
        import win32cred  # type: ignore
    except ImportError:
        return None

    host = (ip or "").strip()
    targets: list[str] = []
    if host:
        targets.extend([host, f"Domain:target={host}", f"TERMSRV/{host}"])
    targets.extend(["GOLD-CLUB", r"GOLD-CLUB\test", "GoldClubLab", "Domain:target=GOLD-CLUB"])
    for fleet_ip in sorted(LAB_FLEET_IPS):
        if fleet_ip not in targets:
            targets.append(fleet_ip)
            targets.append(f"Domain:target={fleet_ip}")

    for target in targets:
        cred = None
        for cred_type in (win32cred.CRED_TYPE_DOMAIN_PASSWORD, win32cred.CRED_TYPE_GENERIC):
            try:
                cred = win32cred.CredRead(target, cred_type, 0)
                break
            except Exception:  # noqa: BLE001 — CredRead raises pywintypes.error
                cred = None
        if cred is None:
            continue
        user = str(cred.get("UserName") or "").strip()
        password = _decode_cred_blob(cred.get("CredentialBlob"))
        if user and password:
            return user, password
    return None


def lab_username_for_host(ip: str | None) -> str:
    """Default WinRM/SMB user for a fleet host (domain vs workgroup)."""
    host = (ip or "").strip()
    aliases = LAB_WORKGROUP_USERS.get(host)
    if aliases:
        return aliases[0]
    return LAB_USERNAME_HINT


def lab_smb_usernames_for_host(ip: str | None) -> tuple[str, ...]:
    """Usernames to try for SMB, preferred first. Password is always ``test``."""
    host = (ip or "").strip()
    aliases = LAB_WORKGROUP_USERS.get(host)
    if aliases:
        return aliases
    users: list[str] = []
    local_test = rf"{host}\test" if host else "test"
    if host and is_lab_fleet_ip(host):
        # Known domain cabinets (.90, .171, …): GOLD-CLUB first.
        users.extend((LAB_USERNAME_HINT, local_test, "test"))
    elif host and is_lab_lan_ip(host):
        # Unknown lab IP (.76, …): local test first (workgroup, like .111).
        users.extend((local_test, LAB_USERNAME_HINT, "test"))
    else:
        users.extend((LAB_USERNAME_HINT, "test"))
    seen: set[str] = set()
    out: list[str] = []
    for user in users:
        key = user.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(user)
    return tuple(out)


def win_error_code(exc: BaseException) -> int | None:
    """Best-effort Win32 error from ``OSError`` / ``pywintypes.error``."""
    winerror = getattr(exc, "winerror", None)
    if isinstance(winerror, int) and winerror:
        return int(winerror)
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return int(args[0])
    errno = getattr(exc, "errno", None)
    if isinstance(errno, int) and errno:
        return int(errno)
    return None


def is_smb_logon_failure(exc: BaseException) -> bool:
    code = win_error_code(exc)
    if code in _SMB_LOGON_WINERRORS:
        return True
    text = str(exc).casefold()
    return (
        "1326" in text
        or "password is incorrect" in text
        or "logon failure" in text
        or "session credential conflict" in text
        or "multiple connections to a server" in text
    )


def format_lab_smb_logon_failure(host: str, exc: BaseException) -> str:
    """User-facing text when UNC open fails after the lab login was applied."""
    ip = (host or "").strip() or "cabinet"
    user = lab_username_for_host(ip)
    workgroup = ip in LAB_WORKGROUP_USERS
    extra = ""
    if workgroup:
        extra = (
            f" This cabinet is workgroup — use {user} / test, "
            "not GOLD-CLUB\\test."
        )
    else:
        tried = " or ".join(lab_smb_usernames_for_host(ip))
        extra = f" Tried silent SMB login as {tried} / test (no credential popup)."
    return (
        f"Cannot reach \\\\{ip}\\slot ({exc}).{extra} "
        "A leftover SMB session from this PC's Windows user can still block it. "
        f"Run: net use \\\\{ip}\\ipc$ /delete"
    )


def lab_winrm_authentication(ip: str | None) -> str:
    """``Invoke-Command -Authentication`` value for a lab-LAN cabinet.

    Lab hosts are always reached by IP. ``Negotiate`` tries Kerberos first and
    often fails with ``0x8009030e`` ("logon session does not exist") when the
    app runs on a local EGM or other non-interactive logon context. ``Default``
    picks NTLM for workgroup hosts and is safe for IP-based domain cabinets too
    (TrustedHosts + explicit ``PSCredential``).
    """
    host = (ip or "").strip()
    if is_lab_lan_ip(host):
        return "Default"
    return "Negotiate"


def _username_ok_for_host(user: str, ip: str | None) -> bool:
    host = (ip or "").strip()
    aliases = LAB_WORKGROUP_USERS.get(host)
    if not aliases:
        return True
    folded = (user or "").replace("/", "\\").casefold()
    return any(folded == alias.casefold() for alias in aliases)


def get_lab_credential(ip: str | None = None) -> tuple[str, str]:
    """Return the lab fleet credential for WinRM/PsExec/SMB.

    Resolution order: ``GOLDCLUB_LAB_PASSWORD`` env override, then a readable
    Credential Manager entry (must match the host's workgroup user when set),
    then the documented lab default. Never raises on Windows — remote probes
    must not be blocked just because Windows hides a ``cmdkey`` password from
    ``CredRead``.
    """
    default_user = lab_username_for_host(ip)
    from_manager = _lab_credential_from_manager(ip)

    env_pw = (os.environ.get(_LAB_PASSWORD_ENV) or "").strip()
    if env_pw:
        user = (
            from_manager[0]
            if from_manager and _username_ok_for_host(from_manager[0], ip)
            else default_user
        )
        return user, env_pw

    if from_manager is not None and _username_ok_for_host(from_manager[0], ip):
        return from_manager

    if sys.platform != "win32":
        raise LabCredentialError(
            "Lab credentials are only available on Windows (or set "
            f"{_LAB_PASSWORD_ENV})."
        )
    return default_user, _LAB_DEFAULT_PASSWORD


def probe_tcp_port(host: str, port: int, *, timeout_sec: float = 2.0) -> bool:
    """True when ``host:port`` accepts a TCP connection (lab LAN probe, not internet)."""
    ip = (host or "").strip()
    if not ip:
        return False
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _last_octet(ip: str) -> int:
    try:
        return int(ip.rsplit(".", 1)[-1])
    except ValueError:
        return 999


def lab_lan_ip_from_text(raw: str) -> str | None:
    """IPv4 on 10.0.0.0/24 from a typed IP or UNC Goldclub path."""
    text = (raw or "").strip().strip('"').replace("/", "\\")
    if is_lab_lan_ip(text):
        return text
    host = text
    if text.startswith("\\\\"):
        host = text.lstrip("\\").split("\\", 1)[0].strip()
    else:
        host = text.split("\\", 1)[0].strip()
    if is_lab_lan_ip(host):
        return host
    return None


def smb_host_from_cabinet_target(raw: str) -> str | None:
    """Host to probe for SMB: lab IP, any IPv4, or a UNC hostname.

    Local Goldclub roots (``C:\\Goldclub``, ``G:``) return None.
    """
    text = (raw or "").strip().strip('"').replace("/", "\\")
    if not text:
        return None
    ip = lab_lan_ip_from_text(text)
    if ip:
        return ip
    if text.startswith("\\\\"):
        host = text.lstrip("\\").split("\\", 1)[0].strip()
        return host or None
    first = text.split("\\", 1)[0].strip()
    if _IPV4_RE.fullmatch(first):
        octets = [int(p) for p in first.split(".")]
        if all(0 <= o <= 255 for o in octets):
            return first
    return None


def host_answers_smb(host: str, *, timeout_sec: float = 0.25) -> bool:
    """True when *host* accepts SMB (TCP 445, else 139)."""
    return _host_answers_smb((host or "").strip(), timeout_sec=timeout_sec)


def cabinet_target_answers_smb(target: str, *, timeout_sec: float = 0.25) -> bool:
    """True when this cabinet path's host is answering SMB."""
    host = smb_host_from_cabinet_target(target)
    if not host:
        return False
    return host_answers_smb(host, timeout_sec=timeout_sec)


def this_pc_lab_lan_ips() -> frozenset[str]:
    """This machine's 10.0.0.x addresses — skip them when listing remote cabinets."""
    keys: set[str] = set()
    try:
        hn = socket.gethostname()
        _name, _aliases, ips = socket.gethostbyname_ex(hn)
        keys.update(str(ip).strip() for ip in ips)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.0.0.1", 80))
            keys.add(sock.getsockname()[0])
    except OSError:
        pass
    return frozenset(ip for ip in keys if is_lab_lan_ip(ip))


def lab_lan_scan_ips(*, skip: Sequence[str] | None = None) -> list[str]:
    """Every host on 10.0.0.0/24 except .0 / .255 and *skip* (usually this PC)."""
    ignored = {str(item).strip() for item in (skip or ()) if str(item).strip()}
    return [
        f"10.0.0.{n}"
        for n in range(1, 255)
        if f"10.0.0.{n}" not in ignored
    ]


def priority_lab_scan_ips(
    recent: Sequence[str] | None = None,
) -> list[str]:
    """Probe last-used cabinets and the named shortcut set first."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in recent or ():
        ip = lab_lan_ip_from_text(str(raw))
        if ip and ip not in seen:
            seen.add(ip)
            out.append(ip)
    for ip in sorted(LAB_FLEET_IPS, key=_last_octet):
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def _app_is_shutting_down() -> bool:
    """True after the Config Scanner window X is clicked (real app session)."""
    try:
        from config_scanner.app_shutdown import is_shutting_down
    except Exception:
        return False
    return bool(is_shutting_down())


def _host_answers_smb(host: str, *, timeout_sec: float) -> bool:
    if probe_tcp_port(host, 445, timeout_sec=timeout_sec):
        return True
    return probe_tcp_port(host, 139, timeout_sec=min(0.15, timeout_sec))


def discover_active_lab_fleet(
    *,
    probe: Callable[[str], bool] | None = None,
    hosts: Sequence[str] | None = None,
    skip_hosts: Sequence[str] | None = None,
    priority_hosts: Sequence[str] | None = None,
    timeout_sec: float = 0.25,
    workers: int = 48,
    on_found: Callable[[str], None] | None = None,
) -> list[str]:
    """Lab LAN IPv4s that answer SMB — the cabinets that are actually up.

    Scans ``10.0.0.0/24`` unless *hosts* is passed. This PC's own 10.0.0.x
    addresses are skipped unless *skip_hosts* is set explicitly. Down
    cabinets are omitted. *priority_hosts* are probed first so remembered
    / named EGMs appear in the dropdown before the rest of the subnet.
    """
    if skip_hosts is None:
        skip = set(this_pc_lab_lan_ips())
    else:
        skip = {str(item).strip() for item in skip_hosts if str(item).strip()}

    if hosts is not None:
        batches = [[h.strip() for h in hosts if h and h.strip() not in skip]]
    else:
        priority = [
            h.strip()
            for h in (priority_hosts or ())
            if h and h.strip() not in skip
        ]
        rest = lab_lan_scan_ips(skip=skip.union(priority))
        batches = [priority, rest] if priority else [rest]

    check = probe or (lambda host: _host_answers_smb(host, timeout_sec=timeout_sec))

    def _guarded(host: str) -> bool:
        if _app_is_shutting_down():
            return False
        return bool(check(host))

    live: list[str] = []
    seen: set[str] = set()
    pool_size = max(1, min(int(workers), 64))
    for batch in batches:
        if _app_is_shutting_down():
            break
        if not batch:
            continue
        with ThreadPoolExecutor(max_workers=min(pool_size, len(batch))) as pool:
            futures = {pool.submit(_guarded, host): host for host in batch}
            for fut in as_completed(futures):
                if _app_is_shutting_down():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    ok = fut.result()
                except Exception:
                    continue
                host = futures[fut]
                if not ok or host in seen:
                    continue
                seen.add(host)
                live.append(host)
                if on_found is not None:
                    try:
                        on_found(host)
                    except Exception:
                        pass
    live.sort(key=_last_octet)
    return live


def format_lab_lan_unreachable(ip: str, *, winrm_open: bool, smb_open: bool, ping_ok: bool) -> str:
    """User-facing hint when a fleet cabinet cannot be reached on the lab subnet."""
    lines = [
        f"Cannot sync time — {ip} is not reachable on the lab LAN.",
        "",
        "Sync Time uses WinRM on the local subnet (10.0.0.x). It does not need internet.",
    ]
    if not ping_ok and not smb_open and not winrm_open:
        lines.extend(
            [
                "",
                "This PC may be off the lab network (e.g. home/office Wi‑Fi).",
                "Connect to the lab subnet, or run Log Investigator from the lab workstation.",
                "Fleet → Refresh known hosts to confirm the cabinet is online.",
            ]
        )
    elif ping_ok or smb_open:
        if not winrm_open:
            lines.extend(
                [
                    "",
                    f"{ip} responds on the network but WinRM (port 5985) is closed.",
                    "Enable WinRM on the cabinet: cabinet_tools\\shared\\Enable-WinRM.ps1",
                    "(or the USB Enable-WinRM script), then retry.",
                ]
            )
    lines.extend(
        [
            "",
            "First time from this PC? Run elevated:",
            "  .\\Initialize-LabAccess.ps1 -Verify",
        ]
    )
    return "\n".join(lines)


def _cmdkey_run(args: list[str]) -> bool:
    import logging
    import subprocess

    run_kw: dict = {
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": 15,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    try:
        completed = subprocess.run(["cmdkey", *args], **run_kw)
        return int(getattr(completed, "returncode", 1) or 0) == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.getLogger(__name__).debug("cmdkey %s failed: %s", args[:1], exc)
        return False


def _store_lab_cmdkey(host: str, user: str, password: str) -> bool:
    _cmdkey_run([f"/delete:{host}"])
    return _cmdkey_run([f"/add:{host}", f"/user:{user}", f"/pass:{password}"])


def _wnet_add(remote: str, username: str, password: str) -> None:
    import win32wnet  # type: ignore

    nr = win32wnet.NETRESOURCE()
    nr.dwType = 1  # RESOURCETYPE_DISK
    nr.lpRemoteName = remote
    # CONNECT_COMMANDLINE: fail instead of opening the Windows credential dialog.
    win32wnet.WNetAddConnection2(
        nr, password, username, _WNET_CONNECT_COMMANDLINE
    )


def _wnet_cancel(remote: str) -> None:
    try:
        import win32wnet  # type: ignore
    except ImportError:
        return
    try:
        win32wnet.WNetCancelConnection2(remote, 0, True)
    except Exception:  # noqa: BLE001
        return


def drop_lab_smb_sessions(host: str) -> None:
    """Drop leftover SMB sessions so the next connect can use the lab user."""
    ip = (host or "").strip()
    if not ip:
        return
    for share in _SMB_SHARES_TO_DROP:
        _wnet_cancel(rf"\\{ip}\{share}")
    import logging
    import subprocess

    run_kw: dict = {
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": 15,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    try:
        subprocess.run(
            ["net", "use", rf"\\{ip}\ipc$", "/delete", "/y"],
            **run_kw,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.getLogger(__name__).debug("net use /delete %s failed: %s", ip, exc)


def _connect_lab_ipc(host: str, username: str, password: str) -> None:
    remote = rf"\\{host}\IPC$"
    try:
        _wnet_add(remote, username, password)
    except ImportError:
        return
    except Exception as exc:  # noqa: BLE001
        code = win_error_code(exc)
        if code in _SMB_ALREADY_CONNECTED:
            return
        raise


def _connect_lab_disk_shares(host: str, username: str, password: str) -> None:
    """Bind ``slot`` / ``c$`` with the same silent login (best-effort)."""
    for share in ("slot", "c$", "C$"):
        try:
            _wnet_add(rf"\\{host}\{share}", username, password)
        except ImportError:
            return
        except Exception as exc:  # noqa: BLE001
            code = win_error_code(exc)
            if code in _SMB_ALREADY_CONNECTED:
                continue
            if is_smb_logon_failure(exc):
                raise


def ensure_lab_smb_credential(ip: str) -> bool:
    """Open a silent SMB session with test/test (no CredUI, no WinRM).

    ``cmdkey`` alone does not override an existing session from this PC's
    user. After a 1326/1219 we drop IPC$/shares and reconnect with the
    host-specific account (``10.0.0.111\\test`` on the workgroup slot,
    ``10.0.0.76\\test`` then ``GOLD-CLUB\\test`` on any other lab LAN IP).

    Returns ``True`` only when an SMB session was opened. Never raises.
    """
    import logging

    host = (ip or "").strip()
    if not host or sys.platform != "win32":
        return False
    if not is_lab_lan_ip(host):
        return False
    try:
        password = get_lab_credential(host)[1]
    except (LabCredentialError, ValueError):
        return False

    users = lab_smb_usernames_for_host(host)
    last_exc: BaseException | None = None
    for attempt, user in enumerate(users):
        _store_lab_cmdkey(host, user, password)
        try:
            _connect_lab_ipc(host, user, password)
            _connect_lab_disk_shares(host, user, password)
            return True
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not is_smb_logon_failure(exc) and attempt == 0:
                logging.getLogger(__name__).debug(
                    "SMB connect %s as %s failed: %s", host, user, exc
                )
                continue
            drop_lab_smb_sessions(host)
            try:
                _connect_lab_ipc(host, user, password)
                _connect_lab_disk_shares(host, user, password)
                return True
            except Exception as retry_exc:  # noqa: BLE001
                last_exc = retry_exc
                continue
    if last_exc is not None:
        logging.getLogger(__name__).debug(
            "lab SMB session for %s failed: %s", host, last_exc
        )
    return False


def safe_join_under(root: Path, relative_path: str) -> Path:
    """
    Join ``relative_path`` under ``root``, rejecting absolute paths and ``..``.

    Raises ``ValueError`` when the resolved destination would escape ``root``.
    """
    rel_raw = (relative_path or "").replace("\\", "/").strip()
    if not rel_raw:
        raise ValueError("Relative path is empty")
    if rel_raw.startswith("/") or re.match(r"^[A-Za-z]:/", rel_raw):
        raise ValueError(f"Absolute paths are not allowed: {relative_path!r}")
    parts = [p for p in Path(rel_raw).parts if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Path traversal is not allowed: {relative_path!r}")
    root_resolved = root.resolve()
    dest = (root_resolved.joinpath(*parts)).resolve()
    try:
        dest.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Resolved path escapes destination root:\n  {dest}\n  root={root_resolved}"
        ) from exc
    return dest


def allowed_ruleta_dest_uncs(ip: str) -> tuple[Path, ...]:
    """Remote Ruleta dests: admin share, or the ``slot`` share (GoldClub root)."""
    host = require_lab_fleet_ip(ip)
    return (
        Path(rf"\\{host}\c$\goldclub\ruleta"),
        Path(rf"\\{host}\slot\ruleta"),
    )


def _unc_key(path: Path | str) -> str:
    return str(path).replace("/", "\\").casefold().rstrip("\\")


def assert_ruleta_dest_unc(ip: str, dest: Path | str) -> Path:
    """Require dest under ``c$\\goldclub\\ruleta`` or ``slot\\ruleta`` on a fleet IP."""
    dest_path = Path(dest)
    dest_key = _unc_key(dest_path)
    allowed = allowed_ruleta_dest_uncs(ip)
    for root in allowed:
        root_key = _unc_key(root)
        if dest_key == root_key or dest_key.startswith(root_key + "\\"):
            return dest_path
    shown = " or ".join(str(p) for p in allowed)
    raise ValueError(
        f"Software Version destination must be under {shown} (got {dest_path})"
    )
