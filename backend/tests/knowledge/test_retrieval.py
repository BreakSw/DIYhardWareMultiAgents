import json
from pathlib import Path

import pytest

from app.knowledge.retrieval import load_catalog_records


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_default_loader_excludes_partial_records(tmp_path: Path) -> None:
    verified = {"model": "Verified CPU", "quality_level": "verified"}
    partial = {"model": "Partial CPU", "quality_level": "partial"}
    _write_jsonl(tmp_path / "verified.jsonl", [verified])
    _write_jsonl(tmp_path / "partial.jsonl", [partial])

    assert load_catalog_records(tmp_path) == [verified]
    assert load_catalog_records(tmp_path, include_partial=True) == [
        verified,
        partial,
    ]


def test_loader_rejects_quality_marker_in_wrong_partition(tmp_path: Path) -> None:
    contaminated = {"model": "Wrong Partition", "quality_level": "partial"}
    _write_jsonl(tmp_path / "verified.jsonl", [contaminated])

    with pytest.raises(ValueError, match="verified.jsonl"):
        load_catalog_records(tmp_path)


def test_loader_reports_invalid_json_with_file_and_line(tmp_path: Path) -> None:
    (tmp_path / "verified.jsonl").write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"verified\.jsonl:1"):
        load_catalog_records(tmp_path)
