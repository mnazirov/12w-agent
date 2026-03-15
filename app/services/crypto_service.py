"""Fernet encryption helpers for sensitive OAuth tokens at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet


class TokenEncryptor:
    """Symmetric token encryptor backed by Fernet."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @staticmethod
    def generate_key() -> str:
        """Generate a Fernet key suitable for GOOGLE_TOKENS_ENCRYPTION_KEY."""
        return Fernet.generate_key().decode()
