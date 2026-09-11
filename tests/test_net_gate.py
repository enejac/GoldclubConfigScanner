"""UNC reachability gate: no share I/O on the GUI thread when the host is down."""

from __future__ import annotations

from pathlib import Path

import pytest

from config_scanner import net_gate


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    net_gate.clear_reachability_cache()
    yield
    net_gate.clear_reachability_cache()


def test_unc_host_parses_both_slash_styles() -> None:
    assert net_gate.unc_host(r"\\10.0.0.249\WinSystems_SLOT\_B2U") == "10.0.0.249"
    assert net_gate.unc_host("//10.0.0.91/usb/_B2U") == "10.0.0.91"
    assert net_gate.unc_host(Path("//10.0.0.249/WinSystems_SLOT")) == "10.0.0.249"
    assert net_gate.unc_host(r"C:\Goldclub") is None
    assert net_gate.unc_host("/tmp/x") is None
    assert net_gate.unc_host("") is None
    assert net_gate.unc_host(None) is None


def test_host_reachable_probes_once_then_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_probe(host: str, timeout_sec: float) -> bool:
        calls.append(host)
        return False

    monkeypatch.setattr(net_gate, "_probe", fake_probe)
    assert net_gate.host_reachable("10.0.0.249") is False
    assert net_gate.host_reachable("10.0.0.249") is False
    assert net_gate.host_reachable("10.0.0.249") is False
    assert calls == ["10.0.0.249"]
    assert net_gate.unreachable_hosts() == ["10.0.0.249"]
    note = net_gate.offline_note()
    assert "10.0.0.249" in note and "not reachable" in note

    net_gate.clear_reachability_cache()
    assert net_gate.host_reachable("10.0.0.249") is False
    assert calls == ["10.0.0.249", "10.0.0.249"]


def test_remote_path_available_local_paths_never_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(host: str, timeout_sec: float) -> bool:
        raise AssertionError(f"probed {host} for a local path")

    monkeypatch.setattr(net_gate, "_probe", boom)
    assert net_gate.remote_path_available(r"C:\Goldclub") is True
    assert net_gate.remote_path_available(Path("/tmp/anything")) is True
    assert net_gate.remote_path_available("") is True


def test_remote_path_available_unc_uses_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net_gate, "_probe", lambda host, timeout_sec: host == "10.0.0.90")
    assert net_gate.remote_path_available(r"\\10.0.0.90\c$\Goldclub") is True
    assert net_gate.remote_path_available("//10.0.0.249/WinSystems_SLOT") is False
    assert net_gate.offline_note() == "Lab share \\\\10.0.0.249 not reachable (SMB 445) — built-in packs only. Refresh list to retry."
    assert net_gate.offline_note([]) == ""
