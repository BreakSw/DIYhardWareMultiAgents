# Hardware Catalog 80-Record Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-based hardware catalog with at least 10 records in each of eight categories, explicit verified/partial quality levels, and verified-only default RAG input.

**Architecture:** Keep batch evidence append-only, classify every real candidate after deterministic validation, and publish a cumulative clean catalog. SerpAPI supplies discovery, product details, and one bounded missing-field follow-up search; managed enrichment providers remain optional and circuit-broken after non-retryable failures.

**Tech Stack:** Python 3.13, Pydantic, httpx, pytest, SerpAPI, ECB exchange rates, JSON/JSONL.

---

## File Structure

- Modify `backend/app/knowledge/models.py`: quality-level and enrichment result models.
- Modify `backend/app/knowledge/validation.py`: verified/partial classification.
- Create `backend/app/knowledge/normalization.py`: category aliases and unit-safe feature normalization.
- Modify `backend/app/knowledge/providers/serpapi.py`: targeted follow-up search and evidence extraction.
- Modify `backend/app/knowledge/pipeline.py`: one follow-up per candidate and category coverage targets.
- Modify `backend/app/knowledge/storage.py`: verified/partial outputs and quality summaries.
- Create `backend/app/knowledge/retrieval.py`: verified-only default record loader.
- Modify `backend/scripts/crawl_hardware_knowledge.py`: bounded target-count CLI controls.
- Modify `backend/tests/knowledge/`: behavior and regression tests.

### Task 1: Quality Classification

**Files:**
- Modify: `backend/app/knowledge/models.py`
- Modify: `backend/app/knowledge/validation.py`
- Test: `backend/tests/knowledge/test_crawl_foundation.py`

- [ ] **Step 1: Write the failing classification test**

```python
def test_validation_classifies_complete_and_incomplete_records():
    complete = classify_hardware("cpu", COMPLETE_CPU_SPECS, OFFERS, SOURCES)
    partial = classify_hardware("cpu", {"socket": "AM5"}, OFFERS, SOURCES)
    assert complete.quality_level == "verified"
    assert complete.missing_fields == []
    assert partial.quality_level == "partial"
    assert "cores" in partial.missing_fields
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m pytest tests/knowledge/test_crawl_foundation.py -q
```

Expected: failure because `quality_level` and `classify_hardware` do not exist.

- [ ] **Step 3: Implement minimal classification**

Add `quality_level: Literal["verified", "partial"]` to the validation result and
make deterministic validation return `verified` only when no required field,
offer, exchange-rate, or source is missing.

- [ ] **Step 4: Run the test and verify GREEN**

Run the same pytest command and expect all tests in the file to pass.

### Task 2: Category Normalization

**Files:**
- Create: `backend/app/knowledge/normalization.py`
- Modify: `backend/app/knowledge/providers/serpapi.py`
- Test: `backend/tests/knowledge/test_normalization.py`

- [ ] **Step 1: Write failing parameterized tests for all eight categories**

```python
@pytest.mark.parametrize(
    ("category", "features", "expected"),
    [
        ("motherboard", {"CPU Socket": "AM5", "M.2 Slots": "4"}, {"socket": "AM5", "m2_slots": "4"}),
        ("memory", {"Type": "DDR5", "Voltage": "1.35 V"}, {"memory_type": "DDR5", "voltage": "1.35 V"}),
        ("storage", {"Capacity": "2 TB", "Endurance": "1200 TBW"}, {"capacity_gb": "2000", "endurance_tbw": "1200"}),
    ],
)
def test_normalize_features(category, features, expected):
    normalized = normalize_features(category, features, "")
    for field, value in expected.items():
        assert normalized[field] == value
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest tests/knowledge/test_normalization.py -q
```

Expected: import failure because `normalization.py` does not exist.

- [ ] **Step 3: Implement schema-driven normalization**

Move feature-key canonicalization and alias maps from the SerpAPI provider into
`normalization.py`. Add unit parsers for GB/TB, mm/cm/in, watts, memory speed,
CAS latency, voltage, slot counts, and endurance. Title parsing may identify
generic units such as DDR generation, capacity, or CL value, but may not contain
product model tables.

- [ ] **Step 4: Integrate provider details**

Replace provider-local alias logic with:

```python
specs, metadata = normalize_product(
    category=candidate.category,
    title=candidate.title,
    features=about.get("features", []),
    description=about.get("description", ""),
)
```

- [ ] **Step 5: Run normalization and existing provider tests**

```powershell
python -m pytest tests/knowledge/test_normalization.py tests/knowledge/test_pipeline_and_cli.py -q
```

Expected: all tests pass.

### Task 3: Bounded Missing-Field Follow-Up Search

**Files:**
- Modify: `backend/app/knowledge/providers/serpapi.py`
- Modify: `backend/app/knowledge/pipeline.py`
- Test: `backend/tests/knowledge/test_pipeline_and_cli.py`

- [ ] **Step 1: Write a failing provider test**

```python
def test_follow_up_search_uses_product_title_and_only_missing_fields():
    result = provider.enrich_missing_fields(
        title="Dynamic Board",
        category="motherboard",
        missing_fields=["socket", "m2_slots"],
    )
    assert captured_params["engine"] == "google"
    assert "Dynamic Board" in captured_params["q"]
    assert "socket" in captured_params["q"]
    assert "m2_slots" in captured_params["q"]
    assert result.provider == "serpapi-follow-up"
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/knowledge/test_pipeline_and_cli.py::test_follow_up_search_uses_product_title_and_only_missing_fields -q
```

Expected: failure because `enrich_missing_fields` is missing.

- [ ] **Step 3: Implement one managed follow-up query**

Use SerpAPI Google Search with an exact product-title query plus missing field
labels. Store organic result titles, snippets, and links as evidence. Normalize
only values explicitly present in snippets or structured answer blocks.

- [ ] **Step 4: Add pipeline retry boundary**

After initial validation, call follow-up enrichment only when fields are
missing and only once per candidate. Merge non-empty values, validate again,
and record the tool call in the batch manifest.

- [ ] **Step 5: Verify follow-up and no-repeat behavior**

Run the full pipeline test file and assert a candidate receives no more than one
follow-up call.

### Task 4: Verified and Partial Catalog Publishing

**Files:**
- Modify: `backend/app/knowledge/storage.py`
- Modify: `backend/app/knowledge/pipeline.py`
- Test: `backend/tests/knowledge/test_storage.py`

- [ ] **Step 1: Write failing publication tests**

```python
def test_catalog_separates_verified_and_partial_records(tmp_path):
    storage.publish_catalog([VERIFIED_RECORD, PARTIAL_RECORD])
    verified = read_jsonl(tmp_path / "catalog/current/verified.jsonl")
    partial = read_jsonl(tmp_path / "catalog/current/partial.jsonl")
    summary = json.loads((tmp_path / "catalog/current/summary.json").read_text())
    assert [r["quality_level"] for r in verified] == ["verified"]
    assert [r["quality_level"] for r in partial] == ["partial"]
    assert summary["quality_levels"] == {"partial": 1, "verified": 1}
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/knowledge/test_storage.py -q
```

Expected: failure because split outputs and summary quality counts are absent.

- [ ] **Step 3: Implement cumulative quality-aware publication**

Preserve stronger verified specifications when a newer partial record has the
same identity. Publish `catalog.json`, `hardware.jsonl`, `verified.jsonl`,
`partial.jsonl`, `summary.json`, and per-category pretty JSON files atomically.

- [ ] **Step 4: Run and verify GREEN**

Run the storage tests and expect all to pass.

### Task 5: Verified-Only Default RAG Input

**Files:**
- Create: `backend/app/knowledge/retrieval.py`
- Test: `backend/tests/knowledge/test_retrieval.py`

- [ ] **Step 1: Write the failing loader test**

```python
def test_default_loader_excludes_partial_records(tmp_path):
    write_jsonl(tmp_path / "verified.jsonl", [VERIFIED_RECORD])
    write_jsonl(tmp_path / "partial.jsonl", [PARTIAL_RECORD])
    assert load_catalog_records(tmp_path) == [VERIFIED_RECORD]
    assert load_catalog_records(tmp_path, include_partial=True) == [
        VERIFIED_RECORD,
        PARTIAL_RECORD,
    ]
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/knowledge/test_retrieval.py -q
```

Expected: import failure because the loader does not exist.

- [ ] **Step 3: Implement the loader**

Load `verified.jsonl` by default. Read `partial.jsonl` only when
`include_partial=True`; preserve the quality marker in every returned record.

- [ ] **Step 4: Run and verify GREEN**

Run the retrieval test and expect it to pass.

### Task 6: Coverage-Oriented Live Collection

**Files:**
- Modify: `backend/scripts/crawl_hardware_knowledge.py`
- Modify: `backend/data/knowledge/hardware/README.md`
- Test: `backend/tests/knowledge/test_pipeline_and_cli.py`

- [ ] **Step 1: Write a failing CLI coverage test**

```python
def test_cli_accepts_minimum_per_category():
    args = _parser().parse_args(["--minimum-per-category", "10", "--max-candidates-per-category", "40"])
    assert args.minimum_per_category == 10
    assert args.max_candidates_per_category == 40
```

- [ ] **Step 2: Run and verify RED**

Run the CLI test and expect argument parsing to fail.

- [ ] **Step 3: Add bounded coverage controls**

Add:

```text
--minimum-per-category 10
--max-candidates-per-category 40
```

The pipeline must stop a category after 10 unique total records, preferring
verified records and filling the remaining slots with partial records.

- [ ] **Step 4: Run all automated checks**

```powershell
python -m pytest -q
python -m compileall -q app scripts
```

Expected: zero failures and successful compilation.

- [ ] **Step 5: Run the managed live collection**

```powershell
python scripts/crawl_hardware_knowledge.py --categories cpu gpu motherboard memory storage psu cooler case --minimum-per-category 10 --max-candidates-per-category 40 --market US
```

Keep each terminal wait at 15 seconds and poll the running session until it
finishes.

- [ ] **Step 6: Run the final data quality gate**

Assert:

```python
summary["record_count"] >= 80
all(count >= 10 for count in summary["categories"].values())
all(record["quality_level"] in {"verified", "partial"} for record in records)
all(not record["quality"]["missing_fields"] for record in verified_records)
```

Also scan all generated data for configured secret values.

- [ ] **Step 7: Update documentation**

Document which files are intended for human review, default RAG input, optional
supplementary retrieval, and batch audit use.

## Verification Checklist

- [ ] At least 80 unique records.
- [ ] Eight categories with at least 10 records each.
- [ ] Verified and partial files are disjoint and correctly labeled.
- [ ] Default loader excludes partial records.
- [ ] No candidate receives more than one follow-up search.
- [ ] No target retailer page is fetched directly by the local process.
- [ ] Full tests and compilation pass.
- [ ] Generated files contain no secrets.
