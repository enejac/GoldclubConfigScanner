#!/usr/bin/env python3
"""Add or rebuild CHANGELOG.md (one line per merged PR).

CI (merge to master):
  python scripts/update_changelog.py --add

Local rebuild from GitHub:
  gh pr list --state merged --limit 100 --json number,title,mergedAt,url \\
    | python scripts/update_changelog.py --rebuild
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_scanner.changelog import (
    DEFAULT_REPO,
    changelog_path,
    entries_from_github_json,
    entry_from_github,
    render_changelog,
    should_skip_title,
    upsert_entry,
    write_changelog,
)


def _repo() -> str:
    return (os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--add",
        action="store_true",
        help="Insert the PR from env (TITLE, NUMBER, MERGED_AT, PR_URL)",
    )
    mode.add_argument(
        "--rebuild",
        action="store_true",
        help="Replace dated sections from JSON on stdin (gh pr list)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="CHANGELOG.md path (default: repo root)",
    )
    args = parser.parse_args(argv)
    path = args.path or changelog_path(ROOT)
    repo = _repo()

    if args.rebuild:
        payload = sys.stdin.read()
        text = render_changelog(entries_from_github_json(payload, repo=repo), repo=repo)
        write_changelog(path, text)
        print(f"rebuilt {path}")
        return 0

    title = os.environ.get("TITLE") or os.environ.get("PR_TITLE") or ""
    if should_skip_title(title):
        print("skip changelog")
        return 0
    number = os.environ.get("NUMBER") or os.environ.get("PR_NUMBER") or ""
    merged_at = os.environ.get("MERGED_AT") or os.environ.get("PR_MERGED_AT") or ""
    url = os.environ.get("PR_URL") or ""
    if not number or not merged_at or not title.strip():
        print("missing TITLE, NUMBER, or MERGED_AT", file=sys.stderr)
        return 2
    entry = entry_from_github(
        title=title,
        number=number,
        merged_at=merged_at,
        url=url,
        repo=repo,
    )
    previous = path.read_text(encoding="utf-8") if path.is_file() else ""
    updated = upsert_entry(previous, entry, repo=repo)
    if updated == previous:
        print("changelog unchanged")
        return 0
    write_changelog(path, updated)
    print(f"logged #{entry.number} {entry.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
