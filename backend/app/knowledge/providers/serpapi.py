from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from app.knowledge.http import create_managed_client, safe_http_status
from app.knowledge.models import Candidate
from app.knowledge.models import ProviderResult
from app.knowledge.normalization import (
    extract_release_date,
    extract_search_specs,
    normalize_specs,
    sanitize_source_url,
)
from app.knowledge.validation import is_category_relevant


_CATEGORY_SEARCH_TERMS: dict[str, str] = {
    "cpu": "desktop CPU processor",
    "gpu": "desktop graphics card GPU",
    "motherboard": "desktop PC motherboard",
    "memory": "desktop RAM memory kit DDR5 DDR4",
    "storage": "internal SSD NVMe SATA hard drive",
    "psu": "ATX PC power supply PSU",
    "cooler": "CPU air liquid cooler AIO",
    "case": "desktop PC case chassis",
}


def _availability(store: dict[str, Any]) -> str:
    value = store.get("details_and_offers")
    if isinstance(value, list):
        details = " ".join(str(item) for item in value)
    elif value is None:
        details = ""
    else:
        details = str(value)
    details = details.lower()
    if "out of stock" in details:
        return "out_of_stock"
    if "in stock" in details:
        return "in_stock"
    return "unknown"


def _search_sources(payload: dict[str, Any]) -> list[str]:
    sources: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key == "link"
                    and isinstance(item, str)
                    and item.strip()
                ):
                    source = sanitize_source_url(item)
                    if source is not None:
                        sources.append(source)
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for section in (
        payload.get("organic_results"),
        payload.get("answer_box"),
        payload.get("knowledge_graph"),
    ):
        visit(section)
    return list(dict.fromkeys(sources))


class SerpApiProvider:
    endpoint = "https://serpapi.com/search.json"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or create_managed_client()

    def discover(
        self,
        category: str,
        limit: int,
    ) -> tuple[list[Candidate], dict[str, Any]]:
        year = datetime.now(UTC).year
        component_terms = _CATEGORY_SEARCH_TERMS.get(category, category)
        query = (
            f"latest current generation {component_terms} component "
            f"released {year - 1} {year} new"
        )
        response = self.client.get(
            self.endpoint,
            params={
                "engine": "google_shopping",
                "q": query,
                "api_key": self.api_key,
                "gl": "us",
                "hl": "en",
                "num": max(limit, 3),
            },
        )
        response.raise_for_status()
        payload = response.json()
        candidates: list[Candidate] = []
        for position, item in enumerate(
            payload.get("shopping_results", []),
            start=1,
        ):
            url = (
                item.get("product_link")
                or item.get("link")
                or item.get("serpapi_product_api")
            )
            title = str(item.get("title") or "").strip()
            if not url or not title or not is_category_relevant(category, title):
                continue
            price = item.get("extracted_price")
            candidates.append(
                Candidate(
                    category=category,
                    title=title,
                    url=url,
                    detail_url=item.get("serpapi_immersive_product_api"),
                    merchant=str(item.get("source") or ""),
                    price_usd=(
                        Decimal(str(price)) if price is not None else None
                    ),
                    position=position,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates, payload

    def details(self, candidate: Candidate) -> ProviderResult:
        started = time.perf_counter()
        if candidate.detail_url is None:
            return ProviderResult(
                provider="serpapi-details",
                status="not_ready",
                error="missing_detail_url",
            )
        try:
            parts = urlsplit(str(candidate.detail_url))
            params = dict(parse_qsl(parts.query))
            params["api_key"] = self.api_key
            response = self.client.get(self.endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
            product = payload.get("product_results", {})
            about = product.get("about_the_product", {})
            features = about.get("features", [])
            specs = normalize_specs(
                candidate.category,
                features,
                title=" ".join(
                    filter(
                        None,
                        (
                            candidate.title,
                            str(about.get("title") or ""),
                        ),
                    )
                ),
                description=str(about.get("description") or ""),
            )
            release_date = extract_release_date(features)
            offers = [
                {
                    "merchant": str(store.get("name") or "serpapi-store"),
                    "url": store.get("link"),
                    "price_usd": str(store.get("extracted_price")),
                    "availability": _availability(store),
                    "provider": "serpapi-details",
                }
                for store in product.get("stores", [])
                if isinstance(store, dict)
                and store.get("link")
                and store.get("extracted_price") is not None
            ]
            source = sanitize_source_url(
                about.get("link") if isinstance(about, dict) else None
            )
            sources = [source] if source is not None else []
            return ProviderResult(
                provider="serpapi-details",
                status="completed",
                data={
                    "record": {
                        "brand": product.get("brand") or "",
                        "model": about.get("title") or candidate.title,
                        "mpn": "",
                        "release_date": release_date,
                        "specs": specs,
                    },
                    "offers": offers,
                    "sources": sources,
                    "raw": payload,
                },
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ProviderResult(
                provider="serpapi-details",
                status="failed",
                error=type(exc).__name__,
                status_code=safe_http_status(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

    def enrich_missing_fields(
        self,
        title: str,
        category: str,
        missing_fields: list[str],
    ) -> ProviderResult:
        started = time.perf_counter()
        requested = list(
            dict.fromkeys(
                field.strip()
                for field in missing_fields
                if field and field.strip()
            )
        )
        if not requested:
            return ProviderResult(
                provider="serpapi-enrichment",
                status="completed",
                data={
                    "record": {"specs": {}},
                    "sources": [],
                    "raw": {},
                },
            )
        try:
            response = self.client.get(
                self.endpoint,
                params={
                    "engine": "google",
                    "q": " ".join((title, category, *requested)),
                    "api_key": self.api_key,
                    "gl": "us",
                    "hl": "en",
                },
            )
            response.raise_for_status()
            payload = response.json()
            return ProviderResult(
                provider="serpapi-enrichment",
                status="completed",
                data={
                    "record": {
                        "specs": extract_search_specs(
                            category,
                            requested,
                            payload,
                        )
                    },
                    "sources": _search_sources(payload),
                    "raw": payload,
                },
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ProviderResult(
                provider="serpapi-enrichment",
                status="failed",
                error=type(exc).__name__,
                status_code=safe_http_status(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
