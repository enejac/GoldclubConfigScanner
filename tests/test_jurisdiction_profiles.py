"""Jurisdiction profile library and consistency rules."""

from __future__ import annotations

from config_scanner.embedded_updates import load_catalog, materialize_country_tool
from config_scanner.jurisdiction import (
    consistency_issues,
    consistency_issues_from_readings,
    find_jurisdiction,
    jurisdictions_path,
    load_jurisdictions,
    probe_against_profile,
    profile_from_recipe,
    slug_jurisdiction_id,
    suggest_jurisdiction_id,
    upsert_jurisdiction,
)
from config_scanner.setting_spec import specs_by_id
from config_scanner.slot_setup import recipe_from_jurisdiction_profile


def test_catalog_loads_trinidad() -> None:
    profiles = load_jurisdictions()
    assert len(profiles) >= 1
    tri = find_jurisdiction("trinidad_ttd")
    assert tri is not None
    assert tri.currency == "TTD"
    assert tri.culture == "en-TT"
    assert "locale.target_market" in tri.expected


def test_catalog_covers_all_share_markets() -> None:
    ids = {p.id for p in load_jurisdictions(jurisdictions_path())}
    required = {
        "trinidad_ttd",
        "trinidad_ttd_sas_only",
        "jamaica_jmd",
        "jamaica_jmd_sas_only",
        "puerto_rico",
        "puerto_rico_sas_only",
        "panama_usd",
        "panama_usd_sas_only",
        "colombia_cop",
        "guyana_gyd",
        "mexico_mxn",
        "peru_pen",
        "poland_pln",
        "south_africa_zar",
    }
    assert required.issubset(ids), f"missing {required - ids}"
    assert len(ids) >= 13
    known = specs_by_id()
    for prof in load_jurisdictions(jurisdictions_path()):
        unknown = set(prof.expected) - set(known)
        assert not unknown, f"{prof.id} expected unknown ids: {unknown}"


def test_ttd_vs_es_pr_consistency_rule() -> None:
    issues = consistency_issues(
        currency="TTD",
        culture_name="es-PR",
        target_market="PuertoRico",
        language="Spanish",
    )
    assert any("CultureName" in i for i in issues)
    assert any("TargetMarket" in i for i in issues)
    assert any("Language" in i for i in issues)


def test_south_africa_profile_from_confluence() -> None:
    sa = find_jurisdiction("south_africa_zar")
    assert sa is not None
    assert sa.currency == "ZAR"
    assert sa.culture == "en-ZA"
    assert sa.target_market == "SA"
    assert sa.language == "English"
    assert sa.expected["locale.jur_tag"] == "SA"
    assert sa.expected["locale.jur_magic_wheel_limit"] == 500
    assert sa.expected["denom.jur_single_denomination"] == 1
    assert sa.expected["locale.jur_currency_base_symbol"] == "c"
    assert consistency_issues(
        currency=sa.currency,
        culture_name=sa.culture,
        target_market=sa.target_market,
        language=sa.language,
        profile=sa,
    ) == []
    recipe = recipe_from_jurisdiction_profile(sa, denom=1)
    assert recipe.jurisdiction.tag == "SA"
    assert recipe.jurisdiction.currency_name == "ZAR"
    assert recipe.jurisdiction.culture_name == "en-ZA"
    assert recipe.jurisdiction.currency_symbol == "R"
    assert recipe.jurisdiction.magic_wheel_money_limit == 500
    assert recipe.denomination_list[0] == 1
    assert recipe.sas.lock_game_when_no_comms is True
    assert recipe.offline_enabled is True


def test_shipped_sa00_pack_fails_confluence_consistency() -> None:
    entries = load_catalog()
    entry = next(e for e in entries if e.id == "CS-Gamestar-SA-00")
    tool = materialize_country_tool(entry)
    leaf = tool / "data" / "South Africa 94" / "Gamestar2" / "Gamestar2 3 Screens"
    assert leaf.is_dir()
    sa = find_jurisdiction("south_africa_zar")
    assert sa is not None
    readings = probe_against_profile(leaf, sa, source_is_cs_leaf=True)
    issues = consistency_issues_from_readings(readings, profile=sa)
    assert issues, "expected leftover PuertoRico / sl-SI vs official en-ZA / SA"
    assert readings["locale.jur_tag"].value == "SA"
    assert readings["locale.target_market"].value == "PuertoRico"
    assert readings["locale.culture_name"].value in {"es-PR", "sl-SI", "en-ZA"}


def test_consistency_ok_for_profile() -> None:
    tri = find_jurisdiction("trinidad_ttd")
    assert tri is not None
    issues = consistency_issues(
        currency=tri.currency,
        culture_name=tri.culture,
        target_market=tri.target_market,
        language=tri.language,
        profile=tri,
    )
    assert issues == []


def test_shipped_trinidad_pack_fails_consistency() -> None:
    entries = load_catalog()
    entry = next(e for e in entries if e.id == "CS-Gamestar-TRI-00_OL+SAS")
    tool = materialize_country_tool(entry)
    leaf = (
        tool
        / "data"
        / "Trinidad&Tobago"
        / "Gamestar OL+SAS 10c"
        / "Gamestar 2 Screens"
    )
    assert leaf.is_dir()
    tri = find_jurisdiction("trinidad_ttd")
    assert tri is not None
    readings = probe_against_profile(leaf, tri, source_is_cs_leaf=True)
    # Pack has TTD currency but PuertoRico market / es-PR culture.
    issues = consistency_issues_from_readings(readings, profile=tri)
    assert issues, "expected TTD vs es-PR / PuertoRico mismatch on shipped pack"
    assert any("sl_SI" in i or "LocaleId" in i for i in issues)
    # Profile expected TargetMarket should DIFFERS vs pack PuertoRico
    assert readings["locale.target_market"].value == "PuertoRico"
    assert readings["locale.currency_name"].value == "TTD"


def test_recipe_from_jurisdiction_profile() -> None:
    tri = find_jurisdiction("trinidad_ttd")
    assert tri is not None
    recipe = recipe_from_jurisdiction_profile(
        tri, denom=10, denomination_list=[2, 5, 10], offline_enabled=True
    )
    assert recipe.denomination_list == [10, 2, 5]
    assert recipe.jurisdiction.currency_name == "TTD"
    assert recipe.jurisdiction.tag == "TrinidadTobago"
    assert recipe.offline_enabled is True
    assert recipe.mg_identity.language == "English"
    assert recipe.mg_identity.inactivity_seconds_to_game_selector == 0


def test_slug_jurisdiction_id_normalizes() -> None:
    assert slug_jurisdiction_id("Colombia (COP)") == "colombia_cop"
    assert slug_jurisdiction_id("  Trinidad & Tobago  ") == "trinidad_tobago"
    assert slug_jurisdiction_id("10c Peru") == "m_10c_peru"
    assert suggest_jurisdiction_id(market="Colombia", currency="COP") == "colombia_cop"


def test_profile_from_recipe_round_trips_through_jurisdiction_profile() -> None:
    tri = find_jurisdiction("trinidad_ttd")
    assert tri is not None
    recipe = recipe_from_jurisdiction_profile(tri)
    recipe.dallas.code = "01D68A721B000019"
    profile = profile_from_recipe(
        recipe,
        profile_id="lab_ttd_copy",
        label="Lab TTD copy",
        country="Trinidad&Tobago",
        notes="from test",
    )
    assert profile.id == "lab_ttd_copy"
    assert profile.currency == "TTD"
    assert profile.target_market == "TrinidadTobago"
    assert "dallas" not in " ".join(profile.expected)
    assert profile.expected.get("id.machine_id") == "GST!!MachineName!!"
    assert "01D68A721B000019" not in str(profile.to_dict())
    again = recipe_from_jurisdiction_profile(profile)
    assert again.jurisdiction.currency_name == "TTD"
    assert again.jurisdiction.tag == "TrinidadTobago"
    assert again.jurisdiction.culture_name == "en-TT"
    assert again.denomination_list == recipe.denomination_list
    assert again.play_limits.bet_multipliers == recipe.play_limits.bet_multipliers
    assert again.sas.aft_enabled is recipe.sas.aft_enabled
    assert again.offline_enabled is recipe.offline_enabled
    assert again.mg_identity.inactivity_seconds_to_game_selector == 0
    assert again.dallas.code == ""


def test_upsert_and_load_merges_user_sidecar(tmp_path, monkeypatch) -> None:
    user = tmp_path / "jurisdictions.user.json"
    monkeypatch.setattr(
        "config_scanner.jurisdiction.user_jurisdictions_path", lambda: user
    )
    tri = find_jurisdiction("trinidad_ttd")
    assert tri is not None
    recipe = recipe_from_jurisdiction_profile(tri)
    recipe.jurisdiction.currency_name = "COP"
    recipe.jurisdiction.tag = "Colombia"
    recipe.jurisdiction.culture_name = "es-CO"
    recipe.mg_identity.language = "Spanish"
    profile = profile_from_recipe(
        recipe,
        profile_id="lab_cop",
        label="Lab Colombia COP",
        country="Colombia",
        notes="sidecar",
    )
    path, replaced = upsert_jurisdiction(profile)
    assert path == user
    assert replaced is False
    assert user.is_file()
    ids = [p.id for p in load_jurisdictions()]
    assert "lab_cop" in ids
    assert "trinidad_ttd" in ids
    found = find_jurisdiction("lab_cop")
    assert found is not None
    assert found.label == "Lab Colombia COP"
    assert found.currency == "COP"

    updated = profile_from_recipe(
        recipe,
        profile_id="lab_cop",
        label="Lab Colombia COP v2",
        country="Colombia",
    )
    _path, replaced = upsert_jurisdiction(updated)
    assert replaced is True
    again = find_jurisdiction("lab_cop")
    assert again is not None
    assert again.label == "Lab Colombia COP v2"

    override = profile_from_recipe(
        recipe,
        profile_id="trinidad_ttd",
        label="TTD from sidecar",
        country="Trinidad&Tobago",
    )
    upsert_jurisdiction(override)
    merged = find_jurisdiction("trinidad_ttd")
    assert merged is not None
    assert merged.label == "TTD from sidecar"
    bundled = load_jurisdictions(jurisdictions_path())
    bundled_tri = next(p for p in bundled if p.id == "trinidad_ttd")
    assert bundled_tri.label != "TTD from sidecar"
