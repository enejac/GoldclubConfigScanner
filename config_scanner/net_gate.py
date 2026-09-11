"""Fast reachability gate for UNC paths.

On Windows, ``Path("//10.0.0.249/...").is_dir()`` against a host that is off
or on another network blocks the calling thread for 20-60 s inside the SMB
redirector. When that happens on the Qt GUI thread, Windows paints
"Not responding" over the window. Every panel that touches a lab share or a
cabinet share from the GUI thread must ask this module first.

A host is probed once with a short TCP connect to 445 (then 139) and the
answer is cached for :data:`CACHE_TTL_SEC`; ``clear_reachability_cache`` (or
the wizard's Refresh list) forces a re-probe.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

CACHE_TTL_SEC = 30.0
DEFAULT_TIMEOUT_SEC = 1.0

_UNC_RE = re.compile(r"^[\\/]{2}([^\\/]+)[\\/]")

_CACHE: dict[str, tuple[bool, float]] = {}


def unc_host(path: str | Path | None) -> str | None:
    """Host part of ``\\\\host\\share`` / ``//host/share``; ``None`` for local paths."""
    text = str(path or "").strip()
    if not text:
        return None
    match = _UNC_RE.match(text)
    if not match:
        return None
    host = match.group(1).strip()
    if not host or host in {"?", "."}:
        return None
    return host


def clear_reachability_cache() -> None:
    _CACHE.clear()


def _probe(host: str, timeout_sec: float) -> bool:
    try:
        from network.lab_access import probe_tcp_port
    except Exception:  # noqa: BLE001 - never block the UI on an import problem
        return True
    if probe_tcp_port(host, 445, timeout_sec=timeout_sec):
        return True
    return probe_tcp_port(host, 139, timeout_sec=min(0.5, timeout_sec))


def host_reachable(
    host: str | None,
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    use_cache: bool = True,
) -> bool:
    """True when *host* answers on SMB (445/139). Cached per host for a short TTL."""
    key = (host or "").strip().casefold()
    if not key:
        return True
    now = time.monotonic()
    if use_cache:
        hit = _CACHE.get(key)
        if hit is not None and now - hit[1] < CACHE_TTL_SEC:
            return hit[0]
    ok = _probe(key, timeout_sec)
    _CACHE[key] = (ok, now)
    return ok


def remote_path_available(path: str | Path | None, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> bool:
    """Gate before any ``Path`` I/O: local paths pass, UNC paths need a live host."""
    host = unc_host(path)
    if host is None:
        return True
    return host_reachable(host, timeout_sec=timeout_sec)


def unreachable_hosts() -> list[str]:
    """Hosts the cache currently knows are down (for inline UI notes)."""
    now = time.monotonic()
    return sorted(
        host
        for host, (ok, stamp) in _CACHE.items()
        if not ok and now - stamp < CACHE_TTL_SEC
    )


def offline_note(hosts: list[str] | None = None) -> str:
    """One-line status for panels: which lab hosts are down, or empty when all up."""
    down = hosts if hosts is not None else unreachable_hosts()
    if not down:
        return ""
    joined = ", ".join(f"\\\\{h}" for h in down)
    return f"Lab share {joined} not reachable (SMB 445) — built-in packs only. Refresh list to retry."
