"""Lab share Country Selector source catalog and GameUpdate handling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config_scanner.b2u_pack import (
    extract_game_update,
    game_update_authoring_note,
    is_game_update_file,
)
from config_scanner.cs_sources import (
    CsSource,
    CsSourceKind,
    clear_share_scan_cache,
    country_from_b2u_folder_name,
    country_matches_profile,
    is_debug_or_test_pack,
    is_game_update_zip,
    list_cs_sources,
    materialize_cs_path,
    recommend_cs_source,
)


def test_country_from_b2u_folder_name() -> None:
    assert country_from_b2u_folder_name("CS-Gamestar-TRI-01_SAS") == "Trinidad"
    assert country_from_b2u_folder_name("CS-Gamestar-JAM-00") == "Jamaica"
    assert country_from_b2u_folder_name("CS-Gamestar-PANC-02") == "Panama"
    assert country_from_b2u_folder_name("CS-Gamestar-PR-05_SAS") == "PuertoRico"
    assert country_from_b2u_folder_name("CS-Gamestar-PRU-00_Debug") == "Peru"
    assert country_from_b2u_folder_name("CS-Gamestar-PER-00") == "Peru"
    assert country_from_b2u_folder_name("CS-Gamestar-COL-01") == "Colombia"
    assert country_from_b2u_folder_name("CS-Gamestar-SA-00") == "South Africa"
    assert country_from_b2u_folder_name("CS-Gamestar-SA-00_SI") == "South Africa"
    assert country_from_b2u_folder_name("CS-Gamestar-TRI-00_SAS") == "Trinidad"


def test_country_matches_trinidad_variants() -> None:
    assert country_matches_profile("Trinidad&Tobago", "Trinidad")
    assert country_matches_profile("Trinidad", "Trinidad&Tobago")
    assert country_matches_profile("TT", "Trinidad")
    assert country_matches_profile("TrinidadTobago", "Trinidad")
    assert not country_matches_profile("Jamaica", "Trinidad")


def test_list_cs_sources_filters_by_jurisdiction() -> None:
    tri = list_cs_sources(profile_country="Trinidad&Tobago", authoring_only=True)
    assert tri
    assert all(
        "trinidad" in s.country.casefold() or "tobago" in s.country.casefold()
        for s in tri
    )
    jam = list_cs_sources(profile_country="Jamaica", authoring_only=True)
    assert any("JAM" in s.id or "jamaica" in s.country.casefold() for s in jam)
    pr = list_cs_sources(profile_country="PuertoRico", authoring_only=True)
    assert any(s.embedded_id and s.embedded_id.startswith("CS-Gamestar-PR-") for s in pr)
    sa = list_cs_sources(profile_country="South Africa", authoring_only=True)
    assert any(s.embedded_id == "CS-Gamestar-SA-00" for s in sa)


def _pack(stem: str, line: str, country: str = "Trinidad") -> CsSource:
    return CsSource(
        id=stem,
        label=stem,
        country=country,
        gamestar_line=line,
        kind=CsSourceKind.SHARE_B2U,
        path=Path(f"{stem}.b2u"),
        authoring=True,
    )


def test_recommend_newest_non_debug_and_ol_sas() -> None:
    tri01 = _pack("CS-Gamestar-TRI-01", "2.0.1")
    tt00 = _pack("CS-Gamestar-TT-00", "2.0.1")
    tri_sas = _pack("CS-Gamestar-TRI-01_SAS", "2.0.1")
    assert recommend_cs_source([tt00, tri01], profile_id="trinidad_ttd") is tri01
    picked = recommend_cs_source([tri01, tri_sas], profile_id="trinidad_ttd_sas_only")
    assert picked is tri_sas
    dbg = _pack("CS-Gamestar-JAM-00_Debug", "2.0.1", country="Jamaica")
    jam = _pack("CS-Gamestar-JAM-01", "2.0.1", country="Jamaica")
    assert is_debug_or_test_pack(dbg)
    assert recommend_cs_source([dbg, jam], profile_id="jamaica_jmd") is jam


def test_pick_cs_source_for_export_accepts_embedded_without_path() -> None:
    from config_scanner.cs_sources import (
        pick_cs_source_for_export,
        source_is_materializable,
    )

    emb = CsSource(
        id="embedded-tri",
        label="Trinidad TRI-01",
        country="Trinidad",
        gamestar_line="TRI-01",
        kind=CsSourceKind.EMBEDDED,
        embedded_id="CS-Gamestar-TRI-01",
        authoring=True,
    )
    missing_jam = CsSource(
        id="share-jam",
        label="Jamaica JAM-01",
        country="Jamaica",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=Path("no-such-jam.b2u"),
        authoring=True,
    )
    assert source_is_materializable(emb)
    assert not source_is_materializable(missing_jam)
    assert pick_cs_source_for_export("TT", sources=[emb, missing_jam]) is emb
    assert pick_cs_source_for_export("Jamaica", sources=[emb, missing_jam]) is None


def test_share_scan_includes_gs200_encrypted_and_gs22(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config_scanner import cs_sources as mod

    gs200 = tmp_path / "GameStar 2.0.0" / "Country Selectors" / "Panama"
    gs200.mkdir(parents=True)
    (gs200 / "CS-Gamestar-PANC-01.b2u").write_bytes(b"x")
    b2u = tmp_path / "_B2U"
    b2u.mkdir()
    enc = b2u / "encrypted"
    enc.mkdir()
    (enc / "CS-Gamestar-PER-00.b2u").write_bytes(b"x")
    gs22 = tmp_path / "GameStar+22" / "Colombia"
    gs22.mkdir(parents=True)
    zip_name = "GameUpdate.Slot.CountrySelector_GS+22_V4_COL_Win10.zip"
    (gs22 / zip_name).write_bytes(b"z")

    monkeypatch.setattr(mod, "_SHARE_GS200", tmp_path / "GameStar 2.0.0" / "Country Selectors")
    monkeypatch.setattr(mod, "_SHARE_GS201", tmp_path / "missing-201")
    monkeypatch.setattr(mod, "_SHARE_B2U", b2u)
    monkeypatch.setattr(mod, "_SHARE_B2U_ENC", enc)
    monkeypatch.setattr(mod, "_SHARE_GS30", tmp_path / "missing-30")
    monkeypatch.setattr(mod, "_SHARE_GS22", tmp_path / "GameStar+22")
    monkeypatch.setattr(mod, "_SHARE_USB91_B2U", tmp_path / "missing-usb91")
    monkeypatch.setattr(mod, "_SHARE_USB91_ENC", tmp_path / "missing-usb91" / "encrypted")
    clear_share_scan_cache()
    found = list_cs_sources(include_share_scan=True, authoring_only=False)
    names = {s.path.name for s in found if s.path is not None}
    assert "CS-Gamestar-PANC-01.b2u" in names
    assert "CS-Gamestar-PER-00.b2u" in names
    apply_only = [s for s in found if not s.authoring]
    assert any(s.gamestar_line == "GS+22" for s in apply_only)
    peru = list_cs_sources(
        profile_country="Peru", authoring_only=True, include_share_scan=True
    )
    assert any(s.path and s.path.name == "CS-Gamestar-PER-00.b2u" for s in peru)
    clear_share_scan_cache()


def test_is_game_update_zip() -> None:
    name = "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip"
    assert is_game_update_zip(Path(name))
    assert is_game_update_file(Path(name))


def test_game_update_meta_only_raises(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip"
    archive.write_bytes(b"enc")
    pkg = tmp_path / "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10"
    meta = pkg / "Meta"
    meta.mkdir(parents=True)
    (meta / "meta.xml").write_bytes(b"blob")

    monkeypatch.setattr(
        "config_scanner.b2u_pack.extract_game_update",
        lambda _path, **kwargs: pkg,
    )
    with pytest.raises(FileNotFoundError) as exc:
        materialize_cs_path(archive)
    assert "Meta/meta.xml" in str(exc.value) or "GameStar+30" in str(exc.value)


def test_game_update_authoring_note_mentions_b2u() -> None:
    note = game_update_authoring_note(
        Path("GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip")
    )
    assert "2.0.1" in note
    assert "CountrySelectorTool" in note


def test_extract_game_update_mock(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip"
    archive.write_bytes(b"x")
    fake_gen = tmp_path / "BiOS2_PackageGenerator.exe"
    fake_gen.write_bytes(b"MZ")
    out = tmp_path / "out"
    stem = archive.stem

    def fake_run(cmd, capture_output=True, text=True, check=False, **kwargs):  # noqa: ANN001
        pkg_root = out / stem
        meta = pkg_root / "Meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "meta.xml").write_bytes(b"meta")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("config_scanner.b2u_pack.subprocess.run", fake_run)
    monkeypatch.setattr(
        "config_scanner.b2u_pack.default_package_generator", lambda: fake_gen
    )
    (fake_gen.parent / "log4net.dll").write_bytes(b"x")
    (fake_gen.parent / "ICSharpCode.SharpZipLib.dll").write_bytes(b"x")
    result = extract_game_update(archive, work_parent=out, reuse_cache=False)
    assert (result / "Meta" / "meta.xml").is_file()


@pytest.mark.skipif(
    not Path(
        "//10.0.0.249/WinSystems_SLOT/GameStar+30/Colombia/"
        "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip"
    ).is_file(),
    reason="lab share not reachable",
)
def test_real_colombia_gameupdate_decrypt_meta_only() -> None:
    from config_scanner.b2u_pack import default_package_generator, extract_game_update
    from config_scanner.cs_sources import game_update_has_country_selector

    if default_package_generator() is None:
        pytest.skip("BiOS2_PackageGenerator not installed")
    path = Path(
        "//10.0.0.249/WinSystems_SLOT/GameStar+30/Colombia/"
        "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip"
    )
    pkg = extract_game_update(path, reuse_cache=True)
    assert (pkg / "Meta" / "meta.xml").is_file()
    assert game_update_has_country_selector(pkg) is False


# --- offline / no-EGM edge cases -------------------------------------------


@pytest.fixture
def _share_down(monkeypatch: pytest.MonkeyPatch):
    """Every lab share host is unreachable; any Path I/O on a UNC root is a bug."""
    from config_scanner import net_gate

    net_gate.clear_reachability_cache()
    probed: list[str] = []

    def fake_probe(host: str, timeout_sec: float) -> bool:
        probed.append(host)
        return False

    monkeypatch.setattr(net_gate, "_probe", fake_probe)

    real_is_dir = Path.is_dir
    real_is_file = Path.is_file
    real_iterdir = Path.iterdir
    real_exists = Path.exists

    def _guard(name, real):
        def wrapper(self, *args, **kwargs):
            if str(self).startswith("//10.0.0.") or str(self).startswith("\\\\10.0.0."):
                raise AssertionError(f"{name}() touched dead share path {self}")
            return real(self, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(Path, "is_dir", _guard("is_dir", real_is_dir))
    monkeypatch.setattr(Path, "is_file", _guard("is_file", real_is_file))
    monkeypatch.setattr(Path, "iterdir", _guard("iterdir", real_iterdir))
    monkeypatch.setattr(Path, "exists", _guard("exists", real_exists))
    clear_share_scan_cache()
    yield probed
    clear_share_scan_cache()
    net_gate.clear_reachability_cache()


def test_list_cs_sources_offline_skips_all_share_io(_share_down: list[str]) -> None:
    from config_scanner.cs_sources import share_offline_note

    found = list_cs_sources(include_share_scan=True, authoring_only=False)
    assert found, "embedded catalog must still be listed offline"
    assert all(s.kind == CsSourceKind.EMBEDDED for s in found)
    # one TCP probe per host, cached — not one per curated path / scan root
    assert sorted(set(_share_down)) == ["10.0.0.249", "10.0.0.91"]
    assert len(_share_down) == 2
    note = share_offline_note()
    assert "10.0.0.249" in note and "built-in packs only" in note


def test_materialize_cs_path_offline_share_fails_fast(_share_down: list[str]) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        materialize_cs_path(Path("//10.0.0.249/WinSystems_SLOT/_B2U/CS-Gamestar-TRI-01.b2u"))
    assert "not reachable" in str(exc.value)
    assert "10.0.0.249" in str(exc.value)


def test_share_browse_start_falls_back_when_host_down(
    _share_down: list[str], tmp_path: Path
) -> None:
    from config_scanner.cs_sources import share_browse_start

    assert share_browse_start(r"\\10.0.0.249\WinSystems_SLOT\_B2U", str(tmp_path)) == str(tmp_path)
    assert share_browse_start(str(tmp_path)) == str(tmp_path)


def _fake_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from config_scanner import embedded_updates as emb

    root = tmp_path / "embedded_updates"
    (root / "b2u").mkdir(parents=True)
    (root / "b2u" / "CS-Gamestar-PR-03.b2u").write_bytes(b"x")
    staged = root / "staged" / "CS-Gamestar-TT-00" / "CountrySelectorTool" / "data"
    staged.mkdir(parents=True)
    (root / "catalog.json").write_text(
        """{"version": 1, "updates": [
            {"id": "CS-Gamestar-PR-03", "label": "Puerto Rico PR-03", "country": "PuertoRico",
             "gamestar_version": "2.0.1", "b2u_file": "CS-Gamestar-PR-03.b2u"},
            {"id": "CS-Gamestar-PR-06", "label": "Puerto Rico PR-06", "country": "PuertoRico",
             "gamestar_version": "2.0.1", "b2u_file": null, "staged_id": "CS-Gamestar-PR-06"},
            {"id": "CS-Gamestar-TT-00", "label": "Trinidad TT-00", "country": "Trinidad",
             "gamestar_version": "2.0.1", "b2u_file": null}
        ]}""",
        encoding="utf-8",
    )
    monkeypatch.setattr(emb, "embedded_updates_root", lambda: root)


def test_embedded_without_payload_is_listed_but_not_authoring(
    _share_down: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config_scanner.cs_sources import source_is_materializable, source_is_not_shipped

    _fake_catalog(tmp_path, monkeypatch)
    pr = list_cs_sources(profile_country="PuertoRico", authoring_only=False, include_share_scan=True)
    by_id = {s.embedded_id: s for s in pr}
    assert by_id["CS-Gamestar-PR-03"].authoring is True
    pr06 = by_id["CS-Gamestar-PR-06"]
    assert pr06.authoring is False
    assert source_is_not_shipped(pr06)
    assert "Not shipped in this build" in pr06.note
    assert "CS-Gamestar-PR-06" in pr06.note
    assert not source_is_materializable(pr06)
    assert source_is_materializable(by_id["CS-Gamestar-PR-03"])

    # newest-version scoring must not pick the entry that cannot be opened
    picked = recommend_cs_source(pr, profile_id="puerto_rico_usd")
    assert picked is not None and picked.embedded_id == "CS-Gamestar-PR-03"

    # authoring_only view hides it entirely
    only = list_cs_sources(profile_country="PuertoRico", authoring_only=True)
    assert [s.embedded_id for s in only] == ["CS-Gamestar-PR-03"]

    tt = list_cs_sources(profile_country="Trinidad", authoring_only=True)
    assert [s.embedded_id for s in tt] == ["CS-Gamestar-TT-00"], "staged tree counts as payload"
