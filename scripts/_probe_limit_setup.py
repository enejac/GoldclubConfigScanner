"""One-off: inspect LimitSetup XML on a cabinet share."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(r"\\10.0.0.111\slot")


def local(tag: str) -> str:
    return tag.split("}")[-1]


def main() -> None:
    for p in ROOT.rglob("mgconfig.xml"):
        try:
            if p.stat().st_size > 3_000_000:
                continue
            tree = ET.parse(p)
        except (OSError, ET.ParseError):
            continue
        for el in tree.getroot().iter():
            if local(el.tag) != "LimitSetup":
                continue
            if list(el) or (el.text and el.text.strip()):
                print("===", p.relative_to(ROOT), "===")
                print(ET.tostring(el, encoding="unicode"))


if __name__ == "__main__":
    main()
