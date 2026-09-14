"""Country-flag textures: names lie, pixels do not."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from config_scanner.language_flags import (
    COUNTRY_FLAG_LABEL,
    LanguageFlagSetting,
    assignment_for_asset,
    decode_flag_preview,
    discover_flag_assets,
    flags_snapshot,
    read_language_flags,
    write_uncompressed_bgra_dds,
)
from config_scanner.live_push import (
    live_field_matches,
    live_push_changed_sections,
    recipe_snapshot_rows,
)
from config_scanner.setting_probe import read_setting_value
from config_scanner.setting_spec import specs_by_id
from config_scanner.slot_setup import (
    JurisdictionSettings,
    SlotSetupRecipe,
    build_config_pack,
    load_recipe_from_goldclub,
    patch_jurisdiction_config,
)
from tests.test_slot_setup import _fake_goldclub


def _png(path: Path, width: int, height: int, rgba: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _solid(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    r, g, b = rgb
    pixel = bytes((r, g, b, 255))
    return pixel * (width * height)


def _flag_tree(tmp_path: Path) -> Path:
    gold = _fake_goldclub(tmp_path)
    btn = (
        gold
        / "slot"
        / "themes"
        / "data"
        / "GameStarColors"
        / "1080p"
        / "Red"
        / "console"
        / "languageBtn"
    )
    # Misleading names: spanish file is PR-blue, english is US-red.
    _png(btn / "flag_spanish.png", 8, 6, _solid(8, 6, (0, 56, 168)))
    _png(btn / "flag_spanish_pressed.png", 8, 6, _solid(8, 6, (0, 40, 120)))
    _png(btn / "flag_english.png", 8, 6, _solid(8, 6, (178, 34, 52)))
    _png(btn / "flag_english_pressed.png", 8, 6, _solid(8, 6, (140, 20, 40)))
    jur = gold / "slot" / "themes" / "jurisdiction_config.xml"
    text = jur.read_text(encoding="utf-8")
    text = text.replace(
        "</JurisdictionSettings>",
        """  <Languages>
    <LanguageButtonStateSetting>
      <StateName>Spanish</StateName>
      <TexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_spanish.png</TexturePath>
      <PressedTexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_spanish_pressed.png</PressedTexturePath>
    </LanguageButtonStateSetting>
    <LanguageButtonStateSetting>
      <StateName>English</StateName>
      <TexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_english.png</TexturePath>
      <PressedTexturePath>data\\GameStarColors\\1080p\\Red\\console\\languageBtn\\flag_english_pressed.png</PressedTexturePath>
    </LanguageButtonStateSetting>
  </Languages>
</JurisdictionSettings>
""",
    )
    jur.write_text(text, encoding="utf-8")
    return gold


def test_read_and_snapshot_uses_basename(tmp_path: Path) -> None:
    gold = _flag_tree(tmp_path)
    flags = read_language_flags(gold)
    assert [f.state_name for f in flags] == ["Spanish", "English"]
    assert flags[0].texture_name() == "flag_spanish.png"
    assert flags_snapshot(flags) == "Spanish=flag_spanish.png; English=flag_english.png"


def test_discover_lists_unused_and_wired(tmp_path: Path) -> None:
    gold = _flag_tree(tmp_path)
    assets = discover_flag_assets(gold, wired=read_language_flags(gold))
    names = {a.name for a in assets}
    assert names == {"flag_spanish.png", "flag_english.png"}
    assert all(a.pressed_absolute_path and a.pressed_absolute_path.is_file() for a in assets)


def test_png_preview_pixels_are_not_the_filename(tmp_path: Path) -> None:
    gold = _flag_tree(tmp_path)
    spanish = (
        gold
        / "slot"
        / "themes"
        / "data"
        / "GameStarColors"
        / "1080p"
        / "Red"
        / "console"
        / "languageBtn"
        / "flag_spanish.png"
    )
    preview = decode_flag_preview(spanish)
    assert preview is not None
    assert preview.rgba[0:3] == bytes((0, 56, 168))


def test_uncompressed_dds_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "flag_spanish.dds"
    bgra = bytes((168, 56, 0, 255)) * 16  # BGRA of the PR-blue PNG
    write_uncompressed_bgra_dds(path, 4, 4, bgra)
    preview = decode_flag_preview(path)
    assert preview is not None
    assert preview.width == 4
    assert preview.rgba[0:3] == bytes((0, 56, 168))


def test_probe_and_apply_retarget_texture(tmp_path: Path) -> None:
    gold = _flag_tree(tmp_path)
    spec = specs_by_id()["locale.jur_language_flags"]
    present, value, _note = read_setting_value(gold, spec)
    assert present is True
    assert value == ["Spanish=flag_spanish.png", "English=flag_english.png"]

    live = load_recipe_from_goldclub(gold, label="live")
    assert flags_snapshot(live.jurisdiction.language_flags).startswith("Spanish=")
    english = next(
        a
        for a in discover_flag_assets(gold, wired=live.jurisdiction.language_flags)
        if a.name == "flag_english.png"
    )
    swapped = [
        assignment_for_asset(live.jurisdiction.language_flags[0], english),
        live.jurisdiction.language_flags[1],
    ]
    dest = gold / "slot" / "themes" / "jurisdiction_config.xml"
    settings = JurisdictionSettings(language_flags=swapped)
    patch_jurisdiction_config(dest, dest, settings)
    after = read_language_flags(gold)
    assert after[0].state_name == "Spanish"
    assert after[0].texture_name() == "flag_english.png"
    assert after[0].pressed_texture_path.endswith("flag_english_pressed.png")


def test_apply_flags_after_language_reorder_keeps_order(tmp_path: Path) -> None:
    gold = _flag_tree(tmp_path)
    dest = gold / "slot" / "themes" / "jurisdiction_config.xml"
    live = load_recipe_from_goldclub(gold, label="live")
    english = next(
        a
        for a in discover_flag_assets(gold, wired=live.jurisdiction.language_flags)
        if a.name == "flag_english.png"
    )
    swapped = [
        assignment_for_asset(live.jurisdiction.language_flags[0], english),
        live.jurisdiction.language_flags[1],
    ]
    patch_jurisdiction_config(
        dest,
        dest,
        JurisdictionSettings(language_flags=swapped),
        language="English",
    )
    after = read_language_flags(gold)
    assert [f.state_name for f in after] == ["English", "Spanish"]
    spanish = next(f for f in after if f.state_name == "Spanish")
    assert spanish.texture_name() == "flag_english.png"


def test_live_push_country_flag_is_jurisdiction_delta() -> None:
    live = SlotSetupRecipe()
    form = SlotSetupRecipe.from_dict(live.to_dict())
    form.jurisdiction.language_flags = [
        LanguageFlagSetting("Spanish", r"data\x\flag_spanish.dds"),
    ]
    rows = dict(recipe_snapshot_rows(form))
    assert rows[COUNTRY_FLAG_LABEL] == "Spanish=flag_spanish.dds"
    assert live_field_matches(live, form)[COUNTRY_FLAG_LABEL] is False
    assert live_push_changed_sections(live, form) == frozenset({"jurisdiction"})


def test_build_pack_writes_languages(tmp_path: Path) -> None:
    gold = _flag_tree(tmp_path)
    live = load_recipe_from_goldclub(gold, label="live")
    assets = discover_flag_assets(gold, wired=live.jurisdiction.language_flags)
    english = next(a for a in assets if a.name == "flag_english.png")
    live.jurisdiction.language_flags = [
        assignment_for_asset(live.jurisdiction.language_flags[0], english),
        live.jurisdiction.language_flags[1],
    ]
    pack = tmp_path / "pack"
    built = build_config_pack(
        live, gold, pack, sections=frozenset({"jurisdiction"})
    )
    assert "slot/themes/jurisdiction_config.xml" in built.files
    written = read_language_flags(pack)
    assert written[0].state_name == "Spanish"
    assert written[0].texture_name() == "flag_english.png"


def test_country_flag_editor_shows_thumbnail(tmp_path: Path) -> None:
    import pytest

    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from gui.country_flag_row import CountryFlagsEditor

    gold = _flag_tree(tmp_path)
    app = QApplication.instance() or QApplication([])
    editor = CountryFlagsEditor()
    editor.load(gold, read_language_flags(gold))
    app.processEvents()
    assert len(editor._combos) == 2
    spanish = editor._combos[0]
    assert spanish.count() == 2
    assert spanish.currentText() == "flag_spanish.png"
    assert not spanish.itemIcon(0).isNull()
    assert spanish.hasFrame() is False
    assert spanish.iconSize().height() <= 20
    assert "border: 0px" in spanish.styleSheet()
    english_idx = next(
        i for i in range(spanish.count()) if spanish.itemText(i) == "flag_english.png"
    )
    spanish.setCurrentIndex(english_idx)
    flags = editor.current_flags()
    assert flags[0].state_name == "Spanish"
    assert flags[0].texture_name() == "flag_english.png"
    assert flags[1].state_name == "English"
