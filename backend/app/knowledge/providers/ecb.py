from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree

import httpx

from app.knowledge.http import create_managed_client
from app.knowledge.models import ExchangeRate


class EcbProvider:
    endpoint = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or create_managed_client()

    def latest(self) -> ExchangeRate:
        response = self.client.get(self.endpoint)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        dated = next(
            element
            for element in root.iter()
            if element.attrib.get("time")
        )
        rates = {
            element.attrib["currency"]: Decimal(element.attrib["rate"])
            for element in dated
            if "currency" in element.attrib and "rate" in element.attrib
        }
        return ExchangeRate(
            usd_cny=(rates["CNY"] / rates["USD"]).quantize(
                Decimal("0.000001")
            ),
            published_at=dated.attrib["time"],
        )
