from __future__ import annotations

import time
from typing import Any

import httpx

from app.knowledge.http import create_managed_client, safe_http_status
from app.knowledge.models import ProviderResult


class ZyteProvider:
    endpoint = "https://api.zyte.com/v1/extract"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or create_managed_client()

    def extract(
        self,
        target_url: str,
        schema: dict[str, Any],
    ) -> ProviderResult:
        started = time.perf_counter()
        try:
            response = self.client.post(
                self.endpoint,
                auth=(self.api_key, ""),
                json={
                    "url": target_url,
                    "product": True,
                    "productOptions": {"extractFrom": "browserHtml"},
                    "customAttributes": schema,
                    "customAttributesOptions": {"method": "extract"},
                    "geolocation": "US",
                },
            )
            response.raise_for_status()
            return ProviderResult(
                provider="zyte",
                status="completed",
                data=response.json(),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ProviderResult(
                provider="zyte",
                status="failed",
                error=type(exc).__name__,
                status_code=safe_http_status(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
