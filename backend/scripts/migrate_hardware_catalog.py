from __future__ import annotations

import argparse
import copy
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.knowledge.hashing import canonical_content_hash
from app.knowledge.storage import BatchStorage, catalog_lock, read_catalog_payload
from app.knowledge.validation import catalog_missing_fields


DEFAULT_ROOT = BACKEND_DIR / "data" / "knowledge" / "hardware"


def _migrate_record(record: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(record)
    quality = migrated.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("legacy record quality must be an object")
    missing_fields = catalog_missing_fields(migrated)
    quality_level = "partial" if missing_fields else "verified"
    migrated["quality_level"] = quality_level
    migrated["missing_fields"] = list(missing_fields)
    quality["complete"] = quality_level == "verified"
    quality["quality_level"] = quality_level
    quality["missing_fields"] = list(missing_fields)
    if quality_level == "partial":
        migrated["reason"] = "missing_required_data"
        migrated["reason_code"] = "missing_required_data"
    else:
        migrated.pop("reason", None)
        migrated.pop("reason_code", None)
    migrated["content_hash"] = canonical_content_hash(migrated)
    return migrated


def migrate_catalog(root: Path, batch_id: str) -> Path:
    with catalog_lock(root):
        payload = read_catalog_payload(root)
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("legacy catalog records must be a list")
        migrated = [_migrate_record(record) for record in records]
        return BatchStorage(root, batch_id, []).publish_catalog(
            migrated,
            merge_existing=False,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate the hardware current catalog to strict quality metadata."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--batch-id",
        default=datetime.now(UTC).strftime("migration-%Y%m%dT%H%M%SZ"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog_path = migrate_catalog(args.root, args.batch_id)
    summary_path = catalog_path.parent / "summary.json"
    print(summary_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
