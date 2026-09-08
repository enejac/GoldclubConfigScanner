"""Limit Setup (mgconfig LimitSetup) read/patch tests."""

from __future__ import annotations

from pathlib import Path

from config_scanner.slot_setup import (
    LimitSetupSettings,
    limit_setup_changed,
    patch_limit_setup,
    read_limit_setup,
)


def _mini_mgconfig(limit_inner: str = "") -> str:
    body = limit_inner or ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Multigamer>
  <LimitSetup>{body}</LimitSetup>
</Multigamer>"""


def test_read_limit_setup_defaults_to_zero(tmp_path: Path) -> None:
    mg = tmp_path / "slot" / "themes" / "mgconfig.xml"
    mg.parent.mkdir(parents=True)
    mg.write_text(_mini_mgconfig(), encoding="utf-8")
    ls = read_limit_setup(tmp_path)
    assert ls.credit_limit == 0
    assert ls.handpay_limit == 0
    assert ls.editable_for("credit_limit")


def test_read_limit_setup_values_and_host_lock(tmp_path: Path) -> None:
    mg = tmp_path / "slot" / "themes" / "mgconfig.xml"
    mg.parent.mkdir(parents=True)
    mg.write_text(
        _mini_mgconfig(
            '<CreditLimit hostLocked="true">5000</CreditLimit>'
            "<JackpotLimit>10000</JackpotLimit>"
            "<MaxHopperPayout>20</MaxHopperPayout>"
        ),
        encoding="utf-8",
    )
    ls = read_limit_setup(tmp_path)
    assert ls.credit_limit == 5000
    assert ls.credit_limit_host_locked is True
    assert not ls.editable_for("credit_limit")
    assert ls.jackpot_limit == 10000
    assert ls.editable_for("jackpot_limit")
    assert ls.max_hopper_payout == 20


def test_patch_limit_setup_skips_host_locked(tmp_path: Path) -> None:
    src = tmp_path / "slot" / "themes" / "mgconfig.xml"
    src.parent.mkdir(parents=True)
    src.write_text(
        _mini_mgconfig('<CreditLimit hostLocked="true">5000</CreditLimit>'),
        encoding="utf-8",
    )
    dest = tmp_path / "out.xml"
    settings = LimitSetupSettings(credit_limit=9999, jackpot_limit=100)
    patch_limit_setup(src, dest, settings)
    text = dest.read_text(encoding="utf-8")
    assert "5000" in text
    assert "9999" not in text
    assert "JackpotLimit>100" in text.replace(" ", "")


def test_limit_setup_changed_detects_editable_diff() -> None:
    live = LimitSetupSettings(credit_limit=0, jackpot_limit=5000)
    same = LimitSetupSettings(credit_limit=0, jackpot_limit=5000)
    changed = LimitSetupSettings(credit_limit=0, jackpot_limit=6000)
    assert not limit_setup_changed(live, same)
    assert limit_setup_changed(live, changed)
