"""Lab SMB login: workgroup user vs GOLD-CLUB\\test, 1326 retry."""

from __future__ import annotations

import pytest

from network import lab_access as la


def _winerror(code: int, msg: str) -> OSError:
    exc = OSError(code, msg)
    exc.winerror = code
    return exc


def test_workgroup_111_uses_ip_test_not_domain() -> None:
    assert la.lab_username_for_host("10.0.0.111") == r"10.0.0.111\test"
    users = la.lab_smb_usernames_for_host("10.0.0.111")
    assert users[0] == r"10.0.0.111\test"
    assert r"GST22377\test" in users
    assert r"GOLD-CLUB\test" not in users
    assert la.lab_username_for_host("10.0.0.90") == r"GOLD-CLUB\test"
    domain = la.lab_smb_usernames_for_host("10.0.0.90")
    assert domain[0] == r"GOLD-CLUB\test"
    assert r"10.0.0.90\test" in domain


def test_unknown_lab_lan_tries_local_test_then_domain() -> None:
    assert la.is_lab_lan_ip("10.0.0.76")
    assert la.is_lab_lan_ip("10.0.0.111")
    assert not la.is_lab_lan_ip("8.8.8.8")
    assert not la.is_lab_lan_ip("10.1.0.76")
    users = la.lab_smb_usernames_for_host("10.0.0.76")
    assert users[0] == r"10.0.0.76\test"
    assert r"GOLD-CLUB\test" in users
    assert "test" in users


def test_is_smb_logon_failure_1326() -> None:
    exc = _winerror(1326, r"The user name or password is incorrect: '\\10.0.0.111\slot\'")
    assert la.is_smb_logon_failure(exc)
    assert la.is_smb_logon_failure(_winerror(1219, "Multiple connections"))
    assert not la.is_smb_logon_failure(OSError(2, "No such file"))


def test_format_1326_tells_workgroup_user() -> None:
    exc = _winerror(1326, "The user name or password is incorrect")
    msg = la.format_lab_smb_logon_failure("10.0.0.111", exc)
    assert r"10.0.0.111\test" in msg
    assert "GOLD-CLUB\\test" in msg
    assert "workgroup" in msg.casefold()
    domain_msg = la.format_lab_smb_logon_failure("10.0.0.90", exc)
    assert "workgroup" not in domain_msg.casefold()
    unknown = la.format_lab_smb_logon_failure("10.0.0.76", exc)
    assert r"10.0.0.76\test" in unknown
    assert "GOLD-CLUB\\test" in unknown
    assert "credential popup" in unknown.casefold() or "silent smb" in unknown.casefold()


def test_ensure_drops_stale_session_then_reconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(la.sys, "platform", "win32")
    monkeypatch.setattr(la, "_store_lab_cmdkey", lambda *_a: True)
    monkeypatch.setattr(la, "_connect_lab_disk_shares", lambda *_a, **_k: None)
    dropped: list[str] = []
    monkeypatch.setattr(la, "drop_lab_smb_sessions", dropped.append)
    n = {"n": 0}

    def connect(host: str, user: str, password: str) -> None:
        n["n"] += 1
        if n["n"] == 1:
            raise _winerror(1326, "The user name or password is incorrect")
        assert user == r"10.0.0.111\test"
        assert password == "test"

    monkeypatch.setattr(la, "_connect_lab_ipc", connect)
    monkeypatch.setattr(
        la,
        "get_lab_credential",
        lambda _ip: (r"10.0.0.111\test", "test"),
    )
    assert la.ensure_lab_smb_credential("10.0.0.111") is True
    assert dropped == ["10.0.0.111"]
    assert n["n"] == 2


def test_ensure_skips_non_lab_lan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(la.sys, "platform", "win32")
    assert la.ensure_lab_smb_credential("8.8.8.8") is False
    assert la.ensure_lab_smb_credential("10.1.0.76") is False


def test_ensure_unknown_lab_lan_uses_ip_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(la.sys, "platform", "win32")
    monkeypatch.setattr(la, "_store_lab_cmdkey", lambda *_a: True)
    monkeypatch.setattr(la, "drop_lab_smb_sessions", lambda *_a: None)
    monkeypatch.setattr(la, "_connect_lab_disk_shares", lambda *_a, **_k: None)
    seen: list[str] = []

    def connect(host: str, user: str, password: str) -> None:
        seen.append(user)
        assert host == "10.0.0.76"
        assert password == "test"
        if user != r"10.0.0.76\test":
            raise _winerror(1326, "The user name or password is incorrect")

    monkeypatch.setattr(la, "_connect_lab_ipc", connect)
    monkeypatch.setattr(
        la,
        "get_lab_credential",
        lambda _ip: (r"GOLD-CLUB\test", "test"),
    )
    assert la.ensure_lab_smb_credential("10.0.0.76") is True
    assert seen[0] == r"10.0.0.76\test"


def test_ensure_unknown_lab_lan_falls_back_to_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(la.sys, "platform", "win32")
    monkeypatch.setattr(la, "_store_lab_cmdkey", lambda *_a: True)
    monkeypatch.setattr(la, "drop_lab_smb_sessions", lambda *_a: None)
    monkeypatch.setattr(la, "_connect_lab_disk_shares", lambda *_a, **_k: None)

    def connect(host: str, user: str, password: str) -> None:
        if user != r"GOLD-CLUB\test":
            raise _winerror(1326, "The user name or password is incorrect")
        assert password == "test"

    monkeypatch.setattr(la, "_connect_lab_ipc", connect)
    monkeypatch.setattr(
        la,
        "get_lab_credential",
        lambda _ip: (r"GOLD-CLUB\test", "test"),
    )
    assert la.ensure_lab_smb_credential("10.0.0.76") is True


def test_username_ok_rejects_domain_on_111() -> None:
    assert la._username_ok_for_host(r"10.0.0.111\test", "10.0.0.111")
    assert not la._username_ok_for_host(r"GOLD-CLUB\test", "10.0.0.111")
    assert la._username_ok_for_host(r"GOLD-CLUB\test", "10.0.0.90")


def test_require_lab_fleet_ip_allows_any_lab_lan_host() -> None:
    assert la.require_lab_fleet_ip("10.0.0.98") == "10.0.0.98"
    assert la.require_lab_fleet_ip("10.0.0.76") == "10.0.0.76"
    assert la.require_lab_fleet_ip("10.0.0.90") == "10.0.0.90"
    with pytest.raises(la.FleetAllowlistError, match="10.0.0.0/24"):
        la.require_lab_fleet_ip("8.8.8.8")
    with pytest.raises(la.FleetAllowlistError, match="10.0.0.0/24"):
        la.require_lab_fleet_ip("10.1.0.76")
    with pytest.raises(la.FleetAllowlistError, match="Invalid cabinet IP"):
        la.require_lab_fleet_ip("not-an-ip")
    with pytest.raises(la.FleetAllowlistError, match="Invalid cabinet IP"):
        la.require_lab_fleet_ip("10.0.0.999")


def test_lab_winrm_auth_is_ntlm_on_lab_lan() -> None:
    assert la.lab_winrm_authentication("10.0.0.98") == "Default"
    assert la.lab_winrm_authentication("10.0.0.111") == "Default"
    assert la.lab_winrm_authentication("8.8.8.8") == "Negotiate"


def test_lab_lan_ip_from_text() -> None:
    assert la.lab_lan_ip_from_text("10.0.0.76") == "10.0.0.76"
    assert la.lab_lan_ip_from_text(r"\\10.0.0.90\c$\Goldclub") == "10.0.0.90"
    assert la.lab_lan_ip_from_text(r"//10.0.0.98/slot") == "10.0.0.98"
    assert la.lab_lan_ip_from_text("8.8.8.8") is None
    assert la.lab_lan_ip_from_text(r"C:\Goldclub") is None


def test_lab_lan_scan_ips_covers_subnet_minus_skip() -> None:
    ips = la.lab_lan_scan_ips(skip=("10.0.0.1",))
    assert "10.0.0.1" not in ips
    assert "10.0.0.76" in ips
    assert "10.0.0.254" in ips
    assert "10.0.0.0" not in ips
    assert "10.0.0.255" not in ips
    assert len(ips) == 253


def test_priority_lab_scan_ips_recent_then_named() -> None:
    pri = la.priority_lab_scan_ips([r"\\10.0.0.76\c$\Goldclub"])
    assert pri[0] == "10.0.0.76"
    assert "10.0.0.111" in pri
    assert "10.0.0.90" in pri


def test_discover_active_lab_fleet_only_hosts_that_answer() -> None:
    seen: list[str] = []

    def probe(host: str) -> bool:
        seen.append(host)
        return host in {"10.0.0.76", "10.0.0.90"}

    live = la.discover_active_lab_fleet(
        hosts=("10.0.0.1", "10.0.0.76", "10.0.0.90", "10.0.0.200"),
        probe=probe,
        skip_hosts=(),
        workers=4,
    )
    assert live == ["10.0.0.76", "10.0.0.90"]
    assert "10.0.0.1" in seen
    assert "10.0.0.200" in seen


def test_discover_active_lab_fleet_skips_this_pc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(la, "this_pc_lab_lan_ips", lambda: frozenset({"10.0.0.5"}))
    live = la.discover_active_lab_fleet(
        hosts=("10.0.0.5", "10.0.0.76"),
        probe=lambda _host: True,
        workers=2,
    )
    assert live == ["10.0.0.76"]


def test_discover_active_lab_fleet_stops_on_app_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config_scanner.app_shutdown import request_shutdown, reset_shutdown_for_tests

    reset_shutdown_for_tests()
    request_shutdown()
    try:
        seen: list[str] = []
        live = la.discover_active_lab_fleet(
            hosts=("10.0.0.1", "10.0.0.76"),
            probe=lambda host: seen.append(host) or True,
            skip_hosts=(),
            workers=2,
        )
        assert live == []
        assert seen == []
    finally:
        reset_shutdown_for_tests()


def test_discover_priority_hosts_are_probed_first() -> None:
    order: list[str] = []

    def probe(host: str) -> bool:
        order.append(host)
        return host == "10.0.0.76"

    live = la.discover_active_lab_fleet(
        priority_hosts=("10.0.0.76",),
        hosts=None,
        skip_hosts=(),
        probe=probe,
        workers=8,
    )
    assert live == ["10.0.0.76"]
    assert order[0] == "10.0.0.76"
    assert "10.0.0.1" in order


def test_smb_host_from_cabinet_target() -> None:
    assert la.smb_host_from_cabinet_target(r"\\10.0.0.76\c$\Goldclub") == "10.0.0.76"
    assert la.smb_host_from_cabinet_target("10.0.0.28") == "10.0.0.28"
    assert la.smb_host_from_cabinet_target(r"\\10.0.0.111\slot (GST22377)") == "10.0.0.111"
    assert la.smb_host_from_cabinet_target(r"C:\Goldclub") is None
    assert la.smb_host_from_cabinet_target("G:") is None
    assert la.smb_host_from_cabinet_target("") is None


def test_cabinet_target_answers_smb_uses_host_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake(host: str, *, timeout_sec: float = 0.25) -> bool:
        seen.append(host)
        return host == "10.0.0.76"

    monkeypatch.setattr(la, "_host_answers_smb", fake)
    assert la.cabinet_target_answers_smb(r"\\10.0.0.76\c$\Goldclub") is True
    assert la.cabinet_target_answers_smb("10.0.0.28") is False
    assert la.cabinet_target_answers_smb(r"C:\Goldclub") is False
    assert seen == ["10.0.0.76", "10.0.0.28"]
