# Hardware Catalog 80-Record Completion

## Outcome

- Published 80 unique hardware records under
  `backend/data/knowledge/hardware/catalog/current`.
- Coverage is exactly 10 records for each of CPU, GPU, motherboard, memory,
  storage, PSU, cooler, and case.
- Quality split is 28 `verified` and 52 `partial` records.
- Default RAG loading reads only `verified.jsonl`; partial records require an
  explicit opt-in and remain available for human review.

## Reliability And Quality Work

- Added strict verified-only catalog retrieval with partition validation.
- Added bounded minimum coverage and candidate limits to the managed crawler.
- Added category-specific search terms and deterministic cross-category title
  filtering without product-model allowlists.
- Added per-category atomic checkpoints so completed work survives later
  interruption.
- Added SerpAPI HTTP 429 circuit breaking and degraded manifests.
- Prevented missing catalog identities from blocking valid partial records.
- Unified catalog identity normalization and merged `WD` / `Western Digital`
  aliases.
- Added archived managed-response recovery that revalidates records with a
  current ECB exchange rate and fills only category shortfalls.
- Added one managed-search evidence record for Crucial P3 Plus 2TB after
  removing the duplicate WD My Book entry.

## Verification

- `python -m pytest -q`: 163 passed, one upstream Starlette deprecation warning.
- `python -m compileall -q app scripts`: passed.
- `npm run build`: passed.
- Data audit: 80 records, 8 categories x 10, unique normalized identities,
  valid partitions, matching deterministic quality metadata, valid hashes,
  HTTP(S) sources, USD prices, and exchange rates.
- Secret scan: 19 configured values checked, zero generated-data matches.

## Remaining Limits

- Memory, motherboard, and storage currently have no fully verified records, so
  they are intentionally absent from default RAG context until more complete
  evidence is collected.
- The latest live SerpAPI batch reached HTTP 429; optional managed providers
  returned authentication or request errors. Future collection should resume
  after provider credentials or quota are available.
- The catalog has not yet been embedded or written to Qdrant.
