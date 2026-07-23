from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Query

from app.core.config import ROOT_DIR
from app.core.response import success
from app.knowledge.retrieval import load_catalog_records


router = APIRouter(prefix="/hardware", tags=["hardware"])
CATALOG_DIRECTORY = (
    ROOT_DIR / "backend" / "data" / "knowledge" / "hardware" / "catalog" / "current"
)


@router.get("/catalog")
def catalog(
    category: str | None = None,
    limit: int = Query(default=16, ge=1, le=50),
) -> dict:
    records = load_catalog_records(CATALOG_DIRECTORY, include_partial=True)
    counts = Counter(str(record.get("category") or "other") for record in records)
    if category:
        records = [record for record in records if record.get("category") == category]
    records.sort(key=lambda record: str(record.get("fetched_at") or ""), reverse=True)
    return success(
        {
            "categories": dict(sorted(counts.items())),
            "items": [_public_record(record) for record in records[:limit]],
            "total": len(records),
        }
    )


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    price = record.get("price") if isinstance(record.get("price"), dict) else {}
    offers = price.get("offers") if isinstance(price.get("offers"), list) else []
    offer_prices = [_decimal(item.get("price_usd")) for item in offers]
    offer_prices = [value for value in offer_prices if value is not None]
    sources = record.get("sources") if isinstance(record.get("sources"), list) else []
    return {
        "category": record.get("category"),
        "brand": record.get("brand"),
        "model": record.get("model"),
        "market": record.get("market"),
        "specs": record.get("specs", {}),
        "price_cny": price.get("reference_cny"),
        "price_usd": price.get("reference_usd"),
        "price_usd_min": str(min(offer_prices)) if offer_prices else None,
        "price_usd_max": str(max(offer_prices)) if offer_prices else None,
        "quality_level": record.get("quality_level"),
        "source": sources[0] if sources else None,
        "fetched_at": record.get("fetched_at"),
    }


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
