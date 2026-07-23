# Initial Hardware Crawl Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a small, source-traceable hardware data collection pipeline that uses only managed crawler APIs for target pages and writes reviewable accepted, rejected, raw, and manifest files.

**Architecture:** A CLI orchestrator asks SerpAPI for dynamic candidates, delegates target-page fetching to Apify, Firecrawl, Zyte, and Bright Data, derives USD/CNY from ECB, validates category-specific required attributes, then writes sanitized batch artifacts. Provider adapters share a typed protocol and injected `httpx.Client`, allowing deterministic tests without live quota.

**Tech Stack:** Python 3.13, Pydantic 2, httpx, pytest, SerpAPI, Apify API, Bright Data API, Zyte API, Firecrawl API, ECB reference-rate XML.

---

## File Structure

- `backend/app/knowledge/models.py`: Typed crawl, source, offer, exchange-rate, hardware-record, and manifest models.
- `backend/app/knowledge/config.py`: Crawler configuration loaded from the root `.env`, including provider readiness without exposing secrets.
- `backend/app/knowledge/http.py`: Shared safe HTTP transport, retries, timeout, error normalization, and secret redaction.
- `backend/app/knowledge/providers/base.py`: Provider protocols and common result types.
- `backend/app/knowledge/providers/serpapi.py`: Dynamic product and shopping-result discovery.
- `backend/app/knowledge/providers/firecrawl.py`: Official-page Markdown/JSON extraction.
- `backend/app/knowledge/providers/apify.py`: Managed browser crawl through the public Web Scraper Actor.
- `backend/app/knowledge/providers/zyte.py`: Structured product and custom-attribute extraction.
- `backend/app/knowledge/providers/brightdata.py`: Web Unlocker or configured product scraper price extraction.
- `backend/app/knowledge/providers/ecb.py`: Latest reference-rate retrieval and USD/CNY derivation.
- `backend/app/knowledge/validation.py`: Category-specific completeness and evidence gates.
- `backend/app/knowledge/storage.py`: Sanitized batch directory and JSON/JSONL persistence.
- `backend/app/knowledge/pipeline.py`: Provider orchestration, candidate normalization, deduplication, acceptance, and rejection.
- `backend/scripts/__init__.py`: Makes the crawler CLI importable for tests.
- `backend/scripts/crawl_hardware_knowledge.py`: CLI entry point.
- `backend/tests/knowledge/`: Unit and integration-style tests using `httpx.MockTransport`.

## Task 1: Typed Knowledge Models

**Files:**
- Create: `backend/app/knowledge/__init__.py`
- Create: `backend/app/knowledge/models.py`
- Test: `backend/tests/knowledge/test_models.py`

- [ ] **Step 1: Write the failing model test**

```python
from app.knowledge.models import HardwareRecord, PriceOffer


def test_hardware_record_keeps_usd_offer_and_sources() -> None:
    record = HardwareRecord(
        category="gpu",
        brand="Example",
        model="Example GPU",
        mpn="EX-1",
        market="US",
        specs={"chipset": "Example", "vram_gb": 16},
        price_offers=[
            PriceOffer(
                merchant="Shop",
                url="https://shop.example/item",
                price_usd=599.99,
                availability="in_stock",
                observed_at="2026-07-20T00:00:00Z",
                provider="serpapi",
            )
        ],
        sources=["https://manufacturer.example/spec"],
        fetched_at="2026-07-20T00:00:00Z",
    )
    assert record.price_offers[0].price_usd == 599.99
    assert record.sources == ["https://manufacturer.example/spec"]
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_models.py -q`

Expected: FAIL with `ModuleNotFoundError: app.knowledge`.

- [ ] **Step 3: Implement focused Pydantic models**

Define `ProviderCall`, `SourceDocument`, `PriceOffer`, `ExchangeRate`, `HardwareRecord`, `RejectedRecord`, `ProviderSummary`, and `CrawlManifest`. Use `Decimal` for money and require `http` or `https` source URLs.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge backend/tests/knowledge/test_models.py
git commit -m "feat: add typed hardware crawl models"
```

## Task 2: Crawler Configuration and Secret Safety

**Files:**
- Create: `backend/app/knowledge/config.py`
- Create: `backend/app/knowledge/http.py`
- Modify: `.env`
- Test: `backend/tests/knowledge/test_config_and_redaction.py`

- [ ] **Step 1: Write failing configuration tests**

```python
from app.knowledge.config import CrawlerSettings
from app.knowledge.http import redact_secrets


def test_provider_readiness_requires_non_placeholder_values(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "serpapi-key=real\n"
        "apify-api-token=<FILL_APIFY_API_TOKEN>\n"
        "brightdata-api-token=real\n"
        "brightdata-zone=<FILL_BRIGHTDATA_ZONE>\n",
        encoding="utf-8",
    )
    settings = CrawlerSettings.from_env(env)
    assert settings.provider_ready("serpapi") is True
    assert settings.provider_ready("apify") is False
    assert settings.provider_ready("brightdata") is False


def test_redaction_removes_tokens_from_urls_and_headers() -> None:
    value = redact_secrets(
        {"url": "https://api.example.test?q=1&api_key=secret", "Authorization": "Bearer secret"}
    )
    assert "secret" not in str(value)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_config_and_redaction.py -q`

Expected: FAIL because `CrawlerSettings` and `redact_secrets` do not exist.

- [ ] **Step 3: Implement configuration and safe transport**

`CrawlerSettings` must read the existing hyphenated keys and these additional non-secret settings:

```dotenv
apify-actor-id=apify~web-scraper
brightdata-zone=<FILL_BRIGHTDATA_ZONE>
firecrawl-base-url=https://api.firecrawl.dev/v2
```

Implement a shared `ManagedApiClient` with a 15-second timeout, two retries for 429/5xx, injected `httpx.Client`, and safe errors containing provider, status code, and error code only.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_config_and_redaction.py -q`

Expected: PASS with no credential text in output.

- [ ] **Step 5: Commit**

```bash
git add .env backend/app/knowledge/config.py backend/app/knowledge/http.py backend/tests/knowledge/test_config_and_redaction.py
git commit -m "feat: add safe crawler configuration"
```

## Task 3: Discovery and Exchange-Rate Providers

**Files:**
- Create: `backend/app/knowledge/providers/__init__.py`
- Create: `backend/app/knowledge/providers/base.py`
- Create: `backend/app/knowledge/providers/serpapi.py`
- Create: `backend/app/knowledge/providers/ecb.py`
- Test: `backend/tests/knowledge/test_discovery_and_fx.py`

- [ ] **Step 1: Write failing provider tests**

```python
from decimal import Decimal

import httpx

from app.knowledge.providers.ecb import EcbRateProvider
from app.knowledge.providers.serpapi import SerpDiscoveryProvider


def test_serpapi_discovers_products_without_static_model_names() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["engine"] == "google_shopping"
        assert request.url.params["gl"] == "us"
        return httpx.Response(
            200,
            json={
                "shopping_results": [
                    {
                        "title": "Example GPU 16GB",
                        "product_link": "https://shop.example/gpu",
                        "source": "Shop",
                        "extracted_price": 599.99,
                    }
                ]
            },
        )

    provider = SerpDiscoveryProvider("key", httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.discover("gpu", limit=3)
    assert result.items[0].title == "Example GPU 16GB"


def test_ecb_derives_usd_cny_cross_rate() -> None:
    xml = b"<Envelope><Cube><Cube time='2026-07-20'><Cube currency='USD' rate='1.2'/><Cube currency='CNY' rate='7.8'/></Cube></Cube></Envelope>"
    provider = EcbRateProvider(httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=xml))))
    rate = provider.latest()
    assert rate.usd_cny == Decimal("6.5")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_discovery_and_fx.py -q`

Expected: FAIL because provider modules do not exist.

- [ ] **Step 3: Implement SerpAPI and ECB providers**

Generate category queries from category labels, market, current year, and requested result count. Do not include product model names in source code. Parse Google Shopping results into candidate and offer models. Parse ECB XML by currency code and derive the cross rate with `Decimal`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_discovery_and_fx.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/providers backend/tests/knowledge/test_discovery_and_fx.py
git commit -m "feat: add dynamic discovery and exchange rates"
```

## Task 4: Managed Page and Product Providers

**Files:**
- Create: `backend/app/knowledge/providers/firecrawl.py`
- Create: `backend/app/knowledge/providers/apify.py`
- Create: `backend/app/knowledge/providers/zyte.py`
- Create: `backend/app/knowledge/providers/brightdata.py`
- Test: `backend/tests/knowledge/test_managed_providers.py`

- [ ] **Step 1: Write failing provider contract tests**

```python
import httpx

from app.knowledge.providers.apify import ApifyProvider
from app.knowledge.providers.brightdata import BrightDataProvider
from app.knowledge.providers.firecrawl import FirecrawlProvider
from app.knowledge.providers.zyte import ZyteProvider


def test_managed_providers_call_only_their_official_api_hosts() -> None:
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        if request.url.host == "api.firecrawl.dev":
            return httpx.Response(200, json={"success": True, "data": {"markdown": "# Specs"}})
        if request.url.host == "api.zyte.com":
            return httpx.Response(200, json={"product": {"name": "Part", "price": "10", "currency": "USD"}})
        if request.url.host == "api.brightdata.com":
            return httpx.Response(200, text="<html>product</html>")
        return httpx.Response(200, json=[{"url": "https://target.example", "text": "Specs"}])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    FirecrawlProvider("key", client).fetch("https://target.example")
    ZyteProvider("key", client).extract_product("https://target.example")
    BrightDataProvider("key", "zone", client).fetch("https://target.example")
    ApifyProvider("key", "apify~web-scraper", client).fetch_many(["https://target.example"])

    assert set(seen_hosts) == {
        "api.firecrawl.dev",
        "api.zyte.com",
        "api.brightdata.com",
        "api.apify.com",
    }
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_managed_providers.py -q`

Expected: FAIL because provider modules do not exist.

- [ ] **Step 3: Implement all four adapters**

Use only official provider API endpoints:

- Firecrawl: `POST /v2/scrape` with Markdown and JSON formats.
- Zyte: `POST https://api.zyte.com/v1/extract` with `product=true` and category-specific `customAttributes`.
- Bright Data: `POST https://api.brightdata.com/request` with configured zone and target URL, then extract product JSON-LD and price evidence from the returned page.
- Apify: run `apify~web-scraper` synchronously and request dataset items.

The target URL may appear only inside provider request bodies. No adapter may call the target host directly.
Firecrawl and Zyte receive the same category field schema used by deterministic validation, so their structured responses can be merged without asking the local script to infer missing attributes from prose.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_managed_providers.py -q`

Expected: PASS and `seen_hosts` contains only managed API hosts.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/providers backend/tests/knowledge/test_managed_providers.py
git commit -m "feat: add managed crawler adapters"
```

## Task 5: Category Completeness and Price Validation

**Files:**
- Create: `backend/app/knowledge/validation.py`
- Test: `backend/tests/knowledge/test_validation.py`

- [ ] **Step 1: Write failing validation tests**

```python
from app.knowledge.validation import validate_record


def test_gpu_missing_length_is_rejected() -> None:
    result = validate_record(
        category="gpu",
        specs={
            "chipset": "Example",
            "vram_gb": 16,
            "memory_type": "GDDR7",
            "tdp_w": 250,
            "power_connectors": ["16-pin"],
            "recommended_psu_w": 750,
        },
        offers=[{"price_usd": "599.99", "availability": "in_stock"}],
        sources=["https://manufacturer.example/spec"],
    )
    assert result.accepted is False
    assert "length_mm" in result.missing_fields


def test_unknown_category_is_rejected_without_guessing() -> None:
    result = validate_record("unknown", {}, [], [])
    assert result.accepted is False
    assert result.reason_code == "unsupported_category"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_validation.py -q`

Expected: FAIL because `validate_record` does not exist.

- [ ] **Step 3: Implement deterministic category schemas**

Represent required fields as category schemas, not product records. Validate positive numeric dimensions, non-empty compatibility fields, at least one USD offer, at least one source, and new/in-stock condition. Return explicit missing and invalid field lists.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_validation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/validation.py backend/tests/knowledge/test_validation.py
git commit -m "feat: enforce hardware knowledge completeness"
```

## Task 6: Sanitized Batch Storage

**Files:**
- Create: `backend/app/knowledge/storage.py`
- Test: `backend/tests/knowledge/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

```python
import json

from app.knowledge.storage import BatchStorage


def test_batch_storage_writes_reviewable_files_without_secrets(tmp_path) -> None:
    storage = BatchStorage(tmp_path, "batch-test", secrets=["secret-token"])
    storage.write_raw("serpapi", {"api_key": "secret-token", "items": [{"name": "Part"}]})
    storage.write_normalized([{"model": "Part"}])
    storage.write_rejected([{"model": "Broken", "reason": "missing_specs"}])
    storage.write_manifest({"status": "completed"})

    all_text = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*") if path.is_file())
    assert "secret-token" not in all_text
    assert json.loads((tmp_path / "manifests" / "batch-test.json").read_text(encoding="utf-8"))["status"] == "completed"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_storage.py -q`

Expected: FAIL because `BatchStorage` does not exist.

- [ ] **Step 3: Implement atomic storage**

Write UTF-8 without BOM. Use temporary files plus `Path.replace` for normalized, rejected, and manifest outputs. Raw provider responses must pass recursive redaction before persistence.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_storage.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/storage.py backend/tests/knowledge/test_storage.py
git commit -m "feat: persist sanitized crawl batches"
```

## Task 7: Crawl Orchestrator

**Files:**
- Create: `backend/app/knowledge/pipeline.py`
- Test: `backend/tests/knowledge/test_pipeline.py`

- [ ] **Step 1: Write a failing orchestration test**

```python
from app.knowledge.pipeline import HardwareKnowledgePipeline


def test_pipeline_uses_dynamic_candidates_and_rejects_incomplete_records(fake_providers, tmp_path) -> None:
    pipeline = HardwareKnowledgePipeline(
        providers=fake_providers,
        output_root=tmp_path,
    )
    manifest = pipeline.run(categories=["gpu"], per_category=2, market="US")
    assert manifest.discovered_count == 2
    assert manifest.accepted_count == 1
    assert manifest.rejected_count == 1
    assert {call.provider for call in manifest.provider_calls} >= {
        "serpapi",
        "firecrawl",
        "zyte",
        "brightdata",
        "apify",
        "ecb",
    }
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_pipeline.py -q`

Expected: FAIL because `HardwareKnowledgePipeline` does not exist.

- [ ] **Step 3: Implement orchestration**

For each category:

1. Discover candidates through SerpAPI.
2. Deduplicate candidates by normalized title and MPN.
3. Ask Firecrawl and Apify for official-page content.
4. Ask Zyte and Bright Data for product and price evidence.
5. Merge only source-backed fields.
6. Fetch ECB rate once per batch.
7. Validate and route records to accepted or rejected.
8. Persist provider raw results and final manifest.

The pipeline must not import a product catalog or product model constants.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/pipeline.py backend/tests/knowledge/test_pipeline.py
git commit -m "feat: orchestrate managed hardware collection"
```

## Task 8: CLI and Dry Run

**Files:**
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/crawl_hardware_knowledge.py`
- Test: `backend/tests/knowledge/test_cli.py`

- [ ] **Step 1: Write a failing CLI dry-run test**

```python
from scripts.crawl_hardware_knowledge import main


def test_dry_run_reports_provider_readiness_without_network(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["crawl_hardware_knowledge.py", "--dry-run"])
    assert main() == 0
    output = capsys.readouterr().out
    assert "serpapi" in output
    assert "target page requests: managed providers only" in output
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend; python -m pytest tests/knowledge/test_cli.py -q`

Expected: FAIL because the script module does not exist.

- [ ] **Step 3: Implement CLI**

Use `argparse` for `--categories`, `--per-category`, `--market`, `--providers`, `--resume-batch`, and `--dry-run`. Default categories come from the supported validation schemas. Dry run must not instantiate network clients or consume quota.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd backend; python -m pytest tests/knowledge/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/crawl_hardware_knowledge.py backend/tests/knowledge/test_cli.py
git commit -m "feat: add hardware crawl command"
```

## Task 9: Verification and First Live Batch

**Files:**
- Modify: `README.md`
- Create: `backend/data/knowledge/.gitignore`
- Create during execution: `backend/data/knowledge/hardware/manifests/<batch_id>.json`
- Create during execution: `backend/data/knowledge/hardware/normalized/<batch_id>/hardware.jsonl`
- Create during execution: `backend/data/knowledge/hardware/rejected/<batch_id>/hardware.jsonl`

- [ ] **Step 1: Run the complete automated suite**

Run: `cd backend; python -m pytest -q`

Expected: all tests pass with no network calls.

- [ ] **Step 2: Compile the backend**

Run: `cd backend; python -m compileall -q app scripts`

Expected: exit code 0.

- [ ] **Step 3: Run provider readiness without quota**

Run: `cd backend; python scripts/crawl_hardware_knowledge.py --dry-run`

Expected: each provider reports `ready` or an exact missing non-secret setting; no external call is made.

- [ ] **Step 4: Run a bounded live sample**

Run:

```powershell
cd backend
python scripts/crawl_hardware_knowledge.py `
  --categories cpu gpu motherboard memory storage psu cooler case `
  --per-category 1 `
  --market US
```

Expected: one manifest, accepted/rejected JSONL files, provider call summaries, and no secret text. This run targets at most eight accepted records to limit initial cost.

- [ ] **Step 5: Audit outputs**

Run:

```powershell
cd backend
python -c "from pathlib import Path; import json; p=max(Path('data/knowledge/hardware/manifests').glob('*.json')); d=json.loads(p.read_text(encoding='utf-8')); print({k:d[k] for k in ['batch_id','discovered_count','accepted_count','rejected_count','provider_status']})"
```

Expected: all six providers have an explicit status, counts are internally consistent, and records with missing required fields are rejected.

- [ ] **Step 6: Document usage and limitations**

Update README with the command, storage locations, provider roles, cost warning, and explicit statement that this batch is staged for review and not yet indexed into Qdrant.

- [ ] **Step 7: Commit**

```bash
git add README.md backend/data/knowledge/.gitignore
git commit -m "docs: document managed hardware crawl"
```

## Execution Note

The current workspace contains an empty `.git` directory and is not a valid Git repository. The commit commands above define intended checkpoints but cannot be executed until Git metadata is restored. Implementation must not initialize a new repository or invent history without user approval.
