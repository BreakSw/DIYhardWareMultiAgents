from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.knowledge.config import CrawlerSettings
from app.knowledge.http import create_managed_client, redact_secrets
from app.knowledge.models import ValidationResult
from app.knowledge.providers.ecb import EcbProvider
from app.knowledge.validation import is_category_relevant, validate_hardware


@pytest.mark.parametrize(
    ("category", "title", "expected"),
    [
        ("storage", "Crucial T705 PCIe Gen5 NVMe M.2 SSD", True),
        ("storage", "Corsair Vengeance 32GB DDR5 Memory Kit", False),
        ("cpu", "AMD Ryzen 9 Desktop Processor", True),
        ("cpu", "iBUYPOWER Gaming Desktop PC", False),
        ("motherboard", "MSI Motherboard CPU Memory Combo", True),
        ("psu", "850W ATX 3.1 Fully Modular Power Supply", True),
        ("cooler", "360mm AIO Liquid CPU Cooler", True),
        ("case", "Dual-Chamber Mid-Tower PC Case", True),
    ],
)
def test_category_relevance_rejects_cross_category_search_results(
    category: str,
    title: str,
    expected: bool,
) -> None:
    assert is_category_relevant(category, title) is expected


def test_crawler_settings_detect_placeholders(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "serpapi-key=ready\n"
        "apify-api-token=<FILL_APIFY_API_TOKEN>\n"
        "brightdata-api-token=ready\n"
        "brightdata-zone=<FILL_BRIGHTDATA_ZONE>\n",
        encoding="utf-8",
    )

    settings = CrawlerSettings.from_env(env)

    assert settings.provider_ready("serpapi")
    assert not settings.provider_ready("apify")
    assert not settings.provider_ready("brightdata")


def test_recursive_redaction_removes_credentials() -> None:
    redacted = redact_secrets(
        {
            "Authorization": "Bearer private-token",
            "url": "https://example.test?q=1&api_key=private-token",
            "nested": [{"token": "private-token"}],
        },
        secrets=["private-token"],
    )

    assert "private-token" not in str(redacted)
    assert "api_key=%2A%2A%2A" in redacted["url"]


def test_recursive_redaction_covers_oauth_and_api_header_keys() -> None:
    redacted = redact_secrets(
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "client_secret": "client-secret",
            "x-api-key": "header-secret",
            "X_API_KEY": "alternate-header-secret",
        }
    )

    assert set(redacted.values()) == {"***"}


def test_url_redaction_rejects_userinfo_and_clears_fragment() -> None:
    redacted = redact_secrets(
        {
            "userinfo": "https://user:password@example.test/spec#token=secret",
            "fragment": (
                "https://example.test/spec?access_token=secret#client_secret=hidden"
            ),
        }
    )

    assert redacted["userinfo"] == ""
    assert redacted["fragment"] == (
        "https://example.test/spec?access_token=%2A%2A%2A"
    )


def test_managed_client_uses_system_proxy_and_certificate_settings() -> None:
    client = create_managed_client()
    try:
        assert client._trust_env is True
    finally:
        client.close()


def test_ecb_provider_derives_usd_cny() -> None:
    xml = (
        b"<Envelope><Cube><Cube time='2026-07-20'>"
        b"<Cube currency='USD' rate='1.2'/>"
        b"<Cube currency='CNY' rate='7.8'/>"
        b"</Cube></Cube></Envelope>"
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=xml)
        )
    )

    result = EcbProvider(client).latest()

    assert result.usd_cny == Decimal("6.5")
    assert result.published_at == "2026-07-20"


def test_gpu_missing_length_is_rejected() -> None:
    result = validate_hardware(
        category="gpu",
        specs={
            "chipset": "Example",
            "vram_gb": 16,
            "memory_type": "GDDR7",
            "tdp_w": 250,
            "power_connectors": ["16-pin"],
            "recommended_psu_w": 750,
        },
        offers=[
            {
                "price_usd": 599.99,
                "availability": "in_stock",
                "url": "https://shop.example/item",
            }
        ],
        sources=["https://manufacturer.example/spec"],
    )

    assert not result.accepted
    assert "length_mm" in result.missing_fields


def test_complete_cpu_record_is_verified() -> None:
    result = validate_hardware(
        category="cpu",
        specs={
            "socket": "AM5",
            "cores": 8,
            "threads": 16,
            "base_clock": "4.2 GHz",
            "boost_clock": "5.0 GHz",
            "tdp_w": 120,
            "memory_types": ["DDR5"],
            "pcie_version": "5.0",
        },
        offers=[
            {
                "price_usd": 399.99,
                "availability": "in_stock",
                "url": "https://shop.example/cpu",
            }
        ],
        sources=["https://manufacturer.example/cpu"],
    )

    assert result.quality_level == "verified"
    assert result.accepted
    assert result.reason_code == ""
    assert result.missing_fields == []


def test_socket_only_cpu_record_is_partial() -> None:
    result = validate_hardware(
        category="cpu",
        specs={"socket": "AM5"},
        offers=[
            {
                "price_usd": 399.99,
                "availability": "in_stock",
                "url": "https://shop.example/cpu",
            }
        ],
        sources=["https://manufacturer.example/cpu"],
    )

    assert result.quality_level == "partial"
    assert not result.accepted
    assert result.reason_code == "missing_required_data"
    assert "socket" not in result.missing_fields
    assert "cores" in result.missing_fields


def test_validation_result_rejects_unknown_quality_level() -> None:
    with pytest.raises(ValidationError):
        ValidationResult(
            accepted=True,
            quality_level="unknown",
        )


def test_validation_result_rejects_contradictory_construction() -> None:
    with pytest.raises(ValidationError):
        ValidationResult(
            accepted=True,
            quality_level="partial",
        )


def test_validation_result_rejects_contradictory_assignment() -> None:
    result = ValidationResult(
        accepted=True,
        quality_level="verified",
    )

    with pytest.raises(ValidationError):
        result.accepted = False

    assert result.accepted
    assert result.quality_level == "verified"
