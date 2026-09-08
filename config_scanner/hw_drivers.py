"""Cabinet button-deck HW drivers (Keyboard.xml + Lights.xml).

Official packs from lab ``HW_config_tools`` (ST3 / Rhapsody / Sublime Axiomtek).
Copied as whole files — formats differ slightly from live ButtonMapping trees.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from config_scanner.paths import bundled_assets_root

_KEYBOARD_REL = "slot/hwdrivers/Keyboard.xml"
_LIGHTS_REL = "slot/hwdrivers/Lights.xml"

HW_DRIVER_FILES: tuple[str, ...] = (_KEYBOARD_REL, _LIGHTS_REL)


@dataclass(frozen=True)
class HwDriverProfile:
    id: str
    label: str
    dir_name: str

    @property
    def root(self) -> Path:
        return hw_drivers_assets_root() / self.dir_name

    def keyboard_path(self) -> Path:
        return self.root / "Keyboard.xml"

    def lights_path(self) -> Path:
        return self.root / "Lights.xml"

    def is_complete(self) -> bool:
        return self.keyboard_path().is_file() and self.lights_path().is_file()


def hw_drivers_assets_root() -> Path:
    return bundled_assets_root() / "hw_drivers"


def list_hw_driver_profiles() -> tuple[HwDriverProfile, ...]:
    specs = (
        HwDriverProfile("ST3", "ST3 (SFB button deck)", "ST3"),
        HwDriverProfile("Rhapsody", "Rhapsody", "Rhapsody"),
        HwDriverProfile(
            "Sublime_Axiomtek", "Sublime Axiomtek", "Sublime_Axiomtek"
        ),
    )
    return tuple(p for p in specs if p.is_complete())


def find_hw_driver_profile(profile_id: str) -> HwDriverProfile | None:
    want = (profile_id or "").strip()
    for prof in list_hw_driver_profiles():
        if prof.id.casefold() == want.casefold():
            return prof
    return None


def _file_md5(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.md5(path.read_bytes()).hexdigest()


def detect_hw_driver_profile(goldclub: Path) -> str | None:
    """Return profile id when live Keyboard+Lights match a bundled pack."""
    kb = goldclub / _KEYBOARD_REL
    lights = goldclub / _LIGHTS_REL
    live_kb = _file_md5(kb)
    live_lights = _file_md5(lights)
    if live_kb is None or live_lights is None:
        return None
    for prof in list_hw_driver_profiles():
        if (
            _file_md5(prof.keyboard_path()) == live_kb
            and _file_md5(prof.lights_path()) == live_lights
        ):
            return prof.id
    return None


def stage_hw_driver_profile(profile_id: str, pack_dir: Path) -> list[str]:
    """Copy Keyboard.xml + Lights.xml into a config pack. Returns relative paths."""
    prof = find_hw_driver_profile(profile_id)
    if prof is None:
        raise ValueError(f"Unknown HW driver profile: {profile_id}")
    written: list[str] = []
    mapping = (
        (prof.keyboard_path(), _KEYBOARD_REL),
        (prof.lights_path(), _LIGHTS_REL),
    )
    for src, rel in mapping:
        if not src.is_file():
            raise FileNotFoundError(src)
        dest = pack_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(rel.replace("\\", "/"))
    return written


def apply_hw_driver_profile(profile_id: str, goldclub: Path) -> list[str]:
    """Write ST3/Rhapsody/Sublime Keyboard+Lights onto a live Goldclub root."""
    pack = goldclub / "_hw_driver_stage"
    try:
        if pack.exists():
            shutil.rmtree(pack)
        pack.mkdir(parents=True, exist_ok=True)
        written = stage_hw_driver_profile(profile_id, pack)
        out: list[str] = []
        for rel in written:
            src = pack / rel
            dest = goldclub / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            out.append(rel)
        return out
    finally:
        shutil.rmtree(pack, ignore_errors=True)
