"""Denomination change rules for Live Push / slot setup.

Official GameStar country packs change mgconfig denoms together with Link2Win
JSON and magic-wheel bet scaling. Live Push must not commit a denom migration
that would leave those companion files inconsistent.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config_scanner.cs_catalog import CountryLeaf, discover_leaves
from config_scanner.embedded_updates import load_catalog
from config_scanner.jurisdiction import (
    JurisdictionProfile,
    _norm_market,
    leaf_matches_profile_country,
    load_jurisdictions,
)
from config_scanner.slot_setup import (
    PlayLimitsSettings,
    SlotSetupRecipe,
    _MAGICWHEEL_REL,
    cabinet_has_magic_wheel_gamepack,
    goldclub_root_from_target,
    read_mgconfig_denoms,
    read_play_limits,
    validate_language_installed,
    validate_onehand_target_market,
)

_LINK2WIN_REL = "slot/themes/Link2WinFeature/Link2WinBonusMath.json"
_LINK2WIN_CONFIG2_REL = "slot/themes/Link2WinFeature/Link2WinBonusMath_Config2.json"

DENOM_COMPANION_RELS: tuple[str, ...] = (
    _LINK2WIN_REL,
    _LINK2WIN_CONFIG2_REL,
    _MAGICWHEEL_REL,
)

# Live Push configures default/base images, not only shipped CS leaves.
# Country Selector packs seed market-specific denoms; operators still need common
# GameStar singles (incl. 100c for Jamaica and high singles up to 5000c for
# COP / PEN / similar markets).
STANDARD_CONFIG_DENOMS: frozenset[int] = frozenset(
    {1, 2, 5, 10, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000}
)

_DENOM_IN_MODE = re.compile(r"(\d+)\s*c\b", re.I)
_SCREENS_IN_LEAF = re.compile(r"(\d+)\s*Screens?", re.I)


def expected_magic_wheel_for_denom(denom_cents: int) -> tuple[int, int]:
    """CS pack scaling: wheel bet = min denom, average = 5 x bet."""
    denom = int(denom_cents)
    return denom, denom * 5


def denom_from_leaf_mode(mode: str) -> int | None:
    match = _DENOM_IN_MODE.search(mode or "")
    return int(match.group(1)) if match else None


def screens_from_leaf_screens(screens: str) -> str | None:
    match = _SCREENS_IN_LEAF.search(screens or "")
    return match.group(1) if match else None


def matching_profiles(currency: str = "", market: str = "") -> list[JurisdictionProfile]:
    cur = (currency or "").strip().upper()
    mkt = _norm_market(market)
    out: list[JurisdictionProfile] = []
    for prof in load_jurisdictions():
        if cur and (prof.currency or "").strip().upper() != cur:
            continue
        out.append(prof)
    if not out or not mkt:
        return out
    narrowed: list[JurisdictionProfile] = []
    for prof in out:
        candidates = {
            _norm_market(prof.target_market),
            _norm_market(prof.country),
            _norm_market(prof.id),
        }
        candidates.discard("")
        if mkt in candidates or any(mkt in c or c in mkt for c in candidates):
            narrowed.append(prof)
    # Cabinets often ship with a stale TargetMarket (e.g. TTD + PuertoRico).
    return narrowed if narrowed else out


def allowed_denoms_for(currency: str = "", market: str = "") -> frozenset[int]:
    """Denoms Live Push may select for a market (CS seeds + standard config set)."""
    denoms: set[int] = set(STANDARD_CONFIG_DENOMS)
    for prof in matching_profiles(currency, market):
        denoms.update(int(x) for x in (prof.allowed_denoms or []))
    return frozenset(denoms)


def allowed_bet_profiles_for(currency: str = "", market: str = "") -> list[tuple[int, ...]]:
    seen: set[tuple[int, ...]] = set()
    out: list[tuple[int, ...]] = []
    for prof in matching_profiles(currency, market):
        mults = tuple(int(x) for x in (prof.allowed_bet_multipliers or []))
        if mults and mults not in seen:
            seen.add(mults)
            out.append(mults)
    return out


def bet_multiplier_preset_labels(currency: str = "", market: str = "") -> tuple[str, ...]:
    """Live Push dropdown labels that Apply will accept for this market.

    These are jurisdiction ``allowed_bet_multipliers`` lists, not per-title
    game-pack rows. Link2Win JSON ``Bet`` values are denom coverage only.
    """
    profiles = allowed_bet_profiles_for(currency, market) or allowed_bet_profiles_for()
    labels = tuple(", ".join(str(x) for x in prof) for prof in profiles)
    return labels or ("1, 2, 3, 4, 5, 8, 10, 12, 15",)


def cabinet_has_link2win(goldclub: Path) -> bool:
    root = goldclub_root_from_target(goldclub)
    return (root / _LINK2WIN_REL).is_file()


_BET_KEYS = frozenset({"bet", "betvalue", "betmultiplier"})
_DENOM_KEYS = frozenset({"denom", "denomination", "denomvalue"})


def _coerce_link2win_denom(value: object) -> int | None:
    """Normalize a Link2Win denom field to cents.

    Live GameStar files store currency units (``0.01`` = 1c, ``1.0`` = 100c).
    Plain test fixtures store integer cents (``5``, ``10``). ``int(0.01)`` is
    ``0``, which is why 1c cabinets were falsely marked red.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, float):
            return int(round(value * 100))
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if "." in text:
                return int(round(float(text) * 100))
            return int(text)
        if isinstance(value, int):
            return int(value)
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_link2win_bet(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _walk_link2win_pairs(obj: object, out: set[tuple[int, int]]) -> None:
    if isinstance(obj, dict):
        bet: int | None = None
        denom: int | None = None
        for key, value in obj.items():
            low = str(key).casefold()
            if low in _BET_KEYS:
                bet = _coerce_link2win_bet(value)
            elif low in _DENOM_KEYS:
                denom = _coerce_link2win_denom(value)
        if bet is not None and denom is not None and denom > 0:
            out.add((bet, denom))
        for value in obj.values():
            _walk_link2win_pairs(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_link2win_pairs(item, out)


def parse_link2win_bytes(raw: bytes) -> frozenset[tuple[int, int]] | None:
    """Parse Bet/Denom rows from plaintext JSON bytes."""
    if not raw or raw.lstrip()[:1] not in (b"{", b"["):
        return None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    pairs: set[tuple[int, int]] = set()
    _walk_link2win_pairs(data, pairs)
    return frozenset(pairs) if pairs else None


def parse_link2win_pairs(path: Path) -> frozenset[tuple[int, int]] | None:
    """Read Bet/Denom rows from a plaintext Link2Win JSON. Encrypted files return None."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return parse_link2win_bytes(raw)


@functools.lru_cache(maxsize=1)
def _link2win_hash_manifest() -> dict[str, int]:
    """SHA-256 -> denom from bundled manifest (works in frozen exe without staged/)."""
    from config_scanner.paths import bundled_assets_root

    path = bundled_assets_root() / "link2win_hashes.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    out: dict[str, int] = {}
    for item in data.get("entries") or []:
        if not isinstance(item, dict):
            continue
        digest = str(item.get("sha256") or "").strip().casefold()
        denom = item.get("denom_cents")
        if not digest or denom is None:
            continue
        try:
            out[digest] = int(denom)
        except (TypeError, ValueError):
            continue
    return out


@functools.lru_cache(maxsize=1)
def _link2win_hash_to_denom() -> dict[str, int]:
    """Map embedded CS Link2Win file hashes to the leaf denom (2c / 5c / 10c)."""
    mapping: dict[str, int] = dict(_link2win_hash_manifest())
    for entry in load_catalog():
        tool = entry.staged_tool_path
        if tool is None:
            continue
        for leaf in discover_leaves(tool):
            denom = denom_from_leaf(leaf)
            if denom is None:
                continue
            for rel in (_LINK2WIN_REL, _LINK2WIN_CONFIG2_REL):
                src = leaf.path / rel
                if not src.is_file():
                    continue
                try:
                    mapping.setdefault(_file_sha256(src), int(denom))
                except OSError:
                    continue
    return mapping


@dataclass(frozen=True)
class Link2WinMathSupport:
    """What one Link2Win JSON is known to allow."""

    path: Path
    denoms: frozenset[int]
    pairs: frozenset[tuple[int, int]] | None

    @property
    def label(self) -> str:
        return path_label(self.path)


def path_label(path: Path) -> str:
    name = path.name
    if not name:
        return "Link2WinBonusMath.json"
    return name


def inspect_link2win_math(
    path: Path,
    *,
    allow_decrypt: bool = True,
) -> Link2WinMathSupport | None:
    """Identify supported denoms (and Bet/Denom pairs when the file is plaintext).

    Hash catalog and filename run before Encryptor. GUI hover must pass
    ``allow_decrypt=False`` so GameStar File Encryptor is not started on
    the interactive desktop.
    """
    if not path.is_file():
        return None
    pairs = parse_link2win_pairs(path)
    if pairs is not None:
        return Link2WinMathSupport(
            path=path,
            denoms=frozenset(denom for _bet, denom in pairs),
            pairs=pairs,
        )
    try:
        digest = _file_sha256(path)
    except OSError:
        return None
    hashed = _link2win_hash_to_denom().get(digest)
    if hashed is not None:
        return Link2WinMathSupport(path=path, denoms=frozenset({hashed}), pairs=None)
    from_name = denom_from_leaf_mode(str(path))
    if from_name is not None:
        return Link2WinMathSupport(path=path, denoms=frozenset({from_name}), pairs=None)
    from config_scanner.math_decrypt import decrypt_math_file

    plain = decrypt_math_file(path, spawn=allow_decrypt)
    if not plain:
        return None
    pairs = parse_link2win_bytes(plain)
    if pairs is None:
        return None
    return Link2WinMathSupport(
        path=path,
        denoms=frozenset(denom for _bet, denom in pairs),
        pairs=pairs,
    )


def _link2win_files_in(root: Path) -> list[Path]:
    out: list[Path] = []
    for rel in (_LINK2WIN_REL, _LINK2WIN_CONFIG2_REL):
        path = root / rel
        if path.is_file():
            out.append(path)
    return out


def playable_denoms_from_recipe(
    recipe: SlotSetupRecipe,
    listed: list[int] | None = None,
) -> list[int]:
    """Denoms OneHand actually looks up in Link2Win.

    ``ShowDenominationSelector=false`` leaves the CS catalog in mgconfig
    (1c through 5000c on lab .76) but the game only uses the first entry.
    Scoring every catalog value against math/allowed-sets paints a working
    1c cabinet red.
    """
    denoms = [
        int(x)
        for x in (listed if listed is not None else recipe.denomination_list or [])
        if int(x) > 0
    ]
    if not denoms:
        return []
    if recipe.play_limits.show_denom_selector is True:
        return denoms
    return [denoms[0]]


def _math_covered_denoms(
    files: list[Path],
    *,
    allow_decrypt: bool = True,
) -> frozenset[int]:
    covered: set[int] = set()
    for path in files:
        support = inspect_link2win_math(path, allow_decrypt=allow_decrypt)
        if support is not None:
            covered.update(support.denoms)
    return frozenset(covered)


def _math_support_errors(
    files: list[Path],
    *,
    denoms: list[int],
    bets: list[int],
    allow_decrypt: bool = True,
) -> list[str]:
    """Proven missing playable denoms. Unidentified encrypted files are not errors.

    mgconfig bet multipliers are not Link2Win JSON ``Bet`` totals, so they are
    not cartesian-checked. Coverage is the union across math files — Config2
    does not have to repeat every row in Link2WinBonusMath.json.
    """
    _ = bets
    target = [int(d) for d in denoms if int(d) > 0]
    if not target:
        return []
    identified = False
    covered: set[int] = set()
    labels: list[str] = []
    for path in files:
        support = inspect_link2win_math(path, allow_decrypt=allow_decrypt)
        if support is None:
            continue
        identified = True
        covered.update(support.denoms)
        labels.append(path_label(path))
    if not identified:
        return []
    missing = [d for d in target if d not in covered]
    if not missing:
        return []
    have = ", ".join(f"{d}c" for d in sorted(covered)) or "none"
    need = ", ".join(f"{d}c" for d in missing)
    shown = " / ".join(labels) if labels else "Link2WinBonusMath.json"
    return [
        f"{shown} do not include denom {need} "
        f"(math files support {have})."
    ]


def _link2win_unidentified(
    files: list[Path],
    *,
    allow_decrypt: bool = True,
) -> bool:
    """True when a Link2Win file exists but cannot be fingerprinted or parsed."""
    return any(
        inspect_link2win_math(path, allow_decrypt=allow_decrypt) is None
        for path in files
    )


def prefetch_link2win_math(goldclub: Path | str) -> None:
    """Decrypt live Link2Win files once on a worker thread (hidden Encryptor)."""
    try:
        root = goldclub_root_from_target(Path(goldclub))
    except (OSError, ValueError):
        return
    for path in _link2win_files_in(root):
        inspect_link2win_math(path, allow_decrypt=True)


def link2win_restage_change_line(
    live: SlotSetupRecipe,
    proposed: SlotSetupRecipe,
    goldclub: Path,
) -> str | None:
    """Human line when Apply must replace live Link2Win math from a country pack."""
    root = goldclub_root_from_target(goldclub)
    if not cabinet_has_link2win(root):
        return None
    listed = [int(x) for x in (proposed.denomination_list or live.denomination_list or [])]
    target = playable_denoms_from_recipe(proposed, listed=listed)
    if not target:
        return None
    if not live_link2win_math_mismatches(root, target):
        return None
    screens = proposed.display_mode or live.display_mode or detect_live_display_mode(root)
    leaf = find_staged_leaf_for_denom(
        min(target),
        currency=(
            proposed.jurisdiction.currency_name
            or proposed.hardware_currency_name
            or live.jurisdiction.currency_name
            or live.hardware_currency_name
            or ""
        ),
        market=proposed.jurisdiction.tag or live.jurisdiction.tag or "",
        screens=screens,
    )
    if leaf is None:
        return None
    return (
        "Link2Win math: live file is missing the selected denom; "
        "country-pack math will be copied"
    )


def live_link2win_math_mismatches(
    goldclub: Path,
    denoms: list[int],
    bets: list[int] | None = None,
    *,
    allow_decrypt: bool = True,
) -> list[str]:
    """Errors if the cabinet's current Link2Win JSON does not cover denoms/bets."""
    root = goldclub_root_from_target(goldclub)
    if not cabinet_has_link2win(root):
        return []
    return _math_support_errors(
        _link2win_files_in(root),
        denoms=[int(x) for x in denoms],
        bets=[int(x) for x in (bets or []) if int(x) > 0],
        allow_decrypt=allow_decrypt,
    )


@dataclass(frozen=True)
class MathReplaceTarget:
    """One live Link2Win math file that must be replaced before Apply."""

    relative_path: str
    dest_path: Path
    label: str
    denoms: tuple[int, ...]
    bets: tuple[int, ...]


def list_link2win_math_replace_targets(
    live: SlotSetupRecipe,
    proposed: SlotSetupRecipe,
    goldclub: Path,
) -> tuple[MathReplaceTarget, ...]:
    """Link2Win files on the cabinet that do not cover the proposed denom/bets."""
    from config_scanner.write_scope import normalize_rel_path

    root = goldclub_root_from_target(goldclub)
    if not cabinet_has_link2win(root):
        return ()
    listed = [
        int(x)
        for x in (proposed.denomination_list or live.denomination_list or [])
        if int(x) > 0
    ]
    target_denoms = playable_denoms_from_recipe(proposed, listed=listed)
    if not target_denoms:
        return ()
    files = _link2win_files_in(root)
    if not _math_support_errors(
        files, denoms=target_denoms, bets=[], allow_decrypt=False
    ):
        return ()
    bets = tuple(_recipe_bets(live, proposed))
    out: list[MathReplaceTarget] = []
    for path in files:
        support = inspect_link2win_math(path, allow_decrypt=False)
        file_errors = _math_support_errors(
            [path],
            denoms=target_denoms,
            bets=[],
            allow_decrypt=False,
        )
        if not file_errors and support is not None:
            continue
        try:
            rel = normalize_rel_path(path.relative_to(root).as_posix())
        except ValueError:
            rel = path.name
        out.append(
            MathReplaceTarget(
                relative_path=rel,
                dest_path=path,
                label=path_label(path),
                denoms=tuple(target_denoms),
                bets=bets,
            )
        )
    return tuple(out)


def resolve_math_replacement_source(source: Path, target: MathReplaceTarget) -> Path | None:
    """Map a user-picked file or folder to the math file for *target*."""
    picked = Path(source)
    if picked.is_dir():
        for candidate in (
            picked / target.label,
            picked / "Link2WinFeature" / target.label,
            picked / "slot/themes/Link2WinFeature" / target.label,
            picked / "themes/Link2WinFeature" / target.label,
        ):
            if candidate.is_file():
                return candidate
        return None
    if picked.is_file():
        if picked.name.casefold() == target.label.casefold():
            return picked
        if picked.suffix.casefold() == ".json":
            return picked
    return None


def validate_math_replacement_source(
    source: Path,
    target: MathReplaceTarget,
) -> str | None:
    """Return an error string when *source* cannot replace *target*, else None."""
    resolved = resolve_math_replacement_source(source, target)
    if resolved is None:
        return (
            f"Could not find {target.label} in the selected path. "
            "Pick the file directly or a folder containing Link2WinFeature\\."
        )
    support = inspect_link2win_math(resolved, allow_decrypt=True)
    if support is None:
        need = ", ".join(f"{d}c" for d in target.denoms)
        return (
            f"{resolved.name} is not recognized as Link2Win math for {need}."
        )
    errors = _math_support_errors(
        [resolved],
        denoms=list(target.denoms),
        bets=list(target.bets),
        allow_decrypt=True,
    )
    if errors:
        return errors[0]
    return None


def replace_cabinet_math_file(
    goldclub: Path,
    target: MathReplaceTarget,
    source: Path,
    *,
    backup_dir: Path | None = None,
) -> Path:
    """Copy validated *source* onto the live cabinet path for *target*."""
    resolved = resolve_math_replacement_source(source, target)
    if resolved is None:
        raise ValueError(
            validate_math_replacement_source(source, target) or "Invalid source"
        )
    err = validate_math_replacement_source(resolved, target)
    if err:
        raise ValueError(err)
    dest = target.dest_path
    if backup_dir is not None and dest.is_file():
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(dest, backup_dir / f"{dest.name}.{stamp}.bak")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resolved, dest)
    return dest


def live_link2win_math_unknown(
    goldclub: Path,
    *,
    allow_decrypt: bool = True,
) -> bool:
    """True when live Link2Win files exist but cannot be identified."""
    root = goldclub_root_from_target(goldclub)
    if not cabinet_has_link2win(root):
        return False
    return _link2win_unidentified(
        _link2win_files_in(root), allow_decrypt=allow_decrypt
    )


def live_cabinet_math_gap(
    goldclub: Path,
    denoms: list[int],
    bets: list[int] | None = None,
    *,
    allow_decrypt: bool = True,
) -> str:
    """Why the live cabinet Link2Win file does not cover the selected denoms.

    Empty when the live file includes those denoms. Country-pack copies are
    ignored — this is only what is on the cabinet now.
    """
    root = goldclub_root_from_target(goldclub)
    if not cabinet_has_link2win(root):
        return ""
    target = [int(x) for x in denoms if int(x) > 0]
    if not target:
        return ""
    mismatches = live_link2win_math_mismatches(
        root, target, bets, allow_decrypt=allow_decrypt
    )
    if mismatches:
        return mismatches[0]
    if live_link2win_math_unknown(root, allow_decrypt=allow_decrypt):
        need = ", ".join(f"{d}c" for d in target)
        return (
            f"Live Link2WinBonusMath.json on the cabinet cannot be verified for {need}."
        )
    return ""


def _recipe_bets(live: SlotSetupRecipe, proposed: SlotSetupRecipe) -> list[int]:
    bets = [int(x) for x in (proposed.play_limits.bet_multipliers or []) if int(x) > 0]
    if bets:
        return bets
    if proposed.math:
        bets = [int(x) for x in (proposed.math[0].bet_multipliers or []) if int(x) > 0]
        if bets:
            return bets
    bets = [int(x) for x in (live.play_limits.bet_multipliers or []) if int(x) > 0]
    if bets:
        return bets
    if live.math:
        return [int(x) for x in (live.math[0].bet_multipliers or []) if int(x) > 0]
    return []


def detect_live_display_mode(goldclub: Path) -> str | None:
    from config_scanner.slot_setup import _MGCONFIG_REL, _elem_text, _parse_xml

    root = goldclub_root_from_target(goldclub)
    mg = root / _MGCONFIG_REL
    if not mg.is_file():
        return None
    doc = _parse_xml(mg).getroot()
    wheel = (_elem_text(doc, "MagicWheelPath") or "").replace("\\", "/").casefold()
    if "3screens" in wheel:
        return "3"
    splash = (_elem_text(doc, "SplashPicture") or "").casefold()
    if "splash3" in splash:
        return "3"
    if "splash2" in splash:
        return "2"
    if wheel.endswith("magicwheel.xml"):
        return "2"
    return None


def _leaf_matches_market(leaf: CountryLeaf, profiles: list[JurisdictionProfile]) -> bool:
    if not profiles:
        return True
    return any(leaf_matches_profile_country(leaf.country, prof) for prof in profiles)


def denom_from_leaf(leaf: CountryLeaf) -> int | None:
    for part in leaf.rel_parts:
        found = denom_from_leaf_mode(part)
        if found is not None:
            return found
    return None


def screens_from_leaf(leaf: CountryLeaf) -> str | None:
    for part in leaf.rel_parts:
        found = screens_from_leaf_screens(part)
        if found is not None:
            return found
    return None


def _normalize_leaf_screens(screens: str | None) -> str | None:
    from config_scanner.slot_setup import _normalize_display_mode

    want = _normalize_display_mode(screens)
    if want:
        return want
    text = str(screens or "").strip()
    return text or None


def _collect_denom_leaves(
    denom: int,
    *,
    screens: str | None = None,
    profiles: list[JurisdictionProfile] | None = None,
) -> list[CountryLeaf]:
    candidates: list[CountryLeaf] = []
    for entry in load_catalog():
        tool = entry.staged_tool_path
        if tool is None:
            continue
        for leaf in discover_leaves(tool):
            if denom_from_leaf(leaf) != int(denom):
                continue
            if screens:
                leaf_screens = screens_from_leaf(leaf)
                if leaf_screens and leaf_screens != str(screens):
                    continue
            if profiles is not None and not _leaf_matches_market(leaf, profiles):
                continue
            candidates.append(leaf)
    return candidates


def find_staged_leaf_for_denom(
    denom: int,
    *,
    currency: str = "",
    market: str = "",
    screens: str | None = None,
) -> Path | None:
    """Best embedded CS leaf for a target single-denom overlay.

    Market/currency is a preference only. Link2Win math is keyed by denom
    (2c / 5c / 10c), so a PuertoRico-tagged cabinet can still use the TRI/TT
    5c pack that is already on the disk.
    """
    screens = _normalize_leaf_screens(screens)
    profiles = matching_profiles(currency, market)
    candidates = _collect_denom_leaves(denom, screens=screens, profiles=profiles)
    if not candidates:
        candidates = _collect_denom_leaves(denom, screens=screens, profiles=None)
    if not candidates and screens:
        candidates = _collect_denom_leaves(denom, screens=None, profiles=None)
    if not candidates:
        return None

    def _rank(leaf: CountryLeaf) -> tuple[int, int, str]:
        mode = " ".join(leaf.rel_parts).casefold()
        ol_rank = 0 if "ol" in mode else 1
        screen_rank = 0
        if screens:
            leaf_screens = screens_from_leaf(leaf)
            screen_rank = 0 if leaf_screens == str(screens) else 1
        return (ol_rank, screen_rank, mode)

    candidates.sort(key=_rank)
    return candidates[0].path


def denomination_lists_equal(a: list[int], b: list[int]) -> bool:
    return [int(x) for x in a] == [int(x) for x in b]


def effective_play_limits(
    live: SlotSetupRecipe, proposed: SlotSetupRecipe, goldclub: Path
) -> PlayLimitsSettings:
    """Merge recipe play limits with live cabinet values for unset fields."""
    live_pl = read_play_limits(goldclub_root_from_target(goldclub))
    merged = PlayLimitsSettings()
    for field_name in (
        "magic_wheel_enabled",
        "magic_wheel_bet",
        "magic_wheel_max_spins",
        "magic_wheel_average",
        "bet_multipliers",
    ):
        prop_val = getattr(proposed.play_limits, field_name)
        live_val = getattr(live_pl, field_name)
        recipe_val = getattr(live.play_limits, field_name)
        if field_name == "bet_multipliers":
            if prop_val:
                setattr(merged, field_name, list(prop_val))
            elif live_val:
                setattr(merged, field_name, list(live_val))
            elif recipe_val:
                setattr(merged, field_name, list(recipe_val))
            continue
        if prop_val is not None:
            setattr(merged, field_name, prop_val)
        elif live_val is not None:
            setattr(merged, field_name, live_val)
        elif recipe_val is not None:
            setattr(merged, field_name, recipe_val)
    return merged


@dataclass(frozen=True)
class DenomValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    leaf_dir: Path | None
    target_denoms: tuple[int, ...]
    denom_changed: bool

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_denom_configuration(
    live: SlotSetupRecipe,
    proposed: SlotSetupRecipe,
    goldclub: Path,
) -> DenomValidation:
    """Return blocking errors when a proposed recipe is not a valid denom setup."""
    root = goldclub_root_from_target(goldclub)
    currency = (
        proposed.jurisdiction.currency_name
        or proposed.hardware_currency_name
        or live.jurisdiction.currency_name
        or live.hardware_currency_name
        or ""
    )
    market = proposed.jurisdiction.tag or live.jurisdiction.tag or ""
    listed = [int(x) for x in (proposed.denomination_list or [])]
    if not listed:
        live_listed, _ = read_mgconfig_denoms(root)
        listed = list(live_listed)
    playable = playable_denoms_from_recipe(proposed, listed=listed)
    errors: list[str] = []
    warnings: list[str] = []
    allowed = allowed_denoms_for(currency, market)
    if allowed:
        for denom in playable:
            if denom not in allowed:
                allowed_text = ", ".join(f"{d}c" for d in sorted(allowed))
                errors.append(
                    f"Denom {denom}c is not allowed for {currency or market or 'this market'} "
                    f"(allowed: {allowed_text})."
                )
    if len(playable) > 1:
        warnings.append(
            "Multi-denom list: Live Push will write mgconfig denoms as listed. "
            "Link2Win/math companions may still need a Country Pack if the game rejects the set."
        )
    if not listed:
        return DenomValidation(tuple(errors), tuple(warnings), None, tuple(), False)

    live_denoms = list(live.denomination_list or [])
    if not live_denoms:
        live_denoms, _ = read_mgconfig_denoms(root)
    # A change is what the game *plays*, not the catalog text: selector-off
    # cabinets play only the first entry, so ``1`` vs ``1, 2, 5, ...`` is no change.
    live_playable = playable_denoms_from_recipe(live, listed=list(live_denoms))
    denom_changed = not denomination_lists_equal(playable, live_playable)
    leaf_dir: Path | None = None
    min_denom = min(playable) if playable else min(listed)

    if cabinet_has_link2win(root):
        live_files = _link2win_files_in(root)
        live_math_errors = _math_support_errors(
            live_files,
            denoms=playable,
            bets=[],
            allow_decrypt=False,
        )
        live_unknown = _link2win_unidentified(live_files, allow_decrypt=False)
        live_gap = live_cabinet_math_gap(root, playable, allow_decrypt=False)
        live_ok = not live_gap and not live_math_errors
        if live_gap:
            errors.append(live_gap)
        elif live_math_errors:
            errors.extend(live_math_errors)
        if not live_ok:
            screens = proposed.display_mode or detect_live_display_mode(root)
            leaf_dir = find_staged_leaf_for_denom(
                min_denom,
                currency=currency,
                market=market,
                screens=screens,
            )
            if leaf_dir is not None:
                leaf_files = _link2win_files_in(leaf_dir)
                leaf_errors = _math_support_errors(
                    leaf_files or live_files,
                    denoms=playable,
                    bets=[],
                )
                errors.extend(leaf_errors)
            elif denom_changed and (live_math_errors or live_unknown or live_gap):
                errors.append(
                    f"No embedded country pack math for {min_denom}c. "
                    "Live Push will not change denom until Link2WinBonusMath.json "
                    "includes that denom."
                )

    if denom_changed and cabinet_has_magic_wheel_gamepack(root):
        expected_bet, expected_avg = expected_magic_wheel_for_denom(min_denom)
        pl = effective_play_limits(live, proposed, root)
        wheel_bet = (
            proposed.play_limits.magic_wheel_bet
            if proposed.play_limits.magic_wheel_bet is not None
            else pl.magic_wheel_bet
        )
        wheel_avg = (
            proposed.play_limits.magic_wheel_average
            if proposed.play_limits.magic_wheel_average is not None
            else pl.magic_wheel_average
        )
        wheel_active = pl.magic_wheel_enabled is not False
        if wheel_active and wheel_bet is not None:
            if wheel_bet != expected_bet or (
                wheel_avg is not None and wheel_avg != expected_avg
            ):
                errors.append(
                    f"Magic wheel must match the new denom ({expected_bet}c bet, "
                    f"{expected_avg}c average). Adjust Magic wheel or pick a valid denom."
                )

    from config_scanner.game_math import theme_bet_step_errors

    # Live Push writes per-theme recipe.math. play_limits.bet_multipliers is
    # leftover from market presets and must not veto a title's own ladder.
    errors.extend(theme_bet_step_errors(live.math, proposed.math))

    return DenomValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        leaf_dir=leaf_dir,
        target_denoms=tuple(playable),
        denom_changed=denom_changed,
    )


def validate_live_push_recipe(
    live: SlotSetupRecipe,
    proposed: SlotSetupRecipe,
    goldclub: Path,
) -> list[str]:
    errors = list(validate_denom_configuration(live, proposed, goldclub).errors)
    errors.extend(
        validate_onehand_target_market(proposed.jurisdiction.tag, goldclub)
    )
    errors.extend(
        validate_language_installed(proposed.mg_identity.language, goldclub)
    )
    return errors


def validate_live_push_warnings(
    live: SlotSetupRecipe,
    proposed: SlotSetupRecipe,
    goldclub: Path,
) -> list[str]:
    return list(validate_denom_configuration(live, proposed, goldclub).warnings)


def apply_magic_wheel_for_denom(recipe: SlotSetupRecipe, denom_cents: int) -> None:
    bet, average = expected_magic_wheel_for_denom(denom_cents)
    recipe.play_limits.magic_wheel_bet = bet
    recipe.play_limits.magic_wheel_average = average


def denom_combo_choices(
    currency: str = "",
    market: str = "",
    *,
    live_denoms: tuple[int, ...] = (),
) -> tuple[str, ...]:
    allowed = allowed_denoms_for(currency, market)
    merged = sorted(
        {int(d) for d in allowed}
        | {int(d) for d in live_denoms}
        | set(STANDARD_CONFIG_DENOMS)
    )
    return tuple(str(d) for d in merged)


@dataclass(frozen=True)
class MathPreflightReport:
    """Startup / Live Push check of live denoms vs Link2Win math."""

    reachable: bool
    ok: bool
    decryptor: str
    messages: tuple[str, ...]
    cabinet_denoms: tuple[int, ...]
    math_denoms: tuple[int, ...]


def cabinet_link2win_preflight(goldclub: Path | str) -> MathPreflightReport:
    """Read-only check: do live mgconfig denoms exist in Link2Win math?"""
    from config_scanner.math_decrypt import find_math_decryptor
    from config_scanner.slot_setup import load_recipe_from_goldclub, read_mgconfig_denoms

    decryptor = find_math_decryptor()
    decryptor_label = str(decryptor) if decryptor is not None else ""
    try:
        root = goldclub_root_from_target(Path(goldclub))
    except (OSError, ValueError) as exc:
        return MathPreflightReport(
            False, True, decryptor_label, (f"Cabinet path not ready: {exc}",), (), ()
        )
    if not cabinet_has_link2win(root):
        return MathPreflightReport(
            True, True, decryptor_label, (), (), ()
        )
    try:
        denoms, _credit = read_mgconfig_denoms(root)
    except (OSError, ValueError) as exc:
        return MathPreflightReport(
            False, True, decryptor_label, (f"Could not read mgconfig: {exc}",), (), ()
        )
    listed = [int(x) for x in denoms]
    if not listed:
        return MathPreflightReport(True, True, decryptor_label, (), (), ())
    recipe = SlotSetupRecipe(denomination_list=list(listed))
    try:
        live = load_recipe_from_goldclub(root, label="preflight")
        recipe.play_limits.show_denom_selector = live.play_limits.show_denom_selector
        recipe.play_limits.bet_multipliers = list(
            live.play_limits.bet_multipliers or []
        )
        if not recipe.play_limits.bet_multipliers and live.math:
            recipe.play_limits.bet_multipliers = list(
                live.math[0].bet_multipliers or []
            )
    except (OSError, ValueError):
        live = recipe
    playable = playable_denoms_from_recipe(live, listed=listed)
    errors = live_link2win_math_mismatches(root, playable)
    math_denoms: set[int] = set()
    for path in _link2win_files_in(root):
        support = inspect_link2win_math(path)
        if support is not None:
            math_denoms.update(support.denoms)
    if not errors:
        return MathPreflightReport(
            True, True, decryptor_label, (), tuple(playable), tuple(sorted(math_denoms))
        )
    return MathPreflightReport(
        True,
        False,
        decryptor_label,
        tuple(errors),
        tuple(playable),
        tuple(sorted(math_denoms)),
    )


def stage_denom_companion_files(leaf_dir: Path, pack_dir: Path) -> list[str]:
    """Copy Link + magic-wheel files from a CS leaf into a config pack."""
    written: list[str] = []
    for rel in DENOM_COMPANION_RELS:
        src = leaf_dir / rel
        if not src.is_file():
            continue
        dest = pack_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(rel.replace("\\", "/"))
    return written
