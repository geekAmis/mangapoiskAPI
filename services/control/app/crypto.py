from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from manga_common.errors import AppError


class SecretBox:
    """Encrypt SSH passwords at rest with a key derived from CONTROL_SECRET_KEY."""

    def __init__(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise AppError(
                "Не удалось расшифровать пароль сервера. Проверьте CONTROL_SECRET_KEY.",
                status_code=500,
                code="secret_decrypt_failed",
            ) from exc
