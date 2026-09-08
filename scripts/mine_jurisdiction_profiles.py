#!/usr/bin/env python3
"""Mine jurisdiction setting presets from CS packs (249 share + local staged).

Walks Country Selector trees, probes every install.json leaf against the
setting registry, merges the most common values per jurisdiction into
``config_scanner/assets/jurisdictions.json``, and writes a variance report.

Degrades gracefully when the share is unreachable (use ``--local-only``).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config_scanner.cs_catalog import discover_leaves, resolve_country_selector_tool  # noqa: E402
from config_scanner.embedded_updates import embedded_updates_root  # noqa: E402
from config_scanner.jurisdiction import (  # noqa: E402
    JurisdictionProfile,
    ensure_expected_locale_keys,
    load_jurisdictions,
    save_jurisdictions,
)
from config_scanner.setting_probe import probe_tree  # noqa: E402

SHARE_B2U = Path(r"//10.0.0.249/WinSystems_SLOT/_B2U")
SHARE_GS201 = Path(r"//10.0.0.249/WinSystems_SLOT/GameStar 2.0.1/Country Selectors")
SHARE_GS200 = Path(r"//10.0.0.249/WinSystems_SLOT/GameStar 2.0.0/Country Selectors")

ASSETS = _ROOT / "config_scanner" / "assets" / "jurisdictions.json"
REPORT_DEFAULT = _ROOT / "config_scanner" / "assets" / "jurisdiction_variance_report.json"


def _path_reachable(path: Path, timeout_s: float = 8.0) -> bool:
    """Best-effort reachability with a soft timeout (Windows UNC can hang)."""
    deadline = time.monotonic() + timeout_s
    try:
        # exists() on UNC can block; poll briefly via listing parent.
        parent = path if path.is_dir() else path.parent
        # Force a quick check — if it takes too long, caller should use local-only.
        while time.monotonic() < deadline:
            try:
                return parent.exists()
            except OSError:
                return False
        return False
    except OSError:
        return False


def _collect_tool_roots(*, local_only: bool, timeout_s: float) -> list[Path]:
    roots: list[Path] = []
    staged = embedded_updates_root() / "staged"
    if staged.is_dir():
        for child in sorted(staged.iterdir()):
            tool = child / "CountrySelectorTool"
            if (tool / "data").is_dir():
                roots.append(tool)
            elif (child / "data").is_dir():
                roots.append(child)

    if local_only:
        return roots

    for share in (SHARE_B2U, SHARE_GS201, SHARE_GS200):
        print(f"checking share {share} …")
        if not _path_reachable(share, timeout_s=timeout_s):
            print(f"  unreachable (timeout {timeout_s}s) — skip")
            continue
        try:
            if share == SHARE_B2U:
                for child in sorted(share.iterdir()):
                    name = child.name
                    if not name.upper().startswith("CS-GAMESTAR"):
                        continue
                    if child.is_dir():
                        roots.append(child)
            else:
                # Country Selectors/<Country>/*.b2u or unpacked folders
                for country_dir in sorted(share.iterdir()):
                    if not country_dir.is_dir():
                        continue
                    for child in sorted(country_dir.iterdir()):
                        if child.is_dir() and (
                            (child / "data").is_dir()
                            or (child / "CountrySelectorTool").is_dir()
                        ):
                            roots.append(child)
        except OSError as exc:
            print(f"  list failed: {exc}")
    return roots


def _jurisdiction_key(country: str, currency: str) -> str:
    c = (country or "unknown").strip()
    cur = (currency or "").strip().upper()
    base = c.replace("&", "and").replace(" ", "_")
    if cur:
        return f"{base}_{cur}".lower()
    return base.lower()


def _serialize(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _deserialize(text: str) -> Any:
    return json.loads(text)


def mine(*, local_only: bool = False, timeout_s: float = 8.0) -> dict[str, Any]:
    tools = _collect_tool_roots(local_only=local_only, timeout_s=timeout_s)
    print(f"tool roots: {len(tools)}")

    # jurisdiction_key -> setting_id -> Counter of serialized values
    value_counts: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    # setting_id -> set of serialized values across all leaves (variance)
    global_values: dict[str, set[str]] = defaultdict(set)
    leaf_meta: list[dict[str, Any]] = []
    jurisdiction_meta: dict[str, dict[str, Any]] = {}

    for tool_src in tools:
        try:
            tool = resolve_country_selector_tool(tool_src)
            leaves = discover_leaves(tool)
        except (OSError, FileNotFoundError, ValueError) as exc:
            print(f"  skip {tool_src}: {exc}")
            continue
        print(f"  {tool}: {len(leaves)} leaves")
        for leaf in leaves:
            readings = probe_tree(leaf.path, expected=None, source_is_cs_leaf=True)
            currency = ""
            rcur = readings.get("locale.currency_name")
            if rcur and rcur.present and rcur.value:
                currency = str(rcur.value)
            jkey = _jurisdiction_key(leaf.country, currency)
            meta = jurisdiction_meta.setdefault(
                jkey,
                {
                    "country": leaf.country,
                    "currency": currency,
                    "cultures": Counter(),
                    "markets": Counter(),
                    "languages": Counter(),
                    "denoms": Counter(),
                    "leaf_count": 0,
                },
            )
            meta["leaf_count"] += 1
            for sid, reading in readings.items():
                if not reading.present or reading.value is None:
                    continue
                ser = _serialize(reading.value)
                value_counts[jkey][sid][ser] += 1
                global_values[sid].add(ser)
                if sid == "locale.culture_name":
                    meta["cultures"][str(reading.value)] += 1
                elif sid == "locale.target_market":
                    meta["markets"][str(reading.value)] += 1
                elif sid == "locale.language":
                    meta["languages"][str(reading.value)] += 1
                elif sid == "denom.list" and isinstance(reading.value, list):
                    for d in reading.value:
                        meta["denoms"][str(d)] += 1
            leaf_meta.append(
                {
                    "jurisdiction": jkey,
                    "country": leaf.country,
                    "screens": leaf.screens,
                    "mode": leaf.mode,
                    "path": str(leaf.path),
                    "readme": leaf.readme,
                }
            )

    # Merge into JurisdictionProfile list (keep existing ids when possible)
    existing = {p.id: p for p in load_jurisdictions()}
    mined: list[JurisdictionProfile] = []
    for jkey, by_setting in sorted(value_counts.items()):
        meta = jurisdiction_meta[jkey]
        expected: dict[str, Any] = {}
        for sid, counter in by_setting.items():
            if not counter:
                continue
            most_common, _count = counter.most_common(1)[0]
            expected[sid] = _deserialize(most_common)

        culture = ""
        if meta["cultures"]:
            culture = meta["cultures"].most_common(1)[0][0]
        market = ""
        if meta["markets"]:
            market = meta["markets"].most_common(1)[0][0]
        language = ""
        if meta["languages"]:
            language = meta["languages"].most_common(1)[0][0]
        denoms = sorted(int(d) for d in meta["denoms"]) if meta["denoms"] else []

        # Prefer seeded profile id if country matches
        profile_id = jkey
        for eid, ep in existing.items():
            if ep.country.casefold().replace("&", "") in meta["country"].casefold().replace(
                "&", ""
            ) or meta["country"].casefold().replace("&", "") in ep.country.casefold().replace(
                "&", ""
            ):
                if (ep.currency or "").upper() == (meta["currency"] or "").upper() or not meta[
                    "currency"
                ]:
                    profile_id = eid
                    break

        prev = existing.get(profile_id)
        label = prev.label if prev else f"{meta['country']} ({meta['currency'] or '?'})"
        notes = (prev.notes + " | " if prev and prev.notes else "") + (
            f"Mined from {meta['leaf_count']} leaves."
        )
        # Prefer seeded correct locale over majority vote when seeded exists
        # (Trinidad packs vote PuertoRico incorrectly).
        currency = meta["currency"] or (prev.currency if prev else "")
        if prev and prev.currency:
            currency = prev.currency
            for key in (
                "locale.currency_name",
                "locale.hw_currency_name",
                "locale.culture_name",
                "locale.language",
                "locale.target_market",
            ):
                if key in prev.expected:
                    expected[key] = prev.expected[key]
            culture = prev.culture or culture
            language = prev.language or language
            market = prev.target_market or market

        prof = JurisdictionProfile(
            id=profile_id,
            label=label,
            country=meta["country"] or (prev.country if prev else ""),
            currency=currency,
            culture=culture,
            language=language,
            target_market=market,
            allowed_denoms=denoms or (prev.allowed_denoms if prev else []),
            allowed_bet_multipliers=(
                prev.allowed_bet_multipliers if prev else [1, 2, 3, 4, 5, 8, 10, 12, 15]
            ),
            expected=expected,
            notes=notes.strip(" |"),
        )
        mined.append(ensure_expected_locale_keys(prof))

    # Keep seeded profiles that had no mined leaves
    mined_ids = {p.id for p in mined}
    for eid, ep in existing.items():
        if eid not in mined_ids:
            mined.append(ep)

    variance_readable: dict[str, list[Any]] = {}
    for sid, vals in global_values.items():
        if len(vals) <= 1:
            continue
        variance_readable[sid] = [_deserialize(v) for v in sorted(vals)]

    report = {
        "leaf_count": len(leaf_meta),
        "jurisdiction_count": len(mined),
        "varying_settings": variance_readable,
        "leaves": leaf_meta,
    }
    return {"profiles": mined, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Only scan config_scanner/assets/embedded_updates/staged",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Seconds to wait for each share path (default 8)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_DEFAULT,
        help="Variance report JSON path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write jurisdictions.json",
    )
    args = parser.parse_args()
    result = mine(local_only=args.local_only, timeout_s=args.timeout)
    profiles: list[JurisdictionProfile] = result["profiles"]
    report = result["report"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"variance report: {args.report} ({len(report.get('varying_settings') or {})} varying settings)")
    if args.dry_run:
        print(f"dry-run: would write {len(profiles)} jurisdictions")
        return 0
    path = save_jurisdictions(profiles, ASSETS)
    print(f"wrote {len(profiles)} jurisdictions -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
