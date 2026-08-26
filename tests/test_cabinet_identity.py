"""MachineName lookup helpers (no live cabinet)."""

from __future__ import annotations

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
