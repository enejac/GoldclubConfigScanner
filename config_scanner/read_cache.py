"""Read caches for slow SMB cabinet loads.

Two independent pieces:

* :func:`open_exe_cached` / :func:`read_exe_bytes_cached` - one read of a game
  executable per ``(path, size, mtime)``. A Live Push load used to pull
  ``OneHand.exe`` (about 9.5 MB) three or four times over SMB: VERSIONINFO
  scan, UTF-16 version sniff, Debug SKU check, and the TargetMarket token
  scan. Now the first caller reads it and the others get a ``BytesIO`` over
  the same buffer. A per-path lock makes concurrent first callers wait for
  the single read instead of racing it.

* :func:`scoped_read_cache` - a ``contextvars`` scope in which XML parses and
  case-insensitive Goldclub path lookups are memoised. Only code running
  inside the scope (and worker threads started with the copied context, see
  :func:`run_in_scope`) sees the cache; a GUI hover or the fleet scan on
  another thread is unaffected. Nothing writes to the cabinet while a load
  scope is open, so stale reads cannot happen.
"""

from __future__ import annotations

import contextvars
import io
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, TypeVar

T = TypeVar("T")

# Executables bigger than this are streamed from disk instead of cached.
EXE_CACHE_MAX_FILE_BYTES = 64 * 1024 * 1024
# Number of distinct executables kept (one per cabinet is plenty).
EXE_CACHE_MAX_ENTRIES = 4

_EXE_LOCK = threading.Lock()
_EXE_PATH_LOCKS: dict[str, threading.Lock] = {}
_EXE_CACHE: "OrderedDict[str, tuple[tuple[int, int], bytes]]" = OrderedDict()
_EXE_READS = 0  # test / diagnostics: how many real disk reads happened


def _exe_key(path: Path) -> str:
    return str(path).casefold()


def _path_lock(key: str) -> threading.Lock:
    with _EXE_LOCK:
        lock = _EXE_PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _EXE_PATH_LOCKS[key] = lock
        return lock


def exe_cache_read_count() -> int:
    """Number of real executable reads since process start (diagnostics)."""
    return _EXE_READS


def clear_exe_cache() -> None:
    with _EXE_LOCK:
        _EXE_CACHE.clear()


def read_exe_bytes_cached(path: Path) -> bytes | None:
    """Whole-file bytes for a game exe, read once per ``(size, mtime)``.

    Returns ``None`` when the file is missing, unreadable, or larger than
    :data:`EXE_CACHE_MAX_FILE_BYTES` - callers then fall back to streaming.
    """
    global _EXE_READS
    path = Path(path)
    try:
        st = path.stat()
    except (OSError, ValueError):
        return None
    if st.st_size > EXE_CACHE_MAX_FILE_BYTES:
        return None
    stamp = (int(st.st_size), int(st.st_mtime_ns))
    key = _exe_key(path)
    with _EXE_LOCK:
        hit = _EXE_CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            _EXE_CACHE.move_to_end(key)
            return hit[1]
    with _path_lock(key):
        # Another thread may have filled it while we waited for the lock.
        with _EXE_LOCK:
            hit = _EXE_CACHE.get(key)
            if hit is not None and hit[0] == stamp:
                _EXE_CACHE.move_to_end(key)
                return hit[1]
        try:
            data = path.read_bytes()
        except (OSError, ValueError):
            return None
        with _EXE_LOCK:
            _EXE_READS += 1
            _EXE_CACHE[key] = (stamp, data)
            _EXE_CACHE.move_to_end(key)
            while len(_EXE_CACHE) > EXE_CACHE_MAX_ENTRIES:
                _EXE_CACHE.popitem(last=False)
        return data


def open_exe_cached(path: Path) -> BinaryIO:
    """``path.open("rb")`` replacement backed by :func:`read_exe_bytes_cached`.

    Raises ``OSError`` like ``open`` when the file cannot be read, so callers
    keep their existing ``except OSError`` handling.
    """
    data = read_exe_bytes_cached(path)
    if data is not None:
        return io.BytesIO(data)
    return Path(path).open("rb")


# --------------------------------------------------------------------------
# Scoped read cache (XML parses, Goldclub path resolution)
# --------------------------------------------------------------------------


@dataclass
class _ReadScope:
    lock: threading.Lock = field(default_factory=threading.Lock)
    xml: dict[str, Any] = field(default_factory=dict)
    resolved: dict[tuple[str, str], Path | None] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0


_SCOPE: contextvars.ContextVar[_ReadScope | None] = contextvars.ContextVar(
    "goldclub_read_scope", default=None
)


@contextmanager
def scoped_read_cache() -> Iterator[_ReadScope]:
    """Memoise XML parses / path lookups for the duration of one cabinet load.

    Nested scopes reuse the outer one.
    """
    current = _SCOPE.get()
    if current is not None:
        yield current
        return
    scope = _ReadScope()
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def read_scope_active() -> bool:
    return _SCOPE.get() is not None


def run_in_scope(fn: Callable[..., T], *args: Any, **kwargs: Any) -> Callable[[], T]:
    """Bind *fn* to the caller's context so a pool thread shares the scope.

    ``ThreadPoolExecutor`` workers do not inherit ``contextvars``; submit
    ``run_in_scope(fn, ...)`` instead of ``fn`` directly.
    """
    ctx = contextvars.copy_context()

    def _call() -> T:
        return ctx.run(fn, *args, **kwargs)

    return _call


def cached_parse(path: Path, parser: Callable[[Path], T]) -> T:
    """``parser(path)`` memoised by path while a read scope is active."""
    scope = _SCOPE.get()
    if scope is None:
        return parser(path)
    key = str(path).casefold()
    with scope.lock:
        if key in scope.xml:
            scope.hits += 1
            return scope.xml[key]
    result = parser(path)
    with scope.lock:
        scope.misses += 1
        scope.xml[key] = result
    return result


def cached_resolve(
    root: Path, relative: str, resolver: Callable[[Path, str], Path | None]
) -> Path | None:
    """``resolver(root, relative)`` memoised while a read scope is active."""
    scope = _SCOPE.get()
    if scope is None:
        return resolver(root, relative)
    key = (str(root).casefold(), relative.replace("\\", "/").casefold())
    with scope.lock:
        if key in scope.resolved:
            scope.hits += 1
            return scope.resolved[key]
    result = resolver(root, relative)
    with scope.lock:
        scope.misses += 1
        scope.resolved[key] = result
    return result
