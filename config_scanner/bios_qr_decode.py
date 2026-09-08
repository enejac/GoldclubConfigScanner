#!/usr/bin/env python3
"""Decode BiOS2 login QR from cabinet screenshot and drive auto-login."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

try:
    import zxingcpp
    from PIL import Image
except ImportError as exc:
    print(f"Missing dependency: {exc}", file=sys.stderr)
    sys.exit(2)


def decode_qr(image_path: Path) -> str:
    img = Image.open(image_path)
    w, h = img.size
    crop = img.crop((0, 0, int(w * 0.45), h))
    codes = zxingcpp.read_barcodes(crop)
    if not codes:
        codes = zxingcpp.read_barcodes(img)
    if not codes:
        raise RuntimeError(f"No QR found in {image_path}")
    return codes[0].text


def extract_login_body(qr_text: str) -> str:
    if qr_text.startswith("mailto:"):
        qs = urllib.parse.urlparse(qr_text).query
        body = urllib.parse.parse_qs(qs).get("body", [""])[0]
        if not body:
            raise RuntimeError("QR mailto has no body")
        return body
    return qr_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode BiOS2 login QR")
    parser.add_argument("image", type=Path, help="PNG screenshot from cabinet")
    parser.add_argument("--emit-ps1", type=Path, help="Write cabinet login helper vars")
    args = parser.parse_args()
    qr = decode_qr(args.image)
    body = extract_login_body(qr)
    print("QR:", qr[:100] + ("..." if len(qr) > 100 else ""))
    print("LOGIN_BODY:", body)
    if args.emit_ps1:
        args.emit_ps1.write_text(
            f"$LoginBody = '{body}'\n",
            encoding="ascii",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
