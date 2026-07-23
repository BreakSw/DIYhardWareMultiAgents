from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "x_api_key",
}


def _is_sensitive_key(value: str) -> bool:
    return value.lower().replace("-", "_") in SENSITIVE_KEYS


def create_managed_client(timeout: float = 15.0) -> httpx.Client:
    """Create an API client that honors the machine's proxy and CA settings."""
    return httpx.Client(timeout=timeout, trust_env=True)


def safe_http_status(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value
    if parts.username is not None or parts.password is not None:
        return ""
    query = [
        (key, "***" if _is_sensitive_key(key) else item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), "")
    )


def redact_secrets(value: Any, secrets: list[str] | None = None) -> Any:
    secret_values = [item for item in secrets or [] if item]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                result[key] = "***"
            else:
                result[key] = redact_secrets(item, secret_values)
        return result
    if isinstance(value, list):
        return [redact_secrets(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, secret_values) for item in value)
    if isinstance(value, str):
        redacted = _redact_url(value)
        for secret in secret_values:
            redacted = redacted.replace(secret, "***")
        return redacted
    return value
