from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def now_iso() -> str:
    return datetime.utcnow().strftime(ISO_FORMAT)


class PostType(str, Enum):
    image = "image"
    video = "video"
    article = "article"


class PostStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    saved_draft = "saved_as_draft"
    canceled = "canceled"


class AssetInfo(BaseModel):
    path: str
    kind: str = "image"
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    validated: bool = False


class Post(BaseModel):
    schema_version: str = "1.0"
    id: str = Field(default_factory=lambda: uuid4().hex)
    type: PostType = PostType.image
    status: PostStatus = PostStatus.draft
    title: str = ""
    body: str = ""
    topics: List[str] = Field(default_factory=list)
    assets: List[AssetInfo] = Field(default_factory=list)
    schedule_at: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)
    platform: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class RevisionSource(str, Enum):
    llm = "llm"
    human_edit = "human_edit"


class Revision(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    post_id: str
    source: RevisionSource = RevisionSource.llm
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class StepResult(BaseModel):
    name: str
    status: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    detail: Optional[str] = None


class Execution(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    post_id: str
    attempt: int = 1
    started_at: str = Field(default_factory=now_iso)
    ended_at: Optional[str] = None
    result: str = "pending"  # success / saved_draft / failed / canceled
    error: Optional[dict[str, Any]] = None
    steps: List[StepResult] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)

