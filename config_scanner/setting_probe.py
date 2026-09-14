"""Probe a Goldclub-shaped tree (live EGM or CS leaf) against the setting registry."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from config_scanner.setting_spec import SettingSpec, all_specs
from config_scanner.slot_setup import _find_child, _find_desc, _local, _parse_xml


class SettingState(str, Enum):
    MATCH = "match"  # green — present and equals expected
    DIFFERS = "differs"  # amber — present, different value
    ABSENT = "absent"  # red — not present at all
    NOT_SUPPLIED = "n/a"  # gray — source cannot deliver / no opinion


@dataclass(frozen=True)
class SettingReading:
    spec_id: str
    state: SettingState
    value: Any = None
    present: bool = False
    note: str = ""


def _boolish(text: str | None) -> bool | None:
    if text is None:
        return None
    t = text.strip().lower()
    if t in ("true", "1", "yes"):
        return True
    if t in ("false", "0", "no"):
        return False
    return None


def _load_xml(path: Path) -> ET.Element | None:
    if not path.is_file():
        return None
    try:
        return _parse_xml(path).getroot()
    except (ET.ParseError, OSError):
        return None


def _find_by_locator(doc: ET.Element, locator: str) -> ET.Element | None:
    parts = [p for p in locator.replace("\\", "/").split("/") if p]
    if not parts:
        return None
    # First segment: prefer descendant (tags may nest under wrappers).
    cur = _find_desc(doc, parts[0])
    if cur is None:
        return _find_desc(doc, parts[-1]) if len(parts) > 1 else None
    for part in parts[1:]:
        nxt = _find_child(cur, part)
        if nxt is None:
            # Some tags like AFT.anyAftEnabled are flat descendants.
            nxt = _find_desc(cur, part)
        if nxt is None:
            # Nested wrapper missing (flat TargetMarket / CultureName).
            return _find_desc(doc, parts[-1])
        cur = nxt
    return cur


def _read_int_list(el: ET.Element) -> list[int]:
    out: list[int] = []
    for child in el:
        if _local(child.tag) == "int" and (child.text or "").strip():
            try:
                out.append(int(child.text.strip()))
            except ValueError:
                continue
    return out


def _read_str_list(el: ET.Element, *, dallas_codes: bool = False) -> list[str]:
    out: list[str] = []
    if dallas_codes:
        for child in el:
            if _local(child.tag) != "DallasKey":
                continue
            code_el = _find_child(child, "Code")
            if code_el is not None and (code_el.text or "").strip():
                out.append((code_el.text or "").strip())
        return out
    for child in el:
        local = _local(child.tag)
        if local in ("string", "int") and (child.text or "").strip():
            out.append((child.text or "").strip())
    return out


def _read_token_map(el: ET.Element) -> dict[str, int]:
    out: dict[str, int] = {}
    for child in el:
        if _local(child.tag) != "TokenMapping":
            continue
        code = (child.attrib.get("Code") or "").strip()
        try:
            value = int((child.text or "0").strip())
        except ValueError:
            continue
        if code:
            out[code] = value
    return out


def _read_button_map(el: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    container = el
    if _local(el.tag) != "mapping":
        mapped = _find_desc(el, "mapping")
        if mapped is not None:
            container = mapped
    for child in container:
        if _local(child.tag) != "ButtonMapping":
            continue
        name = (child.attrib.get("name") or "").strip()
        if name:
            out[name] = (child.text or "").strip()
    return out


def _read_ini_value(path: Path, key: str) -> tuple[bool, Any, str]:
    if not path.is_file():
        return False, None, f"missing {path.name}"
    want = key.strip().casefold()
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return False, None, str(exc)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")):
            continue
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip().casefold() == want:
            return True, value.strip(), ""
    return False, None, f"missing key {key}"


def _read_service_enabled(path: Path, locator: str) -> tuple[bool, Any, str]:
    """Enabled flag for one AurumServicesConfig ServicesToRun block."""
    doc = _load_xml(path)
    if doc is None:
        return False, None, f"missing {path.name}"
    want = locator.strip().casefold()
    if not want:
        return False, None, "empty service locator"
    for svc in doc:
        if _local(svc.tag) != "ServicesToRun":
            continue
        names: list[str] = []
        enabled: bool | None = None
        for child in svc:
            loc = _local(child.tag)
            if loc in ("AssemblyPathName", "ServiceTypeName", "ParametersString"):
                names.append((child.text or "").strip())
            elif loc == "Enabled":
                enabled = _boolish(child.text)
        blob = " ".join(names).casefold()
        if want in blob:
            return True, enabled, ""
    return False, None, f"service {locator} not found"


def _extract_value(spec: SettingSpec, el: ET.Element) -> Any:
    if spec.kind == "bool":
        return _boolish(el.text)
    if spec.kind == "int_list":
        return _read_int_list(el)
    if spec.kind == "str_list":
        return _read_str_list(el, dallas_codes=spec.id == "dallas.key_codes")
    if spec.kind == "token_map":
        return _read_token_map(el)
    if spec.kind == "button_map":
        return _read_button_map(el)
    # scalar
    return (el.text or "").strip() if el.text is not None else ""


def _values_equal(kind: str, left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left == right
    if kind in ("bool", "service_enabled"):
        return bool(left) == bool(right)
    if kind in ("int_list", "str_list"):
        return list(left) == list(right)
    if kind in ("token_map", "button_map"):
        return dict(left) == dict(right)
    return str(left).strip() == str(right).strip()


def _theme_math_paths(goldclub: Path) -> list[Path]:
    themes = goldclub / "slot" / "themes"
    if not themes.is_dir():
        return []
    out: list[Path] = []
    for game_dir in sorted(themes.iterdir()):
        if not game_dir.is_dir() or game_dir.name.casefold() == "data":
            continue
        math = game_dir / "MathSettings.xml"
        if math.is_file():
            out.append(math)
    return out


def _file_for_spec(goldclub: Path, spec: SettingSpec) -> Path | None:
    rel = spec.file_rel.replace("\\", "/")
    if "*" in rel:
        return None
    path = goldclub / Path(rel)
    return path if path.is_file() else None


def read_setting_value(goldclub: Path, spec: SettingSpec) -> tuple[bool, Any, str]:
    """Return (present, value, note) for one setting at a Goldclub-shaped root."""
    goldclub = Path(goldclub)
    if not spec.cs_pack_delivers and not (goldclub / Path(spec.file_rel.replace("*", "x"))).parent.exists():
        # Still try normal path for live EGMs.
        pass

    if spec.kind == "ini_scalar":
        rel = spec.file_rel.replace("\\", "/")
        path = goldclub / Path(rel)
        return _read_ini_value(path, spec.locator)

    if spec.kind == "service_enabled":
        rel = spec.file_rel.replace("\\", "/")
        path = goldclub / Path(rel)
        return _read_service_enabled(path, spec.locator)

    if spec.per_theme:
        paths = _theme_math_paths(goldclub)
        if not paths:
            return False, None, "no MathSettings.xml themes"
        # Aggregate: majority / first for scalar lists of themes.
        values: list[Any] = []
        themes_hit: list[str] = []
        for path in paths:
            doc = _load_xml(path)
            if doc is None:
                continue
            el = _find_by_locator(doc, spec.locator)
            if el is None:
                # FixedBet may be top-level.
                if spec.locator == "FixedBet":
                    el = _find_child(doc, "FixedBet") or _find_desc(doc, "FixedBet")
                elif "DenomConfigSettings/" in spec.locator:
                    leaf = spec.locator.rsplit("/", 1)[-1]
                    denom = _find_desc(doc, "DenomConfigSettings")
                    el = _find_child(denom, leaf) if denom is not None else None
            if el is None:
                continue
            values.append(_extract_value(spec, el))
            themes_hit.append(path.parent.name)
        if not values:
            return False, None, "locator missing in all themes"
        # Return unique set summary for lists; for scalars return first + note if mixed.
        if spec.kind in ("int_list", "str_list", "token_map", "button_map"):
            return True, values[0], f"{len(themes_hit)} themes"
        unique = {str(v) for v in values}
        note = f"{len(themes_hit)} themes"
        if len(unique) > 1:
            note += f"; mixed={sorted(unique)[:5]}"
        return True, values[0], note

    path = _file_for_spec(goldclub, spec)
    if path is None:
        # For cs_pack_delivers=False, file may simply be absent on a CS leaf.
        return False, None, f"missing {spec.file_rel}"

    doc = _load_xml(path)
    if doc is None:
        return False, None, f"unreadable {spec.file_rel}"

    el = _find_by_locator(doc, spec.locator)
    if el is None and spec.kind == "button_map":
        el = doc  # whole Keyboard.xml
    if spec.id == "locale.jur_language_flags":
        from config_scanner.language_flags import probe_language_flags

        return probe_language_flags(doc)
    if el is None:
        return False, None, f"missing locator {spec.locator}"
    return True, _extract_value(spec, el), ""


def probe_setting(
    goldclub: Path,
    spec: SettingSpec,
    *,
    expected: Any = None,
    source_is_cs_leaf: bool = False,
) -> SettingReading:
    """Probe one setting; compare to *expected* when provided."""
    present, value, note = read_setting_value(goldclub, spec)
    if not present:
        if source_is_cs_leaf and not spec.cs_pack_delivers:
            return SettingReading(
                spec_id=spec.id,
                state=SettingState.NOT_SUPPLIED,
                value=None,
                present=False,
                note=note or "CS pack does not always deliver this file",
            )
        if expected is None:
            return SettingReading(
                spec_id=spec.id,
                state=SettingState.NOT_SUPPLIED,
                value=None,
                present=False,
                note=note or "absent (no expected)",
            )
        return SettingReading(
            spec_id=spec.id,
            state=SettingState.ABSENT,
            value=None,
            present=False,
            note=note,
        )

    if expected is None:
        return SettingReading(
            spec_id=spec.id,
            state=SettingState.NOT_SUPPLIED,
            value=value,
            present=True,
            note=note or "present (no expected)",
        )

    if _values_equal(spec.kind, value, expected):
        return SettingReading(
            spec_id=spec.id,
            state=SettingState.MATCH,
            value=value,
            present=True,
            note=note,
        )
    return SettingReading(
        spec_id=spec.id,
        state=SettingState.DIFFERS,
        value=value,
        present=True,
        note=note,
    )


def probe_tree(
    goldclub: Path,
    *,
    expected: dict[str, Any] | None = None,
    source_is_cs_leaf: bool = False,
    specs: tuple[SettingSpec, ...] | None = None,
) -> dict[str, SettingReading]:
    """Probe all (or given) specs; *expected* maps setting id → profile value."""
    exp = expected or {}
    out: dict[str, SettingReading] = {}
    for spec in specs or all_specs():
        out[spec.id] = probe_setting(
            goldclub,
            spec,
            expected=exp.get(spec.id),
            source_is_cs_leaf=source_is_cs_leaf,
        )
    return out


def format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = [f"{k}={v}" for k, v in sorted(value.items(), key=lambda x: str(x[0]))]
        return ", ".join(parts[:12]) + ("…" if len(parts) > 12 else "")
    if isinstance(value, list):
        return "[" + ", ".join(str(x) for x in value) + "]"
    return str(value)
