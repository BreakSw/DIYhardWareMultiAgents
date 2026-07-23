# Hardware Catalog Expansion Design

## Goal

Expand the initial hardware knowledge catalog to at least 80 records across
eight component categories. Each category must contain at least 10 unique
products:

- CPU
- GPU
- Motherboard
- Memory
- Storage
- PSU
- Cooler
- Case

The catalog must remain evidence-based. Product models, specifications, prices,
and availability must come from managed provider responses rather than static
seed lists.

## Quality Levels

Every catalog record receives one of two explicit quality levels.

### Verified

A `verified` record has:

- Every category-specific required specification.
- At least one usable USD offer.
- A USD/CNY exchange rate and converted CNY reference price.
- At least one auditable source URL.
- No unresolved validation errors.

Verified records may be used by recommendation agents and RAG retrieval by
default.

### Partial

A `partial` record is based on real provider evidence but lacks one or more
required specifications. It must include:

- `missing_fields`
- Available specifications and offers
- Source URLs
- Provider failures
- A clear `quality_level: partial` marker

Partial records satisfy catalog coverage but are excluded from recommendation
and default RAG retrieval. They may only be retrieved when explicitly enabled
for supplementary context.

## Collection Flow

1. Generate category-specific current-generation search queries dynamically
   from category and current year.
2. Discover candidates through SerpAPI Google Shopping.
3. Fetch managed product details through the SerpAPI immersive product API.
4. Call enabled managed enrichment providers for manufacturer or merchant
   pages. Direct local target-page requests remain prohibited.
5. Normalize provider feature names into category schemas.
6. If required fields are missing, perform one targeted SerpAPI follow-up
   search using the product title and missing field names.
7. Merge evidence without overwriting stronger existing values.
8. Validate the record and assign `verified` or `partial`.
9. Continue until each category has at least 10 unique records or the bounded
   candidate pool is exhausted.

The pipeline may not fabricate missing values or infer product-specific values
from hardcoded model tables.

## Catalog Structure

The RAG-facing current catalog is stored under:

`backend/data/knowledge/hardware/catalog/current/`

It contains:

- `catalog.json`: human-readable complete catalog.
- `hardware.jsonl`: embedding and ingestion source.
- `summary.json`: counts by category and quality level.
- `by-category/<category>.json`: one human-readable file per component type.
- `verified.jsonl`: records eligible for default retrieval.
- `partial.jsonl`: supplementary records excluded by default.

Provider evidence and batch diagnostics remain in `raw`, `normalized`,
`rejected`, and `manifests`. These directories are audit data, not direct RAG
inputs.

## Deduplication and Updates

The stable product identity is the normalized tuple:

`category + brand + model`

For an existing identity, a newer batch replaces prices, availability,
exchange-rate data, and fetched timestamps. Non-empty verified specifications
must not be replaced with missing values from a partial update.

Historical provider evidence remains append-only in batch audit directories.

## Retrieval Rules

Default RAG retrieval must filter to:

`quality_level = verified`

Partial records may be included only when:

- The caller explicitly enables supplementary retrieval.
- They are clearly labeled in the returned context.
- They are not used as sole evidence for compatibility or pricing claims.

The future vector payload must include category, quality level, model, brand,
market, fetched timestamp, and content hash.

## Error Handling

- HTTP authentication, billing, and invalid-request failures retain safe status
  codes without response bodies or credentials.
- Non-retryable provider failures trigger batch-level circuit breaking.
- Each candidate receives at most one targeted missing-field follow-up search.
- Provider failures do not erase valid evidence from other sources.
- A category that cannot produce 10 verified records is completed with partial
  records, never fabricated records.

## Acceptance Criteria

- The current catalog contains at least 80 unique records.
- All eight categories contain at least 10 records.
- Every record has `quality_level` set to `verified` or `partial`.
- Verified records have no missing required fields.
- Partial records explicitly list every missing required field.
- `verified.jsonl` contains no partial records.
- `partial.jsonl` contains no verified records.
- Summary counts match all catalog and category files.
- No API keys, tokens, passwords, or credentials appear in generated data.
- Automated tests cover classification, targeted enrichment, deduplication,
  catalog publishing, and default retrieval filtering.

## Out of Scope

- Direct retailer-page scraping from the local process.
- Qdrant indexing before the expanded catalog is reviewed.
- Automatic scheduled refresh.
- Fabricated fallback products, specifications, or prices.
