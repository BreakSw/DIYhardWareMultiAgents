import httpx

from app.knowledge.providers.apify import ApifyProvider
from app.knowledge.providers.brightdata import BrightDataProvider
from app.knowledge.providers.firecrawl import FirecrawlProvider
from app.knowledge.providers.zyte import ZyteProvider


def test_target_pages_are_sent_only_to_managed_api_hosts() -> None:
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        if request.url.host == "api.firecrawl.dev":
            return httpx.Response(
                200,
                json={"success": True, "data": {"markdown": "# Product"}},
            )
        if request.url.host == "api.zyte.com":
            return httpx.Response(
                200,
                json={
                    "product": {
                        "name": "Product",
                        "price": "100",
                        "currency": "USD",
                    }
                },
            )
        if request.url.host == "api.brightdata.com":
            return httpx.Response(200, text="<html>Product</html>")
        return httpx.Response(
            200,
            json=[{"url": "https://target.example/item", "text": "Product"}],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    FirecrawlProvider("key", client).fetch(
        "https://target.example/item",
        {"type": "object", "properties": {}},
    )
    ZyteProvider("key", client).extract(
        "https://target.example/item",
        {"type": "object", "properties": {}},
    )
    BrightDataProvider("key", "zone", client).fetch(
        "https://target.example/item"
    )
    ApifyProvider("key", "apify~web-scraper", client).fetch(
        "https://target.example/item"
    )

    assert set(seen_hosts) == {
        "api.firecrawl.dev",
        "api.zyte.com",
        "api.brightdata.com",
        "api.apify.com",
    }
    assert "target.example" not in seen_hosts


def test_managed_provider_failure_keeps_safe_http_status() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(402, json={"error": "billing required"})
        )
    )

    result = FirecrawlProvider("key", client).fetch(
        "https://target.example/item",
        {"type": "object", "properties": {}},
    )

    assert result.status == "failed"
    assert result.error == "HTTPStatusError"
    assert result.status_code == 402
    assert "billing required" not in str(result.model_dump())
