"""Jurisdiction preset library for GameStar country-selector profiling."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config_scanner.paths import bundled_assets_root
from config_scanner.setting_probe import SettingReading, SettingState, probe_tree
from config_scanner.setting_spec import all_specs, specs_by_id

# currency ISO / short name → expected culture regions / markets
_CURRENCY_HINTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "TTD": (frozenset({"en-TT", "en-tt"}), frozenset({"trinidad", "trinidadtobago", "trinidad&tobago"})),
    "USD": (frozenset({"en-US", "en-us", "es-PR", "es-pr", "es-PA", "es-pa"}), frozenset({"usa", "unitedstates", "us", "puertorico", "panama"})),
    "JMD": (frozenset({"en-JM", "en-jm"}), frozenset({"jamaica"})),
    "COP": (frozenset({"es-CO", "es-co"}), frozenset({"colombia"})),
    "GYD": (frozenset({"en-GY", "en-gy"}), frozenset({"guyana"})),
    "MXN": (frozenset({"es-MX", "es-mx"}), frozenset({"mexico"})),
    "PEN": (frozenset({"es-PE", "es-pe"}), frozenset({"peru"})),
    "PLN": (frozenset({"pl-PL", "pl-pl"}), frozenset({"poland"})),
    "ZAR": (frozenset({"en-ZA", "en-za"}), frozenset({"southafrica", "sa"})),
    "PR": (frozenset({"es-PR", "es-pr", "en-PR", "en-pr"}), frozenset({"puertorico", "pr"})),
}


@dataclass
class JurisdictionProfile:
    """Expected settings for one jurisdiction / market."""

    id: str
    label: str
    country: str
    currency: str = ""
    culture: str = ""
    language: str = ""
    target_market: str = ""
    allowed_denoms: list[int] = field(default_factory=list)
    allowed_bet_multipliers: list[int] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "country": self.country,
            "currency": self.currency,
            "culture": self.culture,
            "language": self.language,
            "target_market": self.target_market,
            "allowed_denoms": list(self.allowed_denoms),
            "allowed_bet_multipliers": list(self.allowed_bet_multipliers),
            "expected": dict(self.expected),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JurisdictionProfile:
        return cls(
            id=str(data.get("id") or ""),
            label=str(data.get("label") or data.get("id") or ""),
            country=str(data.get("country") or ""),
            currency=str(data.get("currency") or ""),
            culture=str(data.get("culture") or ""),
            language=str(data.get("language") or ""),
            target_market=str(data.get("target_market") or ""),
            allowed_denoms=[int(x) for x in (data.get("allowed_denoms") or [])],
            allowed_bet_multipliers=[
                int(x) for x in (data.get("allowed_bet_multipliers") or [])
            ],
            expected=dict(data.get("expected") or {}),
            notes=str(data.get("notes") or ""),
        )


_JURISDICTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def jurisdictions_path() -> Path:
    return bundled_assets_root() / "jurisdictions.json"


def user_jurisdictions_path() -> Path:
    """Sidecar for operator-created markets (survives exe upgrades)."""
    if getattr(sys, "frozen", False):
        from app_paths import app_writable_dir

        return app_writable_dir() / "jurisdictions.user.json"
    return bundled_assets_root() / "jurisdictions.user.json"


def slug_jurisdiction_id(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").casefold()).strip("_")
    if slug and slug[0].isdigit():
        slug = "m_" + slug
    return (slug[:63] if slug else "") or "market"


def jurisdiction_id_error(profile_id: str) -> str | None:
    token = (profile_id or "").strip()
    if not token:
        return "Market id is required."
    if not _JURISDICTION_ID_RE.fullmatch(token):
        return "Id must be lowercase letters, digits, and underscores (start with a letter)."
    return None


def suggest_jurisdiction_label(*, market: str = "", currency: str = "") -> str:
    market = (market or "").strip()
    currency = (currency or "").strip().upper()
    if market and currency:
        return f"{market} ({currency})"
    return market or currency or "Custom market"


def suggest_jurisdiction_id(*, label: str = "", market: str = "", currency: str = "") -> str:
    raw = (label or "").strip()
    if not raw:
        bits = [p for p in ((market or "").strip(), (currency or "").strip()) if p]
        raw = "_".join(bits)
    return slug_jurisdiction_id(raw)


def _read_jurisdiction_file(path: Path) -> list[JurisdictionProfile]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[JurisdictionProfile] = []
    for item in data.get("jurisdictions") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        out.append(JurisdictionProfile.from_dict(item))
    return out


def merge_jurisdiction_profiles(
    bundled: list[JurisdictionProfile],
    user: list[JurisdictionProfile],
) -> list[JurisdictionProfile]:
    """Bundled order first; sidecar ids replace matching bundled rows, then extras."""
    order = [p.id for p in bundled]
    by_id = {p.id: p for p in bundled}
    extra: list[JurisdictionProfile] = []
    for prof in user:
        if not prof.id:
            continue
        if prof.id in by_id:
            by_id[prof.id] = prof
        else:
            extra.append(prof)
            by_id[prof.id] = prof
    return [by_id[i] for i in order] + extra


def load_jurisdictions(
    path: Path | None = None, *, include_user: bool = True
) -> list[JurisdictionProfile]:
    if path is not None:
        return _read_jurisdiction_file(path)
    bundled = _read_jurisdiction_file(jurisdictions_path())
    if not include_user:
        return bundled
    return merge_jurisdiction_profiles(bundled, _read_jurisdiction_file(user_jurisdictions_path()))


def save_jurisdictions(
    profiles: list[JurisdictionProfile], path: Path | None = None
) -> Path:
    p = path or jurisdictions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "jurisdictions": [prof.to_dict() for prof in profiles],
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def find_jurisdiction(jurisdiction_id: str) -> JurisdictionProfile | None:
    key = jurisdiction_id.strip().casefold()
    for prof in load_jurisdictions():
        if prof.id.casefold() == key:
            return prof
    return None


def _norm_market(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").casefold())


def consistency_issues(
    *,
    currency: str | None = None,
    culture_name: str | None = None,
    target_market: str | None = None,
    language: str | None = None,
    profile: JurisdictionProfile | None = None,
) -> list[str]:
    """Flag currency / culture / TargetMarket mismatches (e.g. TTD + es-PR)."""
    issues: list[str] = []
    cur = (currency or (profile.currency if profile else "") or "").strip().upper()
    culture = (culture_name or (profile.culture if profile else "") or "").strip()
    market = (target_market or (profile.target_market if profile else "") or "").strip()
    lang = (language or (profile.language if profile else "") or "").strip()

    if cur and culture:
        hints = _CURRENCY_HINTS.get(cur)
        if hints:
            cultures, _markets = hints
            # If currency has a strong culture hint and culture is a known *other* market.
            culture_cf = culture.casefold()
            if cultures and culture_cf not in {c.casefold() for c in cultures}:
                # Special case: TTD must not be paired with Puerto Rico culture.
                if cur == "TTD" and culture_cf.startswith("es-pr"):
                    issues.append(
                        f"Currency {cur} does not match CultureName={culture} "
                        "(expected en-TT for Trinidad)."
                    )
                elif cur == "TTD" and "pr" in culture_cf:
                    issues.append(
                        f"Currency {cur} does not match CultureName={culture}."
                    )

    if cur and market:
        mnorm = _norm_market(market)
        if cur == "TTD" and "puertorico" in mnorm:
            issues.append(
                f"Currency {cur} does not match TargetMarket={market} "
                "(expected Trinidad / TrinidadTobago)."
            )
        if cur == "TTD" and mnorm in ("pr",):
            issues.append(f"Currency {cur} does not match TargetMarket={market}.")

    if cur == "TTD" and lang.casefold() == "spanish":
        issues.append(
            f"Currency {cur} with Language={lang} is unusual for Trinidad "
            "(expected English)."
        )

    if profile and profile.currency and cur and profile.currency.upper() != cur:
        issues.append(
            f"Observed currency {cur} differs from profile {profile.currency}."
        )
    return issues


def consistency_issues_from_readings(
    readings: dict[str, SettingReading],
    profile: JurisdictionProfile | None = None,
) -> list[str]:
    def _val(sid: str) -> Any:
        r = readings.get(sid)
        return r.value if r and r.present else None

    issues = consistency_issues(
        currency=_val("locale.currency_name") or _val("locale.hw_currency_name"),
        culture_name=_val("locale.culture_name"),
        target_market=_val("locale.target_market"),
        language=_val("locale.language"),
        profile=profile,
    )
    loc = _val("id.processor_locale")
    if loc and str(loc).replace("-", "_").casefold() == "sl_si":
        issues.append(
            f"Aurum Processor LocaleId={loc} looks like a Slovenia leftover "
            "(CS packs ship sl_SI for every country)."
        )
    jur_tag = _val("locale.jur_tag")
    market = _val("locale.target_market")
    if jur_tag and market:
        if _norm_market(str(jur_tag)) != _norm_market(str(market)):
            issues.append(
                f"jurisdiction_config Tag={jur_tag} does not match "
                f"mgconfig TargetMarket={market}."
            )
    return issues


def probe_against_profile(
    goldclub: Path,
    profile: JurisdictionProfile,
    *,
    source_is_cs_leaf: bool = False,
) -> dict[str, SettingReading]:
    return probe_tree(
        goldclub,
        expected=profile.expected,
        source_is_cs_leaf=source_is_cs_leaf,
    )


def leaf_matches_profile_country(leaf_country: str, profile: JurisdictionProfile) -> bool:
    a = _norm_market(leaf_country)
    b = _norm_market(profile.country)
    if not a or not b:
        return True
    return a in b or b in a or a == b


def build_expected_from_leaf(goldclub: Path) -> dict[str, Any]:
    """Capture present values from a leaf as an expected map (mining seed)."""
    readings = probe_tree(goldclub, expected=None, source_is_cs_leaf=True)
    out: dict[str, Any] = {}
    for sid, reading in readings.items():
        if reading.state == SettingState.NOT_SUPPLIED and not reading.present:
            continue
        if reading.present and reading.value is not None:
            out[sid] = reading.value
    return out


def ensure_expected_locale_keys(profile: JurisdictionProfile) -> JurisdictionProfile:
    """Fill expected map from profile metadata when keys are missing."""
    exp = dict(profile.expected)
    if profile.currency:
        exp.setdefault("locale.currency_name", profile.currency)
        exp.setdefault("locale.hw_currency_name", profile.currency)
    if profile.culture:
        exp.setdefault("locale.culture_name", profile.culture)
    if profile.language:
        exp.setdefault("locale.language", profile.language)
    if profile.target_market:
        exp.setdefault("locale.target_market", profile.target_market)
    if profile.allowed_denoms:
        exp.setdefault("denom.list", list(profile.allowed_denoms))
        exp.setdefault("denom.credit_rate_values", list(profile.allowed_denoms))
    profile.expected = exp
    return profile


def known_setting_ids() -> frozenset[str]:
    return frozenset(s.id for s in all_specs())


def _recipe_int_list(value: Any) -> list[int]:
    out: list[int] = []
    for item in value or []:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def profile_from_recipe(
    recipe: object,
    *,
    profile_id: str,
    label: str,
    country: str = "",
    notes: str = "",
) -> JurisdictionProfile:
    """Serialize Live Push / SlotSetupRecipe fields into a jurisdiction profile.

    Skips Dallas, door switches, display mode, hardware deck, and live machine
    identity — those stay cabinet-specific when the market is applied later.
    """
    jur = getattr(recipe, "jurisdiction", None)
    mg = getattr(recipe, "mg_identity", None)
    sas = getattr(recipe, "sas", None)
    play = getattr(recipe, "play_limits", None)

    currency = str(getattr(jur, "currency_name", "") or "").strip()
    culture = str(getattr(jur, "culture_name", "") or "").strip()
    language = str(getattr(mg, "language", "") or "").strip()
    market = str(getattr(jur, "tag", "") or "").strip()
    symbol = str(getattr(jur, "currency_symbol", "") or "").strip()
    denoms = _recipe_int_list(getattr(recipe, "denomination_list", None))
    credit = _recipe_int_list(getattr(recipe, "credit_rate_values", None)) or list(denoms)
    bets = _recipe_int_list(getattr(play, "bet_multipliers", None))

    expected: dict[str, Any] = {}
    if market:
        expected["locale.target_market"] = market
    if culture:
        expected["locale.culture_name"] = culture
    if language:
        expected["locale.language"] = language
    if currency:
        expected["locale.currency_name"] = currency
        expected["locale.hw_currency_name"] = str(
            getattr(recipe, "hardware_currency_name", "") or currency
        ).strip() or currency
        expected["locale.currency_format"] = "{0} " + currency
    if symbol:
        expected["locale.currency_short_symbol"] = symbol
    if denoms:
        expected["denom.list"] = list(denoms)
        expected["denom.credit_rate_values"] = list(credit)
    if bets:
        expected["math.bet_multipliers"] = list(bets)
    if sas is not None:
        expected["sas.funds_transfer_type"] = str(
            getattr(sas, "funds_transfer_type", "") or "AFT"
        )
        expected["sas.lock_when_no_comms"] = bool(
            getattr(sas, "lock_game_when_no_comms", False)
        )
        expected["sas.aft_enabled"] = bool(getattr(sas, "aft_enabled", True))
        try:
            expected["sas.address"] = int(getattr(sas, "address", 1) or 1)
        except (TypeError, ValueError):
            expected["sas.address"] = 1
    protocol = str(getattr(recipe, "bill_protocol", "") or "").strip()
    if protocol:
        expected["bill.protocol"] = protocol
        expected["bill.enabled"] = True
    offline = getattr(recipe, "offline_enabled", None)
    if offline is not None:
        expected["ticket.offline_enabled"] = bool(offline)
        if offline:
            expected["ticket.printer_enabled"] = True
    ticket_protocol = str(getattr(recipe, "ticket_protocol", "") or "").strip()
    if ticket_protocol:
        expected["ticket.printer_enabled"] = True
    if play is not None:
        show_denom = getattr(play, "show_denom_selector", None)
        if show_denom is not None:
            expected["denom.show_selector"] = bool(show_denom)
        default_bet = str(getattr(play, "default_bet", "") or "").strip()
        if default_bet:
            expected["ui.default_bet"] = default_bet
        show_lines = getattr(play, "show_all_lines", None)
        if show_lines is not None:
            expected["ui.show_all_lines"] = bool(show_lines)
        cashout = str(getattr(play, "cashout_button_mode", "") or "").strip()
        if cashout:
            expected["ui.cashout_button_mode"] = cashout
        celebration = str(getattr(play, "celebration_limit", "") or "").strip()
        if celebration:
            expected["ui.payout_celebration_limit"] = celebration
        redeem = getattr(play, "ticket_redeem_enabled", None)
        if redeem is not None:
            expected["ticket.redeem_enabled"] = bool(redeem)
        ticket_iso = getattr(play, "ticket_use_currency_iso", None)
        if ticket_iso is not None:
            expected["ticket.use_currency_iso"] = bool(ticket_iso)
        jp_layout = str(getattr(play, "jackpot_receipt_layout", "") or "").strip()
        if jp_layout:
            expected["ticket.layout_jackpot"] = jp_layout
    ina = getattr(mg, "inactivity_seconds_to_game_selector", None)
    if ina is not None:
        expected["ui.inactivity_to_selector"] = str(int(ina))
    mw_limit = getattr(jur, "magic_wheel_money_limit", None)
    if mw_limit is not None:
        expected["locale.jur_magic_wheel_limit"] = int(mw_limit)
    expected["id.machine_id"] = "GST!!MachineName!!"

    known = specs_by_id()
    expected = {key: value for key, value in expected.items() if key in known}

    return JurisdictionProfile(
        id=profile_id.strip(),
        label=label.strip() or profile_id.strip(),
        country=(country or market or currency).strip(),
        currency=currency,
        culture=culture,
        language=language,
        target_market=market,
        allowed_denoms=list(denoms),
        allowed_bet_multipliers=list(bets),
        expected=expected,
        notes=notes.strip(),
    )


def upsert_jurisdiction(
    profile: JurisdictionProfile, *, path: Path | None = None
) -> tuple[Path, bool]:
    """Write *profile* into the user sidecar (create or replace by id)."""
    dest = path or user_jurisdictions_path()
    existing = _read_jurisdiction_file(dest)
    replaced = False
    out: list[JurisdictionProfile] = []
    key = profile.id.casefold()
    for item in existing:
        if item.id.casefold() == key:
            out.append(profile)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(profile)
    save_jurisdictions(out, dest)
    return dest, replaced
