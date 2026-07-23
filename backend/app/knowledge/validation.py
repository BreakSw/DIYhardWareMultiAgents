from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any
import unicodedata
from urllib.parse import urlsplit

from app.knowledge.models import ValidationResult


_CATEGORY_TITLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "cpu": (r"\bprocessor\b", r"\bcpu\b", r"\bryzen\b", r"\bthreadripper\b"),
    "gpu": (
        r"\bgraphics?\s+card\b",
        r"\bgpu\b",
        r"\bgeforce\b",
        r"\bradeon\b",
        r"\brtx\s*\d",
    ),
    "motherboard": (r"\bmotherboard\b", r"\bmainboard\b"),
    "memory": (r"\bmemory\b", r"\bram\b", r"\b(?:so-?)?dimm\b", r"\bddr[345]\b"),
    "storage": (
        r"\bssd\b",
        r"\bnvme\b",
        r"\bhard\s+drive\b",
        r"\bhdd\b",
        r"\bsolid[ -]state\b",
    ),
    "psu": (r"\bpower\s+supply\b", r"\bpsu\b"),
    "cooler": (
        r"\bcpu\s+(?:air\s+|liquid\s+)?cooler\b",
        r"\baio\b",
        r"\bliquid\s+freezer\b",
    ),
    "case": (
        r"\bpc\s+case\b",
        r"\bcomputer\s+case\b",
        r"\b(?:mid|full|mini)[ -]?tower\b",
        r"\bchassis\b",
    ),
}


def is_category_relevant(category: str, title: str) -> bool:
    """Return whether a search title explicitly describes the requested part."""

    normalized_category = unicodedata.normalize("NFKC", category).strip().casefold()
    normalized_title = unicodedata.normalize("NFKC", title).strip().casefold()
    patterns = _CATEGORY_TITLE_PATTERNS.get(normalized_category)
    if not patterns or not normalized_title:
        return False
    return any(re.search(pattern, normalized_title) for pattern in patterns)


REQUIRED_SPECS: dict[str, set[str]] = {
    "cpu": {
        "socket",
        "cores",
        "threads",
        "base_clock",
        "boost_clock",
        "tdp_w",
        "memory_types",
        "pcie_version",
    },
    "gpu": {
        "chipset",
        "vram_gb",
        "memory_type",
        "tdp_w",
        "length_mm",
        "power_connectors",
        "recommended_psu_w",
    },
    "motherboard": {
        "socket",
        "chipset",
        "form_factor",
        "memory_type",
        "memory_slots",
        "max_memory_gb",
        "pcie_slots",
        "m2_slots",
    },
    "memory": {
        "memory_type",
        "total_capacity_gb",
        "module_count",
        "speed_mt_s",
        "cas_latency",
        "voltage",
    },
    "storage": {
        "capacity_gb",
        "form_factor",
        "interface",
        "protocol",
        "sequential_read_mb_s",
        "sequential_write_mb_s",
        "endurance_tbw",
    },
    "psu": {
        "wattage_w",
        "efficiency_rating",
        "form_factor",
        "atx_version",
        "modular_type",
        "pcie_connectors",
    },
    "cooler": {
        "cooler_type",
        "supported_sockets",
        "fan_count",
    },
    "case": {
        "supported_motherboard_form_factors",
        "max_gpu_length_mm",
        "max_cooler_height_mm",
        "supported_radiators",
        "psu_form_factor",
        "drive_bays",
    },
}


def is_valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme.lower() in {"http", "https"}
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
    )


def is_valid_offer(offer: Any) -> bool:
    if not isinstance(offer, dict):
        return False
    try:
        price = Decimal(str(offer.get("price_usd")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return (
        price > 0
        and offer.get("availability") in {"in_stock", "unknown"}
        and is_valid_http_url(offer.get("url"))
    )


def is_valid_exchange_rate(value: Any) -> bool:
    if not isinstance(value, dict) or not value.get("published_at"):
        return False
    try:
        return Decimal(str(value.get("usd_cny"))) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def catalog_missing_fields(record: dict[str, Any]) -> list[str]:
    price = record.get("price")
    offers = price.get("offers", []) if isinstance(price, dict) else []
    sources = record.get("sources")
    valid_sources = (
        [source for source in sources if is_valid_http_url(source)]
        if isinstance(sources, list)
        else []
    )
    validation = validate_hardware(
        unicodedata.normalize("NFKC", str(record.get("category") or ""))
        .strip()
        .casefold(),
        record.get("specs") if isinstance(record.get("specs"), dict) else {},
        offers if isinstance(offers, list) else [],
        valid_sources,
    )
    missing = list(validation.missing_fields)
    if not is_valid_exchange_rate(record.get("exchange_rate")):
        missing.append("exchange_rate")
    return sorted(set(missing))


def category_schema(category: str) -> dict[str, Any]:
    fields = REQUIRED_SPECS.get(category, set())
    properties = {
        name: {
            "type": ["string", "null"],
            "description": (
                f"Explicit {name} value from the product page; null if absent"
            )
        }
        for name in sorted(fields)
    }
    return {
        "type": "object",
        "properties": {
            "brand": {"type": ["string", "null"]},
            "model": {"type": ["string", "null"]},
            "mpn": {"type": ["string", "null"]},
            "specs": {
                "type": "object",
                "properties": properties,
            },
        },
    }


def validate_hardware(
    category: str,
    specs: dict[str, Any],
    offers: list[dict[str, Any]],
    sources: list[str],
) -> ValidationResult:
    required = REQUIRED_SPECS.get(category)
    if required is None:
        return ValidationResult(
            accepted=False,
            quality_level="partial",
            reason_code="unsupported_category",
        )
    missing = sorted(
        field
        for field in required
        if field not in specs or specs[field] in (None, "", [], {})
    )
    if category == "cooler":
        has_clearance = bool(
            specs.get("height_mm")
            or specs.get("radiator_size_mm")
        )
        has_capacity = bool(
            specs.get("rated_tdp_w")
            or specs.get("supported_processor_range")
        )
        if not has_clearance:
            missing.append("height_mm_or_radiator_size_mm")
        if not has_capacity:
            missing.append(
                "rated_tdp_w_or_supported_processor_range"
            )
    valid_offers = [offer for offer in offers if is_valid_offer(offer)]
    if not valid_offers:
        missing.append("usd_price_offer")
    if not any(is_valid_http_url(source) for source in sources):
        missing.append("source")
    return ValidationResult(
        accepted=not missing,
        quality_level="partial" if missing else "verified",
        missing_fields=sorted(set(missing)),
        reason_code="" if not missing else "missing_required_data",
    )
