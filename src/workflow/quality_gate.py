from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image, ImageStat, UnidentifiedImageError

from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import ai_update_history_key, ai_update_quality_issues
from src.storage.models import Post, PostStatus


_BODY_DATE_RE = re.compile(r"(?:日期|发布时间)\s*[:：]\s*(\d{4}-\d{1,2}-\d{1,2})")
_TRACKING_QUERY_PREFIXES = ("utm_", "spm", "from", "source", "ref")
_TRADITIONAL_MARKERS = set(
    "臺灣發佈資訊號網絡軟體數據國際業產經濟場開啟關閉與為後這"
    "應該將會進實現選擇條聞內評價連結點擊瀏覽"
)


@dataclass(frozen=True)
class ImageInspection:
    ok: bool
    code: str
    message: str
    width: int = 0
    height: int = 0
    variance: float = 0.0


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    post_id: str = ""


@dataclass(frozen=True)
class BatchQualityReport:
    issues: tuple[QualityIssue, ...]
    warnings: tuple[QualityIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


def inspect_image(path: Path | str) -> ImageInspection:
    image_path = Path(path)
    if not image_path.is_file():
        return ImageInspection(False, "missing_image", f"图片文件不存在：{image_path}")
    try:
        with Image.open(image_path) as opened:
            opened.verify()
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            if width < 64 or height < 64:
                return ImageInspection(
                    False,
                    "image_too_small",
                    f"图片尺寸过小：{width}x{height}",
                    width,
                    height,
                )
            sample = image.copy()
            sample.thumbnail((256, 256))
            variance = max(float(value) for value in ImageStat.Stat(sample).var)
            if variance < 1.0:
                return ImageInspection(
                    False,
                    "blank_image",
                    "图片接近纯色或空白，不能作为新闻配图。",
                    width,
                    height,
                    variance,
                )
            return ImageInspection(
                True,
                "ok",
                "图片可解码且包含有效视觉内容。",
                width,
                height,
                variance,
            )
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        return ImageInspection(False, "broken_image", f"图片无法解码：{exc}")


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
    if match:
        try:
            return datetime.strptime(match.group(0), "%Y-%m-%d").date()
        except ValueError:
            return None
    compact_match = re.search(r"(?<!\d)(\d{8})(?:T\d{6}Z?)?(?!\d)", text)
    if compact_match:
        try:
            return datetime.strptime(compact_match.group(1), "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _normalized_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return text.lower()
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if any(key_lower == prefix or key_lower.startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES):
            continue
        query.append((key, value))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower().removeprefix("www."),
            parsed.path.rstrip("/") or "/",
            urllib.parse.urlencode(query),
            "",
        )
    )


def _news_metadata(post: Post) -> Mapping[str, object]:
    value = (post.platform or {}).get("news")
    return value if isinstance(value, Mapping) else {}


def _picked_metadata(post: Post) -> Mapping[str, object]:
    value = _news_metadata(post).get("picked")
    return value if isinstance(value, Mapping) else {}


def _source_url(post: Post) -> str:
    news = _news_metadata(post)
    picked = _picked_metadata(post)
    return _normalized_url(news.get("source_url") or picked.get("url"))


def _source_date(post: Post) -> date | None:
    picked = _picked_metadata(post)
    for key in ("seendate", "published_at", "date", "pubDate"):
        parsed = _parse_date(picked.get(key))
        if parsed is not None:
            return parsed
    return None


def _body_date(post: Post) -> date | None:
    match = _BODY_DATE_RE.search(post.body or "")
    return _parse_date(match.group(1)) if match else None


def _normalized_event_text(post: Post) -> str:
    picked = _picked_metadata(post)
    title = str(picked.get("title") or post.title or "")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())


def _ai_digest_metadata(post: Post) -> Mapping[str, object]:
    value = (post.platform or {}).get("ai_digest")
    return value if isinstance(value, Mapping) else {}


def _ai_digest_item_keys(post: Post) -> set[str]:
    raw_items = _ai_digest_metadata(post).get("items")
    if not isinstance(raw_items, list):
        return set()
    keys: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        try:
            item = AIUpdateItem.model_validate(raw_item)
        except Exception:
            item = None
        if item is not None:
            title = re.sub(r"\s+", "", item.title or "")
            # A previous draft with a generic generated headline must not
            # block a corrected retry. Concrete items still use event-level
            # keys so mirrored URLs cannot bypass the duplicate check.
            if (
                "generic_title" in ai_update_quality_issues(item)
                or re.search(r"(?:发布|推出|上线)新进展$", title)
            ):
                continue
            event_key = ai_update_history_key(item)
            if event_key:
                keys.add(event_key)
                continue
        url = _normalized_url(raw_item.get("url"))
        if url:
            keys.add(f"url:{url}")
            continue
        title = re.sub(
            r"[^a-z0-9\u4e00-\u9fff]+",
            "",
            str(raw_item.get("title") or "").lower(),
        )
        if title:
            keys.add(f"title:{title}")
    return keys


def _same_event(left: Post, right: Post) -> bool:
    left_digest = _ai_digest_metadata(left)
    right_digest = _ai_digest_metadata(right)
    if left_digest or right_digest:
        if not left_digest or not right_digest:
            return False
        left_keys = _ai_digest_item_keys(left)
        right_keys = _ai_digest_item_keys(right)
        if not left_keys or not right_keys:
            return False
        overlap_ratio = len(left_keys & right_keys) / min(len(left_keys), len(right_keys))
        return overlap_ratio >= 0.75

    left_url = _source_url(left)
    right_url = _source_url(right)
    if left_url and right_url and left_url == right_url:
        return True
    a = _normalized_event_text(left)
    b = _normalized_event_text(right)
    if not a or not b:
        return False
    ratio = SequenceMatcher(None, a, b).ratio()
    shared = set(re.findall(r"[a-z]{2,}|\d+|[\u4e00-\u9fff]{2,}", a)) & set(
        re.findall(r"[a-z]{2,}|\d+|[\u4e00-\u9fff]{2,}", b)
    )
    if ratio >= 0.72:
        return True
    cjk_a = {a[index : index + 2] for index in range(max(0, len(a) - 1))}
    cjk_b = {b[index : index + 2] for index in range(max(0, len(b) - 1))}
    union = cjk_a | cjk_b
    jaccard = len(cjk_a & cjk_b) / len(union) if union else 0.0
    return ratio >= 0.58 and jaccard >= 0.35 and bool(shared or ("meta" in a and "meta" in b))


def _has_traditional_marker(text: str) -> bool:
    return any(character in _TRADITIONAL_MARKERS for character in (text or ""))


def _post_issues(post: Post) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    text_fields = [post.title or "", post.body or "", *(post.topics or [])]
    if any(_has_traditional_marker(text) for text in text_fields):
        issues.append(
            QualityIssue(
                "non_simplified_chinese",
                "标题、正文或话题中仍含常见繁体字，请转换为简体中文。",
                post.id,
            )
        )
    if "原文标题" in (post.body or ""):
        issues.append(
            QualityIssue(
                "forbidden_original_title",
                "正文仍包含“原文标题”部分。",
                post.id,
            )
        )
    news = _news_metadata(post)
    if news:
        source_url = _source_url(post)
        if not source_url.startswith(("http://", "https://")):
            issues.append(
                QualityIssue(
                    "missing_source_url",
                    "每日新闻缺少可追溯的 HTTP 来源链接。",
                    post.id,
                )
            )
        source_date = _source_date(post)
        body_date = _body_date(post)
        if source_date is None:
            issues.append(
                QualityIssue(
                    "missing_source_date",
                    "来源记录没有可解析的发布时间。",
                    post.id,
                )
            )
        elif body_date is None:
            issues.append(
                QualityIssue(
                    "missing_body_date",
                    "草稿正文没有可解析的日期。",
                    post.id,
                )
            )
        elif source_date != body_date:
            issues.append(
                QualityIssue(
                    "source_date_mismatch",
                    f"正文日期 {body_date.isoformat()} 与来源日期 {source_date.isoformat()} 不一致。",
                    post.id,
                )
            )
    for asset in post.assets or []:
        if (asset.kind or "image").lower() != "image":
            continue
        inspected = inspect_image(asset.path)
        if not inspected.ok:
            issues.append(QualityIssue(inspected.code, inspected.message, post.id))
    return issues


def validate_post_batch(
    posts: Iterable[Post],
    *,
    expected_count: int,
    historical_posts: Iterable[Post] = (),
) -> BatchQualityReport:
    items = list(posts)
    issues: list[QualityIssue] = []
    if len(items) != expected_count:
        issues.append(
            QualityIssue(
                "batch_count_mismatch",
                f"批次数量不完整：要求 {expected_count} 条，当前 {len(items)} 条。",
            )
        )
    for post in items:
        issues.extend(_post_issues(post))
    for index, post in enumerate(items):
        for previous in items[:index]:
            if _same_event(post, previous):
                issues.append(
                    QualityIssue(
                        "duplicate_event",
                        f"与本批草稿 {previous.id} 疑似为同一事件。",
                        post.id,
                    )
                )
                break
    historical = [
        post
        for post in historical_posts
        if post.id not in {item.id for item in items}
        and (post.uploaded or post.status in {PostStatus.saved_draft, PostStatus.published})
    ]
    for post in items:
        for previous in historical:
            if _same_event(post, previous):
                issues.append(
                    QualityIssue(
                        "historical_duplicate",
                        f"与历史草稿或已发布内容 {previous.id} 疑似重复。",
                        post.id,
                    )
                )
                break
    return BatchQualityReport(issues=tuple(issues))
