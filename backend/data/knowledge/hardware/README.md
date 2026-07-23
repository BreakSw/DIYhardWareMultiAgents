# Hardware Knowledge Data

This directory contains reviewable hardware data collected through managed
scraping and search APIs.

- `catalog/current/catalog.json`: human-readable current knowledge catalog.
- `catalog/current/by-category/`: current catalog split into component types.
- `catalog/current/verified.jsonl`: default embedding and RAG input.
- `catalog/current/partial.jsonl`: reviewable supplementary data, excluded from
  retrieval unless `include_partial=True` is explicitly requested.
- `catalog/current/hardware.jsonl`: complete review export containing both
  quality levels; do not use it as the default retrieval input.
- `catalog/current/summary.json`: current record counts and category coverage.

Use `app.knowledge.retrieval.load_catalog_records()` to read the catalog. The
loader validates partition labels and reads only `verified.jsonl` by default.

The following directories are collection audit data and are not the RAG input:

- `raw/<batch_id>/`: redacted provider evidence.
- `normalized/<batch_id>/hardware.jsonl`: accepted records from one run.
- `rejected/<batch_id>/hardware.jsonl`: incomplete records and rejection reasons.
- `manifests/<batch_id>.json`: provider calls, counts, and batch status.

Collection and recovery commands:

```powershell
python scripts/crawl_hardware_knowledge.py --minimum-per-category 10 --max-candidates-per-category 40
python scripts/recover_hardware_catalog.py --minimum-per-category 10
```

The crawler uses managed provider APIs only, checkpoints after every completed
category, stops on SerpAPI HTTP 429, and never fetches retailer target pages
directly. The recovery command revalidates archived managed responses and only
fills current category shortfalls. Inferred or incomplete records remain
`partial` and are not default RAG context.

The current catalog is staged for review and has not yet been embedded or
written to Qdrant.
