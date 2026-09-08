"""GameStar JSON / ProgressiveSetup cryptor (same as CRYPT_TOOLS Encryptor).

Recovered from the unobfuscated ``GameStarCrypter`` assembly Costura-packed
inside ``BiOS Encryptor.exe`` (``C:\\CODE\\BiOS Encryptor\\Encryptor\\GameStarCrypter``).
The 38 MB ``Encryptor.exe`` is the same job, Confuser-packed.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

# UTF-8 of Tools.Encryptor.GameStarCrypter.secret (includes U+00BF, not ASCII '?').
_SECRET = bytes.fromhex(
    "6A727567626864263536504F2839666862766E35683435386F68676E656C6E76"
    "673071343275742B603233352734C2BF3F4D474A53796F"
)
_SALT_LEN = 32
_ITERATIONS = 50000
_KEY_LEN = 32
_IV_LEN = 16


def _key_iv(password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    blob = hashlib.pbkdf2_hmac(
        "sha1", password, salt, _ITERATIONS, dklen=_KEY_LEN + _IV_LEN
    )
    return blob[:_KEY_LEN], blob[_KEY_LEN:]


def decrypt_gamestar_bytes(
    data: bytes,
    *,
    password: bytes = _SECRET,
) -> bytes | None:
    """Plain UTF-8 payload, or None if this is not GameStar ciphertext."""
    if len(data) < _SALT_LEN + 16:
        return None
    if (len(data) - _SALT_LEN) % 16:
        return None
    salt, body = data[:_SALT_LEN], data[_SALT_LEN:]
    key, iv = _key_iv(password, salt)
    dec = Cipher(algorithms.AES(key), modes.CFB(iv)).decryptor()
    raw = dec.update(body) + dec.finalize()
    try:
        unpadder = PKCS7(128).unpadder()
        return unpadder.update(raw) + unpadder.finalize()
    except ValueError:
        return None


def encrypt_gamestar_bytes(
    plain: bytes,
    *,
    password: bytes = _SECRET,
    salt: bytes | None = None,
) -> bytes:
    """Encrypt like GameStarCrypter.FileEncrypt (32-byte salt + AES-CFB)."""
    if salt is None:
        salt = os.urandom(_SALT_LEN)
    if len(salt) != _SALT_LEN:
        raise ValueError("salt must be 32 bytes")
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    key, iv = _key_iv(password, salt)
    enc = Cipher(algorithms.AES(key), modes.CFB(iv)).encryptor()
    return salt + enc.update(padded) + enc.finalize()
