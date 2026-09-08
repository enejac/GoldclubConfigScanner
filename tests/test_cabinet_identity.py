"""MachineName lookup helpers (no live cabinet)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from network.cabinet_identity import (
    _normalize_cabinet_name,
    read_cabinet_machine_name_from_state,
)


def test_read_machine_name_rejects_non_ipv4() -> None:
    assert read_cabinet_machine_name_from_state("") is None
    assert read_cabinet_machine_name_from_state("localhost") is None
    assert read_cabinet_machine_name_from_state("10.0.0") is None


def test_normalize_cabinet_name() -> None:
    assert _normalize_cabinet_name("grt330106") == "GRT330106"
    assert _normalize_cabinet_name("GST20664.gold-club.local") == "GST20664"
    assert _normalize_cabinet_name("") is None
    assert _normalize_cabinet_name("bad name") is None


def test_read_machine_name_from_conf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    var = tmp_path / "Goldclub" / "var"
    maint = var / "state" / "maintenance"
    maint.mkdir(parents=True)
    (maint / "ProductSerialNumber.conf").write_text(
        "ProductKind: ST\nProductSerialNumber: 22377\nMachineName: GST22377\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "network.cabinet_identity._ensure_smb_for_cabinet_ip", lambda _ip: None
    )
    assert read_cabinet_machine_name_from_state(
        "10.0.0.111", scan_root=str(var)
    ) == "GST22377"


def test_read_machine_name_from_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    var = tmp_path / "var"
    maint = var / "state" / "maintenance"
    maint.mkdir(parents=True)
    (maint / "ProductSerialNumber.json").write_text(
        json.dumps(
            {
                "ProductSerialNumber": "330106",
                "MachineName": "GRT330106",
                "ProductKind": "RT",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "network.cabinet_identity._ensure_smb_for_cabinet_ip", lambda _ip: None
    )
    assert read_cabinet_machine_name_from_state(
        "10.0.0.111", scan_root=str(var)
    ) == "GRT330106"


def test_ensure_smb_called_for_fleet_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _fake(ip: str) -> None:
        seen.append(ip)

    monkeypatch.setattr("network.cabinet_identity._ensure_smb_for_cabinet_ip", _fake)
    monkeypatch.setattr("network.cabinet_identity._serial_paths_for_ip", lambda *_a, **_k: ())
    assert read_cabinet_machine_name_from_state("10.0.0.111") is None
    assert seen == ["10.0.0.111"]
