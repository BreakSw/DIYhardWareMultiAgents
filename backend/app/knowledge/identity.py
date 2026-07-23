from __future__ import annotations

from typing import Any
import unicodedata


_BRAND_ALIASES = {
    "wd": "western digital",
    "western digital corporation": "western digital",
}


def canonical_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def canonical_brand(value: Any) -> str:
    normalized = canonical_text(value)
    return _BRAND_ALIASES.get(normalized, normalized)


def record_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        canonical_text(record.get("category")),
        canonical_brand(record.get("brand")),
        canonical_text(record.get("model")),
    )
