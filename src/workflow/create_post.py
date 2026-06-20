from __future__ import annotations

import json
import hashlib
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from dataclasses import replace
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Iterable, List, Optional

from src.config import load_llm_configs
from src.images.auto_image import (
    ImageGenerationAbandoned,
    fetch_and_download_related_images,
    is_auto_image_enabled,
)
from src.llm.generate import generate_draft
from src.news.daily_news import (
    fetch_and_pick_daily_news,
    fetch_daily_news_candidates,
    pick_news_items,
)
from src.storage.files import copy_assets_into_post, post_dir, save_post, save_revision
from src.storage.models import AssetInfo, Post, PostStatus, Revision, RevisionSource
from src.validation.rules import MAX_IMAGE_BODY


_URL_RE = re.compile(r"(?:https?://|www\.)\S+", flags=re.IGNORECASE)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_DAILY_NEWS_PREFIX_RE = re.compile(r"^(?:每日新闻)(?:[｜|:：\-—–\s]+)?")
_SOURCE_LOOKUP_MIN_CHARS = 120


def _strip_urls(text: str) -> str:
    cleaned = _URL_RE.sub("", text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _has_cjk(text: str | None) -> bool:
    return bool(_CJK_CHAR_RE.search(text or ""))


def _has_japanese_kana(text: str | None) -> bool:
    return bool(_JAPANESE_KANA_RE.search(text or ""))


def _source_lookup_min_chars() -> int:
    raw = (os.getenv("NEWS_SOURCE_CONTEXT_MIN_CHARS") or "").strip()
    if not raw:
        return _SOURCE_LOOKUP_MIN_CHARS
    try:
        return max(40, int(raw))
    except ValueError:
        return _SOURCE_LOOKUP_MIN_CHARS


def _source_lookup_enabled() -> bool:
    raw = (os.getenv("NEWS_SOURCE_LOOKUP") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _source_lookup_timeout_s() -> float:
    raw = (os.getenv("NEWS_SOURCE_LOOKUP_TIMEOUT_S") or "").strip()
    if not raw:
        return 8.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 8.0


def _daily_news_context_is_incomplete(picked) -> bool:
    description = _strip_urls(getattr(picked, "description", "") or "")
    content = _strip_urls(getattr(picked, "content", "") or "")
    text = re.sub(r"\s+", " ", f"{description} {content}").strip()
    if len(text) < _source_lookup_min_chars():
        return True
    # NewsAPI frequently returns truncated snippets such as "[+123 chars]".
    return bool(re.search(r"\[\+\d+\s+chars?\]", text, flags=re.IGNORECASE))


def _fetch_original_news_excerpt(
    url: str,
    *,
    timeout_s: float = 8.0,
    max_chars: int = 1200,
) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read(600_000)
    html = raw.decode(charset, errors="replace")
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def _enrich_daily_news_item(picked):
    meta = {
        "source_lookup": {
            "needed": False,
            "ok": False,
            "skipped": "",
            "chars": 0,
        }
    }
    if not _daily_news_context_is_incomplete(picked):
        return picked, meta
    meta["source_lookup"]["needed"] = True
    if not _source_lookup_enabled():
        meta["source_lookup"]["skipped"] = "disabled"
        return picked, meta
    if not (getattr(picked, "url", "") or "").strip():
        meta["source_lookup"]["skipped"] = "missing_url"
        return picked, meta

    try:
        excerpt = _fetch_original_news_excerpt(
            picked.url,
            timeout_s=_source_lookup_timeout_s(),
            max_chars=1200,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        meta["source_lookup"]["error"] = str(exc)
        return picked, meta

    excerpt = _strip_urls(excerpt)
    if not excerpt:
        meta["source_lookup"]["skipped"] = "empty_excerpt"
        return picked, meta

    parts = [str(getattr(picked, "content", "") or "").strip(), f"原文摘录：{excerpt}"]
    content = "\n".join(part for part in parts if part).strip()
    meta["source_lookup"]["ok"] = True
    meta["source_lookup"]["chars"] = len(excerpt)
    return replace(picked, content=content), meta


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_asset_infos(paths: Iterable[Path]) -> List[AssetInfo]:
    infos: List[AssetInfo] = []
    for p in paths:
        if not p.exists():
            continue
        infos.append(
            AssetInfo(
                path=str(p),
                kind="image",
                size_bytes=p.stat().st_size,
                sha256=_sha256(p),
                validated=True,
            )
        )
    return infos


def _merge_image_ids(target: Optional[set[str]], metas: list[dict]) -> None:
    if target is None:
        return
    for meta in metas:
        if not isinstance(meta, dict):
            continue
        picked = meta.get("picked")
        if not isinstance(picked, dict):
            continue
        image_id = picked.get("id")
        if image_id:
            target.add(str(image_id))


def _clean_daily_news_title_candidate(value: str) -> str:
    text = _strip_urls(value or "")
    text = _DAILY_NEWS_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'“”‘’（）()[]【】")
    for sep in ("。", "；", ";", "，", ",", "：", ":", " - ", "—", "（", "("):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if head:
                text = head
                break
    return text.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'“”‘’（）()[]【】")


def _keyword_daily_news_title(text: str, prompt_norm: str = "") -> str:
    lower = f"{text or ''} {prompt_norm or ''}".lower()
    if (
        "外贸" in text
        or "贸易" in text
        or "貿易" in text
        or "貿" in text
        or any(w in lower for w in ("trade", "export", "import"))
    ):
        return "外贸数据出现变化"
    if "科技" in text or "人工智能" in text or any(
        w in lower for w in ("ai", "chip", "tech", "technology", "software", "model")
    ):
        return "科技议题出现进展"
    if "经济" in text or any(w in lower for w in ("market", "inflation", "prices", "economy")):
        return "经济议题出现变化"
    if "社会" in text or any(w in lower for w in ("court", "case", "sentence", "police", "school")):
        return "社会事件出现进展"
    return "国际议题出现进展"


def _normalize_daily_news_title(
    title: str,
    picked=None,
    prompt_norm: str = "",
    *,
    max_len: int = 20,
) -> str:
    candidates: list[str] = [title]
    if picked is not None:
        candidates.extend(
            [
                getattr(picked, "description", "") or "",
                getattr(picked, "content", "") or "",
                getattr(picked, "title", "") or "",
            ]
        )
    candidates.append(prompt_norm)

    for candidate in candidates:
        cleaned = _clean_daily_news_title_candidate(candidate)
        if not cleaned or _has_japanese_kana(cleaned) or not _has_cjk(cleaned):
            continue
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rstrip("，,。.!！?？:：|｜-—–")
        if cleaned and not _has_japanese_kana(cleaned):
            return cleaned

    joined = " ".join(candidates)
    fallback = _keyword_daily_news_title(joined, prompt_norm)
    return fallback[:max_len].rstrip()


def _shorten_daily_news_title(news_title: str, *, max_len: int = 20) -> str:
    return _normalize_daily_news_title(news_title, None, "", max_len=max_len)


def _is_generic_daily_news_title(title: str) -> bool:
    """
    LLM sometimes keeps the seed title "每日新闻" unchanged (or returns "每日新闻｜"),
    which makes the post list hard to scan. Treat these as generic.
    """
    text = (title or "").strip()
    if not text:
        return True
    rest = re.sub(r"^(?:每日新闻)(?:[｜:：—\s-]+)?", "", text).strip()
    return rest == ""


def _daily_news_title_key(title: str) -> str:
    """
    Normalize a daily-news title for in-batch dedupe.

    - Removes "每日新闻" prefix variants
    - Normalizes whitespace/punctuation
    """
    text = (title or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^(?:每日新闻)(?:[｜:：—\s-]+)?", "", text).strip() or text
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip("｜:：—- ")


def _extract_embedded_json_from_daily_news_body(body: str) -> dict | None:
    """
    Some providers return a JSON object *inside* the JSON.body string, e.g.:
        要点摘要：{
        新闻内容：
        "title": "...",
        ...
        "topics": [...],
        "image_event": "..."
        }

    This breaks title/topics extraction and pollutes the final body.
    Try to recover that embedded JSON draft.
    """
    text = (body or "").strip()
    if not text:
        return None
    if not text.startswith(f"{_NEWS_SUMMARY_LABEL}{{"):
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = text[start : end + 1]
    # Remove section labels that might have leaked into the embedded JSON.
    blob = blob.replace(_NEWS_CONTENT_LABEL, "").replace(_NEWS_COMMENT_LABEL, "").strip()
    try:
        obj = json.loads(blob)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if not any(k in obj for k in ("title", "body", "topics", "image_event")):
        return None
    return obj


def _clip_text(value: str | None, *, limit: int = 400) -> str:
    text = (value or "").strip()
    if not text:
        return "无"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _clamp_image_body(body: str) -> str:
    """
    Keep the final body within the platform limit (see validate_post / MAX_IMAGE_BODY).

    Note: daily-news workflow may append source lines after the LLM output, which can
    push the total length over the limit even if the model followed "Body <= 1000".
    """
    text = (body or "").strip()
    if len(text) <= MAX_IMAGE_BODY:
        return text
    return text[:MAX_IMAGE_BODY].rstrip()


def _preferred_image_title(post: Post, fallback: str) -> str:
    news_meta = (post.platform or {}).get("news") or {}
    picked = news_meta.get("picked")
    if isinstance(picked, dict):
        picked_title = (picked.get("title") or "").strip()
        if picked_title:
            return picked_title
    return fallback


def _preferred_image_hint(post: Post, fallback: str) -> str:
    news_meta = (post.platform or {}).get("news") or {}
    if isinstance(news_meta, dict):
        event = (news_meta.get("image_event") or "").strip()
        if event:
            return event
    picked = news_meta.get("picked")
    if isinstance(picked, dict):
        picked_title = (picked.get("title") or "").strip()
        if picked_title:
            return picked_title
        picked_desc = (picked.get("description") or "").strip()
        if picked_desc:
            return picked_desc
    return fallback


_IMAGE_EVENT_DROP_WORDS = (
    "每日新闻",
    "新闻",
    "报道",
    "采访",
    "记者",
    "媒体",
    "来源",
    "链接",
    "时间",
)

_NEWS_SUMMARY_LABEL = "要点摘要："
_NEWS_CONTENT_LABEL = "新闻内容："
_NEWS_COMMENT_LABEL = "点评："

_NEWS_PROMPT_LEAK_MARKERS = (
    "你正在为小红书图文笔记写《每日新闻》栏目",
    "请依据下面提供的新闻信息",
    "注意：body 正文里不要包含",
    "只允许使用下列已提供的新闻信息",
    "输出为严格 JSON",
    "可用新闻信息",
    "新闻标题：",
    "来源名称：",
    "来源域名：",
    "用户关注点",
    "JSON 字段要求",
    "title：",
    "body：正文",
    "topics（数组",
    "image_event（字符串",
)


def _daily_news_body_has_prompt_leak(body: str) -> bool:
    """
    Detect providers that echo the daily-news prompt into the publishable body.

    The section labels alone are not enough to prove the body is safe because some
    models keep the labels while filling them with the prompt/instructions.
    """
    text = body or ""
    if not text.strip():
        return False
    return any(marker in text for marker in _NEWS_PROMPT_LEAK_MARKERS)


def _looks_like_jsonish_body(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return (
        t.startswith("{")
        or t.startswith("[")
        or "```json" in t
        or '"title"' in t
        or '"body"' in t
        or '"topics"' in t
        or '"image_event"' in t
    )


def _strip_json_artifacts(text: str) -> str:
    """
    Remove obvious JSON scaffolding leaked into body text.
    """
    lines: list[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if s in ("{", "}", "[", "]", "},", "],"):
            continue
        if re.match(r'^"?title"?\s*:\s*', s, flags=re.IGNORECASE):
            continue
        if re.match(r'^"?topics"?\s*:\s*', s, flags=re.IGNORECASE):
            continue
        if re.match(r'^"?image_event"?\s*:\s*', s, flags=re.IGNORECASE):
            continue
        m = re.match(r'^"?body"?\s*:\s*(.*)$', s, flags=re.IGNORECASE)
        if m:
            s = m.group(1).strip()
        s = s.rstrip(",").strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            s = s[1:-1]
        s = (
            s.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\'", "'")
            .strip()
        )
        if s:
            lines.extend(s.splitlines())
    out = "\n".join(lines).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def _normalize_image_event(value: str, *, fallback: str = "", limit: int = 40) -> str:
    """
    Normalize the LLM-provided short event description for image generation.

    Goals:
    - Keep it short (~30 chars).
    - Describe the *event* only (avoid "news/reporting" semantics).
    - Remove URLs and obvious workflow prefixes.
    """
    text = (value or "").strip()
    if not text:
        text = (fallback or "").strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"^(?:每日新闻|每日假新闻)(?:[｜:：—\s-]+)?", "", text).strip() or text
    for w in _IMAGE_EVENT_DROP_WORDS:
        if w:
            text = text.replace(w, "")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("：:—-，,。.!！？?\"'“”‘’（）()[]【】 ")
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _normalize_news_summary(value: str, *, fallback: str = "", limit: int = 40) -> str:
    text = (value or "").strip()
    if not text:
        text = (fallback or "").strip()
    text = _strip_urls(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("：:，,。.!！？?\"'“”‘’（）()[]【】")
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _is_publishable_daily_news_topic(topic: str, prompt_norm: str = "") -> bool:
    text = (topic or "").strip().lstrip("#")
    if not text:
        return False
    if prompt_norm and text == prompt_norm.strip():
        return False
    if len(text) > 20:
        return False
    if any(ch in text for ch in ("\n", "\r", "，", "。", "；", "：", "、")):
        return False
    blocked = (
        "选择",
        "适合小红书",
        "正文",
        "提示词",
        "包含要点",
        "点评",
        "生成",
    )
    return not any(word in text for word in blocked)


def _normalize_daily_news_topics(topics, prompt_norm: str = "") -> list[str]:
    normalized_topics: list[str] = []
    seen: set[str] = set()
    for t in topics or []:
        tt = str(t or "").strip().lstrip("#")
        if not _is_publishable_daily_news_topic(tt, prompt_norm):
            continue
        if tt in seen:
            continue
        normalized_topics.append(tt)
        seen.add(tt)
    if "每日新闻" not in seen:
        normalized_topics.insert(0, "每日新闻")
    return normalized_topics[:8]


def _format_news_seendate(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "未知"
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    if "T" in text:
        return text.split("T", 1)[0].strip() or text
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _ensure_news_publish_date(body: str, seendate: str | None) -> str:
    text = (body or "").strip()
    if not text:
        return text
    pub = _format_news_seendate(seendate)
    if pub != "未知" and pub in text:
        return text
    if "发布时间" in text:
        return text
    return f"{text}\n\n发布时间：{pub}"


def _daily_news_prompt(picked, prompt_norm: str) -> str:
    """
    Prompt for LLM to write publishable body ONLY (no metadata/requirements echoed).
    """
    return (
        "你正在为小红书图文笔记写《每日新闻》栏目。\n"
        "请依据下面提供的新闻信息，生成一份可直接发布的草稿。\n"
        "必须全部使用简体中文；如果原始材料是英文新闻、日文新闻或其他语言新闻，先翻译并用中文新闻写法改写，不得保留外文长句或日文假名。\n"
        "注意：body 正文里不要包含提示词/要求等元信息；不得输出 URL、网址、http(s) 链接。\n"
        "来源只写来源名称，网址只保存在本地 post.json 的 metadata 中；发布时间和来源仅在文末固定行输出。\n"
        "只允许使用下列已提供的新闻信息，不得新增事实或编造细节；内容不完整时，必须先查阅原新闻/原文摘录后再评价。\n"
        "如果原文摘录仍不足，不得推测数字、因果、人物关系或后续结果，只能说明“现有信息有限，需等待权威更新”。\n\n"
        "输出为严格 JSON（仅包含 keys: title, body, topics；可选 key: image_event），不要 Markdown/代码块。\n"
        "不要把任何 JSON 片段（例如 { } / \"title\": / \"topics\": / \"image_event\":）写进 body。\n\n"
        "可用新闻信息（仅限以下字段，链接仅供参考不要输出）：\n"
        f"- 新闻标题：{picked.title}\n"
        f"- 来源名称：{picked.source or '未知'}\n"
        f"- 来源域名：{picked.domain or '未知'}\n"
        f"- 发布时间：{picked.seendate or '未知'}\n"
        f"- 摘要：{_clip_text(picked.description, limit=300)}\n"
        f"- 正文片段：{_clip_text(picked.content, limit=500)}\n"
        f"- 链接：{picked.url}\n"
        f"- 用户关注点（可选）：{prompt_norm or '无'}\n\n"
        "JSON 字段要求：\n"
        "title：标题必须是20字以内的简体中文总结标题，基于新闻标题/摘要/原文摘录改写，必须包含具体事件关键词；不要加“每日新闻｜”前缀，不得仅为“每日新闻”，不得出现日文假名。\n"
        "body：正文，必须严格按以下格式输出（保留标签，不得更名/省略；段落之间空一行）：\n"
        "要点摘要：<约50字，概括新闻最重要部分，不要评价>\n"
        "新闻内容：\n"
        "<约200字的完整段落，围绕已给事实说明背景、进展、影响边界；不要写未经证实的细节>\n\n"
        "点评：\n"
        "<约80-120字的完整段落，必须基于上方新闻事实和原文摘录进行评价；信息不足时只做保守提醒，末尾附带1个互动问题>\n\n"
        "发布时间：YYYY-MM-DD\n"
        "来源：来源名称（不要写网址）\n"
        "长度约束：body 总长度（含换行）务必 <= 900 字符，避免写太长导致发布失败。\n"
        "点评写作约束：坚持中国立场（以中国国家利益与中国受众视角分析），同时保持客观理性。\n"
        "先查阅并基于已给事实/原文摘录再给判断，不得推测，不煽动对立、不使用攻击性语言、不做情绪化带节奏表述。\n"
        "可提示风险与影响，但不得夸大、不得杜撰未提供事实。\n"
        "topics（数组，3-8个话题词）：必须包含“每日新闻”。不要把 topics 写进 body。\n"
        "image_event（字符串，可选，20-40字）：仅用于配图的事件描述，只描述发生了什么（主体/动作/对象/场景线索），不含评价；"
        "不要出现“新闻/报道/采访/记者/媒体/来源/链接/时间”等词。不要把 image_event 写进 body。\n"
    )


def _daily_news_fallback_subject(picked, prompt_norm: str) -> str:
    title = _strip_urls((picked.title or "").strip())
    desc = _strip_urls((picked.description or "").strip())
    if _has_cjk(title):
        return _normalize_news_summary(title, limit=48)
    if _has_cjk(desc):
        return _normalize_news_summary(desc, limit=48)

    lower = " ".join(
        [
            picked.title or "",
            picked.description or "",
            picked.content or "",
            prompt_norm or "",
        ]
    ).lower()
    hint = prompt_norm if _has_cjk(prompt_norm) else ""
    if "科技" in hint or any(w in lower for w in ("ai", "chip", "tech", "technology", "model", "software")):
        return "一项科技议题出现新进展"
    if "社会" in hint or any(w in lower for w in ("court", "case", "school", "police", "sentence")):
        return "一项社会议题出现新进展"
    if "经济" in hint or any(w in lower for w in ("market", "inflation", "price", "trade", "economy")):
        return "一项经济议题出现新进展"
    return "一项国际议题出现新进展"


def _daily_news_offline_body(picked, prompt_norm: str) -> str:
    """
    Offline fallback body: keep it publishable and avoid echoing prompt/requirements.
    """
    pub = _format_news_seendate(picked.seendate)
    subject = _daily_news_fallback_subject(picked, prompt_norm)
    source_for_copy = (picked.source or picked.domain or "").strip()
    if not _has_cjk(source_for_copy):
        source_for_copy = "原始来源"
    summary = (
        f"{source_for_copy}披露{subject}，现有信息仍有限，后续需关注权威更新与实际影响。"
    )
    if len(summary) > 70:
        summary = f"{subject}，现有信息仍有限，后续需关注权威更新与实际影响。"
    content = (
        f"根据{source_for_copy}提供的公开信息，{subject}。目前能够确认的内容主要来自原始新闻的标题、摘要和正文片段，"
        "因此这里不扩大事实范围，也不加入未经证实的数字、人物关系或因果判断。"
        "这条动态的后续价值，在于观察官方或权威机构是否披露更多细节，包括执行时间、影响对象和可能的市场或社会反应。"
        "在信息仍有限的情况下，读者可以先把它视为一个需要继续跟踪的进展，而不是已经定论的结果。"
    )
    comment = (
        "从中国受众视角看，越是跨地区、跨产业的新闻，越需要区分已确认事实和外界推测。"
        "接下来更值得关注的是正式文件、权威回应和实际执行效果。你认为这件事最可能影响哪一方？"
    )
    return (
        f"{_NEWS_SUMMARY_LABEL}{summary}\n"
        f"{_NEWS_CONTENT_LABEL}\n"
        f"{content}\n\n"
        f"{_NEWS_COMMENT_LABEL}\n"
        f"{comment}"
        f"\n\n发布时间：{pub}"
    )


def _ensure_daily_news_sections(body: str, prompt_norm: str) -> str:
    text = (body or "").strip()
    if not text:
        return text
    if (
        text.startswith(_NEWS_SUMMARY_LABEL)
        and _NEWS_CONTENT_LABEL in text
        and _NEWS_COMMENT_LABEL in text
        and not _looks_like_jsonish_body(text)
    ):
        return text

    cleaned = (
        text.replace(_NEWS_SUMMARY_LABEL, "")
        .replace(_NEWS_CONTENT_LABEL, "")
        .replace(_NEWS_COMMENT_LABEL, "")
        .strip()
    )
    if _looks_like_jsonish_body(cleaned):
        cleaned = _strip_json_artifacts(cleaned)
    paragraphs = [p.strip() for p in cleaned.splitlines() if p.strip()]
    summary = ""
    if len(paragraphs) >= 3:
        summary = paragraphs[0]
        news = paragraphs[1]
        comment = " ".join(paragraphs[2:])
    elif len(paragraphs) >= 2:
        news = paragraphs[0]
        comment = " ".join(paragraphs[1:])
    else:
        news = paragraphs[0] if paragraphs else cleaned
        comment = "从中国视角和读者关注点来看，这条新闻提示我们需要持续关注后续进展与影响。你怎么看？"

    summary = _normalize_news_summary(summary, fallback=news, limit=40)

    return (
        f"{_NEWS_SUMMARY_LABEL}{summary}\n"
        f"{_NEWS_CONTENT_LABEL}\n{news}\n\n{_NEWS_COMMENT_LABEL}\n{comment}"
    )


def _news_source_line(picked) -> str:
    source = (picked.source or picked.domain or "未知来源").strip()
    return f"来源：{source}"


def _append_news_source_line(body: str, picked) -> str:
    text = _strip_urls(body or "").rstrip()
    if not text:
        return text
    line = _news_source_line(picked)
    if re.search(r"(?:\r?\n)*来源：.*\Z", text):
        text = re.sub(r"(?:\r?\n)*来源：.*\Z", "", text).rstrip()
    return f"{text}\n\n{line}".rstrip()


def _clamp_daily_news_body(body: str) -> str:
    text = (body or "").strip()
    if len(text) <= MAX_IMAGE_BODY:
        return text

    source_match = re.search(r"\n\n来源：[^\n]+\s*$", text)
    source_tail = source_match.group(0).strip() if source_match else ""
    without_source = text[: source_match.start()].rstrip() if source_match else text
    time_match = re.search(r"\n\n发布时间：[^\n]+\s*$", without_source)
    time_tail = time_match.group(0).strip() if time_match else ""
    main = without_source[: time_match.start()].rstrip() if time_match else without_source

    tail_parts = [part for part in (time_tail, source_tail) if part]
    tail = ("\n\n" + "\n\n".join(tail_parts)) if tail_parts else ""
    room = max(0, MAX_IMAGE_BODY - len(tail))
    return f"{main[:room].rstrip()}{tail}".strip()


def _finalize_daily_news_body(body: str, picked, prompt_norm: str) -> str:
    text = _strip_urls(body or "")
    text = _ensure_daily_news_sections(text, prompt_norm)
    text = _ensure_news_publish_date(text, picked.seendate)
    text = _append_news_source_line(text, picked)
    return _clamp_daily_news_body(text)


def _fake_news_prompt(prompt_norm: str) -> str:
    """
    Prompt for humorous, clearly fictional fake news.
    """
    topic = prompt_norm or "日常离谱小事"
    return (
        "你正在为小红书图文笔记写《每日假新闻》栏目。\n"
        "请根据给定主题编写一条**明显虚构、幽默夸张**的新闻，语气轻松有趣。\n"
        "必须让读者一眼看出是娱乐内容，避免与现实新闻混淆。\n"
        "不要引用真实媒体/来源/链接，不要提供可核验的具体事实或真实数据。\n"
        "避免对真实人物/机构做恶意指控或诽谤，内容保持善意搞笑。\n"
        "正文只输出可直接发布的文章，不要复述提示词或规则。\n\n"
        f"主题提示（可自由发挥但要贴合）：{topic}\n\n"
        "正文要求：\n"
        "1) 只输出一段完整正文，不要列点或小标题；\n"
        "2) 字数约 200-400 字；\n"
        "3) 末尾必须加一句：本文纯属虚构，仅供娱乐。\n"
        "4) topics 输出 3-8 个话题词，包含“每日假新闻”。\n"
    )


def _fake_news_offline_body(prompt_norm: str) -> str:
    topic = prompt_norm or "离谱日常"
    return (
        f"【假新闻播报】今日最离谱的主角是「{topic}」。\n"
        "据不可靠但十分认真（的想象）消息称，相关事件在短短几小时内引发了全民围观，"
        "围观群众纷纷表示：这是我今天最开心的笑点。更夸张的是，现场还出现了神秘“反转”，"
        "让事情从“不可思议”直接升级为“笑到肚子疼”。\n\n"
        "专家（其实是路过的瓜友）点评：这类剧情虽然离谱，但快乐是真的。"
        "如果明天还能看到同款离谱升级，请记得第一时间来围观。\n"
        "本文纯属虚构，仅供娱乐。"
    )


def create_post_with_draft(
    *,
    title_hint: str,
    prompt_hint: str,
    asset_paths: list[str],
    copy_assets: bool = True,
    auto_image: bool = True,
    image_exclude_ids: Optional[set[str]] = None,
) -> Post:
    """
    Generate a draft with LLM and persist post + revision.
    """
    cfgs = load_llm_configs()
    title_norm = (title_hint or "").strip()
    platform_meta: dict = {}

    if title_norm == "每日新闻":
        try:
            picked, news_meta = fetch_and_pick_daily_news(prompt_hint or "")
            picked, lookup_meta = _enrich_daily_news_item(picked)
            platform_meta["news"] = {
                **news_meta,
                **lookup_meta,
                "picked": asdict(picked),
                "source_url": picked.url,
                "mode": "daily_news",
                "prompt_hint": (prompt_hint or "").strip(),
            }
            prompt_norm = (prompt_hint or "").strip()
            news_prompt = _daily_news_prompt(picked, prompt_norm)
            seed_title = "每日新闻"
            draft = generate_draft(
                cfgs,
                title_hint=seed_title,
                prompt_hint=news_prompt,
                asset_paths=asset_paths,
            )
            embedded = _extract_embedded_json_from_daily_news_body(draft.get("body", ""))
            if embedded:
                embedded_title = embedded.get("title")
                embedded_body = embedded.get("body")
                embedded_topics = embedded.get("topics")
                embedded_event = embedded.get("image_event")
                if isinstance(embedded_title, str) and embedded_title.strip():
                    draft["title"] = embedded_title.strip()
                if isinstance(embedded_body, str) and embedded_body.strip():
                    draft["body"] = embedded_body.strip()
                if isinstance(embedded_topics, list) and embedded_topics:
                    draft["topics"] = embedded_topics
                if isinstance(embedded_event, str) and embedded_event.strip():
                    draft["image_event"] = embedded_event.strip()
            draft["body"] = _ensure_daily_news_sections(
                draft.get("body", ""), prompt_norm
            )
            draft["body"] = _ensure_news_publish_date(
                draft["body"], picked.seendate
            )
            if draft.get("_fallback_error") or _daily_news_body_has_prompt_leak(draft.get("body", "")):
                draft["title"] = _normalize_daily_news_title(picked.title, picked, prompt_norm)
                draft["body"] = _daily_news_offline_body(picked, prompt_norm)
                draft["topics"] = ["每日新闻"]
            if _is_generic_daily_news_title(draft.get("title", "")):
                title_src = picked.title or picked.description or prompt_norm
                draft["title"] = _normalize_daily_news_title(title_src, picked, prompt_norm)
            draft["title"] = _normalize_daily_news_title(draft.get("title", ""), picked, prompt_norm)
            topics = draft.get("topics") or []
            if not isinstance(topics, list):
                topics = [str(topics)]
            draft["topics"] = _normalize_daily_news_topics(topics, prompt_norm)
            draft["body"] = _finalize_daily_news_body(draft.get("body", ""), picked, prompt_norm)
            image_event = _normalize_image_event(
                str(draft.get("image_event") or ""),
                fallback=picked.title,
            )
            platform_meta["news"]["image_event"] = image_event
            draft["image_event"] = image_event
        except Exception as exc:
            platform_meta["news"] = {
                "mode": "daily_news",
                "prompt_hint": (prompt_hint or "").strip(),
                "error": str(exc),
            }
            raise RuntimeError(f"daily news fetch failed: {exc}") from exc
    elif title_norm == "每日假新闻":
        prompt_norm = (prompt_hint or "").strip()
        fake_prompt = _fake_news_prompt(prompt_norm)
        draft = generate_draft(
            cfgs,
            title_hint="每日假新闻",
            prompt_hint=fake_prompt,
            asset_paths=asset_paths,
        )
        if draft.get("_fallback_error"):
            draft["title"] = "每日假新闻"
            draft["body"] = _fake_news_offline_body(prompt_norm)
        body_text = (draft.get("body") or "").strip()
        if "本文纯属虚构" not in body_text:
            joiner = "\n" if body_text else ""
            draft["body"] = f"{body_text}{joiner}本文纯属虚构，仅供娱乐。"
        topics = draft.get("topics", [])
        if "每日假新闻" not in topics:
            topics = ["每日假新闻"] + [t for t in topics if t and t != "每日假新闻"]
        draft["topics"] = topics
        platform_meta["fake_news"] = {
            "mode": "daily_fake_news",
            "prompt_hint": prompt_norm,
            "is_fiction": True,
            "tone": "humor",
        }
    else:
        draft = generate_draft(
            cfgs,
            title_hint=title_hint,
            prompt_hint=prompt_hint,
            asset_paths=asset_paths,
        )

    post = Post(
        type="image",
        status=PostStatus.draft,
        title=draft["title"],
        body=draft["body"],
        topics=draft.get("topics", []),
    )
    if platform_meta:
        post.platform = platform_meta

    auto_image_enabled = auto_image and is_auto_image_enabled()
    assets_paths = [Path(p) for p in asset_paths]
    effective_copy_assets = copy_assets

    if not assets_paths and auto_image_enabled:
        dest_dir = post_dir(post.id) / "assets"
        image_title = _preferred_image_title(post, post.title)
        image_paths, image_metas = fetch_and_download_related_images(
            title=image_title,
            body=post.body,
            topics=post.topics,
            prompt_hint=_preferred_image_hint(post, prompt_hint),
            dest_dir=dest_dir,
            exclude_ids=image_exclude_ids,
        )
        post.platform.setdefault("image", image_metas[0])
        post.platform["images"] = image_metas
        _merge_image_ids(image_exclude_ids, image_metas)
        assets_paths = image_paths
        # The downloaded file is already under data/posts/<id>/assets.
        effective_copy_assets = False

    if effective_copy_assets:
        copied = copy_assets_into_post(post.id, assets_paths)
        asset_infos = _build_asset_infos(copied)
    else:
        asset_infos = _build_asset_infos(assets_paths)
    post.assets = asset_infos

    rev = Revision(
        post_id=post.id,
        source=RevisionSource.llm,
        content=draft,
    )

    save_post(post)
    save_revision(rev)

    return post


def create_daily_news_posts(
    *,
    prompt_hint: str = "",
    asset_paths: list[str],
    copy_assets: bool = True,
    count: int = 1,
    auto_image: bool = True,
) -> list[Post]:
    """
    Special workflow for title="每日新闻".

    - Use `prompt_hint` to rank candidates, then pick up to `count` items.
    - When `count` is 1, behavior is equivalent to a single best match.
    """
    cfgs = load_llm_configs()
    prompt_norm = (prompt_hint or "").strip()
    if count <= 0:
        count = 1
    auto_image_enabled = auto_image and is_auto_image_enabled()
    used_image_ids: set[str] = set()
    used_title_keys: set[str] = set()
    failed_count = 0

    def _is_fatal_image_config_error(errs: list[str]) -> bool:
        # Aliyun returns this when using image-to-image models without providing an init image.
        joined = " ".join(errs or []).lower()
        return (
            "got 0 images" in joined
            or "must contain 1 to 4 images" in joined
            or "enable_interleave" in joined
        )

    candidates, base_meta = fetch_daily_news_candidates(prompt_norm)
    # Pick more than requested so we can skip items whose image generation fails.
    pick_limit = min(len(candidates), max(count * 5, count + 10))
    picks = pick_news_items(candidates, prompt_norm, count=pick_limit)

    target_count = count
    posts: list[Post] = []

    success_idx = 0
    for candidate_idx, picked in enumerate(picks, start=1):
        if len(posts) >= target_count:
            break
        picked, lookup_meta = _enrich_daily_news_item(picked)
        news_prompt = _daily_news_prompt(picked, prompt_norm)
        if target_count > 1:
            news_prompt = f"（第 {success_idx + 1}/{target_count} 条）\n{news_prompt}"

        seed_title = "每日新闻"
        draft = generate_draft(
            cfgs,
            title_hint=seed_title,
            prompt_hint=news_prompt,
            asset_paths=asset_paths,
        )
        embedded = _extract_embedded_json_from_daily_news_body(draft.get("body", ""))
        if embedded:
            embedded_title = embedded.get("title")
            embedded_body = embedded.get("body")
            embedded_topics = embedded.get("topics")
            embedded_event = embedded.get("image_event")
            if isinstance(embedded_title, str) and embedded_title.strip():
                draft["title"] = embedded_title.strip()
            if isinstance(embedded_body, str) and embedded_body.strip():
                draft["body"] = embedded_body.strip()
            if isinstance(embedded_topics, list) and embedded_topics:
                draft["topics"] = embedded_topics
            if isinstance(embedded_event, str) and embedded_event.strip():
                draft["image_event"] = embedded_event.strip()
        draft["body"] = _ensure_daily_news_sections(draft.get("body", ""), prompt_norm)
        draft["body"] = _ensure_news_publish_date(
            draft["body"], picked.seendate
        )
        if draft.get("_fallback_error") or _daily_news_body_has_prompt_leak(draft.get("body", "")):
            draft["title"] = _normalize_daily_news_title(picked.title, picked, prompt_norm)
            draft["body"] = _daily_news_offline_body(picked, prompt_norm)
            draft["topics"] = ["每日新闻"]
        if _is_generic_daily_news_title(draft.get("title", "")):
            title_src = picked.title or picked.description or prompt_norm
            draft["title"] = _normalize_daily_news_title(title_src, picked, prompt_norm)
        draft["title"] = _normalize_daily_news_title(draft.get("title", ""), picked, prompt_norm)
        title_key = _daily_news_title_key(draft.get("title", ""))
        if title_key:
            if title_key in used_title_keys:
                continue
            used_title_keys.add(title_key)
        topics = draft.get("topics") or []
        if not isinstance(topics, list):
            topics = [str(topics)]
        draft["topics"] = _normalize_daily_news_topics(topics, prompt_norm)
        draft["body"] = _finalize_daily_news_body(draft.get("body", ""), picked, prompt_norm)
        image_event = _normalize_image_event(
            str(draft.get("image_event") or ""),
            fallback=picked.title,
        )
        draft["image_event"] = image_event

        post = Post(
            type="image",
            status=PostStatus.draft,
            title=draft["title"],
            body=draft["body"],
            topics=draft.get("topics", []),
            platform={
                "news": {
                    **base_meta,
                    **lookup_meta,
                    "picked": asdict(picked),
                    "source_url": picked.url,
                    "mode": "daily_news_multi" if target_count > 1 else "daily_news",
                    "prompt_hint": prompt_norm,
                    "pick_index": success_idx + 1,
                    "pick_total": target_count,
                    "candidate_index": candidate_idx,
                    "image_event": image_event,
                }
            },
        )

        assets_paths = [Path(p) for p in asset_paths]
        effective_copy_assets = copy_assets

        if not assets_paths and auto_image_enabled:
            dest_dir = post_dir(post.id) / "assets"
            image_title = _preferred_image_title(post, post.title)
            image_prompt = _preferred_image_hint(post, prompt_norm)
            try:
                image_paths, image_metas = fetch_and_download_related_images(
                    title=image_title,
                    body=post.body,
                    topics=post.topics,
                    prompt_hint=image_prompt,
                    dest_dir=dest_dir,
                    exclude_ids=used_image_ids,
                )
            except ImageGenerationAbandoned as exc:
                post.status = PostStatus.failed
                post.platform["image_generate"] = {
                    "give_up": True,
                    "provider": exc.provider,
                    "attempts": exc.attempts,
                    "errors": exc.errors,
                }
                rev = Revision(post_id=post.id, source=RevisionSource.llm, content=draft)
                save_post(post)
                save_revision(rev)
                failed_count += 1
                err_tail = (exc.errors or [""])[-1].strip()
                if err_tail:
                    print(f"[auto-image] give_up post_id={post.id} provider={exc.provider} err={err_tail}")
                else:
                    print(f"[auto-image] give_up post_id={post.id} provider={exc.provider}")
                if _is_fatal_image_config_error(exc.errors):
                    print(
                        "[auto-image] Detected a likely model/config mismatch: the selected model requires an input image. "
                        "If you are generating images from text only, set ALIYUN_IMAGE_MODELS to a text-to-image model "
                        '(e.g. "wan2.7-image" or "wan2.7-image-pro").'
                    )
                    break
                continue
            post.platform.setdefault("image", image_metas[0])
            post.platform["images"] = image_metas
            _merge_image_ids(used_image_ids, image_metas)
            assets_paths = image_paths
            effective_copy_assets = False

        if effective_copy_assets:
            copied = copy_assets_into_post(post.id, assets_paths)
            post.assets = _build_asset_infos(copied)
        else:
            post.assets = _build_asset_infos(assets_paths)

        rev = Revision(post_id=post.id, source=RevisionSource.llm, content=draft)
        save_post(post)
        save_revision(rev)
        posts.append(post)
        success_idx += 1

    if not posts and failed_count:
        print(
            f"[daily_news] no successful posts (failed={failed_count}). "
            "Check data/posts/*/post.json -> platform.image_generate.errors."
        )
    return posts
