"""Changelog formatting and merge upsert."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from config_scanner.changelog import (
    ChangelogEntry,
    entries_from_github_json,
    entry_from_github,
    format_entry_line,
    parse_changelog,
    render_changelog,
    should_skip_title,
    upsert_entry,
)

_ROOT = Path(__file__).resolve().parents[1]


def _changelog_main(argv: list[str]) -> int:
    spec = importlib.util.spec_from_file_location(
        "update_changelog",
        _ROOT / "scripts" / "update_changelog.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(argv)


def test_format_entry_line_is_one_short_link() -> None:
    line = format_entry_line(
        ChangelogEntry(
            date="2026-09-10",
            number=17,
            title="Write magic-wheel knobs to jurisdiction_config.",
        )
    )
    assert line == (
        "- Write magic-wheel knobs to jurisdiction_config "
        "([#17](https://github.com/enejac/GoldclubConfigScanner/pull/17))"
    )


def test_should_skip_changelog_noise() -> None:
    assert should_skip_title("[skip changelog] tweak typo")
    assert should_skip_title("changelog: #17 Write magic-wheel knobs")
    assert not should_skip_title("Fix OneHand Debug detection in Live Push header")


def test_upsert_is_idempotent_and_newest_first() -> None:
    first = upsert_entry(
        "",
        ChangelogEntry("2026-09-10", 16, "Start Release OneHand via game-start"),
    )
    again = upsert_entry(
        first,
        ChangelogEntry("2026-09-10", 16, "Start Release OneHand via game-start"),
    )
    assert again == first
    two = upsert_entry(
        first,
        ChangelogEntry("2026-09-10", 17, "Write magic-wheel knobs"),
    )
    assert two.index("#17") < two.index("#16")
    assert two.count("#16") == 1
    assert two.count("#17") == 1


def test_parse_round_trip() -> None:
    text = render_changelog(
        [
            ChangelogEntry("2026-09-09", 2, "Auto SMB login for lab cabinets"),
            ChangelogEntry("2026-09-10", 17, "Write magic-wheel knobs"),
        ]
    )
    parsed = parse_changelog(text)
    assert [e.number for e in parsed] == [17, 2]
    assert "Earlier" in text
    rebuilt = render_changelog(parsed)
    assert rebuilt == text


def test_entries_from_github_json_skips_unmerged() -> None:
    rows = [
        {
            "number": 17,
            "title": "Write magic-wheel knobs",
            "mergedAt": "2026-09-10T11:15:32Z",
            "url": "https://github.com/enejac/GoldclubConfigScanner/pull/17",
        },
        {"number": 99, "title": "Open draft", "mergedAt": ""},
        {"number": 3, "title": "[skip changelog] n/a", "mergedAt": "2026-09-09T12:00:00Z"},
    ]
    found = entries_from_github_json(rows)
    assert [e.number for e in found] == [17]
    assert found[0].date == "2026-09-10"


def test_cli_add_and_rebuild(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "CHANGELOG.md"
    monkeypatch.setenv("TITLE", "Allow Live Push on any 10.0.0.x cabinet")
    monkeypatch.setenv("NUMBER", "8")
    monkeypatch.setenv("MERGED_AT", "2026-09-10T07:49:13Z")
    monkeypatch.setenv(
        "PR_URL", "https://github.com/enejac/GoldclubConfigScanner/pull/8"
    )
    assert _changelog_main(["--add", "--path", str(dest)]) == 0
    text = dest.read_text(encoding="utf-8")
    assert "#8" in text
    assert "10.0.0.x" in text
    assert _changelog_main(["--add", "--path", str(dest)]) == 0
    assert dest.read_text(encoding="utf-8").count("#8") == 1

    monkeypatch.setenv("TITLE", "[skip changelog] ignore me")
    monkeypatch.setenv("NUMBER", "50")
    monkeypatch.setenv("MERGED_AT", "2026-09-10T12:00:00Z")
    assert _changelog_main(["--add", "--path", str(dest)]) == 0
    assert "#50" not in dest.read_text(encoding="utf-8")


def test_repo_changelog_lists_merged_prs() -> None:
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    numbers = {item.number for item in parse_changelog(text)}
    assert {17, 16, 14, 2, 1} <= numbers
    assert text.index("[#17]") < text.index("[#1]")


def test_entry_from_github_accepts_date_only() -> None:
    entry = entry_from_github(title="Ship exe", number="13", merged_at="2026-09-10")
    assert entry.date == "2026-09-10"
    assert entry.number == 13
