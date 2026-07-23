from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
PLACEHOLDER_PREFIX = "<FILL_"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _usable(value: str) -> bool:
    return bool(value and not value.startswith(PLACEHOLDER_PREFIX))


@dataclass(frozen=True)
class CrawlerSettings:
    serpapi_key: str = ""
    apify_api_token: str = ""
    apify_actor_id: str = "apify~web-scraper"
    brightdata_api_token: str = ""
    brightdata_zone: str = ""
    zyte_api_key: str = ""
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev/v2"

    @classmethod
    def from_env(cls, path: Path = ROOT_DIR / ".env") -> "CrawlerSettings":
        raw = _read_env(path)
        return cls(
            serpapi_key=raw.get("serpapi-key", ""),
            apify_api_token=raw.get("apify-api-token", ""),
            apify_actor_id=raw.get("apify-actor-id", cls.apify_actor_id),
            brightdata_api_token=raw.get("brightdata-api-token", ""),
            brightdata_zone=raw.get("brightdata-zone", ""),
            zyte_api_key=raw.get("zyte-api-key", ""),
            firecrawl_api_key=raw.get("firecrawl-api-key", ""),
            firecrawl_base_url=raw.get(
                "firecrawl-base-url",
                cls.firecrawl_base_url,
            ).rstrip("/"),
        )

    def provider_ready(self, provider: str) -> bool:
        requirements = {
            "serpapi": [self.serpapi_key],
            "apify": [self.apify_api_token, self.apify_actor_id],
            "brightdata": [
                self.brightdata_api_token,
                self.brightdata_zone,
            ],
            "zyte": [self.zyte_api_key],
            "firecrawl": [self.firecrawl_api_key],
            "ecb": ["public"],
        }
        return all(_usable(value) for value in requirements.get(provider, []))

    def secrets(self) -> list[str]:
        return [
            value
            for value in [
                self.serpapi_key,
                self.apify_api_token,
                self.brightdata_api_token,
                self.zyte_api_key,
                self.firecrawl_api_key,
            ]
            if _usable(value)
        ]


settings = CrawlerSettings.from_env()

