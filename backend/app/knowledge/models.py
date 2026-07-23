from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
)


class Candidate(BaseModel):
    category: str
    title: str
    url: HttpUrl
    detail_url: HttpUrl | None = None
    merchant: str = ""
    price_usd: Decimal | None = None
    position: int = 0


class ExchangeRate(BaseModel):
    usd_cny: Decimal
    published_at: str
    source: str = "ECB"


class ValidationResult(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    accepted: bool
    quality_level: Literal["verified", "partial"]
    missing_fields: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    reason_code: str = ""

    @field_validator("accepted")
    @classmethod
    def accepted_matches_quality_level(
        cls,
        accepted: bool,
        info: ValidationInfo,
    ) -> bool:
        quality_level = info.data.get("quality_level")
        expected = "verified" if accepted else "partial"
        if quality_level is not None and quality_level != expected:
            raise ValueError("accepted and quality_level must agree")
        return accepted

    @field_validator("quality_level")
    @classmethod
    def quality_level_matches_accepted(
        cls,
        quality_level: Literal["verified", "partial"],
        info: ValidationInfo,
    ) -> Literal["verified", "partial"]:
        accepted = info.data.get("accepted")
        expected = "verified" if accepted else "partial"
        if accepted is not None and quality_level != expected:
            raise ValueError("accepted and quality_level must agree")
        return quality_level


class ProviderResult(BaseModel):
    provider: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    status_code: int | None = None
    latency_ms: int = 0
