"""Built-in GameStar country-selector updates shipped inside Config Scanner.

The catalog lives under ``config_scanner/assets/embedded_updates/`` with:
``catalog.json``, ``b2u/*.b2u`` (official encrypted packages), and optional
``staged/<id>/CountrySelectorTool/`` (pre-decrypted data for offline cabinets).
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from config_scanner.paths import bundled_assets_root


@dataclass(frozen=True)
class EmbeddedUpdate:
    id: str
    label: str
    country: str
    gamestar_version: str
    b2u_file: str | None
    staged_id: str | None
    readme: str = ""

    @property
    def b2u_path(self) -> Path | None:
        if not self.b2u_file:
            return None
        path = embedded_updates_root() / "b2u" / self.b2u_file
        return path if path.is_file() else None

    @property
    def staged_tool_path(self) -> Path | None:
        key = self.staged_id or self.id
        tool = embedded_updates_root() / "staged" / key / "CountrySelectorTool"
        if (tool / "data").is_dir():
            return tool
        return None


def embedded_updates_root() -> Path:
    """Resolve bundled or beside-exe embedded country updates.

    Staged CountrySelector trees are **not** packed inside the PyInstaller exe
    (paths exceed Windows MAX_PATH during bootloader extract). Ship them under
    ``embedded_updates/staged/`` next to the exe on USB instead.
    """
    import logging

    log = logging.getLogger(__name__)
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent / "embedded_updates"
        if (beside / "catalog.json").is_file():
            return beside
    root = bundled_assets_root() / "embedded_updates"
    if (root / "catalog.json").is_file():
        return root
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent / "embedded_updates"
        if beside.is_dir():
            log.warning("embedded_updates beside exe missing catalog.json: %s", beside)
            return beside
    return root


def catalog_path() -> Path:
    return embedded_updates_root() / "catalog.json"


def load_catalog() -> list[EmbeddedUpdate]:
    path = catalog_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[EmbeddedUpdate] = []
    for item in data.get("updates") or []:
        if not item.get("id"):
            continue
        out.append(
            EmbeddedUpdate(
                id=str(item["id"]),
                label=str(item.get("label") or item["id"]),
                country=str(item.get("country") or ""),
                gamestar_version=str(item.get("gamestar_version") or ""),
                b2u_file=str(item["b2u_file"]) if item.get("b2u_file") else None,
                staged_id=str(item["staged_id"]) if item.get("staged_id") else None,
                readme=str(item.get("readme") or ""),
            )
        )
    return out


def find_embedded_update(update_id: str) -> EmbeddedUpdate | None:
    key = update_id.strip()
    for entry in load_catalog():
        if entry.id.casefold() == key.casefold():
            return entry
    return None


def materialize_country_tool(entry: EmbeddedUpdate) -> Path:
    """Return CountrySelectorTool path for restore/create (staged preferred)."""
    import logging

    log = logging.getLogger(__name__)
    staged = entry.staged_tool_path
    if staged is not None:
        log.info("materialize %s from staged %s", entry.id, staged)
        return staged
    b2u = entry.b2u_path
    if b2u is not None:
        log.info("materialize %s from b2u %s", entry.id, b2u)
        from config_scanner.b2u_pack import extract_b2u_update
        from config_scanner.pack_detect import detect_pack

        package = extract_b2u_update(b2u, reuse_cache=True)
        detected = detect_pack(package)
        if detected.root.is_dir() and (detected.root / "data").is_dir():
            return detected.root
        raise FileNotFoundError(
            f"decrypted {b2u.name} but no CountrySelectorTool/data found"
        )
    root = embedded_updates_root()
    raise FileNotFoundError(
        f"embedded update {entry.id} has no staged tree or .b2u "
        f"(looked under {root}; staged beside exe required for offline TRI packs)"
    )


def export_b2u_copy(entry: EmbeddedUpdate, dest_dir: Path) -> Path:
    """Copy the official ``.b2u`` to *dest_dir* for BiOS update apply."""
    b2u = entry.b2u_path
    if b2u is None:
        raise FileNotFoundError(f"{entry.id} has no bundled .b2u file")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / b2u.name
    shutil.copy2(b2u, dest)
    return dest


def write_catalog(entries: list[EmbeddedUpdate], path: Path | None = None) -> Path:
    path = path or catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updates": [
            {
                "id": e.id,
                "label": e.label,
                "country": e.country,
                "gamestar_version": e.gamestar_version,
                "b2u_file": e.b2u_file,
                "staged_id": e.staged_id or e.id,
                "readme": e.readme,
            }
            for e in entries
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
