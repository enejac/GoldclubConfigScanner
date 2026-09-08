"""Tests for BiOS QR mailto decode."""
from __future__ import annotations

import urllib.parse

from config_scanner.bios_qr_decode import extract_login_body


def test_extract_login_body_from_mailto():
    qr = (
        "mailto:slot.login@winsysgroup.com?subject=BiOS%20Login"
        "&body=AB4cOZzI2%2FKCc%2BDVFW%2FvQzyX3fLUkgKCmnId4ylfHdDeO%2FPSC1BrszAsJqHQiVQnGflitcelI2Bv71DRbpoPL6pos9Xqty5BTPFE5vbscsiiV5899DFUCvOM1uC%2BJZVEiYUJFAdypm4ohxpWDR1i7jqPs6toCQWh4u55jRFgdWc%3D"
    )
    body = extract_login_body(qr)
    assert body.startswith("AB4cOZzI2/")
    assert "winsys" not in body.lower()
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(qr).query)
    assert body == qs["body"][0]
