import json
from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from app.knowledge.config import CrawlerSettings
from app.knowledge.hashing import canonical_content_hash
from app.knowledge.models import (
    Candidate,
    ExchangeRate,
    ProviderResult,
    ValidationResult,
)
from app.knowledge.pipeline import (
    HardwareKnowledgePipeline,
    ProviderSet,
    _deduplicate_offers,
)
from app.knowledge.providers.serpapi import SerpApiProvider
from app.knowledge.storage import BatchStorage
from app.knowledge.validation import REQUIRED_SPECS
from scripts.crawl_hardware_knowledge import _parser, main


def test_cli_accepts_bounded_category_coverage_controls() -> None:
    args = _parser().parse_args(
        [
            "--minimum-per-category",
            "10",
            "--max-candidates-per-category",
            "40",
        ]
    )

    assert args.minimum_per_category == 10
    assert args.max_candidates_per_category == 40


def test_serpapi_discovers_titles_from_provider_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "serpapi.com"
        assert request.url.params["engine"] == "google_shopping"
        assert request.url.params["gl"] == "us"
        assert "current generation" in request.url.params["q"]
        assert "released" in request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "shopping_results": [
                    {
                        "title": "Dynamically Discovered Graphics Card",
                        "product_link": "https://shop.example/part",
                        "source": "Example Shop",
                        "extracted_price": 199.99,
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    candidates, _ = SerpApiProvider("key", client).discover("gpu", 1)

    assert candidates[0].title == "Dynamically Discovered Graphics Card"
    assert candidates[0].price_usd == Decimal("199.99")


def test_serpapi_uses_specific_search_terms_and_filters_wrong_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "internal SSD NVMe" in request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "shopping_results": [
                    {
                        "title": "DDR5 Desktop Memory Kit",
                        "product_link": "https://shop.example/memory",
                        "extracted_price": 199.99,
                    },
                    {
                        "title": "2TB PCIe 5.0 NVMe SSD",
                        "product_link": "https://shop.example/ssd",
                        "extracted_price": 249.99,
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    candidates, _ = SerpApiProvider("key", client).discover("storage", 10)

    assert [candidate.title for candidate in candidates] == [
        "2TB PCIe 5.0 NVMe SSD"
    ]


def test_serpapi_normalizes_managed_product_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["engine"] == "google_immersive_product"
        assert request.url.params["api_key"] == "key"
        return httpx.Response(
            200,
            json={
                "product_results": {
                    "brand": "Dynamic",
                    "about_the_product": {
                        "title": "Dynamic CPU",
                        "link": "https://manufacturer.example/cpu",
                        "description": "Desktop CPU with PCIe 5.0 support.",
                        "features": [
                            {"title": "Socket Type", "value": "AM5"},
                            {"title": "Number Of Cores", "value": "8"},
                            {"title": "Number Of Threads", "value": "16"},
                            {"title": "Clock Speed", "value": "4.2 GHz"},
                            {"title": "Boost Clock Speed", "value": "5.0 GHz"},
                            {
                                "title": "Thermal Design Power (TDP)",
                                "value": "120 W",
                            },
                            {"title": "Memory Type", "value": "DDR5"},
                            {"title": "Release Date", "value": "2025-01-15"},
                        ],
                    },
                    "stores": [
                        {
                            "name": "Dynamic Store",
                            "link": "https://shop.example/cpu",
                            "extracted_price": 299.99,
                            "details_and_offers": ["In stock online"],
                        }
                    ],
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    candidate = Candidate(
        category="cpu",
        title="Dynamic CPU",
        url="https://shop.example/cpu",
        detail_url=(
            "https://serpapi.com/search.json?"
            "engine=google_immersive_product&page_token=token"
        ),
    )

    result = SerpApiProvider("key", client).details(candidate)

    assert result.status == "completed"
    assert result.data["record"]["specs"] == {
        "socket": "AM5",
        "cores": "8",
        "threads": "16",
        "base_clock": "4.2 GHz",
        "boost_clock": "5.0 GHz",
        "tdp_w": "120 W",
        "memory_types": "DDR5",
        "pcie_version": "PCIe 5.0",
    }
    assert result.data["record"]["release_date"] == "2025-01-15"
    assert result.data["offers"][0]["availability"] == "in_stock"
    assert result.data["sources"] == ["https://manufacturer.example/cpu"]


@pytest.mark.parametrize(
    ("category", "features", "extra_required"),
    [
        (
            "psu",
            [
                ("Output Wattage", "1000 W"),
                ("80 PLUS Rating", "Gold"),
                ("Form Factor", "ATX"),
                ("Supported Standards", "ATX 3.1"),
                ("Modular", "Fully Modular"),
                ("Connectors", "4 x PCIe 8-pin"),
            ],
            set(),
        ),
        (
            "cooler",
            [
                ("Cooling Type", "Air"),
                ("Socket Compatibility", "AM5, LGA1851"),
                ("Included Fans", "2"),
                ("Height", "168 mm"),
                ("Cooling TDP", "250 W"),
            ],
            {"height_mm", "rated_tdp_w"},
        ),
        (
            "case",
            [
                ("Motherboard Form Factor", "ATX, Micro ATX"),
                ("Maximum GPU Length", "455 mm"),
                ("Maximum CPU Cooler Height", "167 mm"),
                ("Radiator Support", "120, 240, 360 mm"),
                ("PSU Form Factor", "ATX"),
                ("Drive Bay Count", "6"),
            ],
            set(),
        ),
    ],
)
def test_serpapi_normalizes_additional_component_categories(
    category: str,
    features: list[tuple[str, str]],
    extra_required: set[str],
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "product_results": {
                        "about_the_product": {
                            "title": "Dynamic Part",
                            "link": "https://manufacturer.example/part",
                            "features": [
                                {"title": title, "value": value}
                                for title, value in features
                            ],
                        },
                        "stores": [
                            {
                                "name": "Store",
                                "link": "https://shop.example/part",
                                "extracted_price": 199.99,
                            }
                        ],
                    }
                },
            )
        )
    )
    candidate = Candidate(
        category=category,
        title="Dynamic Part",
        url="https://shop.example/part",
        detail_url=(
            "https://serpapi.com/search.json?"
            "engine=google_immersive_product&page_token=token"
        ),
    )

    result = SerpApiProvider("key", client).details(candidate)
    specs = result.data["record"]["specs"]

    assert REQUIRED_SPECS[category] <= set(specs)
    assert extra_required <= set(specs)


def test_serpapi_details_handles_availability_value_shapes() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "product_results": {
                        "about_the_product": {
                            "title": "Desktop Component",
                            "features": [],
                        },
                        "stores": [
                            {
                                "name": "Missing Details Store",
                                "link": "https://shop.example/missing",
                                "extracted_price": 100,
                                "details_and_offers": None,
                            },
                            {
                                "name": "Text Details Store",
                                "link": "https://shop.example/text",
                                "extracted_price": 100,
                                "details_and_offers": "In stock online",
                            },
                            {
                                "name": "List Details Store",
                                "link": "https://shop.example/list",
                                "extracted_price": 100,
                                "details_and_offers": ["Out of stock"],
                            },
                        ],
                    }
                },
            )
        )
    )
    candidate = Candidate(
        category="gpu",
        title="Desktop Component",
        url="https://shop.example/component",
        detail_url=(
            "https://serpapi.com/search.json?"
            "engine=google_immersive_product&page_token=token"
        ),
    )

    result = SerpApiProvider("key", client).details(candidate)

    assert result.status == "completed"
    assert [
        offer["availability"] for offer in result.data["offers"]
    ] == ["unknown", "in_stock", "out_of_stock"]


def test_serpapi_enrichment_queries_only_missing_fields_and_keeps_evidence(
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "serpapi.com"
        assert request.url.path == "/search.json"
        assert request.url.params["engine"] == "google"
        assert request.url.params["api_key"] == "key"
        query = request.url.params["q"]
        assert "Dynamic CPU" in query
        assert "cpu" in query
        assert "threads" in query
        assert "boost_clock" in query
        assert "socket" not in query
        assert "cores" not in query
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "title": "Dynamic CPU specifications",
                        "link": "https://manufacturer.example/cpu",
                        "snippet": "Threads: 16; Boost Clock: 5.0 GHz",
                    },
                    {
                        "title": "Dynamic CPU support",
                        "link": "https://manufacturer.example/cpu",
                        "snippet": "Socket: AM5",
                    },
                ],
                "answer_box": {
                    "answer": "Threads: 16",
                    "link": "https://manufacturer.example/cpu",
                },
                "knowledge_graph": {
                    "socket": "AM5",
                    "source": {
                        "link": "https://datasheet.example/cpu",
                    },
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = SerpApiProvider("key", client).enrich_missing_fields(
        "Dynamic CPU",
        "cpu",
        ["threads", "boost_clock"],
    )

    assert result.status == "completed"
    assert result.data["record"]["specs"] == {
        "threads": "16",
        "boost_clock": "5.0 GHz",
    }
    assert result.data["sources"] == [
        "https://manufacturer.example/cpu",
        "https://datasheet.example/cpu",
    ]
    assert set(result.data["raw"]) >= {
        "organic_results",
        "answer_box",
        "knowledge_graph",
    }


def test_serpapi_enrichment_ignores_specs_in_titles_and_descriptions(
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "organic_results": [
                        {
                            "title": "Threads: 16",
                            "description": "Boost Clock: 5.0 GHz",
                            "link": "https://manufacturer.example/cpu",
                        }
                    ],
                    "answer_box": {
                        "title": "Threads: 16",
                        "description": "Boost Clock: 5.0 GHz",
                    },
                    "knowledge_graph": {
                        "title": "Threads: 16",
                        "description": "Boost Clock: 5.0 GHz",
                    },
                },
            )
        )
    )

    result = SerpApiProvider("key", client).enrich_missing_fields(
        "Dynamic CPU",
        "cpu",
        ["threads", "boost_clock"],
    )

    assert result.status == "completed"
    assert result.data["record"]["specs"] == {}


def test_serpapi_enrichment_filters_and_redacts_sources() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "organic_results": [
                        {"link": "javascript:alert('unsafe')"},
                        {
                            "link": (
                                "https://manufacturer.example/spec?"
                                "api_key=source-secret&view=full"
                            )
                        },
                    ]
                },
            )
        )
    )

    result = SerpApiProvider("key", client).enrich_missing_fields(
        "Dynamic CPU",
        "cpu",
        ["threads"],
    )

    assert result.data["sources"] == [
        "https://manufacturer.example/spec?api_key=%2A%2A%2A&view=full"
    ]
    assert "source-secret" not in str(result.data["sources"])
    assert "javascript:" not in str(result.data["sources"])


def test_offer_deduplication_prefers_managed_detail_link() -> None:
    offers = _deduplicate_offers(
        [
            {
                "merchant": "Example Store",
                "url": "https://google.example/result",
                "price_usd": "299.99",
                "availability": "unknown",
                "provider": "serpapi",
            },
            {
                "merchant": "Example Store",
                "url": "https://store.example/product",
                "price_usd": "299.99",
                "availability": "in_stock",
                "provider": "serpapi-details",
            },
        ]
    )

    assert offers == [
        {
            "merchant": "Example Store",
            "url": "https://store.example/product",
            "price_usd": "299.99",
            "availability": "in_stock",
            "provider": "serpapi-details",
        }
    ]


class FakeSerp:
    def discover(self, category: str, limit: int):
        return (
            [
                Candidate(
                    category=category,
                    title="Dynamic CPU",
                    url="https://shop.example/cpu",
                    detail_url="https://serpapi.example/detail",
                    merchant="Shop",
                    price_usd=Decimal("299.99"),
                )
            ],
            {"shopping_results": [{"title": "Dynamic CPU"}]},
        )

    def details(self, candidate: Candidate):
        return ProviderResult(
            provider="serpapi-details",
            status="completed",
            data={"record": {}, "offers": [], "sources": []},
        )


class FakeFirecrawl:
    def fetch(self, target_url: str, schema: dict):
        return ProviderResult(
            provider="firecrawl",
            status="completed",
            data={
                "success": True,
                "data": {
                    "json": {
                        "brand": "Dynamic",
                        "model": "Dynamic CPU",
                        "mpn": "DYN-CPU",
                        "specs": {
                            "socket": "AM5",
                            "cores": "8",
                            "threads": "16",
                            "base_clock": "4.2 GHz",
                            "boost_clock": "5.0 GHz",
                            "tdp_w": "120",
                            "memory_types": "DDR5",
                            "pcie_version": "5.0",
                        },
                    }
                },
            },
        )


class FakeProductProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def extract(self, target_url: str, schema: dict):
        return ProviderResult(
            provider=self.name,
            status="completed",
            data={
                "product": {
                    "name": "Dynamic CPU",
                    "price": "289.99",
                    "currency": "USD",
                    "availability": "InStock",
                    "url": target_url,
                }
            },
        )

    def fetch(self, target_url: str):
        return ProviderResult(
            provider=self.name,
            status="completed",
            data={"url": target_url},
        )


class FakeEcb:
    def latest(self):
        return ExchangeRate(
            usd_cny=Decimal("7.2"),
            published_at="2026-07-20",
        )


class FailingEcb:
    def latest(self):
        raise RuntimeError("exchange rate unavailable")


class CompleteSerp:
    def discover(self, category: str, limit: int):
        return (
            [
                Candidate(
                    category="cpu",
                    title=f"Dynamic CPU {index}",
                    url=f"https://shop.example/cpu-{index}",
                    detail_url=f"https://serpapi.example/detail-{index}",
                    price_usd=Decimal("299.99"),
                )
                for index in range(2)
            ],
            {"shopping_results": [{"title": "Dynamic CPU"}]},
        )

    def details(self, candidate: Candidate):
        return ProviderResult(
            provider="serpapi-details",
            status="completed",
            data={
                "record": {
                    "brand": "Dynamic",
                    "model": candidate.title,
                    "specs": {
                        "socket": "AM5",
                        "cores": "8",
                        "threads": "16",
                        "base_clock": "4.2 GHz",
                        "boost_clock": "5.0 GHz",
                        "tdp_w": "120 W",
                        "memory_types": "DDR5",
                        "pcie_version": "PCIe 5.0",
                    },
                },
                "offers": [],
                "sources": ["https://manufacturer.example/cpu"],
            },
        )


class EnrichingSerp:
    def __init__(self, resolves_missing: bool = True) -> None:
        self.resolves_missing = resolves_missing
        self.enrichment_calls: list[tuple[str, str, list[str]]] = []

    def discover(self, category: str, limit: int):
        return (
            [
                Candidate(
                    category=category,
                    title="Dynamic CPU",
                    url="https://shop.example/cpu",
                    detail_url="https://serpapi.example/detail",
                    merchant="Shop",
                    price_usd=Decimal("299.99"),
                )
            ],
            {"shopping_results": [{"title": "Dynamic CPU"}]},
        )

    def details(self, candidate: Candidate):
        return ProviderResult(
            provider="serpapi-details",
            status="completed",
            data={
                "record": {
                    "brand": "Dynamic",
                    "model": candidate.title,
                    "specs": {
                        "socket": "AM5",
                        "cores": "8",
                        "threads": "16",
                        "base_clock": "4.2 GHz",
                        "tdp_w": "120 W",
                        "memory_types": "DDR5",
                        "pcie_version": "PCIe 5.0",
                    },
                },
                "offers": [],
                "sources": ["https://manufacturer.example/cpu"],
            },
        )

    def enrich_missing_fields(
        self,
        title: str,
        category: str,
        missing_fields: list[str],
    ) -> ProviderResult:
        self.enrichment_calls.append((title, category, missing_fields))
        specs = (
            {
                "boost_clock": "5.0 GHz",
                "socket": "LGA1851",
            }
            if self.resolves_missing
            else {}
        )
        return ProviderResult(
            provider="serpapi-enrichment",
            status="completed",
            data={
                "record": {"specs": specs},
                "sources": [
                    "https://manufacturer.example/cpu",
                    "https://datasheet.example/cpu",
                ],
                "raw": {
                    "organic_results": [
                        {
                            "link": "https://datasheet.example/cpu",
                            "snippet": "Boost Clock: 5.0 GHz",
                        }
                    ]
                },
            },
        )


class CoolerEnrichingSerp:
    def __init__(self) -> None:
        self.enrichment_calls: list[tuple[str, str, list[str]]] = []

    def enrich_missing_fields(
        self,
        title: str,
        category: str,
        missing_fields: list[str],
    ) -> ProviderResult:
        self.enrichment_calls.append((title, category, missing_fields))
        return ProviderResult(
            provider="serpapi-enrichment",
            status="completed",
            data={
                "record": {
                    "specs": {
                        "height_mm": "999 mm",
                        "radiator_size_mm": "360 mm",
                        "rated_tdp_w": "250 W",
                        "supported_processor_range": (
                            "Intel Core i9 / AMD Ryzen 9"
                        ),
                    }
                },
                "sources": [],
                "raw": {},
            },
        )


class TrackingCompleteSerp(CompleteSerp):
    def __init__(self) -> None:
        self.enrichment_calls = 0

    def enrich_missing_fields(
        self,
        title: str,
        category: str,
        missing_fields: list[str],
    ) -> ProviderResult:
        self.enrichment_calls += 1
        raise AssertionError("complete candidate must not be enriched")


class UnsupportedCategorySerp:
    def __init__(self) -> None:
        self.enrichment_calls = 0

    def discover(self, category: str, limit: int):
        return (
            [
                Candidate(
                    category=category,
                    title="Unsupported Part",
                    url="https://shop.example/unsupported",
                    price_usd=Decimal("99.99"),
                )
            ],
            {"shopping_results": [{"title": "Unsupported Part"}]},
        )

    def details(self, candidate: Candidate):
        return ProviderResult(
            provider="serpapi-details",
            status="completed",
            data={
                "record": {"specs": {}},
                "offers": [],
                "sources": ["https://manufacturer.example/unsupported"],
            },
        )

    def enrich_missing_fields(
        self,
        title: str,
        category: str,
        missing_fields: list[str],
    ) -> ProviderResult:
        self.enrichment_calls += 1
        raise AssertionError("empty missing fields must not be enriched")


class NoSourceSerp(CompleteSerp):
    def discover(self, category: str, limit: int):
        return (
            [
                Candidate(
                    category="cpu",
                    title="No Source CPU",
                    url="https://user:password@example.test/item",
                    price_usd=Decimal("299.99"),
                )
            ],
            {"shopping_results": [{"title": "No Source CPU"}]},
        )

    def details(self, candidate: Candidate):
        result = super().details(candidate)
        result.data["sources"] = []
        return result


class CoveragePartialSerp:
    def __init__(self) -> None:
        self.discovery_limits: list[int] = []
        self.detail_calls = 0

    def discover(self, category: str, limit: int):
        self.discovery_limits.append(limit)
        return (
            [
                Candidate(
                    category=category,
                    title=f"Coverage Part {index}",
                    url=f"https://shop.example/coverage-{index}",
                    price_usd=Decimal("99.99"),
                )
                for index in range(limit)
            ],
            {"shopping_results": []},
        )

    def details(self, candidate: Candidate):
        self.detail_calls += 1
        return ProviderResult(
            provider="serpapi-details",
            status="completed",
            data={
                "record": {"brand": "Coverage", "specs": {}},
                "offers": [],
                "sources": [str(candidate.url)],
            },
        )

    def enrich_missing_fields(
        self,
        title: str,
        category: str,
        missing_fields: list[str],
    ) -> ProviderResult:
        return ProviderResult(
            provider="serpapi-enrichment",
            status="completed",
            data={"record": {"specs": {}}, "sources": [], "raw": {}},
        )


class MixedIdentityPartialSerp(CoveragePartialSerp):
    def details(self, candidate: Candidate):
        self.detail_calls += 1
        brand = "Coverage" if candidate.title.endswith("0") else ""
        return ProviderResult(
            provider="serpapi-details",
            status="completed",
            data={
                "record": {"brand": brand, "specs": {}},
                "offers": [],
                "sources": [str(candidate.url)],
            },
        )


class InterruptAfterFirstCategorySerp(CoveragePartialSerp):
    def discover(self, category: str, limit: int):
        if category == "gpu":
            raise KeyboardInterrupt
        return super().discover(category, limit)


class RateLimitedSerp(CoveragePartialSerp):
    def details(self, candidate: Candidate):
        self.detail_calls += 1
        return ProviderResult(
            provider="serpapi-details",
            status="failed",
            status_code=429,
            error="HTTPStatusError",
        )

    def enrich_missing_fields(self, *args, **kwargs):
        raise AssertionError("rate-limited candidate must not run enrichment")


class DiscoveryRateLimitedSerp(CoveragePartialSerp):
    def discover(self, category: str, limit: int):
        request = httpx.Request("GET", "https://serpapi.com/search.json")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        )


class BillingBlockedProvider:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, target_url: str, schema: dict):
        self.calls += 1
        return ProviderResult(
            provider="firecrawl",
            status="failed",
            error="HTTPStatusError",
            status_code=402,
        )


def test_pipeline_stops_repeating_nonretryable_provider_failures(
    tmp_path: Path,
) -> None:
    blocked = BillingBlockedProvider()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=CompleteSerp(),
            firecrawl=blocked,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=2, market="US")

    assert manifest["accepted_count"] == 2
    assert blocked.calls == 1
    assert any(
        call["provider"] == "firecrawl"
        and call["status"] == "skipped"
        for call in manifest["provider_calls"]
    )


def test_coverage_mode_counts_partial_records_and_stops_at_minimum(
    tmp_path: Path,
) -> None:
    serpapi = CoveragePartialSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(
        ["cpu"],
        per_category=1,
        market="US",
        minimum_per_category=2,
        max_candidates_per_category=5,
    )

    assert serpapi.discovery_limits == [5]
    assert serpapi.detail_calls == 2
    assert manifest["coverage"]["cpu"] == 2
    partial = tmp_path / "catalog" / "current" / "partial.jsonl"
    assert len(partial.read_text(encoding="utf-8").splitlines()) == 2


def test_missing_identity_stays_in_audit_without_blocking_catalog(
    tmp_path: Path,
) -> None:
    serpapi = MixedIdentityPartialSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(
        ["cpu"],
        per_category=1,
        market="US",
        minimum_per_category=2,
        max_candidates_per_category=2,
    )

    assert manifest["coverage"]["cpu"] == 1
    assert manifest["rejected_count"] == 2
    partial = tmp_path / "catalog" / "current" / "partial.jsonl"
    records = [json.loads(line) for line in partial.read_text().splitlines()]
    assert [record["model"] for record in records] == ["Coverage Part 0"]


def test_completed_category_is_checkpointed_before_later_interruption(
    tmp_path: Path,
) -> None:
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=InterruptAfterFirstCategorySerp(),
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    with pytest.raises(KeyboardInterrupt):
        pipeline.run(
            ["cpu", "gpu"],
            per_category=1,
            market="US",
            minimum_per_category=1,
            max_candidates_per_category=1,
        )

    partial = tmp_path / "catalog" / "current" / "partial.jsonl"
    assert len(partial.read_text(encoding="utf-8").splitlines()) == 1


def test_serpapi_rate_limit_stops_batch_after_first_failed_detail(
    tmp_path: Path,
) -> None:
    serpapi = RateLimitedSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(
        ["cpu", "gpu"],
        per_category=1,
        market="US",
        minimum_per_category=2,
        max_candidates_per_category=5,
    )

    assert serpapi.detail_calls == 1
    assert manifest["status"] == "degraded"
    assert manifest["degraded_reason"] == "serpapi_rate_limited"


def test_serpapi_discovery_rate_limit_writes_degraded_manifest(
    tmp_path: Path,
) -> None:
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=DiscoveryRateLimitedSerp(),
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(
        ["cpu", "gpu"],
        per_category=1,
        market="US",
        minimum_per_category=2,
        max_candidates_per_category=5,
    )

    assert manifest["status"] == "degraded"
    assert manifest["degraded_reason"] == "serpapi_rate_limited"
    assert len([c for c in manifest["provider_calls"] if c["provider"] == "serpapi"]) == 1


def test_pipeline_writes_complete_dynamic_record(tmp_path: Path) -> None:
    providers = ProviderSet(
        serpapi=FakeSerp(),
        firecrawl=FakeFirecrawl(),
        zyte=FakeProductProvider("zyte"),
        brightdata=FakeProductProvider("brightdata"),
        apify=FakeProductProvider("apify"),
        ecb=FakeEcb(),
    )
    pipeline = HardwareKnowledgePipeline(
        providers=providers,
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=1, market="US")

    assert manifest["accepted_count"] == 1
    assert manifest["rejected_count"] == 0
    normalized = next((tmp_path / "normalized").rglob("hardware.jsonl"))
    content = normalized.read_text(encoding="utf-8")
    assert "Dynamic CPU" in content
    assert '"reference_cny"' in content
    assert {
        item["provider"] for item in manifest["provider_calls"]
    } >= {
        "serpapi",
        "serpapi-details",
        "firecrawl",
        "zyte",
        "brightdata",
        "apify",
        "ecb",
    }


def test_pipeline_enriches_missing_fields_once_and_revalidates(
    tmp_path: Path,
) -> None:
    serpapi = EnrichingSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=1, market="US")

    assert manifest["accepted_count"] == 1
    assert serpapi.enrichment_calls == [
        ("Dynamic CPU", "cpu", ["boost_clock"])
    ]
    enrichment_call = next(
        call
        for call in manifest["provider_calls"]
        if call["provider"] == "serpapi-enrichment"
    )
    assert enrichment_call["status"] == "completed"
    assert enrichment_call["missing_fields"] == ["boost_clock"]
    raw_path = next(
        (tmp_path / "raw").rglob("serpapi-enrichment/*.json")
    )
    assert "organic_results" in json.loads(
        raw_path.read_text(encoding="utf-8")
    )
    normalized = next((tmp_path / "normalized").rglob("hardware.jsonl"))
    record = json.loads(normalized.read_text(encoding="utf-8").splitlines()[0])
    assert record["quality"]["quality_level"] == "verified"
    assert record["specs"]["boost_clock"] == "5.0 GHz"
    assert record["specs"]["socket"] == "AM5"
    assert record["sources"] == [
        "https://manufacturer.example/cpu",
        "https://datasheet.example/cpu",
    ]
    assert record["content_hash"] == canonical_content_hash(record)


def test_pipeline_does_not_repeat_unresolved_enrichment(
    tmp_path: Path,
) -> None:
    serpapi = EnrichingSerp(resolves_missing=False)
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=1, market="US")

    assert manifest["accepted_count"] == 0
    assert manifest["rejected_count"] == 1
    assert len(serpapi.enrichment_calls) == 1


def test_pipeline_enrichment_queries_only_required_spec_fields(
    tmp_path: Path,
) -> None:
    serpapi = EnrichingSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )
    record = {
        "specs": {"socket": "AM5"},
        "price": {"offers": []},
        "sources": [],
    }
    calls: list[dict] = []

    pipeline._enrich_candidate(
        Candidate(
            category="cpu",
            title="Dynamic CPU",
            url="https://shop.example/cpu",
        ),
        record,
        ValidationResult(
            accepted=False,
            quality_level="partial",
            missing_fields=[
                "boost_clock",
                "usd_price_offer",
                "source",
                "exchange_rate",
            ],
        ),
        BatchStorage(tmp_path, "mixed-missing", []),
        calls,
        [],
    )

    assert serpapi.enrichment_calls == [
        ("Dynamic CPU", "cpu", ["boost_clock"])
    ]
    assert calls[0]["missing_fields"] == ["boost_clock"]
    assert record["specs"]["socket"] == "AM5"
    assert record["specs"]["boost_clock"] == "5.0 GHz"


def test_pipeline_skips_enrichment_for_empty_required_spec_intersection(
    tmp_path: Path,
) -> None:
    serpapi = EnrichingSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )
    validation = ValidationResult(
        accepted=False,
        quality_level="partial",
        missing_fields=["usd_price_offer", "source", "exchange_rate"],
    )
    calls: list[dict] = []

    result = pipeline._enrich_candidate(
        Candidate(
            category="cpu",
            title="Dynamic CPU",
            url="https://shop.example/cpu",
        ),
        {"specs": {}, "price": {"offers": []}, "sources": []},
        validation,
        BatchStorage(tmp_path, "metadata-only", []),
        calls,
        [],
    )

    assert result is validation
    assert serpapi.enrichment_calls == []
    assert calls == []
    assert not (tmp_path / "raw").exists()


def test_pipeline_expands_cooler_composite_missing_fields_once(
    tmp_path: Path,
) -> None:
    serpapi = CoolerEnrichingSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )
    record = {
        "specs": {
            "cooler_type": "Air Cooler",
            "supported_sockets": "AM5",
            "fan_count": "1",
            "height_mm": "160 mm",
        },
        "price": {
            "offers": [
                {
                    "price_usd": "99",
                    "availability": "in_stock",
                    "url": "https://shop.example/cooler",
                }
            ]
        },
        "sources": ["https://manufacturer.example/cooler"],
    }

    pipeline._enrich_candidate(
        Candidate(
            category="cooler",
            title="Dynamic Cooler",
            url="https://shop.example/cooler",
        ),
        record,
        ValidationResult(
            accepted=False,
            quality_level="partial",
            missing_fields=[
                "height_mm_or_radiator_size_mm",
                "rated_tdp_w_or_supported_processor_range",
            ],
        ),
        BatchStorage(tmp_path, "cooler-composite", []),
        [],
        [],
    )

    assert serpapi.enrichment_calls == [
        (
            "Dynamic Cooler",
            "cooler",
            [
                "radiator_size_mm",
                "rated_tdp_w",
                "supported_processor_range",
            ],
        )
    ]
    assert record["specs"]["height_mm"] == "160 mm"
    assert record["specs"]["radiator_size_mm"] == "360 mm"
    assert record["specs"]["rated_tdp_w"] == "250 W"
    assert len(serpapi.enrichment_calls) == 1


def test_pipeline_skips_enrichment_for_verified_candidate(
    tmp_path: Path,
) -> None:
    serpapi = TrackingCompleteSerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=1, market="US")

    assert manifest["accepted_count"] == 1
    assert serpapi.enrichment_calls == 0
    assert all(
        call["provider"] != "serpapi-enrichment"
        for call in manifest["provider_calls"]
    )


def test_pipeline_skips_enrichment_when_validation_has_no_missing_fields(
    tmp_path: Path,
) -> None:
    serpapi = UnsupportedCategorySerp()
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=serpapi,
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(
        ["unsupported"],
        per_category=1,
        market="US",
    )

    assert manifest["accepted_count"] == 0
    assert manifest["rejected_count"] == 1
    assert serpapi.enrichment_calls == 0
    assert all(
        call["provider"] != "serpapi-enrichment"
        for call in manifest["provider_calls"]
    )
    rejected = next((tmp_path / "rejected").rglob("hardware.jsonl"))
    audited = json.loads(rejected.read_text(encoding="utf-8").splitlines()[0])
    assert audited["reason"] == "unsupported_category"
    assert audited["reason_code"] == "unsupported_category"
    assert not (tmp_path / "catalog" / "current").exists()


def test_pipeline_marks_missing_exchange_rate_as_partial(
    tmp_path: Path,
) -> None:
    providers = ProviderSet(
        serpapi=FakeSerp(),
        firecrawl=FakeFirecrawl(),
        zyte=FakeProductProvider("zyte"),
        brightdata=FakeProductProvider("brightdata"),
        apify=FakeProductProvider("apify"),
        ecb=FailingEcb(),
    )
    pipeline = HardwareKnowledgePipeline(
        providers=providers,
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=1, market="US")

    assert manifest["accepted_count"] == 0
    rejected = next((tmp_path / "rejected").rglob("hardware.jsonl"))
    record = json.loads(rejected.read_text(encoding="utf-8").splitlines()[0])
    assert record["quality"]["complete"] is False
    assert record["quality"]["quality_level"] == "partial"
    assert "exchange_rate" in record["quality"]["missing_fields"]
    assert record["reason"] == "missing_required_data"
    assert record["reason_code"] == "missing_required_data"
    assert record["missing_fields"] == record["quality"]["missing_fields"]

    current = tmp_path / "catalog" / "current"
    partial = json.loads(
        (current / "partial.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert partial["quality_level"] == "partial"
    assert partial["missing_fields"] == partial["quality"]["missing_fields"]
    assert partial["quality"]["missing_fields"] == record["quality"]["missing_fields"]
    assert partial["reason"] == "missing_required_data"
    assert partial["reason_code"] == "missing_required_data"
    assert (tmp_path / "rejected").is_dir()
    assert (current / "verified.jsonl").read_text(encoding="utf-8") == ""


def test_pipeline_keeps_partial_without_http_source_only_in_audit(
    tmp_path: Path,
) -> None:
    pipeline = HardwareKnowledgePipeline(
        providers=ProviderSet(
            serpapi=NoSourceSerp(),
            firecrawl=None,
            zyte=None,
            brightdata=None,
            apify=None,
            ecb=FakeEcb(),
        ),
        output_root=tmp_path,
        secrets=[],
    )

    manifest = pipeline.run(["cpu"], per_category=1, market="US")

    assert manifest["accepted_count"] == 0
    assert manifest["rejected_count"] == 1
    rejected = next((tmp_path / "rejected").rglob("hardware.jsonl"))
    record = json.loads(rejected.read_text(encoding="utf-8").splitlines()[0])
    assert record["reason"] == "missing_required_data"
    assert "source" in record["missing_fields"]
    assert not (tmp_path / "catalog" / "current").exists()


def test_cli_dry_run_does_not_call_network(
    tmp_path: Path,
    capsys,
) -> None:
    env = tmp_path / ".env"
    env.write_text("serpapi-key=ready\n", encoding="utf-8")
    exit_code = main(
        ["--dry-run", "--env-file", str(env)],
        settings_override=CrawlerSettings.from_env(env),
    )

    assert exit_code == 0
    assert "managed providers only" in capsys.readouterr().out


def test_cli_can_run_as_a_direct_script(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("serpapi-key=ready\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/crawl_hardware_knowledge.py",
            "--dry-run",
            "--env-file",
            str(env),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "managed providers only" in result.stdout
