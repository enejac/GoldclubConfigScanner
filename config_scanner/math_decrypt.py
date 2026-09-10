"""Read-only access to GoldClub crypt tools (never write beside live math).

Sidecar ``tools\\ReadMe.txt`` (legacy packs may still nest ``CRYPT_TOOLS``):

* ``Encryptor.exe`` — JSON / ProgressiveSetup.xml (Link2Win math)
* ``BiOSCrypt.exe`` — Slot BiOS update packages (``.exe``)
* ``BiOS Encryptor.exe`` — BiOS 1.0.6 updates (``.ws``)
* ``JPCrypt.exe`` — external Jackpot Controller updates

Math files are shipped separately. Preflight copies an encrypted JSON into a
temp folder before ``Encryptor.exe`` sees it. Sample / modified theme math
(Tutankhamen*.json) is never copied.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from config_scanner.tool_sidecar import sidecar_tools_dir

# One Encryptor at a time — Live Push inspects two Link2Win files and used
# to spawn a second GameStar GUI in session 1.
_DECRYPT_LOCK = threading.Lock()
_DECRYPT_RESULTS: dict[tuple[str, str, str], bytes | None] = {}
_SW_HIDE = 0
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
_HIDDEN_DESKTOP = "gcs_math_decrypt"
_DEFAULT_DECRYPT_TIMEOUT_SEC = 8.0

CRYPT_TOOL_FILES: tuple[str, ...] = (
    "Encryptor.exe",
    "BiOSCrypt.exe",
    "BiOS Encryptor.exe",
    "JPCrypt.exe",
    "ReadMe.txt",
)

# JSON / ProgressiveSetup — the only tool preflight may run on math files.
JSON_DECRYPTOR_NAME = "Encryptor.exe"

# Never stage these next to CountrySelector (operator math drops, not tools).
_FORBIDDEN_MATH_GLOBS: tuple[str, ...] = (
    "*Tutankhamen*",
    "*Math.json",
    "*.json",
)


def _exe_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def crypt_tools_complete(folder: Path) -> bool:
    """True when the folder has Encryptor.exe (JSON) plus the ReadMe."""
    root = Path(folder)
    return (root / JSON_DECRYPTOR_NAME).is_file() and (root / "ReadMe.txt").is_file()


def crypt_tools_search_roots() -> list[Path]:
    """Folders that may contain Encryptor.exe (flat ``tools`` or legacy nest)."""
    roots: list[Path] = []
    env = (os.environ.get("GCS_CRYPT_TOOLS") or "").strip()
    if env:
        roots.append(Path(env))
    tools = sidecar_tools_dir()
    roots.extend(
        [
            tools,
            tools / "CRYPT_TOOLS",
        ]
    )
    exe_dir = _exe_dir()
    if exe_dir is not None:
        roots.extend(
            [
                exe_dir / "CRYPT_TOOLS",
                exe_dir,
            ]
        )
    repo = _repo_root()
    roots.extend(
        [
            repo / "CRYPT_TOOLS",
            Path.cwd() / "tools",
            Path.cwd() / "CRYPT_TOOLS",
            Path.cwd() / "tools" / "CRYPT_TOOLS",
        ]
    )
    staged = repo / "config_scanner" / "assets" / "embedded_updates" / "staged"
    if staged.is_dir():
        for tool in staged.glob("*/CountrySelectorTool"):
            roots.append(tool / "CRYPT_TOOLS")
            roots.append(tool)
    for letter in "DEFGHI":
        drive = Path(f"{letter}:/")
        if drive.exists():
            roots.extend(
                [
                    drive / "tools",
                    drive / "CRYPT_TOOLS",
                    drive / "tools" / "CRYPT_TOOLS",
                    drive / "ConfigScanner" / "tools",
                    drive / "ConfigScanner" / "CRYPT_TOOLS",
                ]
            )
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def find_crypt_tools_dir() -> Path | None:
    """First complete tools folder (Encryptor.exe + ReadMe)."""
    for root in crypt_tools_search_roots():
        try:
            if crypt_tools_complete(root):
                return root
            nested = root / "CRYPT_TOOLS"
            if crypt_tools_complete(nested):
                return nested
        except OSError:
            continue
    return None


def find_math_decryptor() -> Path | None:
    """``Encryptor.exe`` for JSON math, or GCS_MATH_DECRYPTOR override."""
    env = (os.environ.get("GCS_MATH_DECRYPTOR") or "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
    folder = find_crypt_tools_dir()
    if folder is not None:
        exe = folder / JSON_DECRYPTOR_NAME
        if exe.is_file():
            return exe
    return None


def stage_crypt_tools(dest_tool_dir: Path) -> Path | None:
    """Copy CRYPT_TOOLS next to CountrySelector.exe. Skips sample math JSON."""
    src = find_crypt_tools_dir()
    if src is None:
        return None
    dest = Path(dest_tool_dir) / "CRYPT_TOOLS"
    dest.mkdir(parents=True, exist_ok=True)
    for name in CRYPT_TOOL_FILES:
        source = src / name
        if source.is_file():
            shutil.copy2(source, dest / name)
    for pattern in _FORBIDDEN_MATH_GLOBS:
        for junk in dest.glob(pattern):
            if junk.name in CRYPT_TOOL_FILES:
                continue
            try:
                junk.unlink()
            except OSError:
                continue
    return dest if crypt_tools_complete(dest) else None


def looks_like_plain_math_json(raw: bytes) -> bool:
    if not raw:
        return False
    head = raw.lstrip()[:1]
    return head in (b"{", b"[")


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_if_plain(path: Path) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return raw if looks_like_plain_math_json(raw) else None


def _windows_hidden_desktop() -> str | None:
    """Desktop name for WinForms so Encryptor is not shown in session 1."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        generic_all = 0x10000000
        handle = user32.CreateDesktopW(
            _HIDDEN_DESKTOP, None, None, 0, generic_all, None
        )
        if not handle:
            handle = user32.OpenDesktopW(_HIDDEN_DESKTOP, 0, False, generic_all)
        if not handle:
            return None
        return _HIDDEN_DESKTOP
    except (OSError, AttributeError, ValueError):
        return None


def _decrypt_timeout_sec() -> float:
    raw = (os.environ.get("GCS_MATH_DECRYPT_TIMEOUT") or "").strip()
    if raw:
        try:
            return max(0.3, min(float(raw), 60.0))
        except ValueError:
            pass
    return _DEFAULT_DECRYPT_TIMEOUT_SEC


def _hidden_popen_kwargs() -> dict[str, object]:
    """Background start. CREATE_NO_WINDOW alone is ignored by WinForms."""
    kw: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= _STARTF_USESHOWWINDOW
        startup.wShowWindow = _SW_HIDE
        desktop = _windows_hidden_desktop()
        if desktop:
            startup.lpDesktop = desktop
        kw["startupinfo"] = startup
        kw["creationflags"] = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    return kw


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt" and proc.pid:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=8,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
        return
    proc.kill()


def _decrypt_command(exe: Path, src_copy: Path, dest_plain: Path) -> list[str]:
    """Single argv set — a second Encryptor.exe is a second GameStar dialog."""
    if exe.suffix.casefold() == ".py":
        return [sys.executable, str(exe), str(src_copy), str(dest_plain)]
    return [str(exe), str(src_copy), str(dest_plain)]


def _run_decryptor(exe: Path, src_copy: Path, dest_plain: Path) -> bytes | None:
    """Run Encryptor against temp files only. Hidden; one process; killed on stall."""
    cmd = _decrypt_command(exe, src_copy, dest_plain)
    cwd = str(exe.parent)
    timeout = _decrypt_timeout_sec()
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, **_hidden_popen_kwargs())  # type: ignore[arg-type]
    except OSError:
        return None
    stdout = b""
    try:
        stdout, _stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            stdout, _stderr = proc.communicate(timeout=3)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            stdout = b""
    except OSError:
        _kill_process_tree(proc)
        return None
    plain = _read_if_plain(dest_plain)
    if plain is not None:
        return plain
    inplace = _read_if_plain(src_copy)
    if inplace is not None:
        return inplace
    if stdout and looks_like_plain_math_json(stdout):
        return stdout
    return None


def _decrypt_uncached(src: Path, exe: Path) -> bytes | None:
    tmp_root = Path(tempfile.mkdtemp(prefix="gcs-math-decrypt-"))
    try:
        src_copy = tmp_root / src.name
        dest_plain = tmp_root / (src.stem + ".plain.json")
        shutil.copy2(src, src_copy)
        return _run_decryptor(exe, src_copy, dest_plain)
    except OSError:
        return None
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def decrypt_math_file(
    path: Path,
    *,
    decryptor: Path | None = None,
    spawn: bool = True,
) -> bytes | None:
    """Plain JSON bytes from a live math file, or None.

    Tries the built-in GameStar AES-CFB decoder first (no GUI). Only then
    copies *path* into a temp folder for ``Encryptor.exe``. The cabinet file
    is never overwritten. ``spawn=False`` still runs the built-in decoder;
    it only skips launching the GameStar File Encryptor window.
    """
    src = Path(path)
    try:
        raw = src.read_bytes()
    except OSError:
        return None
    if looks_like_plain_math_json(raw):
        return raw
    try:
        digest = _file_digest(src)
        src_key = str(src.resolve())
    except OSError:
        return None
    builtin_key = (digest, src_key, "gamestar")
    with _DECRYPT_LOCK:
        if builtin_key in _DECRYPT_RESULTS:
            return _DECRYPT_RESULTS[builtin_key]
        from config_scanner.gamestar_crypt import decrypt_gamestar_bytes

        builtin = decrypt_gamestar_bytes(raw)
        if builtin is not None and looks_like_plain_math_json(builtin):
            _DECRYPT_RESULTS[builtin_key] = builtin
            return builtin
        exe = Path(decryptor) if decryptor is not None else find_math_decryptor()
        if exe is None or not exe.is_file():
            return None
        key = (digest, src_key, str(exe.resolve()))
        if key in _DECRYPT_RESULTS:
            return _DECRYPT_RESULTS[key]
        if not spawn:
            return None
        result = _decrypt_uncached(src, exe)
        _DECRYPT_RESULTS[key] = result
        return result


def clear_math_decrypt_cache() -> None:
    with _DECRYPT_LOCK:
        _DECRYPT_RESULTS.clear()
