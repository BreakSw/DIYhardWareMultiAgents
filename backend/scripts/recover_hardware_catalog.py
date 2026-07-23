from __future__ import annotations

import argparse
import copy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.knowledge.hashing import canonical_content_hash
from app.knowledge.http import create_managed_client
from app.knowledge.identity import record_identity
from app.knowledge.models import ExchangeRate
from app.knowledge.normalization import normalize_specs, sanitize_source_url
from app.knowledge.providers.ecb import EcbProvider
from app.knowledge.storage import BatchStorage, read_catalog_payload
from app.knowledge.validation import (
    REQUIRED_SPECS,
    catalog_missing_fields,
    is_category_relevant,
)


DEFAULT_ROOT = BACKEND_DIR / "data" / "knowledge" / "hardware"
_GENERIC_TITLE_PREFIXES = {
    "compatible",
    "desktop",
    "gaming",
    "kit",
    "latest",
    "new",
    "upgrade",
}


def _identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return record_identity(record)


def _infer_title_brand(title: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9.+-]*)", title)
    if match is None:
        return None
    value = match.group(1).strip("-+.")
    if not value or value.casefold() in _GENERIC_TITLE_PREFIXES:
        return None
    return value


def _reference_usd(record: dict[str, Any]) -> Decimal | None:
    price = record.get("price")
    if not isinstance(price, dict):
        return None
    values = [price.get("reference_usd")]
    offers = price.get("offers")
    if isinstance(offers, list):
        values.extend(
            offer.get("price_usd")
            for offer in offers
            if isinstance(offer, dict)
        )
    for value in values:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _revalidate(
    record: dict[str, Any],
    rate: ExchangeRate,
    recovery: dict[str, str],
) -> dict[str, Any] | None:
    recovered = copy.deepcopy(record)
    category = str(recovered.get("category") or "").strip().casefold()
    model = str(recovered.get("model") or "").strip()
    recovered["category"] = category
    recovered["model"] = model
    recovered["brand"] = str(recovered.get("brand") or "").strip()
    if (
        category not in REQUIRED_SPECS
        or not is_category_relevant(category, model)
        or not all(_identity(recovered))
    ):
        return None

    recovered["exchange_rate"] = rate.model_dump(mode="json")
    price = recovered.get("price")
    if not isinstance(price, dict):
        price = {"offers": []}
        recovered["price"] = price
    reference_usd = _reference_usd(recovered)
    if reference_usd is not None:
        price["reference_usd"] = str(reference_usd)
        price["reference_cny"] = str(
            (reference_usd * rate.usd_cny).quantize(Decimal("0.01"))
        )

    missing_fields = catalog_missing_fields(recovered)
    quality_level = "partial" if missing_fields else "verified"
    recovered["quality_level"] = quality_level
    recovered["missing_fields"] = list(missing_fields)
    quality = recovered.get("quality")
    if not isinstance(quality, dict):
        quality = {}
        recovered["quality"] = quality
    quality.update(
        {
            "complete": quality_level == "verified",
            "quality_level": quality_level,
            "missing_fields": list(missing_fields),
        }
    )
    if quality_level == "partial":
        recovered["reason"] = "missing_required_data"
        recovered["reason_code"] = "missing_required_data"
    else:
        recovered.pop("reason", None)
        recovered.pop("reason_code", None)
    recovered["recovery"] = recovery
    recovered["content_hash"] = canonical_content_hash(recovered)
    return recovered


def _raw_shopping_record(
    category: str,
    item: dict[str, Any],
    path: Path,
) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    brand = _infer_title_brand(title)
    source = sanitize_source_url(
        item.get("product_link")
        or item.get("link")
        or item.get("serpapi_product_api")
    )
    try:
        price_usd = Decimal(str(item.get("extracted_price")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if (
        brand is None
        or source is None
        or price_usd <= 0
        or not is_category_relevant(category, title)
    ):
        return None
    return {
        "category": category,
        "brand": brand,
        "model": title,
        "mpn": "",
        "release_date": None,
        "market": "US",
        "specs": normalize_specs(category, [], title=title),
        "price": {
            "reference_usd": str(price_usd),
            "reference_cny": None,
            "offers": [
                {
                    "merchant": str(item.get("source") or "serpapi-archive"),
                    "url": source,
                    "price_usd": str(price_usd),
                    "availability": "unknown",
                    "provider": "serpapi-archive",
                }
            ],
        },
        "exchange_rate": None,
        "sources": [source],
        "fetched_at": datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=UTC,
        ).isoformat(),
        "quality": {},
    }


def collect_recoverable_records(
    root: Path,
    rate: ExchangeRate,
) -> list[dict[str, Any]]:
    recovered: dict[tuple[str, str, str], dict[str, Any]] = {}

    for kind in ("normalized", "rejected"):
        for path in sorted((root / kind).glob("*/hardware.jsonl")):
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                candidate = _revalidate(
                    record,
                    rate,
                    {
                        "source_kind": "audited_record",
                        "path": str(path.relative_to(root)),
                        "line": str(line_number),
                    },
                )
                if candidate is None:
                    continue
                key = _identity(candidate)
                current = recovered.get(key)
                if current is None or len(candidate["missing_fields"]) < len(
                    current["missing_fields"]
                ):
                    recovered[key] = candidate

    for path in sorted((root / "raw").glob("*/*/*.json")):
        category = path.stem.casefold()
        if category not in REQUIRED_SPECS:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for item in payload.get("shopping_results", []):
            if not isinstance(item, dict):
                continue
            record = _raw_shopping_record(category, item, path)
            if record is None:
                continue
            candidate = _revalidate(
                record,
                rate,
                {
                    "source_kind": "archived_shopping_result",
                    "path": str(path.relative_to(root)),
                },
            )
            if candidate is None:
                continue
            key = _identity(candidate)
            current = recovered.get(key)
            if current is None or len(candidate["missing_fields"]) < len(
                current["missing_fields"]
            ):
                recovered[key] = candidate

    return sorted(recovered.values(), key=_identity)


def select_records_for_coverage(
    current_records: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    minimum: int,
) -> list[dict[str, Any]]:
    identities: dict[str, set[tuple[str, str, str]]] = {
        category: set() for category in REQUIRED_SPECS
    }
    for record in current_records:
        category = str(record.get("category") or "").casefold()
        if category in identities:
            identities[category].add(_identity(record))

    def priority(record: dict[str, Any]) -> tuple[Any, ...]:
        recovery = record.get("recovery")
        source_kind = recovery.get("source_kind") if isinstance(recovery, dict) else ""
        return (
            record.get("quality_level") != "verified",
            source_kind != "audited_record",
            len(record.get("missing_fields") or []),
            _identity(record),
        )

    selected: list[dict[str, Any]] = []
    for record in sorted(candidates, key=priority):
        category = str(record.get("category") or "").casefold()
        if category not in identities or len(identities[category]) >= minimum:
            continue
        key = _identity(record)
        if key in identities[category]:
            continue
        identities[category].add(key)
        selected.append(record)
    return selected


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover validated catalog records from archived managed responses."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--minimum-per-category", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = create_managed_client()
    try:
        rate = EcbProvider(client).latest()
    finally:
        client.close()
    records = collect_recoverable_records(args.root, rate)
    try:
        current_records = read_catalog_payload(args.root).get("records", [])
    except FileNotFoundError:
        current_records = []
    selected = select_records_for_coverage(
        current_records,
        records,
        minimum=max(1, args.minimum_per_category),
    )
    if args.dry_run:
        print(f"recoverable={len(records)}")
        print(f"selected={len(selected)}")
        return 0
    batch_id = datetime.now(UTC).strftime("recovery-%Y%m%dT%H%M%SZ")
    path = BatchStorage(args.root, batch_id, []).publish_catalog(selected)
    print((path.parent / "summary.json").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
