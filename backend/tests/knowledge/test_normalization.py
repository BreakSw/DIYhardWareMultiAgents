from __future__ import annotations

import importlib
from typing import Any

import httpx
import pytest

from app.knowledge.models import Candidate
from app.knowledge.providers.serpapi import SerpApiProvider


def _normalize_specs(
    category: str,
    features: list[dict[str, Any]],
    *,
    title: str = "",
    description: str = "",
) -> dict[str, Any]:
    normalization = importlib.import_module("app.knowledge.normalization")
    return normalization.normalize_specs(
        category,
        features,
        title=title,
        description=description,
    )


def _extract_search_specs(
    category: str,
    missing_fields: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalization = importlib.import_module("app.knowledge.normalization")
    return normalization.extract_search_specs(
        category,
        missing_fields,
        payload,
    )


def test_sanitize_source_url_rejects_userinfo_and_removes_fragment() -> None:
    normalization = importlib.import_module("app.knowledge.normalization")

    assert normalization.sanitize_source_url(
        "https://user:password@host/#access_token=secret"
    ) is None
    assert normalization.sanitize_source_url(
        "https://host/spec?view=full#access_token=secret"
    ) == "https://host/spec?view=full"


@pytest.mark.parametrize(
    ("category", "features", "title", "description", "expected"),
    [
        (
            "cpu",
            [
                {"title": "CPU Socket:", "value": "AM5"},
                {"title": "Number of Cores", "value": "8"},
                {"title": "Number of Threads", "value": "16"},
                {"title": "Base Clock Speed", "value": "4.2 GHz"},
                {"title": "Max Boost Clock", "value": "5.0 GHz"},
                {"title": "Thermal Design Power (TDP)", "value": "120 W"},
                {"title": "RAM Type", "value": "DDR5"},
            ],
            "Desktop Processor",
            "Desktop processor with PCIe 5.0 support.",
            {
                "socket": "AM5",
                "cores": "8",
                "threads": "16",
                "base_clock": "4.2 GHz",
                "boost_clock": "5.0 GHz",
                "tdp_w": "120 W",
                "memory_types": "DDR5",
                "pcie_version": "PCIe 5.0",
            },
        ),
        (
            "gpu",
            [
                {"title": "GPU Chipset", "value": "Graphics Processor"},
                {"title": "Video Memory Type", "value": "GDDR7"},
                {"title": "GPU TDP", "value": "300 W"},
                {"title": "Length", "value": "12.5 in"},
                {"title": "Power Connectors", "value": "2 x 8-pin"},
                {"title": "Recommended PSU", "value": "750 W"},
            ],
            "Graphics Card OC 16G",
            "",
            {
                "chipset": "Graphics Processor",
                "vram_gb": "16",
                "memory_type": "GDDR7",
                "tdp_w": "300 W",
                "length_mm": "317.5",
                "power_connectors": "2 x 8-pin",
                "recommended_psu_w": "750 W",
            },
        ),
        (
            "motherboard",
            [
                {"title": "Processor Socket", "value": "LGA1851"},
                {"title": "Motherboard Chipset", "value": "Desktop Chipset"},
                {"title": "Motherboard Form-Factor", "value": "ATX"},
                {"title": "Supported Memory", "value": "DDR5"},
                {"title": "DIMM Slots", "value": "4"},
                {"title": "Maximum Memory Capacity", "value": "192 GB"},
                {
                    "title": "PCI Express Slots",
                    "value": "1 x PCIe 5.0 x16, 2 x PCIe x1",
                },
                {"title": "Number of M.2 Slots", "value": "4"},
            ],
            "Desktop Motherboard",
            "",
            {
                "socket": "LGA1851",
                "chipset": "Desktop Chipset",
                "form_factor": "ATX",
                "memory_type": "DDR5",
                "memory_slots": "4",
                "max_memory_gb": "192",
                "pcie_slots": "1 x PCIe 5.0 x16, 2 x PCIe x1",
                "m2_slots": "4",
            },
        ),
        (
            "memory",
            [{"title": "Operating Voltage", "value": "1.35 V"}],
            "DDR5 64 GB Kit (2 x 32 GB) 6000 MT/s CL30",
            "",
            {
                "memory_type": "DDR5",
                "total_capacity_gb": "64",
                "module_count": "2",
                "speed_mt_s": "6000",
                "cas_latency": "CL30",
                "voltage": "1.35 V",
            },
        ),
        (
            "storage",
            [
                {"title": "Drive Form Factor", "value": "M.2 2280"},
                {"title": "Bus Interface", "value": "PCIe 4.0 x4"},
                {"title": "Maximum Sequential Read", "value": "7.4 GB/s"},
                {"title": "Maximum Sequential Write", "value": "6,900 MB/s"},
                {"title": "Terabytes Written", "value": "1,200 TBW"},
            ],
            "2 TB Solid State Drive",
            "Uses the NVMe 2.0 protocol.",
            {
                "capacity_gb": "2000",
                "form_factor": "M.2 2280",
                "interface": "PCIe 4.0 x4",
                "protocol": "NVMe 2.0",
                "sequential_read_mb_s": "7400",
                "sequential_write_mb_s": "6900",
                "endurance_tbw": "1200",
            },
        ),
        (
            "psu",
            [
                {"title": "Continuous Power", "value": "1000 W"},
                {"title": "80 PLUS Rating", "value": "Gold"},
                {"title": "Form Factor", "value": "ATX"},
                {"title": "Supported Standards", "value": "ATX 3.1"},
                {"title": "Modular", "value": "Fully Modular"},
                {"title": "Cables", "value": "4 x PCIe 8-pin"},
            ],
            "Desktop Power Supply",
            "",
            {
                "wattage_w": "1000 W",
                "efficiency_rating": "Gold",
                "form_factor": "ATX",
                "atx_version": "ATX 3.1",
                "modular_type": "Fully Modular",
                "pcie_connectors": "4 x PCIe 8-pin",
            },
        ),
        (
            "cooler",
            [
                {"title": "Cooling Type", "value": "Air"},
                {"title": "Socket Compatibility", "value": "AM5, LGA1851"},
                {"title": "Included Fans", "value": "2"},
                {"title": "Height", "value": "6.5 in"},
                {"title": "Cooling Capacity", "value": "250 W"},
            ],
            "Desktop CPU Cooler",
            "",
            {
                "cooler_type": "Air",
                "supported_sockets": "AM5, LGA1851",
                "fan_count": "2",
                "height_mm": "165.1",
                "rated_tdp_w": "250 W",
            },
        ),
        (
            "case",
            [
                {"title": "Motherboard Form Factor", "value": "ATX, Micro ATX"},
                {"title": "GPU Length Support", "value": "45.5 cm"},
                {"title": "CPU Cooler Height Support", "value": "167 mm"},
                {"title": "Radiator Support", "value": "120, 240, 360 mm"},
                {"title": "PSU Form Factor", "value": "ATX"},
                {"title": "Maximum Storage Drive Count", "value": "6"},
            ],
            "Desktop Computer Case",
            "",
            {
                "supported_motherboard_form_factors": "ATX, Micro ATX",
                "max_gpu_length_mm": "455",
                "max_cooler_height_mm": "167",
                "supported_radiators": "120, 240, 360 mm",
                "psu_form_factor": "ATX",
                "drive_bays": "6",
            },
        ),
    ],
)
def test_normalize_specs_for_supported_categories(
    category: str,
    features: list[dict[str, Any]],
    title: str,
    description: str,
    expected: dict[str, Any],
) -> None:
    assert _normalize_specs(
        category,
        features,
        title=title,
        description=description,
    ) == expected


def test_extract_release_date_uses_normalized_feature_keys() -> None:
    normalization = importlib.import_module("app.knowledge.normalization")

    assert normalization.extract_release_date(
        [{"title": "CPU Release-Date", "value": "2026-01-15"}]
    ) == "2026-01-15"


@pytest.mark.parametrize(
    ("category", "missing_fields", "payload"),
    [
        (
            "memory",
            ["memory_type"],
            {"answer_box": {"type": "organic_result"}},
        ),
        (
            "storage",
            ["capacity_gb"],
            {
                "knowledge_graph": {
                    "metadata": {"capacity": "unknown"}
                }
            },
        ),
    ],
)
def test_search_specs_ignore_unapproved_structured_scalars(
    category: str,
    missing_fields: list[str],
    payload: dict[str, Any],
) -> None:
    assert _extract_search_specs(
        category,
        missing_fields,
        payload,
    ) == {}


@pytest.mark.parametrize(
    "row",
    [
        ["Storage Capacity", "2 TB"],
        ("Storage Capacity", "2 TB"),
    ],
)
def test_search_specs_accept_approved_answer_box_table_rows(
    row: list[str] | tuple[str, str],
) -> None:
    specs = _extract_search_specs(
        "storage",
        ["capacity_gb"],
        {
            "answer_box": {
                "type": "organic_result",
                "contents": {
                    "table": [row]
                },
            }
        },
    )

    assert specs == {"capacity_gb": "2000"}


def test_search_specs_reject_answer_box_table_dict_rows() -> None:
    specs = _extract_search_specs(
        "storage",
        ["capacity_gb"],
        {
            "answer_box": {
                "contents": {
                    "table": [
                        {
                            "name": "Storage Capacity",
                            "value": "2 TB",
                            "metadata": "extra",
                        }
                    ]
                }
            }
        },
    )

    assert specs == {}


def test_search_specs_accept_root_canonical_fields() -> None:
    specs = _extract_search_specs(
        "storage",
        ["capacity_gb"],
        {"knowledge_graph": {"capacity_gb": "2 TB"}},
    )

    assert specs == {"capacity_gb": "2000"}


@pytest.mark.parametrize(
    ("category", "missing_fields", "snippet"),
    [
        (
            "memory",
            ["memory_type"],
            "Type: Laptop; Memory Type: Laptop",
        ),
        (
            "gpu",
            ["length_mm"],
            "Length: 2 years; GPU Length: 2 years",
        ),
    ],
)
def test_search_specs_reject_generic_labels_and_invalid_values(
    category: str,
    missing_fields: list[str],
    snippet: str,
) -> None:
    assert _extract_search_specs(
        category,
        missing_fields,
        {"organic_results": [{"snippet": snippet}]},
    ) == {}


@pytest.mark.parametrize(
    ("category", "missing_fields", "snippet", "expected"),
    [
        (
            "memory",
            ["memory_type"],
            "Memory Type: DDR5",
            {"memory_type": "DDR5"},
        ),
        (
            "gpu",
            ["length_mm"],
            "GPU Length: 320 mm",
            {"length_mm": "320"},
        ),
    ],
)
def test_search_specs_accept_semantically_valid_values(
    category: str,
    missing_fields: list[str],
    snippet: str,
    expected: dict[str, Any],
) -> None:
    assert _extract_search_specs(
        category,
        missing_fields,
        {"organic_results": [{"snippet": snippet}]},
    ) == expected


@pytest.mark.parametrize(
    ("category", "missing_field", "snippet"),
    [
        ("motherboard", "socket", "Socket: Laptop"),
        ("motherboard", "chipset", "Chipset: Laptop"),
        ("motherboard", "form_factor", "Form Factor: Laptop"),
        ("storage", "interface", "Interface: Warranty"),
        ("storage", "protocol", "Protocol: Fast"),
        ("psu", "modular_type", "Modular Type: Laptop"),
        ("cooler", "cooler_type", "Cooler Type: Laptop"),
        ("cooler", "supported_sockets", "Supported Sockets: Laptop"),
    ],
)
def test_search_specs_reject_high_risk_field_text(
    category: str,
    missing_field: str,
    snippet: str,
) -> None:
    assert _extract_search_specs(
        category,
        [missing_field],
        {"organic_results": [{"snippet": snippet}]},
    ) == {}


def test_search_specs_normalize_memory_type_token() -> None:
    specs = _extract_search_specs(
        "memory",
        ["memory_type"],
        {
            "organic_results": [
                {"snippet": "Memory Type: Laptop with DDR5 support"}
            ]
        },
    )

    assert specs == {"memory_type": "DDR5"}


@pytest.mark.parametrize(
    ("category", "value"),
    [
        ("motherboard", "GDDR7"),
        ("gpu", "DDR5"),
    ],
)
def test_search_specs_reject_cross_category_memory_types(
    category: str,
    value: str,
) -> None:
    assert _extract_search_specs(
        category,
        ["memory_type"],
        {
            "organic_results": [
                {"snippet": f"Memory Type: {value}"}
            ]
        },
    ) == {}


@pytest.mark.parametrize("value", ["SFX", "SFX-L", "ATX"])
def test_search_specs_accept_psu_form_factors(value: str) -> None:
    assert _extract_search_specs(
        "psu",
        ["form_factor"],
        {
            "organic_results": [
                {"snippet": f"Form Factor: {value}"}
            ]
        },
    ) == {"form_factor": value}


def test_search_specs_accept_supported_processor_range() -> None:
    specs = _extract_search_specs(
        "cooler",
        ["supported_processor_range"],
        {
            "organic_results": [
                {
                    "snippet": (
                        "Supported Processor Range: "
                        "Intel Core i9 / AMD Ryzen 9"
                    )
                }
            ]
        },
    )

    assert specs == {
        "supported_processor_range": "Intel Core i9 / AMD Ryzen 9"
    }


def test_memory_title_derives_total_capacity_from_module_configuration() -> None:
    specs = _normalize_specs(
        "memory",
        [],
        title="DDR5 2 x 32 GB",
    )

    assert specs["total_capacity_gb"] == "64"
    assert specs["module_count"] == "2"


def test_memory_explicit_total_capacity_precedes_title_inference() -> None:
    specs = _normalize_specs(
        "memory",
        [{"title": "Total Capacity", "value": "96 GB"}],
        title="DDR5 2 x 32 GB",
    )

    assert specs["total_capacity_gb"] == "96"
    assert specs["module_count"] == "2"


def test_storage_capacity_ignores_throughput_quantities() -> None:
    specs = _normalize_specs(
        "storage",
        [],
        title="7.4 GB/s sequential read, 2 TB capacity",
    )

    assert specs["capacity_gb"] == "2000"


def test_blank_feature_value_allows_title_fallback() -> None:
    specs = _normalize_specs(
        "memory",
        [{"title": "Total Capacity", "value": "   "}],
        title="DDR5 2 x 32 GB",
    )

    assert specs["total_capacity_gb"] == "64"


def test_blank_release_date_normalizes_to_none() -> None:
    normalization = importlib.import_module("app.knowledge.normalization")

    assert normalization.extract_release_date(
        [{"title": "Release Date", "value": "   "}]
    ) is None


def test_gpu_vram_normalizes_to_gigabytes() -> None:
    specs = _normalize_specs(
        "gpu",
        [{"title": "Video Memory", "value": "0.016 TB"}],
    )

    assert specs["vram_gb"] == "16"


def test_dimension_unit_does_not_match_word_prefix() -> None:
    specs = _normalize_specs(
        "gpu",
        [{"title": "Length", "value": "165 internal clearance"}],
    )

    assert specs["length_mm"] == "165 internal clearance"


def test_memory_type_accepts_generic_type_feature() -> None:
    specs = _normalize_specs(
        "memory",
        [{"title": "Type", "value": "DDR5"}],
    )

    assert specs["memory_type"] == "DDR5"


def test_memory_module_configuration_accepts_multiplication_sign() -> None:
    specs = _normalize_specs(
        "memory",
        [],
        title="DDR5 2 × 32 GB",
    )

    assert specs["total_capacity_gb"] == "64"
    assert specs["module_count"] == "2"


def test_module_count_feature_accepts_multiplication_sign() -> None:
    specs = _normalize_specs(
        "memory",
        [{"title": "Kit Configuration", "value": "2 × 32 GB"}],
    )

    assert specs["module_count"] == "2"


def test_duplicate_features_keep_first_non_blank_value() -> None:
    specs = _normalize_specs(
        "cpu",
        [
            {"title": "CPU Socket", "value": "   "},
            {"title": "CPU Socket", "value": "AM5"},
            {"title": "CPU Socket", "value": "LGA1851"},
        ],
    )

    assert specs["socket"] == "AM5"


def test_serpapi_keeps_candidate_title_as_normalization_evidence() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "product_results": {
                        "about_the_product": {
                            "title": "Desktop Graphics Card",
                            "features": [
                                {
                                    "title": "GPU Chipset",
                                    "value": "Graphics Processor",
                                }
                            ],
                        }
                    }
                },
            )
        )
    )
    candidate = Candidate(
        category="gpu",
        title="Graphics Card OC 16G",
        url="https://shop.example/graphics-card",
        detail_url=(
            "https://serpapi.com/search.json?"
            "engine=google_immersive_product&page_token=token"
        ),
    )

    result = SerpApiProvider("key", client).details(candidate)

    assert result.data["record"]["specs"]["vram_gb"] == "16"
