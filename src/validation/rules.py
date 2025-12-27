from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.storage.models import Post, PostType

MAX_IMAGE_TITLE = 20
MAX_IMAGE_BODY = 1000
MAX_IMAGE_COUNT = 18
MAX_IMAGE_SIZE_BYTES = 32 * 1024 * 1024

MAX_ARTICLE_TITLE = 64


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _limit_for_title(post_type: PostType) -> int:
    if post_type == PostType.article:
        return MAX_ARTICLE_TITLE
    return MAX_IMAGE_TITLE


def _limit_for_body(post_type: PostType) -> Optional[int]:
    if post_type == PostType.image:
        return MAX_IMAGE_BODY
    return None


def validate_post(post: Post) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    title = (post.title or "").strip()
    body = (post.body or "").strip()
    if not title:
        errors.append("title is required")
    if not body:
        errors.append("body is required")

    max_title = _limit_for_title(post.type)
    if len(title) > max_title:
        errors.append(f"title too long: {len(title)} > {max_title}")

    max_body = _limit_for_body(post.type)
    if max_body is not None and len(body) > max_body:
        errors.append(f"body too long: {len(body)} > {max_body}")

    assets = post.assets or []
    if post.type == PostType.image:
        if not assets:
            errors.append("at least 1 image asset is required")
        if len(assets) > MAX_IMAGE_COUNT:
            errors.append(f"too many images: {len(assets)} > {MAX_IMAGE_COUNT}")

    for asset in assets:
        path = Path(asset.path)
        if not path.exists():
            errors.append(f"asset not found: {asset.path}")
            continue
        size = path.stat().st_size
        if post.type == PostType.image and size > MAX_IMAGE_SIZE_BYTES:
            errors.append(f"asset too large: {asset.path} ({size} bytes)")

    return ValidationResult(errors=errors, warnings=warnings)
