"""Read the published hardware catalog for retrieval and embedding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_partition(path: Path, expected_quality: str) -> list[dict[str, Any]]:
    if not path.exists():
        if expected_quality == "partial":
            return []
        raise FileNotFoundError(f"catalog partition not found: {path}")

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path.name}:{line_number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"catalog record at {path.name}:{line_number} must be an object")
        if record.get("quality_level") != expected_quality:
            raise ValueError(
                f"{path.name}:{line_number} must contain only {expected_quality} records"
            )
        records.append(record)
    return records


def load_catalog_records(
    catalog_directory: Path | str,
    *,
    include_partial: bool = False,
) -> list[dict[str, Any]]:
    """Load verified records by default, with explicit opt-in for partial data."""

    directory = Path(catalog_directory)
    records = _read_partition(directory / "verified.jsonl", "verified")
    if include_partial:
        records.extend(_read_partition(directory / "partial.jsonl", "partial"))
    return records
