from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_content_hash(record: dict[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in record.items() if key != "content_hash"},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
