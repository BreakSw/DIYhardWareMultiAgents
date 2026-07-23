from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from app.knowledge.models import (
    Candidate,
    ExchangeRate,
    ProviderResult,
    ValidationResult,
)
from app.knowledge.http import redact_secrets, safe_http_status
from app.knowledge.hashing import canonical_content_hash
from app.knowledge.identity import record_identity
from app.knowledge.normalization import sanitize_source_url
from app.knowledge.storage import BatchStorage, read_catalog_payload
from app.knowledge.validation import (
    REQUIRED_SPECS,
    category_schema,
    is_valid_http_url,
    validate_hardware,
)


@dataclass
class ProviderSet:
    serpapi: Any
    firecrawl: Any | None
    zyte: Any | None
    brightdata: Any | None
    apify: Any | None
    ecb: Any


class SerpApiRateLimited(RuntimeError):
    """Stop a batch when the shared SerpAPI quota is exhausted."""


_COMPOSITE_FOLLOW_UP_FIELDS: dict[str, tuple[str, ...]] = {
    "height_mm_or_radiator_size_mm": (
        "height_mm",
        "radiator_size_mm",
    ),
    "rated_tdp_w_or_supported_processor_range": (
        "rated_tdp_w",
        "supported_processor_range",
    ),
}


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _merge(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if not _nonempty(value):
            continue
        if isinstance(value, dict):
            nested = target.setdefault(key, {})
            if isinstance(nested, dict):
                _merge(nested, value)
        elif not _nonempty(target.get(key)):
            target[key] = value


def _sanitize_sources(
    values: Any,
    secrets: list[str],
) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    sources = [
        source
        for value in values
        for source in [sanitize_source_url(value, secrets)]
        if source is not None
    ]
    return list(dict.fromkeys(sources))


def _firecrawl_record(result: ProviderResult) -> dict[str, Any]:
    data = result.data.get("data", {})
    value = data.get("json", {}) if isinstance(data, dict) else {}
    return value if isinstance(value, dict) else {}


def _zyte_record(result: ProviderResult) -> dict[str, Any]:
    custom = result.data.get("customAttributes", {})
    values = custom.get("values", {}) if isinstance(custom, dict) else {}
    return values if isinstance(values, dict) else {}


def _zyte_offer(
    result: ProviderResult,
    fallback_url: str,
) -> dict[str, Any] | None:
    product = result.data.get("product", {})
    if not isinstance(product, dict) or product.get("currency") != "USD":
        return None
    price = product.get("price")
    if not price:
        return None
    availability = str(product.get("availability") or "unknown").lower()
    availability = (
        "in_stock" if availability == "instock" else "out_of_stock"
        if availability == "outofstock"
        else "unknown"
    )
    return {
        "merchant": "zyte-extracted",
        "url": product.get("url") or fallback_url,
        "price_usd": str(price),
        "availability": availability,
        "provider": "zyte",
    }


def _deduplicate_offers(
    offers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for offer in offers:
        merchant = str(offer.get("merchant") or "").strip().casefold()
        price = offer.get("price_usd")
        if not merchant or price in (None, ""):
            continue
        key = (merchant, str(Decimal(str(price)).normalize()))
        current = unique.get(key)
        if current is None:
            unique[key] = offer
            continue
        current_score = (
            current.get("availability") == "in_stock",
            current.get("provider") != "serpapi",
        )
        incoming_score = (
            offer.get("availability") == "in_stock",
            offer.get("provider") != "serpapi",
        )
        if incoming_score > current_score:
            unique[key] = offer
    return list(unique.values())


def _record_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return record_identity(record)


class HardwareKnowledgePipeline:
    def __init__(
        self,
        providers: ProviderSet,
        output_root: Path,
        secrets: list[str],
    ) -> None:
        self.providers = providers
        self.output_root = output_root
        self.secrets = secrets

    def run(
        self,
        categories: list[str],
        per_category: int,
        market: str,
        *,
        minimum_per_category: int | None = None,
        max_candidates_per_category: int = 40,
    ) -> dict[str, Any]:
        if minimum_per_category is not None and minimum_per_category < 1:
            raise ValueError("minimum_per_category must be positive")
        if max_candidates_per_category < 1:
            raise ValueError("max_candidates_per_category must be positive")
        now = datetime.now(UTC)
        batch_id = now.strftime("%Y%m%dT%H%M%SZ")
        storage = BatchStorage(
            self.output_root,
            batch_id,
            self.secrets,
        )
        calls: list[dict[str, Any]] = []
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        publishable_partial: list[dict[str, Any]] = []
        disabled_providers: set[str] = set()
        degraded_reason: str | None = None
        rate = self._exchange_rate(calls)
        coverage_identities: dict[str, set[tuple[str, str, str]]] = {
            category: set() for category in categories
        }
        try:
            current_records = read_catalog_payload(self.output_root).get(
                "records", []
            )
        except FileNotFoundError:
            current_records = []
        for record in current_records:
            category = str(record.get("category") or "")
            if category in coverage_identities:
                coverage_identities[category].add(_record_identity(record))

        for category in categories:
            if (
                minimum_per_category is not None
                and len(coverage_identities[category])
                >= minimum_per_category
            ):
                continue
            discovery_limit = (
                max_candidates_per_category
                if minimum_per_category is not None
                else max(per_category * 3, 3)
            )
            try:
                candidates = self._discover(
                    category,
                    discovery_limit,
                    storage,
                    calls,
                )
            except SerpApiRateLimited:
                degraded_reason = "serpapi_rate_limited"
                self._checkpoint(
                    storage,
                    accepted,
                    rejected,
                    publishable_partial,
                )
                break
            accepted_for_category = 0
            for candidate in candidates:
                if (
                    minimum_per_category is not None
                    and len(coverage_identities[category])
                    >= minimum_per_category
                ):
                    break
                if (
                    minimum_per_category is None
                    and accepted_for_category >= per_category
                ):
                    break
                try:
                    record, failures = self._collect_candidate(
                        candidate,
                        market,
                        rate,
                        storage,
                        calls,
                        disabled_providers,
                    )
                except SerpApiRateLimited:
                    degraded_reason = "serpapi_rate_limited"
                    break
                validation = validate_hardware(
                    category,
                    record["specs"],
                    record["price"]["offers"],
                    record["sources"],
                )
                if validation.missing_fields:
                    validation = self._enrich_candidate(
                        candidate,
                        record,
                        validation,
                        storage,
                        calls,
                        failures,
                    )
                if rate is None:
                    validation = ValidationResult(
                        accepted=False,
                        quality_level="partial",
                        missing_fields=[
                            *validation.missing_fields,
                            "exchange_rate",
                        ],
                        invalid_fields=validation.invalid_fields,
                        reason_code="missing_required_data",
                    )
                identity = _record_identity(record)
                missing_identity = [
                    field
                    for field, value in zip(
                        ("category", "brand", "model"),
                        identity,
                        strict=True,
                    )
                    if not value
                ]
                if (
                    missing_identity
                    and validation.reason_code != "unsupported_category"
                ):
                    validation = ValidationResult(
                        accepted=False,
                        quality_level="partial",
                        missing_fields=sorted(
                            set(validation.missing_fields + missing_identity)
                        ),
                        invalid_fields=validation.invalid_fields,
                        reason_code="missing_required_data",
                    )
                record["quality"] = {
                    "complete": validation.accepted,
                    "quality_level": validation.quality_level,
                    "missing_fields": validation.missing_fields,
                    "provider_failures": failures,
                }
                record["quality_level"] = validation.quality_level
                record["missing_fields"] = list(validation.missing_fields)
                finalized = self._finalize_record(record)
                publishable = False
                if validation.accepted:
                    accepted.append(finalized)
                    accepted_for_category += 1
                    publishable = True
                else:
                    record["reason"] = validation.reason_code
                    record["reason_code"] = validation.reason_code
                    finalized = self._finalize_record(record)
                    rejected.append(finalized)
                    if (
                        validation.reason_code == "missing_required_data"
                        and validation.missing_fields
                        and all(_record_identity(finalized))
                        and any(
                            is_valid_http_url(source)
                            for source in finalized.get("sources", [])
                        )
                    ):
                        publishable_partial.append(finalized)
                        publishable = True
                if publishable:
                    coverage_identities[category].add(
                        _record_identity(finalized)
                    )

            self._checkpoint(
                storage,
                accepted,
                rejected,
                publishable_partial,
            )
            if degraded_reason is not None:
                break

        self._checkpoint(
            storage,
            accepted,
            rejected,
            publishable_partial,
        )
        manifest = {
            "batch_id": batch_id,
            "status": "degraded" if degraded_reason else "completed",
            "degraded_reason": degraded_reason,
            "market": market,
            "categories": categories,
            "discovered_count": len(accepted) + len(rejected),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "provider_calls": calls,
            "provider_status": self._provider_status(calls),
            "coverage": {
                category: len(identities)
                for category, identities in coverage_identities.items()
            },
            "created_at": now.isoformat(),
        }
        storage.write_manifest(manifest)
        return manifest

    @staticmethod
    def _checkpoint(
        storage: BatchStorage,
        accepted: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        publishable_partial: list[dict[str, Any]],
    ) -> None:
        storage.write_records(accepted, rejected)
        catalog_records = [*accepted, *publishable_partial]
        if catalog_records:
            storage.publish_catalog(catalog_records)

    def _enrich_candidate(
        self,
        candidate: Candidate,
        record: dict[str, Any],
        validation: ValidationResult,
        storage: BatchStorage,
        calls: list[dict[str, Any]],
        failures: list[str],
    ) -> ValidationResult:
        required_fields = REQUIRED_SPECS.get(candidate.category, set())
        existing_specs = record.get("specs", {})
        if not isinstance(existing_specs, dict):
            existing_specs = {}
        missing_fields: list[str] = []
        for missing in validation.missing_fields:
            candidates = (
                (missing,)
                if missing in required_fields
                else _COMPOSITE_FOLLOW_UP_FIELDS.get(missing, ())
            )
            for field in candidates:
                if (
                    field not in missing_fields
                    and not _nonempty(existing_specs.get(field))
                ):
                    missing_fields.append(field)
        if not missing_fields:
            return validation
        try:
            result = self.providers.serpapi.enrich_missing_fields(
                candidate.title,
                candidate.category,
                missing_fields,
            )
        except Exception as exc:
            result = ProviderResult(
                provider="serpapi-enrichment",
                status="failed",
                error=type(exc).__name__,
            )

        raw = result.data.get("raw", {})
        call_id = hashlib.sha256(
            (
                f"{candidate.category}:{candidate.title}:"
                f"{','.join(missing_fields)}"
            ).encode()
        ).hexdigest()[:16]
        storage.write_raw(
            "serpapi-enrichment",
            call_id,
            raw if isinstance(raw, dict) else {},
        )
        calls.append(
            {
                "provider": "serpapi-enrichment",
                "status": result.status,
                "category": candidate.category,
                "title": candidate.title,
                "missing_fields": missing_fields,
                "latency_ms": result.latency_ms,
                "error": result.error,
                "status_code": result.status_code,
            }
        )
        if result.status == "completed":
            incoming = result.data.get("record", {})
            if isinstance(incoming, dict):
                _merge(record, incoming)
            incoming_sources = result.data.get("sources", [])
            if isinstance(incoming_sources, list):
                record["sources"] = _sanitize_sources(
                    [*record["sources"], *incoming_sources],
                    self.secrets,
                )
        else:
            failures.append(
                f"serpapi-enrichment:{result.error or result.status}"
            )

        return validate_hardware(
            candidate.category,
            record["specs"],
            record["price"]["offers"],
            record["sources"],
        )

    def _exchange_rate(
        self,
        calls: list[dict[str, Any]],
    ) -> ExchangeRate | None:
        try:
            rate = self.providers.ecb.latest()
            calls.append(
                {
                    "provider": "ecb",
                    "status": "completed",
                    "published_at": rate.published_at,
                }
            )
            return rate
        except Exception as exc:
            calls.append(
                {
                    "provider": "ecb",
                    "status": "failed",
                    "error": type(exc).__name__,
                }
            )
            return None

    def _discover(
        self,
        category: str,
        limit: int,
        storage: BatchStorage,
        calls: list[dict[str, Any]],
    ) -> list[Candidate]:
        try:
            candidates, raw = self.providers.serpapi.discover(
                category,
                limit,
            )
            storage.write_raw("serpapi", category, raw)
            calls.append(
                {
                    "provider": "serpapi",
                    "status": "completed",
                    "category": category,
                    "result_count": len(candidates),
                }
            )
            return candidates
        except Exception as exc:
            status_code = safe_http_status(exc)
            calls.append(
                {
                    "provider": "serpapi",
                    "status": "failed",
                    "category": category,
                    "error": type(exc).__name__,
                    "status_code": status_code,
                }
            )
            if status_code == 429:
                raise SerpApiRateLimited from exc
            return []

    def _collect_candidate(
        self,
        candidate: Candidate,
        market: str,
        rate: ExchangeRate | None,
        storage: BatchStorage,
        calls: list[dict[str, Any]],
        disabled_providers: set[str],
    ) -> tuple[dict[str, Any], list[str]]:
        target_url = str(candidate.url)
        schema = category_schema(candidate.category)
        collected: dict[str, Any] = {
            "brand": "",
            "model": candidate.title,
            "mpn": "",
            "specs": {},
        }
        offers: list[dict[str, Any]] = []
        sources: list[str] = []
        failures: list[str] = []
        if candidate.price_usd is not None:
            offers.append(
                {
                    "merchant": candidate.merchant or "serpapi-result",
                    "url": target_url,
                    "price_usd": str(candidate.price_usd),
                    "availability": "unknown",
                    "provider": "serpapi",
                }
            )

        detail_result = self.providers.serpapi.details(candidate)
        detail_raw = detail_result.data.get("raw", {})
        storage.write_raw(
            "serpapi-details",
            hashlib.sha256(
                f"{candidate.category}:{candidate.title}".encode()
            ).hexdigest()[:16],
            detail_raw if isinstance(detail_raw, dict) else {},
        )
        calls.append(
            {
                "provider": "serpapi-details",
                "status": detail_result.status,
                "category": candidate.category,
                "title": candidate.title,
                "latency_ms": detail_result.latency_ms,
                "error": detail_result.error,
                "status_code": detail_result.status_code,
            }
        )
        if detail_result.status_code == 429:
            raise SerpApiRateLimited
        if detail_result.status == "completed":
            detail_record = detail_result.data.get("record", {})
            if isinstance(detail_record, dict):
                _merge(collected, detail_record)
            detail_offers = detail_result.data.get("offers", [])
            if isinstance(detail_offers, list):
                offers.extend(
                    item for item in detail_offers if isinstance(item, dict)
                )
            detail_sources = detail_result.data.get("sources", [])
            if isinstance(detail_sources, list):
                sources.extend(
                    _sanitize_sources(detail_sources, self.secrets)
                )
            if sources:
                target_url = sources[0]
            elif detail_offers:
                target_url = str(detail_offers[0].get("url") or target_url)
        else:
            failures.append(
                f"serpapi-details:{detail_result.error or detail_result.status}"
            )

        for name in ["firecrawl", "zyte", "brightdata", "apify"]:
            provider = getattr(self.providers, name)
            if name in disabled_providers:
                calls.append(
                    {
                        "provider": name,
                        "status": "skipped",
                        "category": candidate.category,
                        "title": candidate.title,
                        "error": "disabled_after_nonretryable_http_error",
                    }
                )
                failures.append(f"{name}:skipped")
                continue
            if provider is None:
                calls.append(
                    {
                        "provider": name,
                        "status": "not_ready",
                        "category": candidate.category,
                        "title": candidate.title,
                    }
                )
                failures.append(f"{name}:not_ready")
                continue
            result = (
                provider.extract(target_url, schema)
                if name == "zyte"
                else provider.fetch(target_url, schema)
                if name == "firecrawl"
                else provider.fetch(target_url)
            )
            storage.write_raw(
                name,
                hashlib.sha256(
                    f"{candidate.category}:{candidate.title}".encode()
                ).hexdigest()[:16],
                result.model_dump(),
            )
            calls.append(
                {
                    "provider": name,
                    "status": result.status,
                    "category": candidate.category,
                    "title": candidate.title,
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                    "status_code": result.status_code,
                }
            )
            if result.status != "completed":
                failures.append(f"{name}:{result.error or 'failed'}")
                if (
                    result.status_code is not None
                    and 400 <= result.status_code < 500
                    and result.status_code not in {408, 429}
                ):
                    disabled_providers.add(name)
                continue
            if name == "firecrawl":
                _merge(collected, _firecrawl_record(result))
            elif name == "zyte":
                _merge(collected, _zyte_record(result))
                offer = _zyte_offer(result, target_url)
                if offer:
                    offers.append(offer)

        offers = _deduplicate_offers(offers)
        prices = [
            Decimal(str(offer["price_usd"]))
            for offer in offers
            if offer.get("price_usd")
        ]
        reference_usd = (
            Decimal(str(median(prices))) if prices else None
        )
        reference_cny = (
            (reference_usd * rate.usd_cny).quantize(Decimal("0.01"))
            if reference_usd is not None and rate is not None
            else None
        )
        record = {
            "category": candidate.category,
            "brand": collected.get("brand") or "",
            "model": collected.get("model") or candidate.title,
            "mpn": collected.get("mpn") or "",
            "release_date": collected.get("release_date"),
            "market": market,
            "specs": copy.deepcopy(collected.get("specs") or {}),
            "price": {
                "reference_usd": str(reference_usd)
                if reference_usd is not None
                else None,
                "reference_cny": str(reference_cny)
                if reference_cny is not None
                else None,
                "offers": offers,
            },
            "exchange_rate": rate.model_dump(mode="json") if rate else None,
            "sources": _sanitize_sources(
                [*sources, target_url],
                self.secrets,
            ),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        return record, failures

    def _finalize_record(
        self,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        finalized = redact_secrets(record, self.secrets)
        finalized["sources"] = _sanitize_sources(
            finalized.get("sources", []),
            self.secrets,
        )
        finalized["content_hash"] = canonical_content_hash(finalized)
        return finalized

    @staticmethod
    def _provider_status(
        calls: list[dict[str, Any]],
    ) -> dict[str, str]:
        status: dict[str, str] = {}
        priority = {
            "failed": 4,
            "not_ready": 3,
            "skipped": 2,
            "completed": 1,
        }
        for call in calls:
            provider = call["provider"]
            incoming = call["status"]
            current = status.get(provider)
            if current is None or priority.get(incoming, 0) > priority.get(
                current,
                0,
            ):
                status[provider] = incoming
        return status
