from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


WoolSourceType = Literal["official", "social", "aggregator", "search", "github"]


class WoolOffer(BaseModel):
    """A traceable, recently published AI benefit or quota notice."""

    title: str
    provider: str = ""
    benefit: str
    claim_steps: str = ""
    source_name: str = ""
    source_type: WoolSourceType = "official"
    url: str
    published_at: str
    confidence_score: float = 0.0
    tags: list[str] = Field(default_factory=list)

    @field_validator(
        "title",
        "provider",
        "benefit",
        "claim_steps",
        "source_name",
        "url",
        "published_at",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
