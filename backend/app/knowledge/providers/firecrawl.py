from __future__ import annotations

import time
from typing import Any

import httpx

from app.knowledge.http import create_managed_client, safe_http_status
from app.knowledge.models import ProviderResult


class FirecrawlProvider:
    endpoint = "https://api.firecrawl.dev/v2/scrape"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or create_managed_client()

    def fetch(self, target_url: str, schema: dict[str, Any]) -> ProviderResult:
        started = time.perf_counter()
        try:
            response = self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "url": target_url,
                    "onlyMainContent": True,
                    "formats": [
                        "markdown",
                        {
                            "type": "json",
                            "schema": schema,
                            "prompt": (
                                "Extract only values explicitly present on the "
                                "page. Return null for missing values."
                            ),
                        },
                    ],
                },
            )
            response.raise_for_status()
            return ProviderResult(
                provider="firecrawl",
                status="completed",
                data=response.json(),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ProviderResult(
                provider="firecrawl",
                status="failed",
                error=type(exc).__name__,
                status_code=safe_http_status(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
