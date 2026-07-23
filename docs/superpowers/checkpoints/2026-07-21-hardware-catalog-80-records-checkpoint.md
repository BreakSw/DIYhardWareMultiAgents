# Hardware Catalog 80-Record Expansion Checkpoint

## Saved At

2026-07-21 02:02:21 Asia/Shanghai

## Objective

Publish at least 10 real records for each of eight hardware categories, with
explicit `verified` and `partial` quality levels and verified-only default RAG
input.

## Reference Documents

- Design:
  `docs/superpowers/specs/2026-07-21-hardware-catalog-80-records-design.md`
- Implementation plan:
  `docs/superpowers/plans/2026-07-21-hardware-catalog-80-records.md`

## Completed

### Task 1: Quality Classification

- Added strict `verified` / `partial` quality levels.
- Enforced consistency between `accepted` and `quality_level`.
- Fixed the missing-exchange-rate path so it cannot remain `verified`.
- Passed specification and code-quality reviews.

### Task 2: Eight-Category Normalization

- Added `backend/app/knowledge/normalization.py`.
- Covered CPU, GPU, motherboard, memory, storage, PSU, cooler, and case.
- Moved normalization out of the SerpAPI provider.
- Added unit conversion, title fallback, empty-value handling, duplicate-feature
  precedence, multiplication-sign support, and provider availability guards.
- Fixed all specification and code-quality review findings.
- Passed specification and code-quality reviews.

## In Progress

### Task 3: One Missing-Field Follow-Up Search

Implemented:

- Dynamic SerpAPI Google follow-up query containing product title, category,
  and only actual missing fields.
- One follow-up maximum per candidate.
- Managed API only; no local retailer-page requests.
- Raw evidence and manifest trace.
- Merge only into empty specification fields.
- Revalidation after enrichment.
- Extraction limited to organic snippets and whitelisted structured answer
  values.
- Follow-up only when initial `missing_fields` is non-empty.

Latest local verification:

```text
python -m pytest tests/knowledge -q
53 passed
```

Task 3 is not complete yet. Its latest fixes have not received:

1. Specification re-review.
2. Code-quality review.

## Pending

- Task 4: Publish separate verified and partial catalog files.
- Task 5: Implement verified-only default RAG loader.
- Task 6: Add coverage CLI, perform bounded live collection, and verify at
  least 80 records with 10 per category.

## Resume Instructions

1. Do not start Task 4 immediately.
2. Dispatch a fresh specification reviewer for the latest Task 3 changes.
3. If approved, dispatch a fresh code-quality reviewer.
4. Fix and re-review any findings.
5. Mark Task 3 complete, then continue Task 4.
6. Do not run live external collection until Tasks 4-6 code and tests are
   complete.

## External API State

No external API was called while saving this checkpoint. Previous live runs
showed SerpAPI and ECB working; Firecrawl, Bright Data, and Apify returned 401,
and Zyte returned 400.
