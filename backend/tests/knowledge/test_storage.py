import copy
import json
import multiprocessing
from pathlib import Path
import threading
import time

import pytest

from app.knowledge.hashing import canonical_content_hash
import app.knowledge.storage as storage_module
from app.knowledge.storage import BatchStorage
from app.knowledge.validation import REQUIRED_SPECS


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _catalog_record(
    category: str,
    model: str,
    quality_level: str,
    *,
    missing_fields: list[str] | None = None,
) -> dict:
    missing = missing_fields or []
    normalized_category = category.strip().casefold()
    specs = {
        field: f"{field}-value"
        for field in REQUIRED_SPECS.get(normalized_category, set())
    }
    offers = [
        {
            "merchant": "Example",
            "url": "https://shop.example/item",
            "price_usd": "300",
            "availability": "in_stock",
        }
    ]
    sources = ["https://manufacturer.example/item"]
    exchange_rate = {"usd_cny": "7.2", "published_at": "2026-07-20"}
    for field in missing:
        specs.pop(field, None)
    if "usd_price_offer" in missing:
        offers = []
    if "source" in missing:
        sources = []
    if "exchange_rate" in missing:
        exchange_rate = None
    return {
        "category": category,
        "brand": "Dynamic",
        "model": model,
        "specs": specs,
        "price": {"reference_usd": "300", "offers": offers},
        "exchange_rate": exchange_rate,
        "sources": sources,
        "quality_level": quality_level,
        "missing_fields": missing,
        "quality": {
            "complete": quality_level == "verified",
            "quality_level": quality_level,
            "missing_fields": missing,
        },
    }


def _process_publish(
    root: str,
    batch_id: str,
    record: dict,
    started,
    result,
) -> None:
    started.set()
    try:
        BatchStorage(Path(root), batch_id, []).publish_catalog([record])
        result.put("ok")
    except BaseException as exc:
        result.put(type(exc).__name__)


def _directory_snapshot(path: Path) -> dict[str, bytes]:
    return {
        file.relative_to(path).as_posix(): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }


def test_batch_storage_separates_outputs_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    storage = BatchStorage(tmp_path, "batch-test", ["private-token"])
    storage.write_raw(
        "serpapi",
        "call-1",
        {"api_key": "private-token", "items": [{"name": "Part"}]},
    )
    storage.write_records(
        accepted=[{"model": "Complete"}],
        rejected=[{"model": "Incomplete", "reason": "missing_specs"}],
    )
    storage.write_manifest({"batch_id": "batch-test", "status": "completed"})

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert "private-token" not in text
    assert (
        tmp_path
        / "normalized"
        / "batch-test"
        / "hardware.jsonl"
    ).exists()
    assert (
        tmp_path
        / "rejected"
        / "batch-test"
        / "hardware.jsonl"
    ).exists()


def test_record_and_catalog_writes_recursively_redact_secrets(
    tmp_path: Path,
) -> None:
    storage = BatchStorage(tmp_path, "batch-sensitive", [])
    record = _catalog_record("storage", "Drive One", "verified")
    record["sources"] = [
        "https://manufacturer.example/spec?api_key=record-secret"
    ]
    record["evidence"] = {"token": "nested-secret"}

    storage.write_records([record], [])
    storage.publish_catalog([record])

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert "record-secret" not in text
    assert "nested-secret" not in text
    assert "api_key=%2A%2A%2A" in text


def test_publish_catalog_creates_clean_current_view_and_deduplicates(
    tmp_path: Path,
) -> None:
    first = BatchStorage(tmp_path, "batch-1", [])
    first.publish_catalog(
        [_catalog_record("cpu", "Processor One", "verified")]
    )
    second = BatchStorage(tmp_path, "batch-2", [])
    updated_cpu = _catalog_record("cpu", "Processor One", "verified")
    updated_cpu["price"]["reference_usd"] = "280"
    new_gpu = _catalog_record("gpu", "Graphics Two", "verified")
    new_gpu["price"]["reference_usd"] = "500"
    second.publish_catalog(
        [updated_cpu, new_gpu]
    )

    current = tmp_path / "catalog" / "current"
    payload = json.loads(
        (current / "catalog.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (current / "summary.json").read_text(encoding="utf-8")
    )

    assert len(payload["records"]) == 2
    assert payload["records"][0]["price"]["reference_usd"] == "280"
    assert summary == {
        "batch_id": "batch-2",
        "record_count": 2,
        "categories": {"cpu": 1, "gpu": 1},
        "quality_levels": {"partial": 0, "verified": 2},
        "category_quality_levels": {
            "cpu": {"partial": 0, "verified": 1},
            "gpu": {"partial": 0, "verified": 1},
        },
    }
    assert (current / "hardware.jsonl").exists()
    assert len(
        json.loads(
            (current / "by-category" / "cpu.json").read_text(
                encoding="utf-8"
            )
        )
    ) == 1
    assert len(
        json.loads(
            (current / "by-category" / "gpu.json").read_text(
                encoding="utf-8"
            )
        )
    ) == 1


def test_publish_catalog_separates_quality_files_and_counts_summary(
    tmp_path: Path,
) -> None:
    storage = BatchStorage(tmp_path, "batch-quality", [])
    storage.publish_catalog(
        [
            _catalog_record("cpu", "Processor One", "verified"),
            _catalog_record(
                "gpu",
                "Graphics Two",
                "partial",
                missing_fields=["vram_gb"],
            ),
        ]
    )

    current = tmp_path / "catalog" / "current"
    catalog = json.loads(
        (current / "catalog.json").read_text(encoding="utf-8")
    )["records"]
    hardware = _read_jsonl(current / "hardware.jsonl")
    verified = _read_jsonl(current / "verified.jsonl")
    partial = _read_jsonl(current / "partial.jsonl")
    summary = json.loads(
        (current / "summary.json").read_text(encoding="utf-8")
    )

    assert len(catalog) == len(hardware) == 2
    assert {record["quality_level"] for record in catalog} == {
        "verified",
        "partial",
    }
    assert [record["quality_level"] for record in verified] == ["verified"]
    assert [record["quality_level"] for record in partial] == ["partial"]
    assert {
        (record["category"], record["brand"], record["model"])
        for record in verified
    }.isdisjoint(
        {
            (record["category"], record["brand"], record["model"])
            for record in partial
        }
    )
    assert partial[0]["quality"]["missing_fields"] == ["vram_gb"]
    assert summary == {
        "batch_id": "batch-quality",
        "record_count": 2,
        "categories": {"cpu": 1, "gpu": 1},
        "quality_levels": {"partial": 1, "verified": 1},
        "category_quality_levels": {
            "cpu": {"partial": 0, "verified": 1},
            "gpu": {"partial": 1, "verified": 0},
        },
    }
    assert len(
        json.loads(
            (current / "by-category" / "cpu.json").read_text(
                encoding="utf-8"
            )
        )
    ) == 1
    assert len(
        json.loads(
            (current / "by-category" / "gpu.json").read_text(
                encoding="utf-8"
            )
        )
    ) == 1
    assert not list(current.rglob("*.tmp"))


def test_publish_catalog_upgrades_partial_record_to_verified(
    tmp_path: Path,
) -> None:
    BatchStorage(tmp_path, "batch-partial", []).publish_catalog(
        [
            _catalog_record(
                "cpu",
                "Processor One",
                "partial",
                missing_fields=["cores"],
            )
        ]
    )
    verified = _catalog_record("cpu", "Processor One", "verified")
    verified["specs"]["cores"] = "8"

    BatchStorage(tmp_path, "batch-verified", []).publish_catalog([verified])

    current = tmp_path / "catalog" / "current"
    assert _read_jsonl(current / "partial.jsonl") == []
    published = _read_jsonl(current / "verified.jsonl")
    assert len(published) == 1
    assert published[0]["specs"]["cores"] == "8"
    assert published[0]["quality_level"] == "verified"


def test_publish_catalog_does_not_downgrade_verified_record(
    tmp_path: Path,
) -> None:
    verified = _catalog_record("cpu", "Processor One", "verified")
    verified["specs"].update({"socket": "AM5", "cores": "8"})
    verified.update(
        {
            "availability": "in_stock",
            "exchange_rate": {
                "usd_cny": "7.1",
                "published_at": "2026-07-19",
            },
            "fetched_at": "2026-07-20T00:00:00Z",
            "content_hash": "stale-verified-hash",
        }
    )
    BatchStorage(tmp_path, "batch-verified", []).publish_catalog([verified])
    partial = _catalog_record(
        "cpu",
        "Processor One",
        "partial",
        missing_fields=["cores"],
    )
    partial.update(
        {
            "price": {
                "reference_usd": "280",
                "offers": [
                    {
                        "merchant": "Example",
                        "url": "https://shop.example/item",
                        "price_usd": "280",
                        "availability": "unknown",
                    }
                ],
            },
            "availability": "unknown",
            "exchange_rate": {
                "usd_cny": "7.2",
                "published_at": "2026-07-20",
            },
            "fetched_at": "2026-07-21T00:00:00Z",
            "content_hash": "stale-partial-hash",
        }
    )
    partial["specs"].update({"socket": "LGA1851", "cores": ""})

    BatchStorage(tmp_path, "batch-partial", []).publish_catalog([partial])

    current = tmp_path / "catalog" / "current"
    assert _read_jsonl(current / "partial.jsonl") == []
    published = _read_jsonl(current / "verified.jsonl")[0]
    assert published["quality_level"] == "verified"
    assert published["quality"]["missing_fields"] == []
    assert published["specs"] == verified["specs"]
    assert published["price"] == partial["price"]
    assert published["availability"] == "unknown"
    assert published["exchange_rate"] == {
        "usd_cny": "7.2",
        "published_at": "2026-07-20",
    }
    assert published["fetched_at"] == "2026-07-21T00:00:00Z"
    assert published["content_hash"] == canonical_content_hash(published)
    assert published["content_hash"] not in {
        "stale-verified-hash",
        "stale-partial-hash",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.pop("quality_level"),
        lambda record: record.update(quality_level="unknown"),
        lambda record: record.update(missing_fields=["cores"]),
        lambda record: (
            record.update(quality_level="partial", missing_fields=[]),
            record["quality"].update(
                complete=False,
                quality_level="partial",
                missing_fields=[],
            ),
        ),
    ],
    ids=[
        "missing-quality-level",
        "invalid-quality-level",
        "verified-with-missing-fields",
        "partial-without-missing-fields",
    ],
)
def test_publish_catalog_rejects_invalid_quality_records(
    tmp_path: Path,
    mutate,
) -> None:
    record = _catalog_record("cpu", "Processor One", "verified")
    mutate(record)

    with pytest.raises(ValueError, match="quality"):
        BatchStorage(tmp_path, "invalid-quality", []).publish_catalog([record])

    assert not (tmp_path / "catalog" / "current").exists()


def test_publish_catalog_rejects_partial_missing_field_mismatch(
    tmp_path: Path,
) -> None:
    record = _catalog_record(
        "cpu",
        "Processor One",
        "partial",
        missing_fields=["cores"],
    )
    record["quality"]["missing_fields"] = ["threads"]

    with pytest.raises(ValueError, match="missing_fields"):
        BatchStorage(tmp_path, "mismatch", []).publish_catalog([record])


def test_publish_catalog_identity_ignores_case_and_outer_whitespace(
    tmp_path: Path,
) -> None:
    first = _catalog_record(
        "cpu",
        "processor one",
        "partial",
        missing_fields=["cores"],
    )
    first["category"] = " ＣＰＵ "
    first["model"] = " Ｐｒｏｃｅｓｓｏｒ Ｏｎｅ "
    first["brand"] = " ＤＹＮＡＭＩＣ "
    second = _catalog_record("cpu", "processor one", "verified")
    second["brand"] = "dynamic"
    second["specs"]["cores"] = "8"

    BatchStorage(tmp_path, "identity-1", []).publish_catalog([first])
    BatchStorage(tmp_path, "identity-2", []).publish_catalog([second])

    records = json.loads(
        (tmp_path / "catalog" / "current" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )["records"]
    assert len(records) == 1
    assert records[0]["quality_level"] == "verified"


def test_catalog_identity_merges_common_brand_aliases(tmp_path: Path) -> None:
    short = _catalog_record("storage", "My Book Desktop Hard Drive", "verified")
    short["brand"] = "WD"
    long = copy.deepcopy(short)
    long["brand"] = "Western Digital"

    BatchStorage(tmp_path, "brand-alias", []).publish_catalog([short, long])

    records = _read_jsonl(
        tmp_path / "catalog" / "current" / "hardware.jsonl"
    )
    assert len(records) == 1


@pytest.mark.parametrize("field", ["category", "brand", "model"])
def test_publish_catalog_rejects_empty_identity_field(
    tmp_path: Path,
    field: str,
) -> None:
    record = _catalog_record("cpu", "Processor", "verified")
    record[field] = " \u3000 "

    with pytest.raises(ValueError, match="identity"):
        BatchStorage(tmp_path, "bad-identity", []).publish_catalog([record])


def test_publish_catalog_rejects_falsely_verified_record(tmp_path: Path) -> None:
    record = _catalog_record("cpu", "Fake", "verified")
    record["specs"].pop("cores")

    with pytest.raises(ValueError, match="deterministic"):
        BatchStorage(tmp_path, "fake", []).publish_catalog([record])


def test_publish_catalog_rejects_partial_without_valid_http_source(
    tmp_path: Path,
) -> None:
    record = _catalog_record(
        "cpu",
        "No Source",
        "partial",
        missing_fields=["cores"],
    )
    record["sources"] = ["ftp://example.test/spec"]

    with pytest.raises(ValueError, match="source"):
        BatchStorage(tmp_path, "no-source", []).publish_catalog([record])


def test_partial_empty_market_fields_do_not_erase_verified_values(
    tmp_path: Path,
) -> None:
    verified = _catalog_record("cpu", "Processor", "verified")
    verified.update(
        availability="in_stock",
        fetched_at="2026-07-20T00:00:00+00:00",
    )
    BatchStorage(tmp_path, "verified", []).publish_catalog([verified])
    partial = _catalog_record(
        "cpu",
        "Processor",
        "partial",
        missing_fields=["cores", "usd_price_offer", "exchange_rate"],
    )
    partial.update(availability="", fetched_at="")

    BatchStorage(tmp_path, "partial", []).publish_catalog([partial])

    published = _read_jsonl(
        tmp_path / "catalog" / "current" / "verified.jsonl"
    )[0]
    assert published["price"] == verified["price"]
    assert published["exchange_rate"] == verified["exchange_rate"]
    assert published["availability"] == "in_stock"
    assert published["fetched_at"] == "2026-07-20T00:00:00+00:00"


def test_publish_catalog_rolls_back_when_staging_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BatchStorage(tmp_path, "stable", []).publish_catalog(
        [_catalog_record("cpu", "Stable", "verified")]
    )
    catalog_root = tmp_path / "catalog"
    current = catalog_root / "current"
    before = _directory_snapshot(current)
    original_write_jsonl = BatchStorage._write_jsonl

    def interrupt_partial_write(path: Path, records: list[dict]) -> None:
        if path.name == "partial.jsonl":
            raise OSError("simulated staging write interruption")
        original_write_jsonl(path, records)

    monkeypatch.setattr(
        BatchStorage,
        "_write_jsonl",
        staticmethod(interrupt_partial_write),
    )

    with pytest.raises(OSError, match="staging write interruption"):
        BatchStorage(tmp_path, "interrupted-write", []).publish_catalog(
            [_catalog_record("gpu", "New", "verified")]
        )

    assert _directory_snapshot(current) == before
    assert not list(catalog_root.glob("current.staging-*"))
    assert not list(catalog_root.glob("current.backup-*"))


def test_publish_catalog_rolls_back_when_directory_swap_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BatchStorage(tmp_path, "stable", []).publish_catalog(
        [_catalog_record("cpu", "Stable", "verified")]
    )
    catalog_root = tmp_path / "catalog"
    current = catalog_root / "current"
    before = _directory_snapshot(current)
    original_replace = Path.replace

    def interrupt_staging_swap(path: Path, target: Path) -> Path:
        if path.name.startswith("current.staging-") and Path(target) == current:
            raise OSError("simulated directory swap interruption")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupt_staging_swap)

    with pytest.raises(OSError, match="directory swap interruption"):
        BatchStorage(tmp_path, "interrupted-swap", []).publish_catalog(
            [_catalog_record("gpu", "New", "verified")]
        )

    assert _directory_snapshot(current) == before
    assert not list(catalog_root.glob("current.staging-*"))
    assert not list(catalog_root.glob("current.backup-*"))


def test_publish_catalog_success_leaves_no_transaction_directories(
    tmp_path: Path,
) -> None:
    BatchStorage(tmp_path, "clean-swap", []).publish_catalog(
        [_catalog_record("cpu", "Processor One", "verified")]
    )

    catalog_root = tmp_path / "catalog"
    assert not list(catalog_root.glob("current.staging-*"))
    assert not list(catalog_root.glob("current.backup-*"))


def test_concurrent_thread_publishers_do_not_lose_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BatchStorage(tmp_path, "baseline", []).publish_catalog(
        [_catalog_record("cpu", "Baseline", "verified")]
    )
    first_entered = threading.Event()
    release_first = threading.Event()
    original_write_snapshot = BatchStorage._write_catalog_snapshot
    errors: list[BaseException] = []

    def delayed_write_snapshot(self, staging: Path, *args) -> None:
        if self.batch_id == "thread-one":
            first_entered.set()
            assert release_first.wait(timeout=5)
        original_write_snapshot(self, staging, *args)

    monkeypatch.setattr(
        BatchStorage,
        "_write_catalog_snapshot",
        delayed_write_snapshot,
    )

    def publish(batch_id: str, model: str) -> None:
        try:
            BatchStorage(tmp_path, batch_id, []).publish_catalog(
                [_catalog_record("cpu", model, "verified")]
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=publish, args=("thread-one", "One"))
    second = threading.Thread(target=publish, args=("thread-two", "Two"))
    first.start()
    assert first_entered.wait(timeout=5)
    second.start()
    time.sleep(0.1)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    records = json.loads(
        (tmp_path / "catalog" / "current" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )["records"]
    assert {record["model"] for record in records} == {"Baseline", "One", "Two"}


def test_catalog_lock_serializes_two_publishers_in_other_processes(
    tmp_path: Path,
) -> None:
    assert hasattr(storage_module, "catalog_lock")
    context = multiprocessing.get_context("spawn")
    first_started = context.Event()
    second_started = context.Event()
    result = context.Queue()
    first = context.Process(
        target=_process_publish,
        args=(
            str(tmp_path),
            "process-one",
            _catalog_record("cpu", "Process One", "verified"),
            first_started,
            result,
        ),
    )
    second = context.Process(
        target=_process_publish,
        args=(
            str(tmp_path),
            "process-two",
            _catalog_record("cpu", "Process Two", "verified"),
            second_started,
            result,
        ),
    )

    with storage_module.catalog_lock(tmp_path):
        first.start()
        second.start()
        assert first_started.wait(timeout=5)
        assert second_started.wait(timeout=5)
        time.sleep(0.2)
        assert first.is_alive()
        assert second.is_alive()

    first.join(timeout=5)
    second.join(timeout=5)
    assert first.exitcode == second.exitcode == 0
    assert {result.get(timeout=1), result.get(timeout=1)} == {"ok"}
    records = json.loads(
        (tmp_path / "catalog" / "current" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )["records"]
    assert {record["model"] for record in records} == {
        "Process One",
        "Process Two",
    }


def test_publish_recovers_unique_backup_and_cleans_staging(tmp_path: Path) -> None:
    BatchStorage(tmp_path, "baseline", []).publish_catalog(
        [_catalog_record("cpu", "Baseline", "verified")]
    )
    catalog_root = tmp_path / "catalog"
    current = catalog_root / "current"
    backup = catalog_root / "current.backup-crash"
    staging = catalog_root / "current.staging-crash"
    current.replace(backup)
    staging.mkdir()
    (staging / "partial.tmp").write_text("incomplete", encoding="utf-8")

    BatchStorage(tmp_path, "recovered", []).publish_catalog(
        [_catalog_record("cpu", "Recovered", "verified")]
    )

    records = json.loads((current / "catalog.json").read_text(encoding="utf-8"))[
        "records"
    ]
    assert {record["model"] for record in records} == {"Baseline", "Recovered"}
    assert not list(catalog_root.glob("current.staging-*"))
    assert not list(catalog_root.glob("current.backup-*"))


def test_failed_install_and_rollback_is_recovered_on_next_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BatchStorage(tmp_path, "baseline", []).publish_catalog(
        [_catalog_record("cpu", "Baseline", "verified")]
    )
    catalog_root = tmp_path / "catalog"
    current = catalog_root / "current"
    original_replace = Path.replace

    def fail_install_and_rollback(path: Path, target: Path) -> Path:
        target = Path(target)
        if path.name.startswith("current.staging-") and target == current:
            raise OSError("install failed")
        if path.name.startswith("current.backup-") and target == current:
            raise OSError("rollback failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_install_and_rollback)
    with pytest.raises(OSError, match="rollback failed"):
        BatchStorage(tmp_path, "broken", []).publish_catalog(
            [_catalog_record("cpu", "Broken", "verified")]
        )

    assert not current.exists()
    assert len(list(catalog_root.glob("current.backup-*"))) == 1
    monkeypatch.undo()

    BatchStorage(tmp_path, "next", []).publish_catalog(
        [_catalog_record("cpu", "Next", "verified")]
    )
    records = json.loads((current / "catalog.json").read_text(encoding="utf-8"))[
        "records"
    ]
    assert {record["model"] for record in records} == {"Baseline", "Next"}
    assert not list(catalog_root.glob("current.backup-*"))


def test_backup_cleanup_failure_does_not_fail_publish_and_retries_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    BatchStorage(tmp_path, "baseline", []).publish_catalog(
        [_catalog_record("cpu", "Baseline", "verified")]
    )
    original_rmtree = storage_module.shutil.rmtree
    failed_once = False

    def fail_backup_cleanup_once(path: Path, *args, **kwargs) -> None:
        nonlocal failed_once
        if Path(path).name.startswith("current.backup-") and not failed_once:
            failed_once = True
            raise OSError("cleanup failed")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(storage_module.shutil, "rmtree", fail_backup_cleanup_once)

    published = BatchStorage(tmp_path, "cleanup", []).publish_catalog(
        [_catalog_record("cpu", "Published", "verified")]
    )
    assert published.exists()
    catalog_root = tmp_path / "catalog"
    assert len(list(catalog_root.glob("current.backup-*"))) == 1

    BatchStorage(tmp_path, "cleanup-next", []).publish_catalog(
        [_catalog_record("cpu", "Next", "verified")]
    )
    assert not list(catalog_root.glob("current.backup-*"))
