from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime
import json
import os
import shutil
from pathlib import Path
import threading
import time
from typing import Any
from uuid import uuid4

from app.knowledge.hashing import canonical_content_hash
from app.knowledge.identity import record_identity
from app.knowledge.http import redact_secrets
from app.knowledge.validation import (
    catalog_missing_fields,
    is_valid_exchange_rate,
    is_valid_http_url,
    is_valid_offer,
)


_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.RLock] = {}
_LOCK_DEPTH = threading.local()


def _thread_lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path, threading.RLock())


def _acquire_file_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def catalog_lock(root: Path):
    catalog_root = root / "catalog"
    catalog_root.mkdir(parents=True, exist_ok=True)
    lock_path = (catalog_root / ".catalog.lock").resolve()
    lock = _thread_lock(lock_path)
    depths = getattr(_LOCK_DEPTH, "values", {})
    _LOCK_DEPTH.values = depths
    with lock:
        if depths.get(lock_path, 0):
            depths[lock_path] += 1
            try:
                yield
            finally:
                depths[lock_path] -= 1
            return
        depths[lock_path] = 1
        with lock_path.open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _acquire_file_lock(handle)
            try:
                yield
            finally:
                _release_file_lock(handle)
                depths.pop(lock_path, None)


def _remove_directory_best_effort(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _recover_catalog_state(catalog_root: Path) -> None:
    current = catalog_root / "current"
    backups = sorted(catalog_root.glob("current.backup-*"))
    if not current.exists() and backups:
        if len(backups) != 1:
            raise RuntimeError("catalog recovery requires exactly one backup")
        backups[0].replace(current)
        backups = []
    if current.exists():
        for backup in backups:
            _remove_directory_best_effort(backup)
    for staging in catalog_root.glob("current.staging-*"):
        _remove_directory_best_effort(staging)


def read_catalog_payload(root: Path) -> dict[str, Any]:
    with catalog_lock(root):
        _recover_catalog_state(root / "catalog")
        path = root / "catalog" / "current" / "catalog.json"
        return json.loads(path.read_text(encoding="utf-8"))


class BatchStorage:
    def __init__(
        self,
        root: Path,
        batch_id: str,
        secrets: list[str],
    ) -> None:
        self.root = root
        self.batch_id = batch_id
        self.secrets = secrets

    def write_raw(
        self,
        provider: str,
        call_id: str,
        payload: Any,
    ) -> Path:
        path = self.root / "raw" / self.batch_id / provider / f"{call_id}.json"
        self._write_json(path, redact_secrets(payload, self.secrets))
        return path

    def write_records(
        self,
        accepted: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
    ) -> None:
        safe_accepted = redact_secrets(accepted, self.secrets)
        safe_rejected = redact_secrets(rejected, self.secrets)
        self._write_jsonl(
            self.root
            / "normalized"
            / self.batch_id
            / "hardware.jsonl",
            safe_accepted,
        )
        self._write_jsonl(
            self.root
            / "rejected"
            / self.batch_id
            / "hardware.jsonl",
            safe_rejected,
        )

    def write_manifest(self, payload: dict[str, Any]) -> Path:
        path = self.root / "manifests" / f"{self.batch_id}.json"
        self._write_json(path, redact_secrets(payload, self.secrets))
        return path

    def publish_catalog(
        self,
        records: list[dict[str, Any]],
        *,
        merge_existing: bool = True,
    ) -> Path:
        with catalog_lock(self.root):
            _recover_catalog_state(self.root / "catalog")
            return self._publish_catalog_locked(
                records,
                merge_existing=merge_existing,
            )

    def _publish_catalog_locked(
        self,
        records: list[dict[str, Any]],
        *,
        merge_existing: bool,
    ) -> Path:
        catalog_root = self.root / "catalog"
        current = catalog_root / "current"
        catalog_path = current / "catalog.json"
        existing: list[dict[str, Any]] = []
        if merge_existing and catalog_path.exists():
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            existing = payload.get("records", [])

        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in [*existing, *records]:
            safe_record = self._catalog_record(record)
            key = self._identity(safe_record)
            previous = merged.get(key)
            if (
                previous is not None
                and previous["quality_level"] == "verified"
                and safe_record["quality_level"] == "partial"
            ):
                merged[key] = self._refresh_verified_record(
                    previous,
                    safe_record,
                )
            else:
                merged[key] = safe_record
        catalog_records: list[dict[str, Any]] = []
        for record in merged.values():
            finalized = copy.deepcopy(record)
            finalized["content_hash"] = canonical_content_hash(finalized)
            catalog_records.append(finalized)
        catalog = sorted(
            catalog_records,
            key=lambda item: (
                str(item.get("category") or ""),
                str(item.get("brand") or ""),
                str(item.get("model") or ""),
            ),
        )
        categories: dict[str, int] = {}
        category_records: dict[str, list[dict[str, Any]]] = {}
        quality_levels = {"partial": 0, "verified": 0}
        category_quality_levels: dict[str, dict[str, int]] = {}
        for record in catalog:
            category = str(record.get("category") or "unknown")
            quality_level = record["quality_level"]
            categories[category] = categories.get(category, 0) + 1
            category_records.setdefault(category, []).append(record)
            quality_levels[quality_level] += 1
            category_counts = category_quality_levels.setdefault(
                category,
                {"partial": 0, "verified": 0},
            )
            category_counts[quality_level] += 1

        verified = [
            record for record in catalog if record["quality_level"] == "verified"
        ]
        partial = [
            record for record in catalog if record["quality_level"] == "partial"
        ]

        transaction_id = uuid4().hex
        staging = catalog_root / f"current.staging-{transaction_id}"
        backup = catalog_root / f"current.backup-{transaction_id}"
        try:
            self._write_catalog_snapshot(
                staging,
                catalog,
                verified,
                partial,
                category_records,
                categories,
                quality_levels,
                category_quality_levels,
            )
            self._swap_snapshot(current, staging, backup)
        except BaseException:
            if staging.exists():
                _remove_directory_best_effort(staging)
            raise
        return catalog_path

    def _catalog_record(self, record: dict[str, Any]) -> dict[str, Any]:
        safe_record = redact_secrets(record, self.secrets)
        self._identity(safe_record)
        quality_level = safe_record.get("quality_level")
        if quality_level not in {"verified", "partial"}:
            raise ValueError("quality_level must be verified or partial")
        missing_fields = safe_record.get("missing_fields")
        if not isinstance(missing_fields, list):
            raise ValueError("quality missing_fields must be a list")
        quality = safe_record.get("quality")
        if not isinstance(quality, dict):
            raise ValueError("quality must be an object")
        if quality.get("quality_level") != quality_level:
            raise ValueError("quality_level must match quality.quality_level")
        if quality.get("missing_fields") != missing_fields:
            raise ValueError("missing_fields must match quality.missing_fields")
        expected_complete = quality_level == "verified"
        if quality.get("complete") is not expected_complete:
            raise ValueError("quality.complete must match quality_level")
        if quality_level == "verified" and missing_fields:
            raise ValueError("verified quality requires empty missing_fields")
        if quality_level == "partial" and not missing_fields:
            raise ValueError("partial quality requires non-empty missing_fields")
        sources = safe_record.get("sources")
        if not isinstance(sources, list) or not any(
            is_valid_http_url(source) for source in sources
        ):
            raise ValueError("catalog record requires a valid http(s) source")
        deterministic_missing = catalog_missing_fields(safe_record)
        deterministic_level = "partial" if deterministic_missing else "verified"
        if (
            deterministic_level != quality_level
            or deterministic_missing != sorted(set(missing_fields))
        ):
            raise ValueError(
                "quality metadata does not match deterministic validation"
            )
        return safe_record

    def _write_catalog_snapshot(
        self,
        staging: Path,
        catalog: list[dict[str, Any]],
        verified: list[dict[str, Any]],
        partial: list[dict[str, Any]],
        category_records: dict[str, list[dict[str, Any]]],
        categories: dict[str, int],
        quality_levels: dict[str, int],
        category_quality_levels: dict[str, dict[str, int]],
    ) -> None:
        self._write_json(
            staging / "catalog.json",
            {"batch_id": self.batch_id, "records": catalog},
        )
        self._write_jsonl(staging / "hardware.jsonl", catalog)
        self._write_jsonl(staging / "verified.jsonl", verified)
        self._write_jsonl(staging / "partial.jsonl", partial)
        for category, items in category_records.items():
            self._write_json(staging / "by-category" / f"{category}.json", items)
        self._write_json(
            staging / "summary.json",
            {
                "batch_id": self.batch_id,
                "record_count": len(catalog),
                "categories": dict(sorted(categories.items())),
                "quality_levels": quality_levels,
                "category_quality_levels": dict(
                    sorted(category_quality_levels.items())
                ),
            },
        )

    @staticmethod
    def _swap_snapshot(current: Path, staging: Path, backup: Path) -> None:
        old_moved = False
        new_installed = False
        try:
            if current.exists():
                current.replace(backup)
                old_moved = True
            staging.replace(current)
            new_installed = True
        except BaseException:
            if new_installed and current.exists():
                shutil.rmtree(current)
            if old_moved and backup.exists():
                backup.replace(current)
            raise
        if backup.exists():
            _remove_directory_best_effort(backup)

    @staticmethod
    def _identity(record: dict[str, Any]) -> tuple[str, str, str]:
        identity = record_identity(record)
        if not all(identity):
            raise ValueError("catalog identity fields must be non-empty")
        return identity

    @staticmethod
    def _refresh_verified_record(
        verified: dict[str, Any],
        partial: dict[str, Any],
    ) -> dict[str, Any]:
        refreshed = copy.deepcopy(verified)
        price = partial.get("price")
        if isinstance(price, dict) and any(
            is_valid_offer(offer) for offer in price.get("offers", [])
        ):
            refreshed["price"] = copy.deepcopy(price)
        availability = partial.get("availability")
        if availability in {"in_stock", "out_of_stock", "unknown"}:
            refreshed["availability"] = availability
        if is_valid_exchange_rate(partial.get("exchange_rate")):
            refreshed["exchange_rate"] = copy.deepcopy(partial["exchange_rate"])
        fetched_at = partial.get("fetched_at")
        if isinstance(fetched_at, str) and fetched_at.strip():
            try:
                datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            except ValueError:
                pass
            else:
                refreshed["fetched_at"] = fetched_at
        return refreshed if not catalog_missing_fields(refreshed) else copy.deepcopy(verified)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _write_jsonl(
        path: Path,
        records: list[dict[str, Any]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False, default=str) + "\n"
                for record in records
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
