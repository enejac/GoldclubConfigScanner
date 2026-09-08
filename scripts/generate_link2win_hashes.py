"""Regenerate bundled Link2Win SHA-256 manifest for frozen ConfigScanner.exe."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_scanner.cs_catalog import discover_leaves
from config_scanner.denom_compat import (
    _LINK2WIN_CONFIG2_REL,
    _LINK2WIN_REL,
    _file_sha256,
    denom_from_leaf,
)
from config_scanner.embedded_updates import load_catalog

OUT = ROOT / "config_scanner" / "assets" / "link2win_hashes.json"


def main() -> int:
    entries: list[dict[str, object]] = []
    for entry in load_catalog():
        tool = entry.staged_tool_path
        if tool is None:
            continue
        for leaf in discover_leaves(tool):
            denom = denom_from_leaf(leaf)
            if denom is None:
                continue
            for rel in (_LINK2WIN_REL, _LINK2WIN_CONFIG2_REL):
                src = leaf.path / rel
                if not src.is_file():
                    continue
                entries.append(
                    {
                        "sha256": _file_sha256(src),
                        "denom_cents": int(denom),
                        "relative_path": rel.replace("\\", "/"),
                        "leaf": "/".join(leaf.rel_parts),
                        "update_id": entry.id,
                    }
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"entries": entries}, indent=2) + "\n", encoding="utf-8")
    print(f"link2win_hashes: {len(entries)} entries -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
