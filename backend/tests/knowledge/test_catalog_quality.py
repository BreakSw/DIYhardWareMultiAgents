import json
from pathlib import Path
import subprocess
import sys

from app.knowledge.hashing import canonical_content_hash
from app.knowledge.validation import REQUIRED_SPECS, catalog_missing_fields


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_CATALOG = (
    BACKEND_ROOT / "data" / "knowledge" / "hardware" / "catalog" / "current"
)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _old_record(
    model: str,
    *,
    complete: bool,
    missing_fields: list[str],
) -> dict:
    specs = {field: f"{field}-value" for field in REQUIRED_SPECS["cpu"]}
    for field in missing_fields:
        specs.pop(field, None)
    record = {
        "category": "cpu",
        "brand": "Arbitrary Brand",
        "model": model,
        "specs": specs,
        "price": {
            "reference_usd": "100",
            "offers": [
                {
                    "merchant": "Example",
                    "url": "https://shop.example/item",
                    "price_usd": "100",
                    "availability": "in_stock",
                }
            ],
        },
        "exchange_rate": {"usd_cny": "7.2", "published_at": "2026-07-20"},
        "sources": ["https://manufacturer.example/item"],
        "quality": {
            "complete": complete,
            "missing_fields": missing_fields,
        },
    }
    if not complete:
        record["reason"] = "missing_required_data"
    return record


def _assert_valid_catalog(current: Path) -> dict:
    required_files = {
        "catalog.json",
        "hardware.jsonl",
        "verified.jsonl",
        "partial.jsonl",
        "summary.json",
    }
    assert required_files <= {path.name for path in current.iterdir() if path.is_file()}

    payload = json.loads((current / "catalog.json").read_text(encoding="utf-8"))
    records = payload["records"]
    for record in records:
        quality_level = record["quality_level"]
        missing_fields = record["missing_fields"]
        assert quality_level in {"verified", "partial"}
        assert missing_fields == record["quality"]["missing_fields"]
        assert record["quality"]["quality_level"] == quality_level
        assert record["quality"]["complete"] is (quality_level == "verified")
        assert (not missing_fields) if quality_level == "verified" else bool(missing_fields)
        assert missing_fields == catalog_missing_fields(record)
        assert record["content_hash"] == canonical_content_hash(record)

    assert _read_jsonl(current / "hardware.jsonl") == records
    assert _read_jsonl(current / "verified.jsonl") == [
        record for record in records if record["quality_level"] == "verified"
    ]
    assert _read_jsonl(current / "partial.jsonl") == [
        record for record in records if record["quality_level"] == "partial"
    ]

    categories: dict[str, int] = {}
    quality_levels = {"partial": 0, "verified": 0}
    category_quality_levels: dict[str, dict[str, int]] = {}
    for record in records:
        category = record["category"]
        quality_level = record["quality_level"]
        categories[category] = categories.get(category, 0) + 1
        quality_levels[quality_level] += 1
        counts = category_quality_levels.setdefault(
            category,
            {"partial": 0, "verified": 0},
        )
        counts[quality_level] += 1

    summary = json.loads((current / "summary.json").read_text(encoding="utf-8"))
    assert summary["batch_id"] == payload["batch_id"]
    assert summary["record_count"] == len(records)
    assert summary["categories"] == dict(sorted(categories.items()))
    assert summary["quality_levels"] == quality_levels
    assert summary["category_quality_levels"] == dict(
        sorted(category_quality_levels.items())
    )

    category_dir = current / "by-category"
    assert {path.stem for path in category_dir.glob("*.json")} == set(categories)
    for category in categories:
        category_records = json.loads(
            (category_dir / f"{category}.json").read_text(encoding="utf-8")
        )
        assert category_records == [
            record for record in records if record["category"] == category
        ]
    assert not list(current.parent.glob("current.staging-*"))
    assert not list(current.parent.glob("current.backup-*"))
    return summary


def test_migration_infers_quality_and_rebuilds_complete_snapshot(
    tmp_path: Path,
) -> None:
    current = tmp_path / "catalog" / "current"
    current.mkdir(parents=True)
    records = [
        _old_record("Unlisted Verified Model", complete=True, missing_fields=[]),
        _old_record(
            "Unlisted Partial Model",
            complete=False,
            missing_fields=["cores"],
        ),
    ]
    fake_verified = _old_record(
        "Falsely Verified Model",
        complete=True,
        missing_fields=[],
    )
    fake_verified["specs"].pop("threads")
    records.append(fake_verified)
    (current / "catalog.json").write_text(
        json.dumps({"batch_id": "legacy", "records": records}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_hardware_catalog.py",
            "--root",
            str(tmp_path),
            "--batch-id",
            "migration-test",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = _assert_valid_catalog(current)
    assert summary["quality_levels"] == {"partial": 2, "verified": 1}
    assert all(
        record["reason"] == record["reason_code"] == "missing_required_data"
        for record in _read_jsonl(current / "partial.jsonl")
    )


def test_canonical_content_hash_helper_is_deterministic_and_ignores_old_hash(
) -> None:
    assert canonical_content_hash(
        {"second": 2, "first": 1, "content_hash": "stale"}
    ) == canonical_content_hash({"first": 1, "second": 2})


def test_repository_catalog_current_passes_quality_gate() -> None:
    _assert_valid_catalog(REPOSITORY_CATALOG)
