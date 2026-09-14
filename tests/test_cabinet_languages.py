"""Language on 2.0.1+ images: slot\\languages catalog + jurisdiction_config <Languages>."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from config_scanner import slot_setup
from config_scanner.slot_setup import (
    CabinetLanguages,
    InstalledLanguage,
    JurisdictionSettings,
    MgIdentitySettings,
    patch_jurisdiction_config,
    patch_mgconfig_denoms,
    patch_mgconfig_locale,
    read_cabinet_languages,
    read_installed_languages,
    read_mg_identity,
    read_pack_languages,
    set_pack_initial_language,
    validate_language_installed,
)

_CATALOG = """<?xml version='1.0' encoding='UTF-8'?>
<languages>
\t<language id="en">English</language>
\t<language id="es">Spanish</language>
\t<language id="fr">French</language>
\t<language id="nl">Dutch</language>
\t<language id="pl">Polish</language>
</languages>
"""

_JURISDICTION = """<?xml version="1.0" encoding="utf-8"?>
<Jurisdiction xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Tag>PuertoRico</Tag>
  <CultureInformation>
    <CultureName>es-PR</CultureName>
  </CultureInformation>
  <Languages><!--The first language of the list will be the initial language of the pack-->
    <LanguageButtonStateSetting>
      <StateName>Spanish</StateName>
      <TexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_spanish.{ext}</TexturePath>
      <PressedTexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_spanish_pressed.{ext}</PressedTexturePath>
    </LanguageButtonStateSetting>
    <LanguageButtonStateSetting>
      <StateName>English</StateName>
      <TexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_english.{ext}</TexturePath>
      <PressedTexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_english_pressed.{ext}</PressedTexturePath>
    </LanguageButtonStateSetting>
  </Languages>
</Jurisdiction>
"""

_MGCONFIG_NEW = """<?xml version="1.0"?>
<Multigamer>
  <MachineID>GST!!MachineName!!</MachineID>
  <LanguageKey>
    <Key>NumPad7</Key>
  </LanguageKey>
  <MarketSpecific>
    <TargetMarket>PuertoRico</TargetMarket>
  </MarketSpecific>
  <CultureInfoData>
    <CultureName>es-PR</CultureName>
  </CultureInfoData>
</Multigamer>
"""

_MGCONFIG_LEGACY = """<?xml version="1.0"?>
<Multigamer>
  <MachineID>GST!!MachineName!!</MachineID>
  <Language>Polish</Language>
</Multigamer>
"""


def _goldclub(
    tmp_path: Path,
    *,
    ext: str = "dds",
    catalog: bool = True,
    files: tuple[str, ...] = ("en", "es", "fr", "nl", "pl", "cs", "sl", "zh_Hans"),
    jurisdiction: bool = True,
    mgconfig: str = _MGCONFIG_NEW,
) -> Path:
    root = tmp_path / "Goldclub"
    themes = root / "slot" / "themes"
    themes.mkdir(parents=True)
    (themes / "mgconfig.xml").write_text(mgconfig, encoding="utf-8")
    if jurisdiction:
        (themes / "jurisdiction_config.xml").write_text(
            _JURISDICTION.replace("{ext}", ext), encoding="utf-8"
        )
    langs = root / "slot" / "languages"
    langs.mkdir()
    if catalog:
        (langs / "languages.xml").write_text(_CATALOG, encoding="utf-8")
    for code in files:
        (langs / f"{code}.xml").write_text("<strings/>", encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def test_installed_languages_are_catalog_entries_with_translation_files(tmp_path: Path) -> None:
    root = _goldclub(tmp_path, files=("en", "es", "nl", "cs"))
    got = read_installed_languages(root)
    # fr / pl are in the catalog but have no file; cs has a file but no catalog row.
    assert got == (
        InstalledLanguage("en", "English"),
        InstalledLanguage("es", "Spanish"),
        InstalledLanguage("nl", "Dutch"),
    )


def test_installed_languages_fall_back_to_files_without_catalog(tmp_path: Path) -> None:
    root = _goldclub(tmp_path, catalog=False, files=("es", "en"))
    got = read_installed_languages(root)
    assert got == (InstalledLanguage("en", "en"), InstalledLanguage("es", "es"))


def test_installed_languages_empty_without_folder(tmp_path: Path) -> None:
    root = tmp_path / "Goldclub"
    (root / "slot" / "themes").mkdir(parents=True)
    assert read_installed_languages(root) == ()


def test_pack_languages_keep_file_order(tmp_path: Path) -> None:
    root = _goldclub(tmp_path)
    assert read_pack_languages(root) == ("Spanish", "English")


def test_cabinet_languages_initial_is_first_pack_entry(tmp_path: Path) -> None:
    root = _goldclub(tmp_path)
    langs = read_cabinet_languages(root)
    assert langs.initial == "Spanish"
    assert langs.mgconfig == ""
    assert langs.names == ("English", "Spanish", "French", "Dutch", "Polish")
    assert langs.code_for("spanish") == "es"
    assert langs.is_installed("NL") and not langs.is_installed("Portuguese")


def test_recipe_language_comes_from_pack_when_mgconfig_has_none(tmp_path: Path) -> None:
    """The .76 / .111 case: mgconfig has only <LanguageKey>, so the field was blank."""
    root = _goldclub(tmp_path)
    assert read_mg_identity(root).language == "Spanish"


def test_recipe_language_prefers_legacy_mgconfig_element(tmp_path: Path) -> None:
    root = _goldclub(tmp_path, mgconfig=_MGCONFIG_LEGACY)
    assert read_mg_identity(root).language == "Polish"
    assert read_cabinet_languages(root).mgconfig == "Polish"


def test_recipe_language_blank_when_neither_source_exists(tmp_path: Path) -> None:
    root = _goldclub(tmp_path, jurisdiction=False)
    assert read_mg_identity(root).language == ""


def test_each_root_has_its_own_languages(tmp_path: Path) -> None:
    """Two EGMs with different slot\\languages must not share a result."""
    a = _goldclub(tmp_path / "a", files=("en", "es"))
    b = _goldclub(tmp_path / "b", files=("en", "pl", "nl"))
    la = read_cabinet_languages(a)
    lb = read_cabinet_languages(b)
    assert la.names == ("English", "Spanish")
    assert lb.names == ("English", "Dutch", "Polish")
    assert slot_setup.installed_languages_cached(a) == la.installed
    assert slot_setup.installed_languages_cached(b) == lb.installed


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def test_validate_rejects_language_without_translation(tmp_path: Path) -> None:
    root = _goldclub(tmp_path)
    assert validate_language_installed("Spanish", root) == []
    assert validate_language_installed("es", root) == []
    errors = validate_language_installed("Portuguese", root)
    assert len(errors) == 1
    assert "Portuguese" in errors[0] and "Dutch (nl)" in errors[0]


def test_validate_uses_memo_not_share(tmp_path: Path, monkeypatch) -> None:
    root = _goldclub(tmp_path)
    read_installed_languages(root)  # fills the memo like the load worker does

    def _boom(_root):
        raise AssertionError("must not list slot\\languages on the GUI thread")

    monkeypatch.setattr(slot_setup, "read_installed_languages", _boom)
    assert validate_language_installed("Dutch", root) == []
    assert validate_language_installed("Portuguese", root)


def test_validate_skips_images_without_languages_folder(tmp_path: Path) -> None:
    root = tmp_path / "Goldclub"
    (root / "slot" / "themes").mkdir(parents=True)
    assert validate_language_installed("Anything", root) == []


def test_validate_explicit_installed_list() -> None:
    have = (InstalledLanguage("en", "English"),)
    assert validate_language_installed("English", Path("."), installed=have) == []
    assert validate_language_installed("Spanish", Path("."), installed=have)


def test_live_push_recipe_validation_includes_language(tmp_path: Path) -> None:
    from config_scanner.denom_compat import validate_live_push_recipe
    from config_scanner.slot_setup import load_recipe_from_goldclub

    root = _goldclub(tmp_path)
    live = load_recipe_from_goldclub(root, label="live")
    proposed = load_recipe_from_goldclub(root, label="form")
    proposed.mg_identity.language = "Portuguese"
    errors = validate_live_push_recipe(live, proposed, root)
    assert any("Portuguese" in e for e in errors)
    proposed.mg_identity.language = "English"
    assert not any("not installed" in e for e in validate_live_push_recipe(live, proposed, root))


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def _state_names(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        (s.find("StateName").text or "")
        for s in root.iter("LanguageButtonStateSetting")
    ]


def test_set_pack_initial_language_reorders_existing_entry(tmp_path: Path) -> None:
    root = _goldclub(tmp_path)
    path = root / "slot" / "themes" / "jurisdiction_config.xml"
    patch_jurisdiction_config(path, path, JurisdictionSettings(), language="English")
    assert _state_names(path) == ["English", "Spanish"]
    assert read_pack_languages(root) == ("English", "Spanish")
    # Already first: no-op, order stable.
    patch_jurisdiction_config(path, path, JurisdictionSettings(), language="english")
    assert _state_names(path) == ["English", "Spanish"]


@pytest.mark.parametrize("ext", ["dds", "png"])
def test_set_pack_initial_language_clones_entry_with_matching_textures(
    tmp_path: Path, ext: str
) -> None:
    """New entry copies the sibling's texture convention (.dds on .76, .png on .111)."""
    root = _goldclub(tmp_path, ext=ext)
    path = root / "slot" / "themes" / "jurisdiction_config.xml"
    patch_jurisdiction_config(path, path, JurisdictionSettings(), language="Dutch")
    assert _state_names(path) == ["Dutch", "Spanish", "English"]
    tree = ET.parse(path).getroot()
    first = next(tree.iter("LanguageButtonStateSetting"))
    assert first.find("TexturePath").text.endswith(f"languageBtn\\flag_dutch.{ext}")
    assert first.find("PressedTexturePath").text.endswith(
        f"languageBtn\\flag_dutch_pressed.{ext}"
    )
    # Spanish/English entries untouched.
    others = list(tree.iter("LanguageButtonStateSetting"))[1:]
    assert others[0].find("TexturePath").text.endswith(f"flag_spanish.{ext}")


def test_set_pack_initial_language_without_languages_block_is_noop() -> None:
    root = ET.fromstring("<Jurisdiction><Tag>TT</Tag></Jurisdiction>")
    assert set_pack_initial_language(root, "English") is False
    assert root.find("Languages") is None


def test_mgconfig_language_not_created_when_pack_owns_it(tmp_path: Path) -> None:
    root = _goldclub(tmp_path)
    mg = root / "slot" / "themes" / "mgconfig.xml"
    patch_mgconfig_locale(mg, mg, JurisdictionSettings(), language="English", language_in_pack=True)
    assert ET.parse(mg).getroot().find("Language") is None
    patch_mgconfig_denoms(
        mg, mg, [], [], identity=MgIdentitySettings(language="English"), language_in_pack=True
    )
    assert ET.parse(mg).getroot().find("Language") is None
    # Legacy behaviour when the pack has no <Languages>.
    patch_mgconfig_locale(mg, mg, JurisdictionSettings(), language="English")
    assert ET.parse(mg).getroot().find("Language").text == "English"


def test_mgconfig_language_still_refreshed_when_element_exists(tmp_path: Path) -> None:
    root = _goldclub(tmp_path, mgconfig=_MGCONFIG_LEGACY)
    mg = root / "slot" / "themes" / "mgconfig.xml"
    patch_mgconfig_locale(mg, mg, JurisdictionSettings(), language="English", language_in_pack=True)
    assert ET.parse(mg).getroot().find("Language").text == "English"


def test_apply_config_pack_writes_language_into_pack(tmp_path: Path) -> None:
    """Changing Language on a 2.0.1+ tree reorders <Languages>, not mgconfig."""
    from config_scanner.slot_setup import build_config_pack, load_recipe_from_goldclub

    root = _goldclub(tmp_path)
    recipe = load_recipe_from_goldclub(root, label="form")
    assert recipe.mg_identity.language == "Spanish"
    recipe.mg_identity.language = "English"
    pack_dir = tmp_path / "pack"
    build_config_pack(
        recipe, root, pack_dir, sections=frozenset({"mgconfig", "jurisdiction"})
    )
    staged_j = pack_dir / "slot" / "themes" / "jurisdiction_config.xml"
    assert staged_j.is_file(), "language change alone must stage jurisdiction_config"
    assert _state_names(staged_j) == ["English", "Spanish"]
    staged_mg = pack_dir / "slot" / "themes" / "mgconfig.xml"
    if staged_mg.is_file():
        assert ET.parse(staged_mg).getroot().find("Language") is None


# --------------------------------------------------------------------------
# loader + GUI wiring
# --------------------------------------------------------------------------


def test_load_live_cabinet_carries_languages(tmp_path: Path) -> None:
    from config_scanner.live_push import load_live_cabinet

    root = _goldclub(tmp_path)
    outcome = load_live_cabinet(str(root))
    assert outcome.error == ""
    assert isinstance(outcome.languages, CabinetLanguages)
    assert outcome.languages.initial == "Spanish"
    assert outcome.recipe is not None and outcome.recipe.mg_identity.language == "Spanish"


def test_language_field_maps_to_jurisdiction_config() -> None:
    from config_scanner.live_push import LIVE_FIELD_CONFIG_RELS, _LABEL_SECTIONS

    assert "jurisdiction" in _LABEL_SECTIONS["Language"]
    assert LIVE_FIELD_CONFIG_RELS["Language"][0].endswith("jurisdiction_config.xml")
