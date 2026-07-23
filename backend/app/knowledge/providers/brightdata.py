from __future__ import annotations

import time

import httpx

from app.knowledge.http import create_managed_client, safe_http_status
from app.knowledge.models import ProviderResult


class BrightDataProvider:
    endpoint = "https://api.brightdata.com/request"

    def __init__(
        self,
        api_token: str,
        zone: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_token = api_token
        self.zone = zone
        self.client = client or create_managed_client()

    def fetch(self, target_url: str) -> ProviderResult:
        started = time.perf_counter()
        try:
            response = self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_token}"},
                json={
                    "zone": self.zone,
                    "url": target_url,
                    "format": "raw",
                },
            )
            response.raise_for_status()
            return ProviderResult(
                provider="brightdata",
                status="completed",
                data={"html": response.text},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ProviderResult(
                provider="brightdata",
                status="failed",
                error=type(exc).__name__,
                status_code=safe_http_status(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
