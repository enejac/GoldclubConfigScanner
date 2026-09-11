"""Human-readable changelog: one line per merged PR, newest first."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_REPO = "enejac/GoldclubConfigScanner"
CHANGELOG_NAME = "CHANGELOG.md"

HEADER = """# Changelog

What landed on `master`. One line per merged pull request, newest first.
Updated automatically when a PR is merged.

"""

FOOTER = """
## Earlier

Direct commits before GitHub PRs (9 Sep 2026 and earlier):

- OneHand version and Debug/Release in the Live Push header
- Licence push off by default on Debug OneHand
- Silent SMB `test`/`test` for `10.0.0.x` cabinets
- Live Push Load spinner and Restore backup
- Fork Config Scanner from Log Investigator
"""

_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
_LINK_LINE_RE = re.compile(
    r"^- (?P<title>.+?) \(\[#(?P<num>\d+)\]\((?P<url>https?://[^)]+)\)\)\s*$"
)
_PLAIN_LINE_RE = re.compile(r"^- (?P<title>.+?) \(#(?P<num>\d+)\)\s*$")
_SKIP_TITLE = re.compile(
    r"\[skip changelog\]|^\s*changelog\s*:",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ChangelogEntry:
    date: str
    number: int
    title: str
    url: str = ""

    def key(self) -> int:
        return self.number


def changelog_path(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / CHANGELOG_NAME


def normalize_title(title: str) -> str:
    text = " ".join((title or "").split())
    return text.rstrip(".").strip()


def pr_url(number: int, repo: str = DEFAULT_REPO) -> str:
    return f"https://github.com/{repo}/pull/{int(number)}"


def format_entry_line(entry: ChangelogEntry, *, repo: str = DEFAULT_REPO) -> str:
    title = normalize_title(entry.title)
    url = (entry.url or "").strip() or pr_url(entry.number, repo)
    return f"- {title} ([#{entry.number}]({url}))"


def should_skip_title(title: str) -> bool:
    """True when the PR must not get a changelog line."""
    return bool(_SKIP_TITLE.search(title or ""))


def parse_iso_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("missing date")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    stamp = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(stamp).date().isoformat()


def parse_changelog(text: str) -> list[ChangelogEntry]:
    """Read dated ``- Title ([#N](url))`` lines. Footer / earlier is ignored."""
    entries: list[ChangelogEntry] = []
    current_date = ""
    for line in text.splitlines():
        date_hit = _DATE_RE.match(line)
        if date_hit:
            current_date = date_hit.group(1)
            continue
        if line.strip() == "## Earlier":
            break
        hit = _LINK_LINE_RE.match(line) or _PLAIN_LINE_RE.match(line)
        if not hit or not current_date:
            continue
        entries.append(
            ChangelogEntry(
                date=current_date,
                number=int(hit.group("num")),
                title=hit.group("title") or "",
                url=(hit.groupdict().get("url") or ""),
            )
        )
    return entries


def _sort_entries(entries: list[ChangelogEntry]) -> list[ChangelogEntry]:
    return sorted(entries, key=lambda e: (e.date, e.number), reverse=True)


def render_changelog(
    entries: list[ChangelogEntry],
    *,
    repo: str = DEFAULT_REPO,
) -> str:
    seen: dict[int, ChangelogEntry] = {}
    for entry in _sort_entries(entries):
        seen[entry.number] = entry
    ordered = _sort_entries(list(seen.values()))
    chunks = [HEADER]
    last_date = ""
    for entry in ordered:
        if entry.date != last_date:
            if last_date:
                chunks.append("\n")
            chunks.append(f"## {entry.date}\n\n")
            last_date = entry.date
        chunks.append(format_entry_line(entry, repo=repo) + "\n")
    chunks.append(FOOTER)
    return "".join(chunks)


def upsert_entry(
    text: str,
    entry: ChangelogEntry,
    *,
    repo: str = DEFAULT_REPO,
) -> str:
    """Insert or replace the line for this PR number, then re-render."""
    existing = {item.number: item for item in parse_changelog(text)}
    existing[entry.number] = ChangelogEntry(
        date=entry.date,
        number=entry.number,
        title=normalize_title(entry.title),
        url=entry.url or pr_url(entry.number, repo),
    )
    return render_changelog(list(existing.values()), repo=repo)


def entry_from_github(
    *,
    title: str,
    number: int | str,
    merged_at: str,
    url: str = "",
    repo: str = DEFAULT_REPO,
) -> ChangelogEntry:
    num = int(number)
    return ChangelogEntry(
        date=parse_iso_date(merged_at),
        number=num,
        title=normalize_title(title),
        url=(url or "").strip() or pr_url(num, repo),
    )


def entries_from_github_json(payload: str | list[dict], *, repo: str = DEFAULT_REPO) -> list[ChangelogEntry]:
    rows = json.loads(payload) if isinstance(payload, str) else payload
    found: list[ChangelogEntry] = []
    for row in rows:
        title = str(row.get("title") or "")
        if should_skip_title(title):
            continue
        merged = str(row.get("mergedAt") or row.get("merged_at") or "")
        if not merged:
            continue
        found.append(
            entry_from_github(
                title=title,
                number=int(row["number"]),
                merged_at=merged,
                url=str(row.get("url") or row.get("html_url") or ""),
                repo=repo,
            )
        )
    return found


def write_changelog(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
