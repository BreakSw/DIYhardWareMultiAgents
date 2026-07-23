import json
from decimal import Decimal
from pathlib import Path

from app.knowledge.models import ExchangeRate
from scripts.recover_hardware_catalog import (
    collect_recoverable_records,
    select_records_for_coverage,
)


def test_recovery_uses_relevant_archived_shopping_results_only(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw" / "batch-1" / "managed-search" / "storage.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(
        json.dumps(
            {
                "shopping_results": [
                    {
                        "title": "Lexar 2TB PCIe 5.0 NVMe SSD",
                        "product_link": "https://shop.example/lexar-ssd",
                        "source": "Example Shop",
                        "extracted_price": 200,
                    },
                    {
                        "title": "Corsair 32GB DDR5 Memory Kit",
                        "product_link": "https://shop.example/memory",
                        "source": "Example Shop",
                        "extracted_price": 100,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    records = collect_recoverable_records(
        tmp_path,
        ExchangeRate(
            usd_cny=Decimal("7.00"),
            published_at="2026-07-22",
        ),
    )

    assert len(records) == 1
    record = records[0]
    assert record["category"] == "storage"
    assert record["brand"] == "Lexar"
    assert record["price"]["reference_usd"] == "200"
    assert record["price"]["reference_cny"] == "1400.00"
    assert record["quality_level"] == "partial"
    assert record["recovery"]["source_kind"] == "archived_shopping_result"


def test_recovery_revalidates_audited_record_with_current_exchange_rate(
    tmp_path: Path,
) -> None:
    audit = tmp_path / "rejected" / "batch-1" / "hardware.jsonl"
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {
                "category": "psu",
                "brand": "Dynamic",
                "model": "Dynamic 850W ATX Power Supply",
                "specs": {},
                "price": {
                    "reference_usd": "100",
                    "reference_cny": None,
                    "offers": [
                        {
                            "merchant": "Shop",
                            "url": "https://shop.example/psu",
                            "price_usd": "100",
                            "availability": "unknown",
                            "provider": "serpapi",
                        }
                    ],
                },
                "exchange_rate": None,
                "sources": ["https://shop.example/psu"],
                "quality": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = collect_recoverable_records(
        tmp_path,
        ExchangeRate(
            usd_cny=Decimal("7.00"),
            published_at="2026-07-22",
        ),
    )

    assert len(records) == 1
    assert records[0]["exchange_rate"]["usd_cny"] == "7.00"
    assert records[0]["price"]["reference_cny"] == "700.00"
    assert "exchange_rate" not in records[0]["missing_fields"]


def test_recovery_selection_only_fills_category_shortfall() -> None:
    current = [
        {"category": "cpu", "brand": "Current", "model": f"CPU {index}"}
        for index in range(9)
    ]
    candidates = [
        {
            "category": "cpu",
            "brand": "Candidate",
            "model": f"CPU {index}",
            "quality_level": "partial",
            "missing_fields": ["cores"],
            "recovery": {"source_kind": "archived_shopping_result"},
        }
        for index in range(5)
    ]

    selected = select_records_for_coverage(current, candidates, minimum=10)

    assert len(selected) == 1
