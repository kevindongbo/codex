"""Small server-only encryption helper for third-party credentials.

The Fernet key is intentionally read only from ``INTEGRATION_ENCRYPTION_KEY``.
It is never serialized, returned by an API, or written into audit records.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken
from django.core.exceptions import ImproperlyConfigured, ValidationError


def _fernet() -> Fernet:
    key = os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip()
    if not key:
        raise ImproperlyConfigured("缺少 INTEGRATION_ENCRYPTION_KEY，无法安全保存第三方凭据")
    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("INTEGRATION_ENCRYPTION_KEY 不是有效的 Fernet 密钥") from exc


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValidationError("第三方凭据无法解密，请重新授权或重新保存配置") from exc
