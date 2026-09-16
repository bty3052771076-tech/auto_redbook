from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator


SourceType = Literal["official", "aggregator", "social", "search", "github"]
VerificationStatus = Literal[
    "official_only",
    "aggregator_confirmed",
    "social_confirmed",
    "aggregator_only",
    "social_only",
    "search_only",
    "rejected",
]


_VOID_HTML_TAGS = (
    "script",
    "style",
    "noscript",
    "img",
    "br",
    "hr",
    "source",
    "iframe",
    "video",
    "audio",
    "embed",
    "input",
    "meta",
    "link",
)
_HTML_TAG_RE = re.compile(r"(?is)<\s*/?\s*[a-zA-Z][a-zA-Z0-9:-]*(?:\s[^<>]*)?>")
_DANGLING_HTML_TAG_RE = re.compile(r"(?is)<\s*/?\s*[a-zA-Z][a-zA-Z0-9:-]*\b[^<>]*$")
_HTML_ATTR_RE = re.compile(
    r"(?i)\b(?:referrerpolicy|src|width|height|alt|class|style|id|data-[a-z0-9-]+)"
    r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s，。！？；;，]+)"
)
_BARE_HTML_ATTR_RE = re.compile(r"(?i)\b(?:referrerpolicy|src|width|height)\b(?=\s|$)")
_HTML_ARTIFACT_RE = re.compile(
    r"(?is)<\s*/?\s*(?:p|div|img|span|a|br|table|tr|td|ul|ol|li|h[1-6]|html|body|section|article|font|strong|em|figure)\b"
)


def strip_html_artifacts(text: str) -> str:
    """Remove HTML markup and leftover attributes from source text.

    Search providers frequently return NetEase-style fragments such as
    ``<p id="x">...</p><img referrerpolicy='no-referrer' src='...'>``. Those
    must never reach a card image or a saved draft, so every ingestion path
    funnels through here before the text is stored on an item.
    """

    cleaned = unescape(str(text or ""))
    if not cleaned:
        return ""
    for tag in _VOID_HTML_TAGS:
        cleaned = re.sub(rf"(?is)<{tag}\b[^<>]*>?", " ", cleaned)
    cleaned = re.sub(r"(?is)<br\s*/?>", " ", cleaned)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    # A payload cut off mid-tag leaves a bare ``<img referrerpolicy=...`` tail.
    cleaned = _DANGLING_HTML_TAG_RE.sub(" ", cleaned)
    cleaned = _HTML_ATTR_RE.sub(" ", cleaned)
    cleaned = _BARE_HTML_ATTR_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("<", " ").replace(">", " ")
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def has_html_artifacts(text: str) -> bool:
    """Return True when source text still looks like raw HTML or attributes."""

    value = str(text or "")
    if not value:
        return False
    if _HTML_ARTIFACT_RE.search(value):
        return True
    if _DANGLING_HTML_TAG_RE.search(value):
        return True
    return bool(_BARE_HTML_ATTR_RE.search(value) or _HTML_ATTR_RE.search(value))


def _normalize_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    query_parts = []
    for chunk in (parts.query or "").split("&"):
        if not chunk:
            continue
        key = chunk.split("=", 1)[0].lower()
        if key.startswith("utm_") or key in {"ref", "source", "fbclid", "gclid"}:
            continue
        query_parts.append(chunk)
    path = parts.path or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            "&".join(query_parts),
            "",
        )
    )


def _normalize_title_key(value: str) -> str:
    text = re.sub(r"\s+", "", value or "").lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text


class AIUpdateItem(BaseModel):
    title: str
    summary: str = ""
    source_name: str = ""
    source_type: SourceType = "official"
    url: str = ""
    published_at: str = ""
    vendor: str = ""
    product: str = ""
    raw_excerpt: str = ""
    confidence_score: float = 0.0
    verification_status: VerificationStatus = "official_only"
    evidence_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "summary", "source_name", "vendor", "product", "raw_excerpt", mode="before")
    @classmethod
    def _strip_text(cls, value):
        text = str(value or "").strip()
        if not text:
            return ""
        # Source payloads (especially search-provider results) can embed raw
        # HTML fragments. Strip them on construction so no downstream caller
        # can render or store markup as reader-facing text.
        return strip_html_artifacts(text)

    @field_validator("url", "published_at", mode="before")
    @classmethod
    def _strip_url_text(cls, value):
        # URLs and timestamps must survive verbatim; only trim whitespace.
        return str(value or "").strip()

    @field_validator("evidence_urls", "tags", mode="before")
    @classmethod
    def _clean_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            out.append(text)
            seen.add(text)
        return out

    @model_validator(mode="after")
    def _normalize_status_and_score(self):
        if self.source_type == "social" and self.verification_status == "official_only":
            self.verification_status = "social_only"
        if self.source_type == "aggregator" and self.verification_status == "official_only":
            self.verification_status = "aggregator_only"
        if self.source_type == "search" and self.verification_status == "official_only":
            self.verification_status = "search_only"
        if self.confidence_score <= 0:
            base = {
                "official": 0.85,
                "github": 0.78,
                "aggregator": 0.62,
                "search": 0.55,
                "social": 0.45,
            }.get(self.source_type, 0.4)
            if self.evidence_urls:
                base += min(0.1, len(self.evidence_urls) * 0.03)
            self.confidence_score = round(min(base, 0.98), 3)
        return self

    @property
    def normalized_url(self) -> str:
        return _normalize_url(self.url)

    @property
    def title_key(self) -> str:
        return _normalize_title_key(self.title)

    @property
    def dedupe_key(self) -> str:
        url = self.normalized_url
        if url:
            return f"url:{url}"
        return f"title:{self.title_key}"

    @property
    def timestamp_sort_key(self) -> str:
        raw = (self.published_at or "").strip()
        if not raw:
            return ""
        try:
            if raw.endswith("Z"):
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return raw


class AIDigestBrief(BaseModel):
    title: str = "每日AI讯息"
    subtitle: str = ""
    date: str = ""
    items: list[AIUpdateItem] = Field(default_factory=list)
    source_summary: str = ""
    generated_at: str = ""
