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
