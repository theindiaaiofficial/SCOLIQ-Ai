from __future__ import annotations

import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FaceTemplateCipher:
    """Versioned AES-256-GCM encryption for biometric-linked embedding payloads."""

    key_id = "v1"

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-GCM key must be 32 bytes")
        self._aes = AESGCM(key)

    def encrypt_embeddings(self, embeddings: list[list[float]], *, student_id: str) -> bytes:
        nonce = os.urandom(12)
        plaintext = json.dumps(embeddings, separators=(",", ":"), allow_nan=False).encode()
        ciphertext = self._aes.encrypt(nonce, plaintext, student_id.encode())
        return nonce + ciphertext

    def decrypt_embeddings(self, payload: bytes, *, student_id: str) -> list[list[float]]:
        if len(payload) < 29:
            raise ValueError("Encrypted template payload is invalid")
        nonce, ciphertext = payload[:12], payload[12:]
        plaintext = self._aes.decrypt(nonce, ciphertext, student_id.encode())
        parsed = json.loads(plaintext)
        if not isinstance(parsed, list) or any(not isinstance(item, list) for item in parsed):
            raise ValueError("Decrypted face template payload has invalid shape")
        return parsed
