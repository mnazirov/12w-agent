"""Tests for TokenEncryptor Fernet wrapper."""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken

from app.services.crypto_service import TokenEncryptor


def test_encrypt_decrypt_round_trip() -> None:
    key = TokenEncryptor.generate_key()
    encryptor = TokenEncryptor(key)

    plain = "access-token-123"
    encrypted = encryptor.encrypt(plain)
    decrypted = encryptor.decrypt(encrypted)

    assert decrypted == plain
    assert encrypted != plain


def test_encrypt_decrypt_empty_string() -> None:
    key = TokenEncryptor.generate_key()
    encryptor = TokenEncryptor(key)

    encrypted = encryptor.encrypt("")
    assert encryptor.decrypt(encrypted) == ""


def test_encrypt_decrypt_unicode_text() -> None:
    key = TokenEncryptor.generate_key()
    encryptor = TokenEncryptor(key)

    plain = "почта:user@example.com"
    encrypted = encryptor.encrypt(plain)
    assert encryptor.decrypt(encrypted) == plain


def test_decrypt_with_wrong_key_raises() -> None:
    enc1 = TokenEncryptor(TokenEncryptor.generate_key())
    enc2 = TokenEncryptor(TokenEncryptor.generate_key())
    cipher = enc1.encrypt("secret")

    with pytest.raises(InvalidToken):
        enc2.decrypt(cipher)


def test_decrypt_garbage_raises() -> None:
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())
    with pytest.raises(InvalidToken):
        encryptor.decrypt("not-a-token")


def test_generate_key_creates_valid_encryptor() -> None:
    key = TokenEncryptor.generate_key()
    encryptor = TokenEncryptor(key)
    assert encryptor.decrypt(encryptor.encrypt("ok")) == "ok"
