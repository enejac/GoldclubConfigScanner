"""Theme math scan/compare — SHA1 only, no decrypt, no hardcoded game paths."""

from __future__ import annotations

from pathlib import Path

from config_scanner.report import file_diff_header_label
from config_scanner.scanner import FileEntry, Manifest, collect_scan_files
from config_scanner.theme_math import (
    is_theme_math_filename,
    is_theme_math_rel,
    iter_theme_math_files,
    theme_math_compare_note,
)
from config_scanner.xml_diff import FileDiff, compare_manifests, file_content_diff


def test_filename_patterns_do_not_name_a_game() -> None:
    assert is_theme_math_filename("AnythingMath.json")
    assert is_theme_math_filename("AnythingBonusMath_Config2.json")
    assert is_theme_math_filename("ProgressiveSetup.xml")
    assert not is_theme_math_filename("MathSettings.xml")
    assert not is_theme_math_filename("game.xml")
    src = Path(__file__).resolve().parents[1] / "config_scanner" / "theme_math.py"
    text = src.read_text(encoding="utf-8")
    assert "Link2WinFeature" not in text
    assert "Tutankhamen" not in text


def test_rel_path_accepts_any_theme_folder() -> None:
    assert is_theme_math_rel("slot/themes/RenamedTitle_X/RenamedTitle_XMath.json")
    assert is_theme_math_rel(r"themes\OtherBonus\OtherBonusMath_Config2.json")
    assert is_theme_math_rel("slot/themes/Foo/ProgressiveSetup.xml")
    assert not is_theme_math_rel("slot/themes/RenamedTitle_X/MathSettings.xml")
    assert not is_theme_math_rel("slot/themes/data/fooMath.json")
    assert not is_theme_math_rel("Licenses/math.json")


def test_iter_finds_renamed_game_and_skips_media(tmp_path: Path) -> None:
    themes = tmp_path / "slot" / "themes"
    game = themes / "FreshName_99"
    game.mkdir(parents=True)
    (game / "FreshName_99Math.json").write_bytes(b"\x00math")
    (game / "videos" / "clip.mp4").parent.mkdir()
    (game / "videos" / "clipMath.json").write_bytes(b"skip-me")
    (themes / "data" / "noiseMath.json").parent.mkdir(parents=True)
    (themes / "data" / "noiseMath.json").write_bytes(b"skip-data")
    found = {p.relative_to(tmp_path).as_posix() for p in iter_theme_math_files(tmp_path)}
    assert "slot/themes/FreshName_99/FreshName_99Math.json" in found
    assert not any("videos" in p or "/data/" in p for p in found)


def test_collect_scan_includes_math_without_game_name_globs(tmp_path: Path) -> None:
    from config_scanner.profiles import get_profile

    profile = get_profile("slot_lab_90")
    game = tmp_path / "slot" / "themes" / "BrandNewTitle"
    game.mkdir(parents=True)
    payload = b"\xffencrypted"
    (game / "BrandNewTitleMath.json").write_bytes(payload)
    files = collect_scan_files(
        tmp_path,
        profile.scan_roots,
        profile.include_patterns,
        extra_file_globs=profile.extra_file_globs,
    )
    rels = {path.relative_to(tmp_path).as_posix() for path in files}
    assert "slot/themes/BrandNewTitle/BrandNewTitleMath.json" in rels


def test_compare_math_is_sha1_only_not_line_diff(tmp_path: Path) -> None:
    rel = "slot/themes/BrandNewTitle/BrandNewTitleMath.json"
    old = tmp_path / "old" / rel
    new = tmp_path / "new" / rel
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_bytes(b"\x00\x01cipher-a")
    new.write_bytes(b"\x00\x02cipher-b")
    assert file_content_diff(rel, old, new) == []

    baseline = Manifest(
        scanned_at="t0",
        file_count=1,
        elapsed_seconds=0.1,
        files=[FileEntry(rel, "AAAA", 10, "t")],
    )
    target = Manifest(
        scanned_at="t1",
        file_count=1,
        elapsed_seconds=0.1,
        files=[FileEntry(rel, "BBBB", 12, "t")],
    )
    diffs = compare_manifests(
        baseline,
        target,
        baseline_content_root=tmp_path / "old",
        target_content_root=tmp_path / "new",
    )
    assert len(diffs) == 1
    item = diffs[0]
    assert item.status == "modified"
    assert item.content_diff == []
    assert item.baseline_sha1 == "AAAA"
    assert item.target_sha1 == "BBBB"
    header = file_diff_header_label(rel, "modified")
    assert "SHA1 only" in header
    note = theme_math_compare_note(item)
    assert "AAAA" in note and "BBBB" in note
    assert "not decrypted" in note.casefold()
