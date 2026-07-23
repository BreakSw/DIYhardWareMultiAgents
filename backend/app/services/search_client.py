from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.recommendations import RequirementProfile


class SerpApiClient:
    endpoint = "https://serpapi.com/search.json"

    @property
    def is_configured(self) -> bool:
        return bool(settings.serpapi_key)

    def search_hardware(
        self, profile: RequirementProfile, query: str | None = None
    ) -> dict[str, Any]:
        if not settings.serpapi_key:
            return self._unavailable("SerpAPI key 未配置")

        budget_text = (
            f"{profile.budget_min}元以上"
            if profile.budget_max is None
            else f"{profile.budget_min}到{profile.budget_max}元"
        )
        query = query or (
            f"{budget_text} 电脑配置单 "
            f"{profile.resolution} {profile.usage} 显卡 CPU 价格 2026"
        )
        started = time.perf_counter()
        try:
            response = httpx.get(
                self.endpoint,
                params={
                    "engine": "google",
                    "q": query,
                    "api_key": settings.serpapi_key,
                    "hl": "zh-cn",
                    "gl": "cn",
                    "num": 8,
                    "output": "json",
                },
                timeout=20.0,
                trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))

            raw_results = payload.get("shopping_results") or payload.get("organic_results") or []
            results = [
                {
                    "title": item.get("title", ""),
                    "link": item.get("link") or item.get("product_link") or "",
                    "source": item.get("source") or item.get("displayed_link") or "Google",
                    "snippet": item.get("snippet", ""),
                    "price": item.get("price"),
                    "extracted_price": item.get("extracted_price"),
                }
                for item in raw_results[:8]
            ]
            return {
                "status": "success",
                "provider": "serpapi",
                "query": query,
                "result_count": len(results),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "results": results,
                "error": None,
            }
        except Exception as exc:
            return self._unavailable(str(exc), query, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _unavailable(error: str, query: str = "", latency_ms: int = 0) -> dict[str, Any]:
        return {
            "status": "failed",
            "provider": "serpapi",
            "query": query,
            "result_count": 0,
            "latency_ms": latency_ms,
            "results": [],
            "error": error[:300],
        }
