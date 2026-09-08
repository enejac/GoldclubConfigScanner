"""Theme math payloads for Config Scanner — filename patterns only.

Game / feature folder names change between images. Discovery walks
``themes/<any>/`` and ``slot/themes/<any>/`` and keeps files whose *names*
look like math (``*math*.json``, ``ProgressiveSetup.xml``). Compare uses SHA1
only; these files are not decrypted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class _HashDiff(Protocol):
    baseline_sha1: str | None
    target_sha1: str | None
    baseline_size_bytes: int | None
    target_size_bytes: int | None

# Media / selector trees — not game names. Do not descend here for math.
_SKIP_THEME_SUBDIRS = frozenset(
    {
        "assets",
        "data",
        "help",
        "image",
        "images",
        "movie",
        "movies",
        "sound",
        "sounds",
        "textures",
        "video",
        "videos",
    }
)

_THEME_ROOT_RELS = ("themes", "slot/themes")


def is_theme_math_filename(name: str) -> bool:
    """True for encrypted/plain theme math payloads (any game folder)."""
    n = (name or "").casefold()
    if n == "progressivesetup.xml":
        return True
    return n.endswith(".json") and "math" in n


def is_theme_math_rel(relative_path: str) -> bool:
    """True when *relative_path* is a theme math payload (not MathSettings)."""
    low = (relative_path or "").replace("\\", "/").casefold().strip("/")
    parts = [p for p in low.split("/") if p]
    if "themes" not in parts:
        return False
    idx = parts.index("themes")
    rest = parts[idx + 1 :]
    if not rest or rest[0] == "data":
        return False
    return is_theme_math_filename(parts[-1])


def _math_files_in_dir(folder: Path) -> list[Path]:
    out: list[Path] = []
    try:
        children = list(folder.iterdir())
    except OSError:
        return out
    for child in children:
        try:
            if child.is_file() and is_theme_math_filename(child.name):
                out.append(child)
        except OSError:
            continue
    return out


def math_files_under_theme_game_dir(game_dir: Path) -> list[Path]:
    """Math payloads in one theme folder (any name) plus one non-media child."""
    root = Path(game_dir)
    found = _math_files_in_dir(root)
    try:
        children = list(root.iterdir())
    except OSError:
        return found
    for child in children:
        try:
            if not child.is_dir():
                continue
            if child.name.casefold() in _SKIP_THEME_SUBDIRS:
                continue
            found.extend(_math_files_in_dir(child))
        except OSError:
            continue
    return found


def math_files_under_theme_root(themes_root: Path) -> list[Path]:
    """Math payloads under a ``themes`` directory (root files + each game folder)."""
    root = Path(themes_root)
    if not root.is_dir():
        return []
    found = _math_files_in_dir(root)
    try:
        children = list(root.iterdir())
    except OSError:
        return found
    for child in children:
        try:
            if not child.is_dir():
                continue
            if child.name.casefold() in _SKIP_THEME_SUBDIRS:
                continue
            found.extend(math_files_under_theme_game_dir(child))
        except OSError:
            continue
    return found


def iter_theme_math_files(game_drive: Path) -> list[Path]:
    """All theme math files under a Goldclub / slot scan root."""
    drive = Path(game_drive)
    seen: set[Path] = set()
    out: list[Path] = []
    for rel in _THEME_ROOT_RELS:
        root = drive / rel
        for path in math_files_under_theme_root(root):
            try:
                key = path.resolve()
            except OSError:
                key = path
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def theme_math_compare_note(file_diff: _HashDiff) -> str:
    """One-line SHA1 compare text — no decrypt, no ciphertext line dump."""
    old = file_diff.baseline_sha1 or "(none)"
    new = file_diff.target_sha1 or "(none)"
    old_n = file_diff.baseline_size_bytes
    new_n = file_diff.target_size_bytes
    sizes = ""
    if old_n is not None or new_n is not None:
        left = "?" if old_n is None else str(old_n)
        right = "?" if new_n is None else str(new_n)
        sizes = f" ({left} → {right} bytes)"
    return (
        f"Theme math payload — SHA1 {old} → {new}{sizes}. "
        "Compared by hash only (not decrypted)."
    )
