from __future__ import annotations

import time

import httpx

from app.knowledge.http import create_managed_client, safe_http_status
from app.knowledge.models import ProviderResult


PAGE_FUNCTION = """
async function pageFunction(context) {
  const { request, document } = context;
  const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .map((node) => node.textContent);
  return {
    url: request.loadedUrl,
    title: document.title,
    text: document.body ? document.body.innerText : '',
    jsonLd,
  };
}
""".strip()


class ApifyProvider:
    def __init__(
        self,
        api_token: str,
        actor_id: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_token = api_token
        self.actor_id = actor_id
        self.client = client or create_managed_client()

    @property
    def endpoint(self) -> str:
        return (
            "https://api.apify.com/v2/acts/"
            f"{self.actor_id}/run-sync-get-dataset-items"
        )

    def fetch(self, target_url: str) -> ProviderResult:
        started = time.perf_counter()
        try:
            response = self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_token}"},
                params={"timeout": 14},
                json={
                    "startUrls": [{"url": target_url}],
                    "maxRequestsPerCrawl": 1,
                    "pageFunction": PAGE_FUNCTION,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return ProviderResult(
                provider="apify",
                status="completed",
                data={"items": payload if isinstance(payload, list) else []},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ProviderResult(
                provider="apify",
                status="failed",
                error=type(exc).__name__,
                status_code=safe_http_status(exc),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
