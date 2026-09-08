"""Built-in GameStar JSON cryptor (no Encryptor.exe)."""

from __future__ import annotations

from pathlib import Path

from config_scanner.gamestar_crypt import (
    decrypt_gamestar_bytes,
    encrypt_gamestar_bytes,
)
from config_scanner.math_decrypt import clear_math_decrypt_cache, decrypt_math_file


def test_roundtrip_small_json() -> None:
    plain = b'[{"Bet": 30, "Denom": 5}]'
    salt = b"\x11" * 32
    blob = encrypt_gamestar_bytes(plain, salt=salt)
    assert blob[:32] == salt
    assert blob.lstrip()[:1] not in (b"{", b"[")
    assert decrypt_gamestar_bytes(blob) == plain


def test_rejects_truncated() -> None:
    assert decrypt_gamestar_bytes(b"\x00" * 20) is None


def test_decrypt_math_file_uses_builtin_without_exe(
    tmp_path: Path, monkeypatch
) -> None:
    plain = b'{"virtualReelValues": ["CreditWin"], "Denom": 5}'
    encrypted = tmp_path / "Link2WinBonusMath.json"
    encrypted.write_bytes(encrypt_gamestar_bytes(plain))
    launched: list[int] = []
    monkeypatch.setattr(
        "config_scanner.math_decrypt._run_decryptor",
        lambda *a, **k: launched.append(1) or None,
    )
    monkeypatch.setattr(
        "config_scanner.math_decrypt.find_math_decryptor",
        lambda: tmp_path / "missing-Encryptor.exe",
    )
    clear_math_decrypt_cache()
    out = decrypt_math_file(encrypted, spawn=False)
    assert out == plain
    assert launched == []
    assert encrypted.read_bytes()[:1] != b"{"


def test_decrypt_staged_link2win_bonus_math() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "config_scanner"
        / "assets"
        / "embedded_updates"
        / "staged"
    )
    path = next(root.rglob("Link2WinBonusMath.json"), None)
    if path is None:
        return
    plain = decrypt_gamestar_bytes(path.read_bytes())
    assert plain is not None
    assert plain.lstrip()[:1] in (b"{", b"[")
    assert b"virtualReel" in plain or b"Denom" in plain or b"Bet" in plain
