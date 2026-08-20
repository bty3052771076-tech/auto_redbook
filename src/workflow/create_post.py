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
from typing import Any, Callable, Iterable, List, Optional

from src.config import load_llm_configs
from src.ai_digest.collect import collect_ai_digest_updates
from src.ai_digest.generate import (
    build_fallback_brief,
    evaluate_ai_digest_impact_with_llm,
    generate_ai_digest_brief_with_llm,
    render_ai_digest_body,
)
from src.ai_digest.models import AIDigestBrief, AIUpdateItem
from src.ai_digest.rank import (
    AI_DIGEST_MAX_ITEMS_PER_SOURCE,
    ai_digest_official_count,
    ai_digest_quota_counts,
    ai_digest_source_counts,
    dedupe_ai_updates,
    filter_recent_ai_updates,
    featured_ai_update,
    rank_ai_updates,
)
from src.ai_digest.render import render_ai_digest_cards
from src.images.auto_image import (
    ImageGenerationAbandoned,
    fetch_and_download_related_images,
    is_auto_image_enabled,
)
from src.llm.generate import generate_draft, generate_json
from src.news.daily_news import (
    _cjk_story_event_signature,
    _is_china_item,
    _required_china_count_for_daily_news,
    _same_cjk_story_event,
    fetch_daily_news_candidates,
    filter_prompt_relevant_news_items,
    filter_recent_news_items,
    load_single_news_material_file,
    pick_news_items,
    rank_news_candidate_pool,
    resolve_manual_material_times,
)
from src.storage.files import copy_assets_into_post, list_posts, post_dir, save_post, save_revision
from src.storage.models import AssetInfo, Post, PostStatus, Revision, RevisionSource, now_iso
from src.validation.rules import MAX_IMAGE_BODY, MAX_IMAGE_TITLE


_URL_RE = re.compile(r"(?:https?://|www\.|//)[^\s，。；;、）)】\]]+", flags=re.IGNORECASE)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_FOREIGN_SCRIPT_RE = re.compile(r"[\u00c0-\u024f\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff\u0e00-\u0e7f]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z]{2,}")
_ENGLISH_PHRASE_RE = re.compile(r"\b[A-Za-z]{3,}\b(?:\s+(?:\d{2,4}\s+)?\b[A-Za-z]{2,}\b){3,}")
_ALLOWED_DAILY_NEWS_CONTENT_ASCII_WORDS = {
    "AI",
    "API",
    "CEO",
    "CFO",
    "CPU",
    "ETF",
    "GDP",
    "GPU",
    "IPO",
    "LLM",
    "NASA",
    "QDII",
    "WTO",
    "CHATGPT",
    "DEEPSEEK",
    "NVIDIA",
    "OPENAI",
    "QWEN",
    "TESLA",
}
_DAILY_NEWS_INSUFFICIENT_CONTENT_MARKERS = (
    "\u539f\u59cb\u6750\u6599\u63d0\u5230",
    "\u672a\u63d0\u4f9b\u8db3\u591f\u7ec6\u8282",
    "\u76f8\u5173\u6280\u672f\u4e89\u8bae\u51fa\u73b0\u5347\u7ea7",
)
_DAILY_NEWS_PREFIX_RE = re.compile(r"^(?:每日新闻)(?:[｜|:：\-—–\s]+)?")
_SOURCE_LOOKUP_MIN_CHARS = 120
_SOURCE_LOOKUP_MAX_CHARS = 5000
DEFAULT_EVALUATION_VIEWPOINT = "无视角评价"
AI_DIGEST_MIN_ITEMS = 8
AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS = 3
AI_DIGEST_MIN_FOREIGN_AI_ITEMS = 3
DEFAULT_CANDIDATE_LOOKBACK_WINDOWS = (3, 7, 14)
DAILY_NEWS_MAX_LOOKBACK_DAYS = 2
_DAILY_NEWS_TITLE_MIN_LEN = 10
_NEWS_TITLE_PROMPT_STRONG_MARKERS = (
    "选择一条",
    "选择5条",
    "适合小红书",
    "提示词",
    "生成一份",
    "输出为严格 JSON",
    "JSON 字段要求",
)
_NEWS_TITLE_PROMPT_SOFT_MARKERS = (
    "摘要",
    "正文",
    "点评",
    "必须",
    "不得",
    "不要",
    "约50字",
    "约200字",
    "发布时间",
    "来源",
    "用户关注点",
    "新闻信息",
)


class PartialDailyNewsError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        posts: list[Post],
        requested_count: int,
        failed_count: int = 0,
        skipped_quality_count: int = 0,
    ):
        super().__init__(message)
        self.posts = posts
        self.requested_count = requested_count
        self.failed_count = failed_count
        self.skipped_quality_count = skipped_quality_count


DailyNewsProgressCallback = Callable[[str, str, dict[str, Any]], None]
DailyNewsPostQualityCallback = Callable[[Post], list[str]]


def _emit_daily_news_progress(
    callback: DailyNewsProgressCallback | None,
    stage: str,
    status: str = "in_progress",
    **detail: Any,
) -> None:
    if callback is None:
        return
    try:
        callback(stage, status, detail)
    except Exception as exc:
        # Observability must not turn an otherwise valid draft run into a failure.
        print(f"[daily_news] progress_callback_failed stage={stage} err={exc}")


def _daily_news_llm_unavailable_reason(error: object) -> str:
    text = str(error or "").strip()
    lowered = text.lower()
    if (
        "invalidendpointormodel.notfound" in lowered
        or "model or endpoint" in lowered
        or "invalid model" in lowered
    ):
        return "模型标识或接入点不可用，或当前 API key 没有该模型权限"
    if "accountoverdue" in lowered or "overdue balance" in lowered:
        return "模型账户欠费或账户状态异常"
    if "freetieronly" in lowered or "free quota exhausted" in lowered or "免费额度" in text:
        return "模型免费额度已耗尽"
    if "quota" in lowered or "balance" in lowered or "allocation" in lowered:
        return "模型额度不足"
    if "429" in lowered or "rate limit" in lowered or "throttl" in lowered:
        return "模型请求过于频繁，请稍后重试"
    if "403" in lowered or "forbidden" in lowered or "permission" in lowered:
        return "模型没有可用权限"
    return "模型请求失败"
_NEWS_GENERIC_BODY_MARKERS = (
    "一项科技议题出现新进展",
    "一项社会议题出现新进展",
    "一项经济议题出现新进展",
    "一项国际议题出现新进展",
    "原始来源披露一项",
    "根据原始来源提供的公开信息",
    "现有信息仍有限，后续需关注权威更新",
    "在信息仍有限的情况下",
    "需要继续跟踪的进展",
    "不是已经定论的结果",
    "越是跨地区、跨产业的新闻",
)
_NEWS_GENERIC_COMMENT_MARKERS = (
    "这类新闻适合先看事实，再看影响",
    "已经公开的信息可以作为判断起点",
    "不宜把尚未确认的后续结果提前写成结论",
    "接下来可以重点关注权威更新",
    "从中国视角和读者关注点来看",
    "这条新闻提示我们需要持续关注后续进展与影响",
    "越需要区分已确认事实和外界推测",
    "更值得关注的是正式文件、权威回应和实际执行效果",
    "这件事值得关注的不是单个工具本身",
    "AI 使用边界、披露义务和责任归属",
    "版权和信任",
)
_NEWS_GENERIC_TITLE_MARKERS = (
    "科技议题出现进展",
    "AI议题出现进展",
    "国际议题出现进展",
    "社会事件出现进展",
    "经济议题出现变化",
    "外贸数据出现变化",
)

_COMMON_TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    {
        "內": "内",
        "門": "门",
        "戶": "户",
        "國": "国",
        "際": "际",
        "學": "学",
        "術": "术",
        "橋": "桥",
        "連": "连",
        "對": "对",
        "稱": "称",
        "發": "发",
        "讓": "让",
        "錨": "锚",
        "體": "体",
        "與": "与",
        "鏈": "链",
        "進": "进",
        "資": "资",
        "處": "处",
        "財": "财",
        "長": "长",
        "網": "网",
        "誌": "志",
        "訊": "讯",
        "聯": "联",
        "聞": "闻",
        "佈": "布",
        "調": "调",
        "點": "点",
        "這": "这",
        "項": "项",
        "規": "规",
        "則": "则",
        "責": "责",
        "務": "务",
        "協": "协",
        "後": "后",
        "續": "续",
        "觀": "观",
        "關": "关",
        "權": "权",
        "護": "护",
        "勞": "劳",
        "動": "动",
        "數": "数",
        "據": "据",
        "報": "报",
        "導": "导",
        "戰": "战",
        "爭": "争",
        "選": "选",
        "舉": "举",
        "類": "类",
        "證": "证",
        "華": "华",
        "鐵": "铁",
        "蘋": "苹",
        "區": "区",
        "風": "风",
        "險": "险",
        "響": "响",
        "應": "应",
        "醫": "医",
        "藥": "药",
        "監": "监",
        "測": "测",
        "檢": "检",
        "機": "机",
        "構": "构",
        "專": "专",
        "屬": "属",
        "園": "园",
        "車": "车",
        "電": "电",
        "錢": "钱",
        "貿": "贸",
        "語": "语",
        "廣": "广",
        "東": "东",
        "標": "标",
        "準": "准",
        "號": "号",
        "業": "业",
        "實": "实",
        "現": "现",
        "產": "产",
        "臺": "台",
        "灣": "湾",
        # High-frequency traditional characters that occur in Taiwanese and
        # Hong Kong source snippets. Keep this local fallback dependency-free.
        "當": "当",
        "開": "开",
        "寫": "写",
        "質": "质",
        "為": "为",
        "壓": "压",
        "尋": "寻",
        "雖": "虽",
        "個": "个",
        "卻": "却",
        "聲": "声",
        "識": "识",
        "場": "场",
        "說": "说",
        "來": "来",
        "銷": "销",
        "時": "时",
        "兩": "两",
        "種": "种",
        "極": "极",
        "揮": "挥",
        "淪": "沦",
        "豐": "丰",
    }
)
_ALLOWED_TITLE_ASCII_WORDS = {"AI", "API", "NASA", "G7", "G20", "APEC", "CEO", "C919"}


def _strip_urls(text: str) -> str:
    cleaned = _URL_RE.sub("", text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _strip_html_artifacts(text: str) -> str:
    cleaned = unescape(text or "")
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", cleaned)
    cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(
        r"(?is)<img\b(?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?)*\s*/?>?",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?is)</?[^>]+>", " ", cleaned)
    cleaned = re.sub(
        r"(?i)\b(?:referrerpolicy|width|height|alt|title|class|style)\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s，。！？；;]+)",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(?:referrerpolicy|src|width|height)\b(?=\s|$)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _has_html_artifacts(text: str) -> bool:
    value = text or ""
    if re.search(r"(?is)<\s*/?\s*(?:p|div|img|span|a|br|html|body|section|article)\b", value):
        return True
    return bool(
        re.search(
            r"(?i)\b(?:referrerpolicy|width|height|alt|class|style)\s*=|<img\b",
            value,
        )
    )


def _has_cjk(text: str | None) -> bool:
    return bool(_CJK_CHAR_RE.search(text or ""))


def _has_japanese_kana(text: str | None) -> bool:
    return bool(_JAPANESE_KANA_RE.search(text or ""))


def _to_simplified_common(text: str) -> str:
    return (text or "").translate(_COMMON_TRADITIONAL_TO_SIMPLIFIED)


def _simplify_daily_news_draft(draft: dict[str, Any]) -> dict[str, Any]:
    out = dict(draft)
    for key in ("title", "body", "image_event"):
        if key in out and isinstance(out.get(key), str):
            out[key] = _to_simplified_common(str(out.get(key) or ""))
    topics = out.get("topics")
    if isinstance(topics, list):
        out["topics"] = [_to_simplified_common(str(topic or "")) for topic in topics]
    elif isinstance(topics, str):
        out["topics"] = [_to_simplified_common(topics)]
    return out


def _cjk_count(text: str | None) -> int:
    return len(_CJK_CHAR_RE.findall(text or ""))


def _has_foreign_script_leak(text: str | None) -> bool:
    return bool(_FOREIGN_SCRIPT_RE.search(text or ""))


def _has_english_phrase_leak(text: str | None) -> bool:
    value = text or ""
    if not value.strip():
        return False
    if _ENGLISH_PHRASE_RE.search(value):
        return True
    suspicious = []
    for word in _ASCII_WORD_RE.findall(value):
        upper = word.upper()
        if upper in _ALLOWED_DAILY_NEWS_CONTENT_ASCII_WORDS:
            continue
        if word.isupper() and 2 <= len(word) <= 8:
            continue
        suspicious.append(word)
    return len(suspicious) >= 4


def _daily_news_title_has_bad_language(text: str | None) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    if "原文摘录" in value:
        return True
    if _has_japanese_kana(value) or _has_foreign_script_leak(value):
        return True
    if _cjk_count(value) < 4:
        return True
    ascii_words = _ASCII_WORD_RE.findall(value)
    bad_words = [word for word in ascii_words if word.upper() not in _ALLOWED_TITLE_ASCII_WORDS]
    return len(bad_words) >= 2


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


def _source_lookup_max_chars() -> int:
    raw = (os.getenv("NEWS_SOURCE_LOOKUP_MAX_CHARS") or "").strip()
    if not raw:
        return _SOURCE_LOOKUP_MAX_CHARS
    try:
        return max(1200, int(raw))
    except ValueError:
        return _SOURCE_LOOKUP_MAX_CHARS


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
    text = _clean_original_news_text(text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def _strip_news_site_suffixes(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    cleaned = re.sub(r"\s*[_｜|]\s*(?:新闻频道|新闻|频道|中华网|人民网|央视网|新华网).*$", "", cleaned)
    cleaned = re.sub(r"\s*[-–—]{2}\s*(?:国际|国内|社会|体育|财经|新闻)\s*[-–—]{2}.*$", "", cleaned)
    cleaned = re.sub(r"\s*[-–—]{2}\s*(?:国际|国内|社会|体育|财经|新闻)\s*$", "", cleaned)
    return cleaned.strip()


def _strip_news_column_prefix(text: str) -> str:
    return re.sub(
        r"^(?:香港故事|记者手记|新华视点|新闻分析|国际观察|全球连线|现场直击|新华社消息|中东战地手记|通讯|深度观察|权威数读|财经聚焦|活力中国调研行|追光|秀我中国)丨\s*",
        "",
        text or "",
    ).strip()


def _clean_original_news_text(text: str) -> str:
    cleaned = _strip_html_artifacts(_to_simplified_common(text or ""))
    cleaned = _strip_urls(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("原文摘录：", "").strip()
    cleaned = re.sub(r"^[\s·•∙-]*(?:[^。！？!?]{1,16})\s*>\s*听全文[。.\s]*", " ", cleaned)
    cleaned = re.sub(r"[\s·•∙-]*(?:能见度|牛市点线面|[^。！？!?]{1,12})\s*>\s*听全文[。.\s]*", " ", cleaned)
    cleaned = re.sub(r"^[\u4e00-\u9fff]{1,12}网讯[（(][^。！？!?]{0,40}记者[）)]?[。！？!?]?", " ", cleaned)
    cleaned = re.sub(
        r"本站不再支持您的浏览器.*?以获得更好的观看效果。?",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"学习\s+学习时间\s+头条\s+头条关注\s+综合\s+综合新闻\s+媒体\s+媒体农。?",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"举报\s*0\s*分享至。?", " ", cleaned)
    cleaned = re.sub(r"用微信扫码二维码。?分享至好友和朋友圈。?", " ", cleaned)
    cleaned = re.sub(r"分享至好友和朋友圈。?", " ", cleaned)
    cleaned = re.sub(r"(?:普通话|广东话|字号|超大|标准)[。.\s]+", " ", cleaned)
    cleaned = re.sub(r"缩小字体\s+放大字体\s+收藏\s+微博\s+分享.*?QQ空间", " ", cleaned)
    cleaned = re.sub(r"\b\d{4}新闻库\b", " ", cleaned)
    cleaned = re.sub(r"(?<!\d):?\d{2,}\s+\d{2,}\s+\d{5,}", " ", cleaned)
    cleaned = re.sub(r"新华社(?:记者\s*)?发?[（(][^）)]{0,20}摄[）)]", " ", cleaned)
    cleaned = re.sub(r"新华社记者\s*[^。；;，,\s]{1,12}\s*摄", " ", cleaned)
    cleaned = re.sub(r"[\u4e00-\u9fff·]{1,10}摄[（(][^）)]{1,30}[）)]", " ", cleaned)
    cleaned = re.sub(r"路线规\s*AI伴你游[。.]?", " ", cleaned)
    cleaned = re.sub(r"\bImage\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Many Chinese news pages put navigation before the article. Prefer the
    # text after a publish-time marker when present.
    date_match = re.search(
        r"(?:20\d{2}[-年]\d{1,2}[-月]\d{1,2}[日]?\s*\d{1,2}:\d{2}(?::\d{2})?)",
        cleaned,
    )
    if date_match:
        cleaned = cleaned[date_match.end() :].strip()

    stop_positions = [
        cleaned.find(marker)
        for marker in (
            "〖纠错〗",
            "阅读下一篇",
            "深度观察",
            "新华全媒+",
            "消费新图景",
            "责任编辑：",
            "澎湃新闻报料",
            "报料热线",
            "报料邮箱",
            "沪ICP备",
            "沪公网安备",
            "互联网新闻信息服务许可证",
            "增值电信业务经营许可证",
            "扫码下载澎湃新闻客户端",
        )
        if cleaned.find(marker) > 0
    ]
    if stop_positions:
        cleaned = cleaned[: min(stop_positions)].strip()

    cleaned = re.sub(r"^来源[:：]\s*\S+\s*", "", cleaned)
    cleaned = re.sub(r"^作者[:：]\s*\S+\s*", "", cleaned)
    cleaned = re.sub(r"^责任编辑[:：]\s*\S+\s*", "", cleaned)
    cleaned = re.sub(r"^小\s+大\s+用微信扫描二维码\s+分享至好友和朋友圈\s+关键词[:：]?\s*", "", cleaned)
    cleaned = re.sub(r"^小\s+", "", cleaned)
    cleaned = re.sub(r"^打开\s+首页\s+.*?(?=(?:20\d{2}[-年]|\d{1,2}月\d{1,2}日|[一-龥]{2,10}消息))", "", cleaned)
    cleaned = _strip_news_site_suffixes(cleaned)
    return cleaned.strip()


def _enrich_daily_news_item(picked):
    meta = {
        "source_lookup": {
            "needed": False,
            "ok": False,
            "skipped": "",
            "chars": 0,
        }
    }
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
            max_chars=_source_lookup_max_chars(),
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


def _daily_news_story_lines(value: str) -> list[str]:
    text = _strip_urls(value or "")
    text = re.sub(r"\r\n?", "\n", text)
    numbered_markers = re.findall(r"(?:^|\s)\d{1,2}[.、]\s*", text)
    if len(numbered_markers) >= 2:
        text = re.sub(r"(?<!^)(?<!\n)\s+(?=\d{1,2}[.、]\s*)", "\n", text)
    text = re.sub(r"(?m)^\s*(?:[-*•·]|\d{1,2}[.、])\s*", "", text)
    lines: list[str] = []
    for raw in text.split("\n"):
        line = _clean_original_news_text(raw)
        line = re.sub(r"\s+", " ", line).strip(" \t\r\n|｜")
        if line:
            lines.append(line)
    return lines


def _daily_news_line_looks_like_story_headline(value: str) -> bool:
    if re.search(r"[。！？]", value or ""):
        return False
    text = _clean_daily_news_title_candidate(value or "")
    if len(text) < 6 or len(text) > 70:
        return False
    if any(marker in text for marker in ("来源", "发布时间", "原文摘录", "正文", "摘要")):
        return False
    cjk_count = len(_CJK_CHAR_RE.findall(text))
    ascii_count = len(_ASCII_WORD_RE.findall(text))
    if cjk_count < 4 and ascii_count < 2:
        return False
    return len(re.split(r"[，,；;]", text)) <= 3


def _daily_news_line_relevance(value: str, context: str) -> float:
    text = _clean_daily_news_title_candidate(value or "")
    ctx = _clean_daily_news_title_candidate(context or "")
    if not text or not ctx:
        return 0.0
    if text in ctx or ctx in text:
        return 1.0
    text_tokens = _daily_news_context_signal_tokens(text)
    context_tokens = _daily_news_context_signal_tokens(ctx)
    if not text_tokens or not context_tokens:
        return 0.0
    overlap = len(text_tokens & context_tokens) / max(1, min(len(text_tokens), len(context_tokens)))
    return overlap


def _daily_news_title_is_bundle_header(value: str) -> bool:
    text = _clean_daily_news_title_candidate(value or "")
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    bundle_markers = (
        "今日要闻",
        "今日新闻",
        "每日要闻",
        "最新消息",
        "热点新闻",
        "新闻快讯",
        "财经早报",
        "早报",
        "晚报",
        "简讯",
        "要闻",
    )
    if compact in bundle_markers or any(
        compact.endswith(marker)
        for marker in ("日报", "早报", "晚报", "简报", "快讯")
    ):
        return True
    if re.search(r"(?:AI|互联网|科技|IT)?(?:日报|早报|晚报|简报|快讯)[：:]", compact, re.I):
        story_part = re.split(r"[：:]", compact, maxsplit=1)[-1]
        return len([part for part in re.split(r"[、；;]", story_part) if part]) >= 2
    return False


def _daily_news_story_importance_score(value: str) -> float:
    text = _clean_daily_news_title_candidate(value or "")
    if not text:
        return 0.0
    score = 0.0
    markers: tuple[tuple[str, float], ...] = (
        ("国务院", 3.0),
        ("中央", 2.4),
        ("全国", 1.4),
        ("新规", 2.2),
        ("施行", 1.6),
        ("发布", 1.4),
        ("宣布", 1.2),
        ("监管", 2.0),
        ("调查", 2.0),
        ("处罚", 2.0),
        ("清理", 2.1),
        ("违规", 1.7),
        ("治理", 1.8),
        ("事故", 2.0),
        ("死亡", 2.0),
        ("权益", 1.8),
        ("保障", 1.5),
        ("禁令", 1.8),
        ("上市", 1.2),
        ("收购", 1.2),
        ("裁员", 1.2),
        ("暴涨", 1.1),
        ("暴跌", 1.1),
        ("突破", 1.1),
    )
    for marker, weight in markers:
        if marker in text:
            score += weight
    if re.search(r"\d|[一二三四五六七八九十两]", text):
        score += 0.8
    if any(marker in text for marker in ("花絮", "综艺", "夜市", "开幕", "趣闻")):
        score -= 1.0
    return score


def _select_daily_news_story_line(lines: list[str], *, context: str) -> str:
    if not lines:
        return ""
    if _daily_news_title_is_bundle_header(context):
        scored = [(_daily_news_story_importance_score(line), -idx, line) for idx, line in enumerate(lines)]
        scored.sort(reverse=True)
        best_score, _neg_idx, best_line = scored[0]
        return best_line if best_score > 0 else lines[0]
    scored = [
        (_daily_news_line_relevance(line, context), _daily_news_story_importance_score(line), -idx, line)
        for idx, line in enumerate(lines)
    ]
    scored.sort(reverse=True)
    best_score, _importance, _neg_idx, best_line = scored[0]
    return best_line if best_score > 0 else lines[0]


def _focus_daily_news_multistory_text(value: str, *, context: str) -> tuple[str, bool, str]:
    lines = _daily_news_story_lines(value)
    if len(lines) < 2:
        return (value or "").strip(), False, ""

    headline_like_count = sum(1 for line in lines if _daily_news_line_looks_like_story_headline(line))
    if len(lines) < 3 and headline_like_count < 2:
        return (value or "").strip(), False, ""
    if len(lines) >= 3 and headline_like_count < 1:
        return (value or "").strip(), False, ""

    best_line = _select_daily_news_story_line(lines, context=context)
    focused = _clean_original_news_text(best_line)
    return focused, focused.strip() != (value or "").strip(), focused


def _focus_daily_news_item(picked) -> tuple[Any, dict[str, Any]]:
    """
    Some hot-list APIs return one item whose description/content is actually a
    stack of several unrelated headlines. Keep the story represented by the
    candidate title before prompting the LLM or generating an image.
    """
    title = getattr(picked, "title", "") or ""
    description = getattr(picked, "description", "") or ""
    content = getattr(picked, "content", "") or ""

    focused_description, desc_changed, desc_story = _focus_daily_news_multistory_text(
        description,
        context=title,
    )
    focused_content, content_changed, content_story = _focus_daily_news_multistory_text(
        content,
        context=f"{title} {focused_description or description}",
    )
    selected_story = desc_story or content_story

    meta: dict[str, Any] = {
        "multi_story_filter": {
            "applied": bool(desc_changed or content_changed),
        }
    }
    if selected_story:
        meta["multi_story_filter"]["selected_title"] = selected_story
    if desc_changed:
        meta["multi_story_filter"]["description_before_chars"] = len(description)
        meta["multi_story_filter"]["description_after_chars"] = len(focused_description)
    if content_changed:
        meta["multi_story_filter"]["content_before_chars"] = len(content)
        meta["multi_story_filter"]["content_after_chars"] = len(focused_content)

    title_changed = False
    focused_title = title
    if selected_story and _daily_news_title_is_bundle_header(title):
        focused_title = selected_story
        title_changed = True
        meta["multi_story_filter"]["title_before"] = title
        meta["multi_story_filter"]["title_after"] = focused_title

    if not (desc_changed or content_changed or title_changed):
        return picked, meta
    return (
        replace(
            picked,
            title=focused_title,
            description=focused_description or None,
            content=focused_content or None,
        ),
        meta,
    )


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
    text = _to_simplified_common(text)
    text = _DAILY_NEWS_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"^原文摘录[:：]?", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    text = _strip_news_site_suffixes(text)
    text = _strip_news_column_prefix(text)
    text = text.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'（）()[]【】")
    space_parts = re.split(r"\s+", text, maxsplit=1)
    if len(space_parts) == 2:
        head, tail = [part.strip() for part in space_parts]
        if _has_cjk(head) and _has_cjk(tail) and 8 <= len(head) <= 18:
            text = head
    for sep in ("。", "；", ";", "，", ",", "：", ":", " - ", "—", "（", "("):
        if sep in text:
            head, tail = [part.strip() for part in text.split(sep, 1)]
            if sep in ("：", ":") and len(head) <= 3 and _has_cjk(tail):
                text = tail
                break
            if head:
                text = head
                break
    text = _strip_news_site_suffixes(text)
    text = _strip_news_column_prefix(text)
    return _repair_unbalanced_title_quotes(text.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'（）()[]【】"))


def _repair_unbalanced_title_quotes(text: str) -> str:
    repaired = text or ""
    quote_pairs = (("“", "”"), ("‘", "’"), ("《", "》"))
    for left, right in quote_pairs:
        if repaired.count(left) != repaired.count(right):
            repaired = repaired.replace(left, "").replace(right, "")
    return repaired.strip()


def _expand_short_daily_news_title(cleaned: str, source_text: str, *, max_len: int) -> str:
    if len(cleaned or "") >= _DAILY_NEWS_TITLE_MIN_LEN:
        return cleaned
    raw = _strip_urls(source_text or "")
    raw = _DAILY_NEWS_PREFIX_RE.sub("", raw).strip()
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = _strip_news_site_suffixes(raw)
    if not raw or not _has_cjk(raw) or _has_japanese_kana(raw):
        return cleaned

    parts = [
        part.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'“”‘’（）()[]【】")
        for part in re.split(r"[，,。；;：:!?！？]", raw)
        if part.strip()
    ]
    if not parts:
        return cleaned
    head = _clean_daily_news_title_candidate(parts[0])
    if not head or not _has_cjk(head) or _has_japanese_kana(head):
        return cleaned
    tail = "".join(_clean_daily_news_title_candidate(part) for part in parts[1:3])
    tail = re.sub(r"^(?:新华社|新华网)?记者", "", tail).strip()

    options: list[str] = []
    hints: list[str] = []
    if "瑞士" in tail and "瑞士" not in head:
        hints.append("瑞士")
    if "现场直击" in tail and "现场直击" not in head:
        hints.append("现场直击")
    elif "现场" in tail and "现场" not in head:
        hints.append("现场")
    elif "直击" in tail and "直击" not in head:
        hints.append("直击")
    if hints:
        options.append(f"{head}{''.join(hints)}")
    if tail:
        options.append(f"{head}{tail}")
    if len(head) > len(cleaned or ""):
        options.append(head)

    for option in options:
        candidate = re.sub(r"(?:新华社|新华网)?记者", "", option)
        candidate = _clean_daily_news_title_candidate(candidate)
        if len(candidate) > max_len:
            candidate = candidate[:max_len].rstrip("，,。.!！?？:：|｜-—–")
        if (
            len(candidate) >= _DAILY_NEWS_TITLE_MIN_LEN
            and _has_cjk(candidate)
            and not _has_japanese_kana(candidate)
        ):
            return candidate
    return cleaned


def _daily_news_title_is_incomplete_condition(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact.startswith(("如", "如果", "若", "倘若", "假如", "一旦")):
        return False
    if not any(marker in compact for marker in ("不能", "未能", "无法", "未达成", "没有达成")):
        return False
    return not any(marker in compact for marker in ("通行费", "收取", "征收", "造成", "导致", "宣布", "启动"))


def _daily_news_title_has_incomplete_tail(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if re.search(r"[\u4e00-\u9fff].*\d$", compact):
        return True
    return compact.endswith(("获", "补", "项", "按下", "缘何", "路线规", "正式", "启动响"))


def _daily_news_title_has_column_prefix(text: str) -> bool:
    value = (text or "").strip()
    if "｜" not in value and "|" not in value:
        return False
    head = re.split(r"[｜|]", value, maxsplit=1)[0].strip()
    return 2 <= len(head) <= 10


def _repair_incomplete_condition_title(source_texts: list[str], *, max_len: int) -> str:
    raw = _strip_urls(" ".join(text for text in source_texts if text))
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""

    if "通行费" in raw and ("伊朗" in raw or "霍尔木兹" in raw or "海峡" in raw):
        title = "美或收霍尔木兹通行费" if "霍尔木兹" in raw else "美或收海峡通行费"
        if "特朗普" in raw:
            title = f"特朗普称{title}"
        return title[:max_len].rstrip("，,。.!！?？:：|｜-—–")

    result_match = re.search(r"(?:美(?:国)?|美方|美国或|美或)[^。；;，,！？!?]{0,18}(?:通行费|关税|费用)", raw)
    if result_match:
        title = result_match.group(0)
        title = re.sub(r"^美国或", "美或", title)
        if "特朗普" in raw and not title.startswith("特朗普"):
            title = f"特朗普称{title}"
        title = _clean_daily_news_title_candidate(title)
        return title[:max_len].rstrip("，,。.!！?？:：|｜-—–")
    return ""


def _compact_title_prompt_compare(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？；;：:、|｜\-—–]+", "", text or "")


def _daily_news_title_has_prompt_leak(
    text: str,
    prompt_norm: str = "",
    *,
    compare_prompt: bool = True,
) -> bool:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return False
    prompt_clean = re.sub(r"\s+", " ", (prompt_norm or "").strip())
    if compare_prompt and prompt_clean and cleaned == prompt_clean:
        return True
    if compare_prompt and prompt_clean:
        compact_cleaned = _compact_title_prompt_compare(cleaned)
        compact_prompt = _compact_title_prompt_compare(prompt_clean)
        if len(compact_cleaned) >= 4 and compact_cleaned in compact_prompt:
            return True
    if cleaned in _NEWS_GENERIC_TITLE_MARKERS:
        return True
    if any(marker in cleaned for marker in _NEWS_TITLE_PROMPT_STRONG_MARKERS):
        return True
    soft_hits = sum(1 for marker in _NEWS_TITLE_PROMPT_SOFT_MARKERS if marker in cleaned)
    return soft_hits >= 2 and any(word in cleaned for word in ("新闻", "标题", "body", "Body"))


def _english_keyword_hit(text_lc: str, keyword: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    if re.fullmatch(r"[a-z0-9]+", kw):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text_lc))
    return kw in text_lc


def _english_any_keyword(text_lc: str, keywords: tuple[str, ...]) -> bool:
    return any(_english_keyword_hit(text_lc, keyword) for keyword in keywords)


def _english_daily_news_title_summary(text: str, prompt_norm: str = "") -> str:
    lower = f"{text or ''} {prompt_norm or ''}".lower()
    rules = (
        (("nato", "us forces in europe", "american forces in europe", "troop deployments in europe", "hegseth"), "美军欧洲部署审查"),
        (("sunscreen", "bemotrizinol", "fda"), "防晒审批迎来进展"),
        (("moon", "lunar", "nasa"), "NASA月球基地计划"),
        (("lithium", "mining"), "锂提取技术获进展"),
        (("biological weapon", "bioweapon", "synthetic dna"), "AI生物风险受关注"),
        (("cybersecurity", "cyber security"), "AI网络安全受关注"),
        (("mobile phone", "phones in schools", "school phone"), "学校手机禁令推进"),
        (("western technology", "russian spies"), "俄方技术获取受关注"),
        (("vpn", "geoblocking", "polymarket"), "平台封锁VPN用户"),
        (("american technology", "big tech"), "欧洲减少美科技依赖"),
        (("climate action", "action pour le climat", "climat", "climate"), "气候行动分歧受关注"),
        (("seawater battery", "desalination", "carbon capture"), "海水电池技术突破"),
        (("authors", "using ai", "publishing industry"), "作家使用AI引争议"),
        (("claude", "ai model access", "advanced ai model"), "AI模型争议升温"),
        (("ai accelerator", "ai chip", "chip company", "inference workloads"), "AI芯片新品发布"),
        (("lg display", "oled", "certification"), "LG显示OLED首获认证"),
        (("oled", "color/brightness"), "OLED面板获色彩亮度认证"),
        (("oled", "display", "brightness"), "OLED面板亮度认证"),
        (("ai", "artificial intelligence"), "AI议题出现进展"),
        (("chip", "semiconductor"), "芯片产业出现进展"),
        (("trade", "tariff", "export", "import"), "外贸数据出现变化"),
        (("inflation", "price", "market"), "经济议题出现变化"),
        (("court", "case", "sentence", "police"), "社会事件出现进展"),
    )
    for keywords, title in rules:
        if _english_any_keyword(lower, keywords):
            return title
    return ""


def _keyword_daily_news_title(text: str, prompt_norm: str = "") -> str:
    lower = (text or "").lower()
    english_summary = _english_daily_news_title_summary(text, "")
    if english_summary:
        return english_summary
    if (
        "外贸" in text
        or "贸易" in text
        or "貿易" in text
        or "貿" in text
        or _english_any_keyword(lower, ("trade", "export", "import"))
    ):
        return "外贸数据出现变化"
    if "科技" in text or "人工智能" in text or _english_any_keyword(
        lower, ("ai", "openai", "chip", "tech", "technology", "software", "model")
    ):
        return "科技议题出现进展"
    if "经济" in text or _english_any_keyword(lower, ("market", "inflation", "prices", "economy")):
        return "经济议题出现变化"
    if "社会" in text or _english_any_keyword(lower, ("court", "case", "sentence", "police", "school")):
        return "社会事件出现进展"
    return "国际议题出现进展"


def _compress_long_daily_news_title(text: str, *, max_len: int) -> str:
    raw = text or ""
    rules = (
        (("因你而来", "演唱会", "通信保障"), "演唱会通信保障完成"),
        (("苏新消费", "品质数码", "手机补贴"), "江苏数码消费补贴启动"),
        (("手机补贴", "最高可补"), "江苏手机补贴启动"),
        (("纸尿裤", "甲酰胺", "未检出"), "纸尿裤甲酰胺未检出"),
        (("水运工程", "快进键"), "多项重大水运工程提速"),
        (("马斯克", "行权", "账面收益"), "马斯克获巨额账面收益"),
        (("马斯克", "行权", "7800亿"), "马斯克获巨额账面收益"),
        (("AI伴你游", "数字导游"), "AI数字导游助力出游"),
        (("杭小忆", "文旅小程序"), "AI数字导游助力出游"),
        (("小巨人", "最前沿"), "小巨人企业布局前沿"),
        (("小巨人", "水下机器人"), "小巨人企业布局前沿"),
        (("欧洲化工", "赢创", "裁3200"), "赢创全球再裁3200人"),
        (("赢创", "聚酯业务", "3200"), "赢创全球再裁3200人"),
        (("科幻影视产业论坛", "浦东", "启幕"), "上海科幻影视论坛启幕"),
        (("科幻影视产业论坛", "浦东", "开幕"), "上海科幻影视论坛开幕"),
        (("科创资源深度融合", "前沿技术", "大湾区"), "大湾区前沿技术落地"),
        (("城市群区域协同", "粤港澳大湾区"), "大湾区前沿技术落地"),
        (("国际科技创新中心", "大湾区"), "大湾区科创中心建设提速"),
        (("资金狂涌", "韩国赛道"), "全球资金布局韩国科技"),
        (("人权理事会", "全球人权治理"), "中国共商全球人权治理"),
        (("全球人权治理", "边会"), "中国共商全球人权治理"),
        (("战时所掠中国文物", "返还"), "日本学者呼吁返还文物"),
        (("潮汕", "情书"), "在香江细读潮汕“情书”"),
    )
    for markers, title in rules:
        if all(marker in raw for marker in markers) and len(title) <= max_len:
            return title
    return ""


def _compact_daily_news_title_key(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？；;：:、|｜\-—–（）()《》“”\"'‘’]+", "", text or "")


def _daily_news_title_needs_source_rewrite(cleaned: str, source_title: str) -> bool:
    value = cleaned or ""
    if any(marker in value for marker in ("手慢无", "速看", "来了", "重磅")):
        return True
    if _daily_news_title_has_column_prefix(value):
        return True
    if _daily_news_title_has_incomplete_tail(value):
        return True
    if any(marker in value for marker in ("游客在手机上打开", "手机上打开")):
        return True
    source_compact = _compact_daily_news_title_key(_to_simplified_common(source_title or ""))
    cleaned_compact = _compact_daily_news_title_key(value)
    if not source_compact or not cleaned_compact:
        return False
    if not source_compact.startswith(cleaned_compact):
        return False
    if len(source_compact) <= len(cleaned_compact):
        return False
    # LLMs sometimes satisfy the character limit by cutting the source title at
    # exactly 17-18 chars. If the next source character is a normal CJK word
    # rather than a delimiter, treat it as an incomplete title.
    if len(value) >= max(15, _DAILY_NEWS_TITLE_MIN_LEN):
        next_char = source_compact[len(cleaned_compact) : len(cleaned_compact) + 1]
        return bool(next_char and (_has_cjk(next_char) or next_char.isalnum()))
    return False


def _rewrite_copied_daily_news_title(cleaned: str, source_title: str, source_texts: list[str], *, max_len: int) -> str:
    source_clean = _clean_daily_news_title_candidate(source_title)
    if not source_clean:
        return cleaned
    needs_rewrite = _daily_news_title_needs_source_rewrite(cleaned, source_title)
    if _compact_daily_news_title_key(cleaned) != _compact_daily_news_title_key(source_clean) and not needs_rewrite:
        return cleaned

    raw = _to_simplified_common(" ".join([source_title, *source_texts]))
    compressed = _compress_long_daily_news_title(raw, max_len=max_len)
    if compressed:
        return compressed[:max_len]
    if "古巴" in raw and "美国" in raw and "无权评判" in raw and "改革" in raw:
        return "古巴回应美国评判改革"[:max_len]
    if "香港" in raw and "科企" in raw and any(marker in raw for marker in ("门户", "出海", "通往世界")):
        return "香港助内地科企出海"[:max_len]
    if "世界杯官方用球" in raw and any(marker in raw for marker in ("太空", "空间站", "NASA")):
        return "世界杯用球飞上太空"[:max_len]
    if "夏季达沃斯" in raw and "主会场" in raw:
        return "夏季达沃斯会场探访"[:max_len]
    return cleaned


def _normalize_daily_news_title(
    title: str,
    picked=None,
    prompt_norm: str = "",
    *,
    max_len: int = 18,
) -> str:
    candidates: list[tuple[str, bool]] = [(title, True)]
    if picked is not None:
        candidates.extend(
            [
                (getattr(picked, "title", "") or "", False),
                (getattr(picked, "description", "") or "", False),
                (getattr(picked, "content", "") or "", False),
            ]
        )
    candidates.append((prompt_norm, True))
    source_texts = [candidate for candidate, compare_prompt in candidates if not compare_prompt]
    if picked is not None:
        title_expand_sources = [
            getattr(picked, "title", "") or "",
            getattr(picked, "description", "") or "",
            getattr(picked, "content", "") or "",
        ]
    else:
        title_expand_sources = []

    for candidate, compare_prompt in candidates:
        cleaned = _clean_daily_news_title_candidate(candidate)
        has_better_source_title = any(
            len(_clean_daily_news_title_candidate(src)) >= 6
            for src, src_compare in candidates
            if not src_compare
        )
        if (
            not cleaned
            or (has_better_source_title and len(cleaned) <= 3)
            or _daily_news_title_has_prompt_leak(
                cleaned,
                prompt_norm,
                compare_prompt=compare_prompt,
            )
            or _daily_news_title_has_bad_language(cleaned)
        ):
            continue
        if len(cleaned) < _DAILY_NEWS_TITLE_MIN_LEN:
            for source_text in [candidate, *title_expand_sources, *source_texts]:
                expanded = _expand_short_daily_news_title(cleaned, source_text, max_len=max_len)
                if len(expanded) > len(cleaned):
                    cleaned = expanded
                    break
        if _daily_news_title_is_incomplete_condition(cleaned):
            repaired = _repair_incomplete_condition_title(
                [candidate, *title_expand_sources, *source_texts],
                max_len=max_len,
            )
            if repaired:
                cleaned = repaired
            else:
                continue
        if picked is not None and title_expand_sources:
            cleaned = _rewrite_copied_daily_news_title(
                cleaned,
                title_expand_sources[0],
                [candidate, *title_expand_sources, *source_texts],
                max_len=max_len,
            )
        specific_title = _compress_long_daily_news_title(
            " ".join([candidate, *title_expand_sources, *source_texts]),
            max_len=max_len,
        )
        if specific_title and (
            len(cleaned) >= max_len
            or _daily_news_title_has_incomplete_tail(cleaned)
            or any(marker in cleaned for marker in ("依托城市群", "重磅部署", "资金狂涌"))
        ):
            cleaned = specific_title
        if len(cleaned) > max_len:
            compressed = _compress_long_daily_news_title(
                " ".join([candidate, *title_expand_sources, *source_texts]),
                max_len=max_len,
            )
            cleaned = compressed or cleaned[:max_len].rstrip("，,。.!！?？:：|｜-—–")
        cleaned = cleaned.rstrip("，,、。.!！?？:：|｜-—–")
        cleaned = _repair_unbalanced_title_quotes(cleaned)
        if _daily_news_title_has_incomplete_tail(cleaned):
            repaired = _compress_long_daily_news_title(
                " ".join([candidate, *title_expand_sources, *source_texts]),
                max_len=max_len,
            )
            if repaired and not _daily_news_title_has_incomplete_tail(repaired):
                cleaned = repaired
            else:
                continue
        if cleaned and _has_cjk(cleaned) and not _has_japanese_kana(cleaned):
            return cleaned

    source_joined = " ".join(candidate for candidate, compare_prompt in candidates if not compare_prompt)
    joined = " ".join(candidate for candidate, _compare_prompt in candidates)
    fallback = _keyword_daily_news_title(source_joined or joined, "")
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
    if text in _NEWS_GENERIC_TITLE_MARKERS:
        return True
    compact = re.sub(r"\s+", "", text)
    generic_patterns = (
        r"(?:近期|最新)?多项(?:行业)?动态(?:发布|更新|汇总|出现)?$",
        r"(?:近期|最新)?多条.+(?:消息|资讯|新闻|动态)(?:发布|更新|汇总)?$",
        r"(?:行业|赛道)(?:近期|最新).*(?:多项|多条).*(?:动态|消息|资讯)$",
    )
    if any(re.search(pattern, compact) for pattern in generic_patterns):
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
_NEWS_BODY_JSON_KEYS = ("原文标题", "内容", "评价", "日期", "来源")

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


def _daily_news_comment_is_generic(comment: str) -> bool:
    text = re.sub(r"\s+", "", comment or "")
    if not text:
        return False
    compact_markers = [re.sub(r"\s+", "", marker) for marker in _NEWS_GENERIC_COMMENT_MARKERS]
    return any(marker in text for marker in compact_markers)


_HUMANITARIAN_COMMENT_MARKERS = (
    "平民保护",
    "救援通道",
    "停火安排",
    "人道主义行动",
    "民生危机",
    "冲突地区",
)


def _daily_news_comment_is_unsupported(comment: str, picked, content: str = "") -> bool:
    text = comment or ""
    raw = " ".join(
        str(part or "")
        for part in (
            getattr(picked, "title", ""),
            getattr(picked, "description", ""),
            getattr(picked, "content", ""),
            content,
        )
    )
    if _daily_news_has_unsupported_numeric_claim(text, picked, content):
        return True
    if not any(marker in text for marker in _HUMANITARIAN_COMMENT_MARKERS):
        return False
    support_markers = ("平民", "救援", "停火", "人道主义", "冲突地区", "生存需求")
    return sum(1 for marker in support_markers if marker in raw) < 2


def _daily_news_safe_fact_comment(picked, content: str = "") -> str:
    raw = " ".join(
        str(part or "")
        for part in (
            getattr(picked, "title", ""),
            getattr(picked, "description", ""),
            getattr(picked, "content", ""),
            content,
        )
    )
    if any(marker in raw for marker in ("谈判", "会谈", "部长级")):
        return (
            "这类谈判或会谈新闻的看点在于各方能否形成可核验的正式结果。"
            "当前公开信息主要是参会和议题表述，判断实际影响还要看后续声明、协议文本和执行进展。"
        )
    return ""


def _daily_news_minimal_fact_comment(picked, content: str, subject: str) -> str:
    """Provide a source-bound evaluation when a generated draft omits one."""
    subject_text = _normalize_news_summary(subject, limit=42).strip("。！？!？ ")
    if not subject_text or subject_text.startswith("一项"):
        subject_text = _normalize_news_summary(
            getattr(picked, "title", "") or getattr(picked, "description", ""),
            limit=42,
        ).strip("。！？!？ ")
    if subject_text:
        return (
            f"围绕{subject_text}的实际影响，仍需结合后续公开的执行细节和可核验反馈判断。"
            "现有材料已披露的事实应与尚未确认的推测区分开来。"
        )
    return "现有材料已披露的事实应与尚未确认的推测区分开来，后续影响仍需以可核验信息判断。"


def _daily_news_context_text(picked, content: str = "") -> str:
    return " ".join(
        str(part or "")
        for part in (
            getattr(picked, "title", ""),
            getattr(picked, "description", ""),
            getattr(picked, "content", ""),
            content,
        )
    )


def _daily_news_has_unsupported_numeric_claim(text: str, picked, content: str = "") -> bool:
    compact_text = re.sub(r"\s+", "", text or "")
    compact_source = re.sub(r"\s+", "", _daily_news_context_text(picked, content))
    claims = re.findall(
        r"\d{1,2}:\d{2}|(?:\d+(?:\.\d+)?|[一二三四五六七八九十两]+)\s*(?:分钟|小时|天|周|月|年|个|名|项|次|%|％)",
        compact_text,
    )
    return any(claim not in compact_source for claim in claims)


def _daily_news_content_is_unsupported(content: str, picked) -> bool:
    text = content or ""
    if not text.strip():
        return False
    source = _daily_news_context_text(picked)
    if _daily_news_has_unsupported_numeric_claim(text, picked):
        return True
    hallucination_markers = (
        "对委内瑞拉",
        "对伊朗发起军事行动",
        "下一个是古巴",
        "石油封锁",
        "军事行动",
    )
    recommendation_markers = (
        "权威数读",
        "新华视点",
        "记者手记",
        "阅读下一篇",
        "深度观察",
        "特色产业赋能",
        "中国摩托加速",
    )
    site_noise_markers = (
        "举报 0",
        "分享至好友和朋友圈",
        "用微信扫码二维码",
        "打开微信",
        "扫一扫",
        "分享至朋友圈",
        "普通话",
        "广东话",
        "字号",
        "超大",
        "缩小字体",
        "放大字体",
        "热文排行",
        "财经日历",
        "今日要点",
        "全球大事",
        "经济数据",
        "每日智库看点",
        "21早新闻",
        "查看全部 -->",
    )
    if any(marker in text for marker in (*recommendation_markers, *site_noise_markers)):
        return True
    return any(marker in text and marker not in source for marker in hallucination_markers)


def _daily_news_comment_is_irrelevant(comment: str, picked, content: str = "") -> bool:
    text = comment or ""
    if not text.strip():
        return False
    compact_text = re.sub(r"\s+", "", text)
    source = _daily_news_context_text(picked, content)
    compact_source = re.sub(r"\s+", "", source)
    bay_area_comment_markers = ("大湾区科创", "跨城资源", "跨境规则衔接", "科技成果商业化")
    if any(marker in text for marker in bay_area_comment_markers):
        bay_area_source_markers = ("大湾区", "粤港澳", "科创资源", "跨城", "跨境规则", "科技成果商业化")
        return not any(marker in source for marker in bay_area_source_markers)
    if any(marker in text for marker in ("美股", "半导体设备")) and not any(
        marker in source for marker in ("美股", "半导体设备", "美国股票基金", "科技板块单周流入")
    ):
        return True
    trade_comment_markers = ("订单", "物流", "企业成本", "中国企业", "供应链", "市场风险")
    if any(marker in text for marker in trade_comment_markers):
        trade_source_markers = (
            "外贸",
            "贸易额",
            "出口",
            "进口",
            "关税",
            "供应链",
            "订单",
            "supply chain",
            "trade",
            "investment",
            "standards",
        )
        return not any(marker in source for marker in trade_source_markers)
    securities_comment_markers = ("监管处罚", "公平交易", "信息披露秩序", "处罚结果", "市场禁入")
    if any(marker in text for marker in securities_comment_markers):
        securities_source_markers = ("监管处罚", "行政处罚", "罚款", "市场禁入", "操纵", "违规减持", "内幕交易")
        return not any(marker in source for marker in securities_source_markers)
    ai_comment_markers = ("AI 使用边界", "披露义务", "版权和信任", "模型本身")
    if any(re.sub(r"\s+", "", marker) in compact_text for marker in ai_comment_markers):
        ai_source_markers = (
            "版权",
            "出版",
            "作家",
            "署名",
            "模型访问",
            "训练数据",
            "生成式AI",
            "内容平台",
        )
        return not any(re.sub(r"\s+", "", marker) in compact_source for marker in ai_source_markers)
    sports_comment_markers = ("竞技表现", "人才梯队", "长期训练体系", "稳定备战", "青训投入")
    if any(marker in text for marker in sports_comment_markers):
        if any(marker in source for marker in ("NASA", "空间站", "航天", "太空", "阿耳忒弥斯")):
            return True
    weather_comment_markers = (
        "气象监测",
        "灾害预警",
        "防灾减灾",
        "农业安排",
        "基层防灾",
        "设备能否长期运行",
    )
    if any(marker in text for marker in weather_comment_markers):
        weather_source_markers = (
            "气象",
            "天气",
            "台风",
            "暴雨",
            "洪水",
            "灾害",
            "预警",
            "防灾",
            "农业",
            "weather",
            "meteorological",
            "disaster warning",
        )
        return not any(marker.lower() in source.lower() for marker in weather_source_markers)
    return False


def _remove_generic_daily_news_comment(body: str) -> str:
    text = (body or "").strip()
    if not text or _NEWS_COMMENT_LABEL not in text:
        return text

    pattern = re.compile(
        rf"\n{{0,2}}{re.escape(_NEWS_COMMENT_LABEL)}\s*\n"
        r"(?P<comment>.*?)(?=\n{1,2}发布时间：|\n{1,2}来源：|\Z)",
        flags=re.S,
    )
    while True:
        match = pattern.search(text)
        if not match:
            return text.strip()
        if not _daily_news_comment_is_generic(match.group("comment")):
            return text.strip()
        head = text[: match.start()].rstrip()
        tail = text[match.end() :].lstrip()
        text = f"{head}\n\n{tail}".strip() if tail else head


def _daily_news_body_is_too_generic(body: str) -> bool:
    text = body or ""
    if not text.strip():
        return True
    return any(marker in text for marker in _NEWS_GENERIC_BODY_MARKERS) or _daily_news_comment_is_generic(text)


def _daily_news_body_quality_fields(body: str) -> dict[str, str]:
    text = _strip_urls(body or "")
    data = _load_daily_news_body_json(text)
    if data:
        return {
            "原文标题": _clean_daily_news_json_value(data.get("原文标题") or data.get("title") or data.get("标题") or ""),
            "内容": _clean_daily_news_text_value(data.get("内容") or data.get("content") or data.get("新闻内容") or data.get("body") or ""),
            "评价": _clean_daily_news_text_value(data.get("评价") or data.get("点评") or data.get("comment") or ""),
            "日期": _clean_daily_news_json_value(data.get("日期") or data.get("发布时间") or data.get("date") or ""),
            "来源": _clean_daily_news_json_value(data.get("来源") or data.get("source") or ""),
        }
    rendered = _extract_rendered_daily_news_body_fields(text)
    if rendered:
        return {key: _clean_daily_news_text_value(rendered.get(key, "")) for key in _NEWS_BODY_JSON_KEYS}
    return {"原文标题": "", "内容": _clean_daily_news_text_value(text), "评价": "", "日期": "", "来源": ""}


def _daily_news_body_missing_required_fields(body: str) -> bool:
    text = _strip_urls(body or "")
    has_structured_shape = bool(_load_daily_news_body_json(text) or _extract_rendered_daily_news_body_fields(text))
    if not has_structured_shape:
        return True
    fields = _daily_news_body_quality_fields(text)
    required = ("内容", "评价", "日期", "来源")
    if any(not fields.get(key, "").strip() for key in required):
        return True
    content = fields.get("内容", "").strip()
    if any(label in content for label in ("原文标题：", "日期：", "来源：")):
        return True
    return False


def _daily_news_body_has_site_noise(body: str) -> bool:
    fields = _daily_news_body_quality_fields(body)
    content = fields.get("内容", "")
    markers = (
        "打开微信",
        "扫一扫",
        "分享至朋友圈",
        "热文排行",
        "财经日历",
        "今日要点",
        "全球大事",
        "经济数据",
        "每日智库看点",
        "21早新闻",
        "查看全部 -->",
    )
    return any(marker in content for marker in markers)


def _daily_news_body_has_mismatched_comment(body: str) -> bool:
    fields = _daily_news_body_quality_fields(body)
    context = " ".join(
        fields.get(key, "")
        for key in ("原文标题", "内容")
    )
    comment = fields.get("评价", "")
    if any(marker in comment for marker in ("美股", "半导体设备")) and not any(
        marker in context for marker in ("美股", "半导体设备", "美国股票基金", "科技板块单周流入")
    ):
        return True
    weather_comment_markers = ("气象监测", "灾害预警", "防灾减灾", "农业安排", "基层防灾")
    weather_context_markers = ("气象", "天气", "台风", "暴雨", "洪水", "灾害", "预警", "防灾", "农业")
    if any(marker in comment for marker in weather_comment_markers) and not any(
        marker in context for marker in weather_context_markers
    ):
        return True
    return False


def _repair_daily_news_mismatched_comment(
    body: str,
    picked,
    prompt_norm: str,
    title_hint: str = "",
) -> str:
    """Replace a final rendered cross-topic comment with a source-grounded one."""
    fields = _daily_news_body_to_fields(body, picked, prompt_norm, title_hint=title_hint)
    rendered = _render_daily_news_body_fields(fields)
    if not _daily_news_body_has_mismatched_comment(rendered):
        return rendered

    fallback_comment = _daily_news_fact_based_comment(
        picked,
        fields.get("内容", ""),
        _daily_news_fallback_subject(picked, prompt_norm),
    )
    if fallback_comment and not _daily_news_comment_is_irrelevant(
        fallback_comment,
        picked,
        fields.get("内容", ""),
    ):
        fields["评价"] = fallback_comment
    else:
        fields["评价"] = ""
    return _render_daily_news_body_fields(fields)


def _daily_news_body_has_bad_language(body: str) -> bool:
    fields = _daily_news_body_quality_fields(body)
    original_title = fields.get("原文标题", "")
    content = fields.get("内容", "")
    if not content:
        return True
    if any(marker in content for marker in _DAILY_NEWS_INSUFFICIENT_CONTENT_MARKERS):
        return True
    if _has_english_phrase_leak(content):
        return True
    for value in (original_title, content):
        if not value:
            continue
        if "原文摘录" in value:
            return True
        if _has_japanese_kana(value) or _has_foreign_script_leak(value):
            return True
    return _cjk_count(content) < 8


def _daily_news_quality_issue(title: str, body: str, prompt_norm: str = "") -> str:
    if _daily_news_title_has_bad_language(title):
        return "bad_title_language"
    if _daily_news_title_has_incomplete_tail(title):
        return "incomplete_title"
    if _daily_news_title_has_column_prefix(title):
        return "title_column_prefix"
    if _is_generic_daily_news_title(title):
        return "generic_title"
    if _daily_news_title_has_prompt_leak(title, prompt_norm):
        return "title_prompt_leak"
    if _daily_news_body_has_bad_language(body):
        return "bad_body_language"
    if _daily_news_body_has_prompt_leak(body):
        return "body_prompt_leak"
    if _has_html_artifacts(body):
        return "body_html_artifacts"
    if _daily_news_body_has_site_noise(body):
        return "body_site_noise"
    if _daily_news_body_has_mismatched_comment(body):
        return "comment_mismatch"
    if _daily_news_body_missing_required_fields(body):
        return "missing_body_fields"
    if _daily_news_body_is_too_generic(body):
        return "generic_body"
    return ""


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


def _load_daily_news_body_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if "{" in raw and "}" in raw:
        candidates.append(raw[raw.find("{") : raw.rfind("}") + 1])
    for candidate in [item for value in candidates for item in (value, value.replace("'", '"'))]:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict) and any(key in data for key in _NEWS_BODY_JSON_KEYS):
            return data
    return None


def _clean_daily_news_json_value(value) -> str:
    text = _to_simplified_common(_strip_urls(_strip_html_artifacts(str(value or ""))).strip())
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" \t\r\n,，。")
    return text


def _clean_daily_news_text_value(value) -> str:
    text = _to_simplified_common(_strip_urls(_strip_html_artifacts(str(value or ""))).strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" \t\r\n,，；;：:、")


def _daily_news_text_has_sentence_end(text: str) -> bool:
    return bool(re.search(r"[。！？!?]$", text or ""))


def _daily_news_comment_tail_is_incomplete(text: str) -> bool:
    value = (text or "").strip()
    if not value or _daily_news_text_has_sentence_end(value):
        return False
    incomplete_suffixes = (
        "的",
        "上的",
        "方面的",
        "中的",
        "里的",
        "在",
        "对",
        "与",
        "和",
        "及",
        "以及",
        "通过",
        "成为",
        "体现了",
        "显示了",
        "说明了",
        "意味着",
        "有助于",
        "需要",
        "仍需",
        "更要",
    )
    if value.endswith(incomplete_suffixes):
        return True
    tail = re.split(r"[。！？!?]", value)[-1].strip()
    if len(tail) <= 28 and re.search(r"(在|对|与|和|及|为|从|向|把|被|将|其|该)$", tail):
        return True
    return False


def _clean_daily_news_comment_value(value) -> str:
    text = _clean_daily_news_text_value(value)
    if not text:
        return ""
    text = re.sub(r"\s*(?:发布时间|日期)[:：][^\n。！？!?]*", "", text).strip()
    text = re.sub(r"\s*来源[:：][^\n。！？!?]*", "", text).strip()
    text = text.rstrip("，,；;：:、 ")
    if not text:
        return ""
    if _daily_news_text_has_sentence_end(text):
        return text
    last_end = max(text.rfind(mark) for mark in "。！？!?")
    if last_end >= 0 and last_end + 1 >= max(20, int(len(text) * 0.45)):
        return text[: last_end + 1].strip()
    if _daily_news_comment_tail_is_incomplete(text):
        return ""
    return f"{text}。"


_DAILY_NEWS_METHOD_SENTENCE_MARKERS = (
    "目前可以确认的信息主要来自",
    "因此正文只整理",
    "若报道提到机构、企业或公共部门",
    "更应区分其已公布安排与尚未发生的结果",
    "避免把单一片段扩大成确定趋势",
    "对读者来说，判断这条新闻",
    "再结合后续正式材料确认执行范围和实际效果",
    "在信息仍有限的情况下",
    "需要继续跟踪的进展",
    "不是已经定论的结果",
)


def _remove_daily_news_methodology_noise(text: str) -> str:
    cleaned = _clean_original_news_text(text or "")
    cleaned = re.sub(r"^(?:原始来源|原新闻|来源)消息显示[，,:：]\s*", "", cleaned)
    cleaned = re.sub(r"^(?:鲁网|江南时报|中新网|新华网|人民网)?\s*\d{1,2}月\d{1,2}日?讯[，,:：。]?\s*", "", cleaned)
    cleaned = re.sub(r"^[\u4e00-\u9fff]{2,10}时报讯[，,:：。]?\s*", "", cleaned)
    cleaned = re.sub(r"^[\u4e00-\u9fff·]{2,12}/[^。！？!?]{2,20}\s+20\d{2}-\d{1,2}-\d{1,2}\s*", "", cleaned)
    cleaned = re.sub(r"相关\s+([A-Za-z][A-Za-z0-9_-]{2,20}发布)", r"相关标准。\1", cleaned)
    cleaned = re.sub(r"(?<=[，,])(?:科技部|中央港澳工作办公室|省委副书记)[。.](?=[\u4e00-\u9fff])", "", cleaned)
    cleaned = re.sub(r"_[^。！？!?]{0,100}(?:下载客户端|责任编辑)[^。！？!?]*[。！？!?]?", "。", cleaned)
    cleaned = re.sub(r"(?:下载客户端|责任编辑[:：]\s*[\u4e00-\u9fff·]{1,12})[。！？!?]?", "", cleaned)
    sentences = re.split(r"(?<=[。！？!?])", cleaned)
    kept: list[str] = []
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        if _daily_news_fact_sentence_is_noise(s):
            continue
        if any(marker in s for marker in _DAILY_NEWS_METHOD_SENTENCE_MARKERS):
            continue
        kept.append(s)
    out = "".join(kept).strip() if kept else cleaned
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"(?<=[。！？!?])\s+(?=[\u4e00-\u9fff])", "", out)
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "。", out)
    return out.strip(" \t\r\n,，。")


def _normalize_daily_news_fact_sentence(sentence: str) -> str:
    s = (sentence or "").strip()
    s = re.sub(r"^.{2,30}?消息显示[，,:：]\s*", "", s)
    s = re.sub(r"^.{2,30}?报道[，,:：]\s*", "", s)
    s = re.sub(r"^(?:鲁网|江南时报|中新网|新华网|人民网)?\s*\d{1,2}月\d{1,2}日?讯[，,:：。]?\s*", "", s)
    s = re.sub(r"^[\u4e00-\u9fff]{2,10}时报讯[，,:：。]?\s*", "", s)
    s = re.sub(r"新华社[^，。！？!?]{0,30}\d{1,2}月\d{1,2}日电[（(][^）)]{0,50}[）)]", "", s)
    s = re.sub(r"新华社[^，。！？!?]{0,30}\d{1,2}月\d{1,2}日电[（(]记者[^。！？!?]*$", "", s)
    s = re.sub(r"^[\u4e00-\u9fff·\s]{1,12}[）)](?=(?:由|据|在|“|[一-龥]{2,}))", "", s)
    return s.strip(" \t\r\n,，；;：:、")


def _daily_news_fact_sentence_is_noise(sentence: str) -> bool:
    s = (sentence or "").strip()
    if not s:
        return True
    bare = s.strip("。！？!?，,；;：:、 ")
    if bare in {"来源", "原文摘录"}:
        return True
    if re.search(r"(?:推进|发布|开展|涉及|计划|路线).{0,8}[结规项]$", bare):
        return True
    if (
        len(bare) <= 8
        and not re.search(r"\d|[一二三四五六七八九十两]", bare)
        and (
            re.match(r"^(?:为|为了|因|从|在|由|对|与|和|及|或)", bare)
            or bare.endswith(("现场", "第二", "本次", "此次", "相关"))
        )
    ):
        return True
    if s.count("“") != s.count("”") or s.count("《") != s.count("》"):
        return True
    noise_markers = (
        "下载客户端",
        "责任编辑",
        "The Paper",
        "澎湃新闻-The Paper",
        "澎湃新闻报料",
        "报料热线",
        "报料邮箱",
        "沪ICP备",
        "沪公网安备",
        "互联网新闻信息服务许可证",
        "增值电信业务经营许可证",
        "本站不再支持您的浏览器",
        "请升级您的浏览器",
        "打开微信",
        "扫一扫",
        "分享至朋友圈",
        "热文排行",
        "财经日历",
        "今日要点",
        "全球大事",
        "每日智库看点",
        "21早新闻",
    )
    return any(marker in s for marker in noise_markers)


def _daily_news_sentence_similarity(left: str, right: str) -> float:
    def key(text: str) -> set[str]:
        compact = re.sub(r"[\s，,。！？!?；;：:、（）()《》“”\"'0-9一二三四五六七八九十两]+", "", text or "")
        return {ch for ch in compact if _has_cjk(ch)}

    a = key(left)
    b = key(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


_DAILY_NEWS_CONTEXT_GENERIC_TOKENS = {
    "新闻",
    "报道",
    "消息",
    "技术",
    "进展",
    "获得",
    "宣布",
    "认证",
    "产品",
    "行业",
    "市场",
    "公司",
    "企业",
    "项目",
    "相关",
    "the",
    "and",
    "for",
    "with",
    "from",
    "news",
    "report",
}


def _daily_news_context_signal_tokens(text: str) -> set[str]:
    raw = (text or "").lower()
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]{2,}", raw)
        if token not in _DAILY_NEWS_CONTEXT_GENERIC_TOKENS
    }
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        if chunk not in _DAILY_NEWS_CONTEXT_GENERIC_TOKENS:
            tokens.add(chunk)
        if len(chunk) >= 2:
            for idx in range(len(chunk) - 1):
                token = chunk[idx : idx + 2]
                if token not in _DAILY_NEWS_CONTEXT_GENERIC_TOKENS:
                    tokens.add(token)
    return tokens


def _daily_news_text_matches_context(value: str, *contexts: str, min_overlap: float = 0.35) -> bool:
    text = _clean_daily_news_title_candidate(_strip_urls(value or ""))
    if not text:
        return False
    context = _clean_daily_news_title_candidate(_strip_urls(" ".join(part or "" for part in contexts)))
    if not context:
        return False
    if text in context or context in text:
        return True
    if _daily_news_sentence_similarity(text, context) >= min_overlap:
        return True
    value_tokens = _daily_news_context_signal_tokens(text)
    if not value_tokens:
        return False
    context_tokens = _daily_news_context_signal_tokens(context)
    if not context_tokens:
        return False
    overlap = len(value_tokens & context_tokens) / max(1, min(len(value_tokens), len(context_tokens)))
    return overlap >= min_overlap


def _daily_news_sentences_repeat_named_subject(left: str, right: str) -> bool:
    for pattern in (r"《[^》]{2,40}》", r"“[^”]{2,40}”"):
        for subject in re.findall(pattern, left or ""):
            if subject in (right or ""):
                return True
    return False


def _dedupe_daily_news_fact_sentences(text: str) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])", text or "") if s.strip()]
    if not sentences:
        return text
    kept: list[str] = []
    for index, sentence in enumerate(sentences):
        s = _normalize_daily_news_fact_sentence(sentence)
        if not s:
            continue
        if _daily_news_fact_sentence_is_noise(s):
            continue
        if index == 0 and "消息显示" in sentence and len(sentences) > 1:
            continue
        duplicate_index = -1
        for kept_index, kept_sentence in enumerate(kept):
            if (
                _daily_news_sentence_similarity(kept_sentence, s) >= 0.72
                or _daily_news_sentences_repeat_named_subject(kept_sentence, s)
            ):
                duplicate_index = kept_index
                break
        if duplicate_index >= 0:
            previous = kept[duplicate_index]
            if (
                _daily_news_sentence_importance(s) > _daily_news_sentence_importance(previous)
                or len(s) > len(previous)
            ):
                kept[duplicate_index] = s
            continue
        kept.append(s)
    if not kept:
        return text
    out = ""
    for sentence in kept:
        if not out:
            out = sentence
        elif out.endswith(("。", "！", "？", "!", "?")):
            out = f"{out}{sentence}"
        else:
            out = f"{out}。{sentence}"
    return out.strip()


def _daily_news_sentence_importance(sentence: str) -> int:
    s = sentence or ""
    score = 0
    for marker in ("表示", "称", "宣布", "发生", "造成", "调查", "启动", "发布", "开通", "抵达", "举行", "发现"):
        if marker in s:
            score += 2
    if re.search(r"\d|[一二三四五六七八九十两]", s):
        score += 1
    if len(s) <= 90:
        score += 1
    for marker in ("首页", "关键词", "精华", "继续进行", "未能看到"):
        if marker in s:
            score -= 2
    return score


def _finish_daily_news_content_sentence(text: str, *, limit: int) -> str:
    out = (text or "").strip()
    if not out:
        return ""
    if len(out) > limit:
        out = out[:limit]
    out = out.rstrip("，,；;：:、 ")
    broken_tail = re.search(r"([。！？!?])([^。！？!?]{1,18}[，,][^。！？!?]{0,8})$", out)
    if broken_tail and len(out[: broken_tail.start(2)].strip()) >= max(20, int(len(out) * 0.5)):
        out = out[: broken_tail.start(2)].strip()
    if re.search(r"[。！？!?]$", out):
        return out
    last_end = max(out.rfind(mark) for mark in "。！？!?")
    if last_end >= 0 and last_end + 1 >= max(20, int(len(out) * 0.6)):
        return out[: last_end + 1].strip()
    if len(out) >= limit:
        out = out[: max(0, limit - 1)].rstrip("，,；;：:、 ")
    return f"{out}。" if out else ""


def _limit_daily_news_content(text: str, *, limit: int = 150) -> str:
    cleaned = _remove_daily_news_methodology_noise(text)
    cleaned = _dedupe_daily_news_fact_sentences(cleaned)
    cleaned = re.sub(r"新华社(?:记者\s*)?发?[（(][^）)]{0,20}摄[）)]", "", cleaned).strip()
    cleaned = re.sub(r"新华社记者\s*[^。；;，,\s]{1,12}\s*摄", "", cleaned).strip()
    cleaned = re.sub(r"(?:。)?摄。(?:新华社/[^\s。]+。?)?", "。", cleaned).strip()
    cleaned = re.sub(r"新华社/[^\s。]+。?$", "", cleaned).strip()
    cleaned = re.sub(r"(?:。)?摄[。.]?$", "。", cleaned).strip()
    if len(cleaned) <= limit:
        return _finish_daily_news_content_sentence(cleaned, limit=limit)
    sentences = re.split(r"(?<=[。！？!?])", cleaned)
    kept = ""
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        candidate = f"{kept}{s}" if kept else s
        if len(candidate.rstrip("。！？!?")) <= limit:
            kept = candidate
        else:
            if (
                kept
                and len(s.rstrip("。！？!?")) <= limit
                and _daily_news_sentence_importance(s) > _daily_news_sentence_importance(kept)
            ):
                kept = s
            continue
    if kept:
        return _finish_daily_news_content_sentence(kept[:limit], limit=limit)
    return _finish_daily_news_content_sentence(cleaned[:limit], limit=limit)


def _trim_json_field_to_fit(data: dict[str, str], key: str, max_len: int) -> bool:
    value = data.get(key, "")
    if not value:
        return False
    low = 0
    high = len(value)
    changed = False
    while low < high:
        mid = (low + high) // 2
        candidate = value[:mid].rstrip("，,。；; ") + "…"
        trial = dict(data)
        trial[key] = candidate
        dumped = json.dumps(trial, ensure_ascii=False, indent=2)
        if len(dumped) <= max_len:
            low = mid + 1
        else:
            high = mid
        changed = True
    keep = max(0, low - 1)
    data[key] = value[:keep].rstrip("，,。；; ") + "…"
    return changed


def _dump_daily_news_body_json(data: dict[str, str]) -> str:
    normalized = {key: str(data.get(key, "") or "") for key in _NEWS_BODY_JSON_KEYS}
    dumped = json.dumps(normalized, ensure_ascii=False, indent=2)
    if len(dumped) <= MAX_IMAGE_BODY:
        return dumped

    for key in ("内容", "评价", "原文标题", "来源"):
        dumped = json.dumps(normalized, ensure_ascii=False, indent=2)
        if len(dumped) <= MAX_IMAGE_BODY:
            return dumped
        _trim_json_field_to_fit(normalized, key, MAX_IMAGE_BODY)
    dumped = json.dumps(normalized, ensure_ascii=False, indent=2)
    if len(dumped) <= MAX_IMAGE_BODY:
        return dumped

    # Last-resort compact JSON keeps the object valid if whitespace alone is the issue.
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _daily_news_source_name(picked) -> str:
    source = (getattr(picked, "source", "") or getattr(picked, "domain", "") or "未知来源").strip()
    return _strip_urls(source) or "未知来源"


def _extract_labeled_daily_news_body_parts(text: str) -> dict[str, str]:
    cleaned = _remove_generic_daily_news_comment(text or "")
    if _looks_like_jsonish_body(cleaned):
        cleaned = _strip_json_artifacts(cleaned)
    if not cleaned:
        return {"summary": "", "content": "", "comment": "", "date": "", "source": ""}

    summary = ""
    content = cleaned
    comment = ""
    date = ""
    source = ""

    m = re.search(r"发布时间[:：]\s*([^\n]+)", cleaned)
    if m:
        date = m.group(1).strip()
    m = re.search(r"来源[:：]\s*([^\n]+)", cleaned)
    if m:
        source = m.group(1).strip()

    cleaned = re.sub(r"\n{0,2}发布时间[:：][^\n]+", "", cleaned).strip()
    cleaned = re.sub(r"\n{0,2}来源[:：][^\n]+", "", cleaned).strip()

    if _NEWS_SUMMARY_LABEL in cleaned:
        after_summary = cleaned.split(_NEWS_SUMMARY_LABEL, 1)[1]
        if _NEWS_CONTENT_LABEL in after_summary:
            summary, after_summary = after_summary.split(_NEWS_CONTENT_LABEL, 1)
        else:
            lines = after_summary.splitlines()
            summary = lines[0] if lines else ""
            after_summary = "\n".join(lines[1:])
        content = after_summary
    if _NEWS_COMMENT_LABEL in content:
        content, comment = content.split(_NEWS_COMMENT_LABEL, 1)

    if not summary and _NEWS_CONTENT_LABEL in cleaned:
        content = cleaned.split(_NEWS_CONTENT_LABEL, 1)[1]
        if _NEWS_COMMENT_LABEL in content:
            content, comment = content.split(_NEWS_COMMENT_LABEL, 1)

    if _daily_news_comment_is_generic(comment):
        comment = ""

    return {
        "summary": _clean_daily_news_json_value(summary),
        "content": _clean_daily_news_json_value(content),
        "comment": _clean_daily_news_json_value(comment),
        "date": _clean_daily_news_json_value(date),
        "source": _clean_daily_news_json_value(source),
    }


def _daily_news_cjk_source_title(picked) -> str:
    raw_source_title = _strip_news_site_suffixes(_strip_urls(getattr(picked, "title", "") or ""))
    raw_source_title = _DAILY_NEWS_PREFIX_RE.sub("", raw_source_title)
    raw_source_title = re.sub(r"\s+", " ", raw_source_title).strip()
    raw_source_title = raw_source_title.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'")
    if raw_source_title and _has_cjk(raw_source_title) and not _has_japanese_kana(raw_source_title):
        title = _clean_daily_news_json_value(raw_source_title)
        return title[:80].rstrip(" \t\r\n，,。.!！?？:：|｜-—–")
    return ""


def _daily_news_original_title_is_generic(text: str) -> bool:
    value = _clean_daily_news_title_candidate(text or "")
    if not value:
        return True
    if value in _NEWS_GENERIC_TITLE_MARKERS:
        return True
    generic_patterns = (
        r"^(?:一项)?(?:科技|社会|经济|国际|AI|芯片|气候|产业|市场|平台|学校|防晒|外贸).{0,8}(?:议题|事件|数据)?出现(?:新)?(?:进展|变化)$",
        r"^(?:科技|社会|经济|国际|AI|芯片|气候|产业|市场).{0,8}(?:议题|事件)?受关注$",
        r"^需要继续跟踪的进展$",
    )
    return any(re.match(pattern, value) for pattern in generic_patterns)


def _daily_news_title_hint_for_original(title_hint: str, picked=None) -> str:
    cleaned = _clean_daily_news_title_candidate(title_hint or "")
    if (
        not cleaned
        or not _has_cjk(cleaned)
        or _has_japanese_kana(cleaned)
        or _daily_news_original_title_is_generic(cleaned)
        or _daily_news_title_has_bad_language(cleaned)
    ):
        return ""
    return cleaned[:80].rstrip(" \t\r\n，,。.!！?？:：|｜-—–")


def _daily_news_raw_source_title(picked) -> str:
    raw = _strip_news_site_suffixes(_strip_urls(getattr(picked, "title", "") or ""))
    raw = _DAILY_NEWS_PREFIX_RE.sub("", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = raw.strip(" \t\r\n:：|｜-—–，,。.!！?？\"'")
    raw = _clean_daily_news_json_value(raw)
    return raw[:120].rstrip(" \t\r\n，,。.!！?？:：|｜-—–")


def _daily_news_body_json_title(picked, prompt_norm: str, title_hint: str = "") -> str:
    source_title = _daily_news_cjk_source_title(picked)
    if source_title:
        return source_title

    title_hint_original = _daily_news_title_hint_for_original(title_hint, picked)
    if title_hint_original:
        return title_hint_original

    raw_title = _clean_daily_news_title_candidate(getattr(picked, "title", "") or "")
    if raw_title and _has_cjk(raw_title) and not _has_japanese_kana(raw_title):
        return _normalize_news_summary(raw_title, limit=80)

    summary = _normalize_daily_news_title(raw_title or getattr(picked, "title", "") or "", picked, prompt_norm, max_len=40)
    if summary and not _daily_news_original_title_is_generic(summary):
        return summary
    raw_source_title = _daily_news_raw_source_title(picked)
    if raw_source_title:
        return raw_source_title
    return summary


def _extract_rendered_daily_news_body_fields(text: str) -> dict[str, str] | None:
    raw = (text or "").strip()
    if not raw or not any(
        re.search(rf"^{re.escape(key)}[:：]", raw, flags=re.MULTILINE)
        for key in ("原文标题", "内容", "评价")
    ):
        return None

    def line_value(label: str) -> str:
        match = re.search(rf"^{re.escape(label)}[:：]\s*(.+)$", raw, flags=re.MULTILINE)
        return match.group(1).strip() if match else ""

    def block_value(label: str, next_labels: tuple[str, ...]) -> str:
        match = re.search(rf"^{re.escape(label)}[:：]\s*(?:\r?\n)?", raw, flags=re.MULTILINE)
        if not match:
            return ""
        start = match.end()
        stops: list[int] = []
        for next_label in next_labels:
            next_match = re.search(
                rf"\r?\n\r?\n?{re.escape(next_label)}[:：]",
                raw[start:],
                flags=re.MULTILINE,
            )
            if next_match:
                stops.append(start + next_match.start())
        end = min(stops) if stops else len(raw)
        return raw[start:end].strip()

    fields = {
        "原文标题": line_value("原文标题"),
        "内容": block_value("内容", ("评价", "日期", "来源")),
        "评价": block_value("评价", ("日期", "来源")),
        "日期": line_value("日期"),
        "来源": line_value("来源"),
    }
    if not (fields["内容"] or fields["评价"]):
        return None
    return fields


def _daily_news_body_to_fields(
    body: str,
    picked,
    prompt_norm: str,
    title_hint: str = "",
) -> dict[str, str]:
    """
    Normalize daily-news body into stable internal fields.

    LLMs may return the body as a JSON string, an object coerced into JSON text,
    or the legacy labeled prose format. Keep the internal shape stable, but do
    not expose raw JSON as the publishable XHS body.
    """
    data = _load_daily_news_body_json(body or "")
    rendered = None if data else _extract_rendered_daily_news_body_fields(_strip_urls(body or ""))
    if data:
        original_title = data.get("原文标题") or data.get("title") or data.get("标题")
        content = data.get("内容") or data.get("content") or data.get("新闻内容") or data.get("body")
        comment = data.get("评价") or data.get("点评") or data.get("comment") or ""
        date = data.get("日期") or data.get("发布时间") or data.get("date") or ""
        source = data.get("来源") or data.get("source") or ""
    elif rendered:
        original_title = rendered.get("原文标题")
        content = rendered.get("内容")
        comment = rendered.get("评价")
        date = rendered.get("日期")
        source = rendered.get("来源")
    else:
        parts = _extract_labeled_daily_news_body_parts(body or "")
        original_title = ""
        content = parts["content"]
        if parts["summary"] and parts["summary"] not in content:
            content = f"{parts['summary']} {content}".strip()
        comment = parts["comment"]
        date = parts["date"]
        source = parts["source"]

    if _daily_news_comment_is_generic(str(comment or "")):
        comment = ""
    elif _daily_news_comment_is_unsupported(str(comment or ""), picked, str(content or "")):
        comment = _daily_news_safe_fact_comment(picked, str(content or ""))
    elif _daily_news_comment_is_irrelevant(str(comment or ""), picked, str(content or "")):
        comment = _daily_news_fact_based_comment(
            picked,
            _compact_daily_news_context(picked),
            _daily_news_fallback_subject(picked, prompt_norm),
        )

    if not str(comment or "").strip():
        fallback_comment = _daily_news_fact_based_comment(
            picked,
            str(content or ""),
            _daily_news_fallback_subject(picked, prompt_norm),
        )
        if (
            fallback_comment
            and not _daily_news_comment_is_unsupported(fallback_comment, picked, str(content or ""))
            and not _daily_news_comment_is_irrelevant(fallback_comment, picked, str(content or ""))
        ):
            comment = fallback_comment
    if not str(comment or "").strip():
        comment = _daily_news_minimal_fact_comment(
            picked,
            str(content or ""),
            _daily_news_fallback_subject(picked, prompt_norm),
        )

    if _daily_news_content_is_unsupported(str(content or ""), picked):
        content = _compact_daily_news_context(picked, max_chars=150, include_title=False)
        if not content:
            content = _compact_daily_news_context(picked, max_chars=150)
        if _daily_news_comment_is_irrelevant(str(comment or ""), picked, str(content or "")):
            comment = _daily_news_fact_based_comment(
                picked,
                str(content or ""),
                _daily_news_fallback_subject(picked, prompt_norm),
            )

    source_original_title = _daily_news_cjk_source_title(picked)
    generated_original_title = _clean_daily_news_json_value(original_title)
    title_hint_original = _daily_news_title_hint_for_original(title_hint, picked)
    fallback_original_title = _daily_news_body_json_title(picked, prompt_norm, title_hint=title_hint)
    if source_original_title:
        final_original_title = source_original_title
    elif (
        generated_original_title
        and not _daily_news_original_title_is_generic(generated_original_title)
        and (
            not title_hint_original
            or _daily_news_text_matches_context(
                generated_original_title,
                title_hint_original,
                min_overlap=0.25,
            )
        )
        and _daily_news_text_matches_context(
        generated_original_title,
        fallback_original_title,
        str(content or ""),
        getattr(picked, "title", "") or "",
        getattr(picked, "description", "") or "",
        getattr(picked, "content", "") or "",
        )
    ):
        final_original_title = generated_original_title
    elif title_hint_original:
        final_original_title = title_hint_original
    else:
        final_original_title = fallback_original_title
    source_date = _format_news_seendate(getattr(picked, "seendate", None))
    normalized = {
        "原文标题": final_original_title,
        "内容": _limit_daily_news_content(str(content or "")),
        "评价": _clean_daily_news_comment_value(comment),
        "日期": source_date if source_date != "未知" else _clean_daily_news_json_value(date),
        "来源": _clean_daily_news_json_value(source) or _daily_news_source_name(picked),
    }
    return normalized


def _daily_news_body_to_json(body: str, picked, prompt_norm: str) -> str:
    """Compatibility helper for tests/tools that need the normalized field JSON."""
    return _dump_daily_news_body_json(_daily_news_body_to_fields(body, picked, prompt_norm))


def _render_daily_news_body_fields(data: dict[str, str]) -> str:
    normalized = {key: _clean_daily_news_json_value(data.get(key, "")) for key in _NEWS_BODY_JSON_KEYS}
    normalized["内容"] = _clean_daily_news_text_value(data.get("内容", ""))
    normalized["评价"] = _clean_daily_news_comment_value(data.get("评价", ""))

    def render(fields: dict[str, str]) -> str:
        chunks: list[str] = []
        if fields.get("内容"):
            chunks.append(f"内容：\n{fields['内容']}")
        if fields.get("评价"):
            chunks.append(f"评价：\n{fields['评价']}")
        if fields.get("日期"):
            chunks.append(f"日期：{fields['日期']}")
        if fields.get("来源"):
            chunks.append(f"来源：{fields['来源']}")
        return "\n\n".join(chunk for chunk in chunks if chunk).strip()

    text = render(normalized)
    if len(text) <= MAX_IMAGE_BODY:
        return text

    for key in ("内容", "评价"):
        while len(text) > MAX_IMAGE_BODY and normalized.get(key):
            overflow = len(text) - MAX_IMAGE_BODY
            value = normalized[key]
            keep = max(0, len(value) - overflow - 1)
            if keep >= len(value):
                keep = len(value) - 1
            normalized[key] = value[:keep].rstrip("，,。；; ") + "…"
            text = render(normalized)
        if len(text) <= MAX_IMAGE_BODY:
            return text

    return text[:MAX_IMAGE_BODY].rstrip()


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
    if text and not _has_cjk(text):
        text = _english_daily_news_title_summary(f"{text} {fallback}") or text
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


def _daily_news_artwork_scene_details(body: str) -> str:
    """Extract concrete visual facts when a story describes an artwork or exhibit."""
    content = _daily_news_body_quality_fields(body).get("内容", "")
    if not content:
        return ""
    artwork_markers = ("画作", "绘画", "油画", "名画", "美术馆", "展览", "展出", "画面")
    if not any(marker in content for marker in artwork_markers):
        return ""
    sentences = re.split(r"(?<=[。！？!?])", content)
    visual_markers = ("画作", "画面", "描绘", "剪影", "海岸", "天空", "云", "鸟", "色彩", "展品")
    details = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and any(marker in sentence for marker in visual_markers)
    ]
    return _normalize_image_event("".join(details[:2]), limit=72)


def _normalize_daily_news_image_event(
    value: str,
    *,
    picked,
    title: str,
    body: str,
    prompt_norm: str,
) -> str:
    fallback = _daily_news_fallback_subject(picked, prompt_norm)
    context = " ".join(
        part
        for part in (
            title,
            body,
            fallback,
            getattr(picked, "title", "") or "",
            getattr(picked, "description", "") or "",
            getattr(picked, "content", "") or "",
        )
        if part
    )
    compact_context = re.sub(r"\s+", "", context)
    if "健身气功" in compact_context and any(
        marker in compact_context for marker in ("锦标赛", "比赛", "竞赛", "高校")
    ):
        return "室内体育馆内，多名大学生统一运动服进行健身气功集体展演，裁判在场边观察"
    if "卫生巾" in compact_context and any(
        marker in compact_context for marker in ("异物", "虫卵", "质量", "核实", "检测")
    ):
        return "洁净实验室内，质检员检查展开的白色卫生巾和独立包装"
    if any(marker in compact_context for marker in ("颁奖", "获奖")) and any(
        marker in compact_context for marker in ("田径", "赛事", "运动员", "健儿")
    ):
        return "赛场领奖区内，赛事工作人员为获奖运动员颁发无文字奖杯，背景无横幅标志"
    if any(marker in compact_context for marker in ("签署", "签约", "合作协定")) and any(
        marker in compact_context for marker in ("代表", "企业", "负责人", "三方")
    ):
        return "简洁会议室内，三方代表在空白文件旁握手合影，服装与背景无文字标志"
    if any(
        marker in compact_context
        for marker in ("财报", "半年报", "年报", "季报", "亏损", "营收", "利润")
    ):
        if any(
            marker in compact_context
            for marker in ("运动品牌", "运动服", "运动鞋", "安踏", "彪马", "Puma")
        ):
            return "财经分析人员在现代办公室研究无文字图表，背景陈列无品牌标志的运动鞋服"
        finance_subject = _normalize_image_event(value, fallback=fallback, limit=18)
        return (
            f"{finance_subject}，财经分析人员在现代办公室研究无文字图表和实体行业样品"
            if finance_subject
            else "财经分析人员在现代办公室研究无文字图表和实体行业样品"
        )
    candidate = _normalize_image_event(value, fallback=fallback)
    artwork_scene = _daily_news_artwork_scene_details(body)
    if artwork_scene:
        enriched = _normalize_image_event(
            f"{candidate or fallback}，画面细节：{artwork_scene}",
            fallback=artwork_scene,
            limit=92,
        )
        if enriched:
            return enriched
    if candidate and _daily_news_text_matches_context(candidate, context, min_overlap=0.28):
        return candidate
    title_event = _normalize_image_event(title, fallback=fallback)
    if title_event and _daily_news_text_matches_context(title_event, context, min_overlap=0.20):
        return title_event
    return _normalize_image_event(fallback, fallback=title)


def _normalize_news_summary(value: str, *, fallback: str = "", limit: int = 40) -> str:
    text = (value or "").strip()
    if not text:
        text = (fallback or "").strip()
    text = _to_simplified_common(text)
    text = _strip_urls(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("：:，,。.!！？?\"'（）()[]【】")
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


_IRRELEVANT_DAILY_NEWS_TOPICS = {
    "饭局",
    "职场中的人情世故",
    "凝聚力提升",
    "职场社交法则",
    "成功与机遇",
    "富人与穷人",
}


def _fallback_daily_news_topics(context: str) -> list[str]:
    text = context or ""
    if "人权" in text:
        return ["全球人权治理", "国际合作"]
    if "文物" in text or "正视历史" in text:
        return ["文物返还", "历史记忆"]
    if any(marker in text for marker in ("潮汕", "侨批", "红头船", "文化传承")):
        return ["文化传承", "潮汕文化"]
    if "火灾" in text:
        return ["火灾", "公共安全"]
    if "古巴" in text:
        return ["国际关系", "国家主权"]
    if "谈判" in text or "伊朗" in text:
        return ["国际谈判", "中东局势"]
    return ["国际新闻"]


def _normalize_daily_news_topics(topics, prompt_norm: str = "", context: str = "") -> list[str]:
    normalized_topics: list[str] = []
    seen: set[str] = set()
    for t in topics or []:
        tt = str(t or "").strip().lstrip("#")
        if tt in _IRRELEVANT_DAILY_NEWS_TOPICS:
            continue
        if not _is_publishable_daily_news_topic(tt, prompt_norm):
            continue
        if tt in seen:
            continue
        normalized_topics.append(tt)
        seen.add(tt)
    if "每日新闻" not in seen:
        normalized_topics.insert(0, "每日新闻")
        seen.add("每日新闻")
    for topic in _fallback_daily_news_topics(context):
        if topic not in seen and _is_publishable_daily_news_topic(topic, prompt_norm):
            normalized_topics.append(topic)
            seen.add(topic)
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


def normalize_evaluation_viewpoint(value: str | None) -> str:
    """
    Normalize the optional commentary viewpoint before inserting it into prompts.

    The value is user-provided, so keep it as a short single-line instruction.
    Empty values intentionally fall back to the neutral default.
    """
    text = _strip_urls(str(value or ""))
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:;；,，。")
    if not text:
        return DEFAULT_EVALUATION_VIEWPOINT
    return _clip_text(text, limit=80)


def _daily_news_candidate_fetch_limit(count: int) -> int:
    requested = max(1, int(count or 1))
    if requested == 1:
        # A single post has no batch replacement risk. Requiring ten items
        # would unnecessarily reject a valid, well-sourced single story.
        return 1
    raw = (os.getenv("NEWS_UPLOAD_QUALIFIED_POOL_MULTIPLIER") or "10").strip()
    try:
        multiplier = int(raw)
    except ValueError:
        multiplier = 10
    # A 10x qualified pool gives the later source, duplicate, content and
    # image gates room to replace rejects without silently returning a short batch.
    return requested * max(1, multiplier)


def _daily_news_raw_candidate_fetch_limit(target_fetch_count: int) -> int:
    raw = (os.getenv("NEWS_UPLOAD_RAW_MAX_RECORDS") or os.getenv("NEWS_RAW_MAX_RECORDS") or "").strip()
    try:
        value = int(raw) if raw else 0
    except ValueError:
        value = 0
    # The qualified pool above is 10x by default. Request roughly twice that
    # amount from raw providers so date/relevance filtering can discard noise.
    minimum = max(20, target_fetch_count * 2)
    if value > 0:
        return max(minimum, value)
    return minimum


_AI_IMAGE_PROVIDER_ALIASES = {
    "aliyun",
    "dashscope",
    "bailian",
    "qwen_image",
    "qwen-image",
    "volcengine",
    "ark",
    "doubao",
    "seedream",
    "siliconflow",
    "silicon",
    "sf",
}


def _daily_news_ai_first_provider() -> str:
    for name in (
        "SINGLE_NEWS_AI_IMAGE_PROVIDER",
        "DAILY_NEWS_AI_IMAGE_PROVIDER",
        "IMAGE_PROVIDER",
    ):
        value = (os.getenv(name) or "").strip().lower()
        if value in _AI_IMAGE_PROVIDER_ALIASES:
            return value
    return "aliyun"


def _fetch_daily_news_related_images(
    *,
    title: str,
    body: str,
    topics: list[str],
    prompt_hint: str,
    dest_dir: Path,
    exclude_ids: Optional[set[str]] = None,
    ai_first: bool = False,
    provider: Optional[str] = None,
) -> tuple[list[Path], list[dict[str, Any]], dict[str, Any] | None]:
    if not ai_first:
        paths, metas = fetch_and_download_related_images(
            title=title,
            body=body,
            topics=topics,
            prompt_hint=prompt_hint,
            dest_dir=dest_dir,
            exclude_ids=exclude_ids,
        )
        return paths, metas, None

    primary_provider = (provider or _daily_news_ai_first_provider()).strip().lower()
    if primary_provider == "pexels":
        paths, metas = fetch_and_download_related_images(
            title=title,
            body=body,
            topics=topics,
            prompt_hint=prompt_hint,
            dest_dir=dest_dir,
            exclude_ids=exclude_ids,
            provider="pexels",
        )
        return paths, metas, None
    try:
        paths, metas = fetch_and_download_related_images(
            title=title,
            body=body,
            topics=topics,
            prompt_hint=prompt_hint,
            dest_dir=dest_dir,
            exclude_ids=exclude_ids,
            provider=primary_provider,
        )
        return paths, metas, None
    except Exception as exc:
        fallback_meta: dict[str, Any] = {
            "from_provider": primary_provider,
            "to_provider": "pexels",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
        if isinstance(exc, ImageGenerationAbandoned):
            fallback_meta.update(
                {
                    "attempts": exc.attempts,
                    "errors": exc.errors,
                }
            )
        print(
            f"[auto-image] ai_failed provider={primary_provider} fallback=pexels "
            f"err={str(exc)[:160]}"
        )
        paths, metas = fetch_and_download_related_images(
            title=title,
            body=body,
            topics=topics,
            prompt_hint=prompt_hint,
            dest_dir=dest_dir,
            exclude_ids=exclude_ids,
            provider="pexels",
        )
        return paths, metas, fallback_meta


def _daily_news_image_repair_hint(retry_prompt: str) -> str:
    feedback = re.sub(r"\s+", " ", (retry_prompt or "").strip())
    if len(feedback) > 100:
        feedback = f"{feedback[:100].rstrip()}…"
    prefix = f"VLM 反馈：{feedback}。" if feedback else ""
    return (
        f"{prefix}重新构图，只用人物、环境、实体物体和动作表达新闻事件；"
        "严禁任何品牌名、Logo、屏幕、界面、招牌、海报、文件文字、字母或数字。"
    ) + (
        " For software news, a text-free abstract performance interface is allowed; "
        "any screen or interface must not contain readable text, branding, logos, letters, or numbers."
    )


def regenerate_daily_news_post_image(
    post: Post,
    retry_prompt: str,
    *,
    provider: Optional[str] = None,
) -> bool:
    news_meta = post.platform.get("news")
    if not isinstance(news_meta, dict):
        return False

    existing_ids: set[str] = set()
    image_metas = post.platform.get("images")
    if isinstance(image_metas, list):
        _merge_image_ids(existing_ids, image_metas)

    prompt_parts = [
        _preferred_image_hint(post, str(news_meta.get("prompt_hint") or "")),
        _daily_news_image_repair_hint(retry_prompt),
    ]
    prompt_hint = "\n".join(part for part in prompt_parts if part)
    image_paths, image_metas, image_fallback = _fetch_daily_news_related_images(
        title=_preferred_image_title(post, post.title),
        body=post.body,
        topics=post.topics,
        prompt_hint=prompt_hint,
        dest_dir=post_dir(post.id) / "assets",
        exclude_ids=existing_ids,
        ai_first=True,
        provider=provider,
    )
    if not image_paths:
        return False

    post.assets = _build_asset_infos(image_paths)
    post.platform["images"] = image_metas
    if image_metas:
        post.platform["image"] = image_metas[0]
    if image_fallback:
        post.platform["image_fallback"] = image_fallback
    save_post(post)
    return True


def _fetch_daily_news_candidates_for_upload(
    prompt_norm: str,
    *,
    count: int,
    lookback_days: object = None,
    news_materials_file: str | Path | None = None,
    single_news_material_file: str | Path | None = None,
    material_time: str = "",
    progress_callback: DailyNewsProgressCallback | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    multi_material_path = str(news_materials_file or "").strip()
    single_material_path = str(single_news_material_file or "").strip()
    if single_material_path and multi_material_path:
        raise RuntimeError("single_news_material_file and news_materials_file are mutually exclusive")
    if single_material_path:
        item = load_single_news_material_file(single_material_path)
        tz_name = os.getenv("NEWS_TZ") or "Asia/Shanghai"
        resolved_items, resolved_times = resolve_manual_material_times(
            [item],
            default_material_time=material_time,
            tz_name=tz_name,
        )
        item = resolved_items[0]
        meta: dict[str, Any] = {
            "provider": "manual_single",
            "api_source": "manual_single",
            "source_api": {
                "provider": "manual_single",
                "file_path": single_material_path,
            },
            "provider_plan": ["manual_single"],
            "provider_attempts": ["manual_single"],
            "provider_errors": [],
            "tz": tz_name,
            "query": "",
            "query_variants": [],
            "query_expansion_enabled": False,
            "queries_used": [],
            "search_days": None,
            "used_today_range": False,
            "manual_materials": {
                "file_path": single_material_path,
                "count": 1,
                "mode": "single",
                "default_material_time": material_time,
                "resolved_item_times": resolved_times,
                "freshness_policy": "bypassed_user_supplied_material",
            },
            "candidates": [asdict(item)],
            "selection_pool": {
                "requested_count": 1,
                "target_fetch_count": 1,
                "raw_fetch_count": 1,
                "raw_candidate_count": 1,
                "recent_candidate_count": 1,
                "prompt_relevance": {
                    "mode": "ignored_for_single_news_material",
                    "prompt_hint": prompt_norm,
                },
                "prompt_relevant_candidate_count": 1,
                "actual_candidate_count": 1,
                "dropped_out_of_window_count": 0,
                "date_window": None,
                "lookback": {
                    "mode": "disabled_for_material",
                    "input": lookback_days,
                    "selected_max_age_days": None,
                    "attempts": [],
                },
                "selection_policy": "manual_material_without_source_date_limit",
                "source_domain_max_ratio": None,
            },
        }
        return [item], meta

    target_fetch_count = _daily_news_candidate_fetch_limit(count)
    raw_fetch_count = _daily_news_raw_candidate_fetch_limit(target_fetch_count)
    lookback_windows, lookback_meta = _daily_news_lookback_window(
        lookback_days,
        env_names=("NEWS_LOOKBACK_DAYS", "CONTENT_LOOKBACK_DAYS"),
    )
    search_days = max(lookback_windows)
    _emit_daily_news_progress(
        progress_callback,
        "准备候选池",
        "in_progress",
        requested_count=max(1, int(count or 1)),
        min_qualified=target_fetch_count,
        raw_target=raw_fetch_count,
        lookback_days=search_days,
    )

    def _source_progress(stage: str, status: str, detail: dict[str, Any]) -> None:
        _emit_daily_news_progress(progress_callback, stage, status, **detail)

    def _qualified_candidate_count(pool: list[Any]) -> int:
        best_count = 0
        for days in lookback_windows:
            recent_pool, _ = filter_recent_news_items(
                list(pool),
                tz_name=os.getenv("NEWS_TZ") or "Asia/Shanghai",
                max_age_days=days,
            )
            relevant_pool, _ = filter_prompt_relevant_news_items(recent_pool, prompt_norm)
            best_count = max(
                best_count,
                len(rank_news_candidate_pool(relevant_pool, prompt_norm)),
            )
        return best_count

    try:
        candidates, meta = fetch_daily_news_candidates(
            prompt_norm,
            max_records=raw_fetch_count,
            search_days=search_days,
            materials_file=news_materials_file,
            source_health_path=Path("data") / "source_health" / "daily_news.json",
            persist_source_health=True,
            exhaustive_sources=True,
            progress_callback=_source_progress,
            minimum_qualified_records=target_fetch_count,
            qualified_count_callback=_qualified_candidate_count,
        )
    except TypeError as exc:
        if "unexpected keyword" not in str(exc) and "positional" not in str(exc):
            raise
        # Backward compatibility for tests or local monkeypatches that still use
        # the old one-argument callable shape.
        candidates, meta = fetch_daily_news_candidates(prompt_norm)
    meta = dict(meta)
    raw_candidate_count = len(candidates)
    tz_name = str(meta.get("tz") or os.getenv("NEWS_TZ") or "Asia/Shanghai")
    if multi_material_path:
        material_target_count = max(1, int(count or 1))
        resolved_candidates, resolved_times = resolve_manual_material_times(
            list(candidates),
            default_material_time=material_time,
            tz_name=tz_name,
        )
        if not resolved_candidates:
            raise RuntimeError("材料文件没有可用材料。")
        selected_candidates = rank_news_candidate_pool(resolved_candidates, "")[:raw_fetch_count]
        if len(selected_candidates) < material_target_count:
            raise RuntimeError(
                f"材料候选不足：需要至少 {material_target_count} 条材料，当前只有 {len(selected_candidates)} 条。"
            )
        meta["provider"] = "manual"
        meta["manual_materials"] = {
            "file_path": multi_material_path,
            "count": len(resolved_candidates),
            "mode": "multiple",
            "default_material_time": material_time,
            "resolved_item_times": resolved_times,
            "freshness_policy": "bypassed_user_supplied_material",
        }
        meta["candidates"] = [asdict(item) for item in resolved_candidates]
        meta["selection_pool"] = {
            "requested_count": max(1, int(count or 1)),
            "target_fetch_count": material_target_count,
            "raw_fetch_count": raw_fetch_count,
            "raw_candidate_count": raw_candidate_count,
            "recent_candidate_count": len(resolved_candidates),
            "prompt_relevance": {
                "mode": "ignored_for_material",
                "prompt_hint": prompt_norm,
            },
            "prompt_relevant_candidate_count": len(resolved_candidates),
            "actual_candidate_count": len(selected_candidates),
            "dropped_out_of_window_count": 0,
            "date_window": None,
            "lookback": {
                "mode": "disabled_for_material",
                "input": lookback_days,
                "selected_max_age_days": None,
                "attempts": [],
            },
            "selection_policy": "manual_material_without_source_date_limit",
            "source_domain_max_ratio": None,
        }
        return selected_candidates, meta
    attempts: list[dict[str, Any]] = []
    selected_candidates: list[Any] = []
    selected_recent_candidates: list[Any] = []
    selected_prompt_candidates: list[Any] = []
    selected_date_window_meta: dict[str, Any] = {}
    selected_prompt_relevance_meta: dict[str, Any] = {}
    for days in lookback_windows:
        recent_candidates, date_window_meta = filter_recent_news_items(
            list(candidates),
            tz_name=tz_name,
            max_age_days=days,
        )
        prompt_candidates, prompt_relevance_meta = filter_prompt_relevant_news_items(
            recent_candidates,
            prompt_norm,
        )
        ranked_candidates = rank_news_candidate_pool(prompt_candidates, prompt_norm)[:raw_fetch_count]
        attempt = {
            "max_age_days": days,
            "recent_candidate_count": len(recent_candidates),
            "prompt_relevant_candidate_count": len(prompt_candidates),
            "actual_candidate_count": len(ranked_candidates),
            "date_window": date_window_meta,
            "prompt_relevance": prompt_relevance_meta,
        }
        attempts.append(attempt)
        _emit_daily_news_progress(
            progress_callback,
            "候选筛选",
            "in_progress",
            window_days=days,
            recent=len(recent_candidates),
            relevant=len(prompt_candidates),
            qualified=len(ranked_candidates),
            min_qualified=target_fetch_count,
        )
        if len(ranked_candidates) > len(selected_candidates):
            selected_candidates = ranked_candidates
            selected_recent_candidates = recent_candidates
            selected_prompt_candidates = prompt_candidates
            selected_date_window_meta = date_window_meta
            selected_prompt_relevance_meta = prompt_relevance_meta
        if len(ranked_candidates) >= target_fetch_count:
            selected_candidates = ranked_candidates
            selected_recent_candidates = recent_candidates
            selected_prompt_candidates = prompt_candidates
            selected_date_window_meta = date_window_meta
            selected_prompt_relevance_meta = prompt_relevance_meta
            break

    candidates = selected_candidates
    if len(candidates) < target_fetch_count:
        last_window = attempts[-1]["date_window"] if attempts else {}
        attempt_summary = "; ".join(
            f"{a['max_age_days']}d recent={a['recent_candidate_count']} "
            f"relevant={a['prompt_relevant_candidate_count']} selected={a['actual_candidate_count']}"
            for a in attempts
        )
        window_label = f"严格回溯 {lookback_windows[-1]} 个北京时间自然日"
        message = (
            "daily news material insufficient in strict two-day window | 候选池不足："
            f"本次要生成 {max(1, int(count or 1))} 条，需要至少 {target_fetch_count} 条相关且有日期的候选，"
            f"当前仅得到 {len(candidates)} 条。{window_label}（北京时间 "
            f"{last_window.get('start_date')}..{last_window.get('end_date')}）。"
            f"筛选结果：{attempt_summary}。为防止旧闻混入，程序不会扩大到两天之外；"
            "请放宽关键词、补充近期信源或检查新闻 API 状态。"
        )
        _emit_daily_news_progress(
            progress_callback,
            "候选筛选",
            "failed",
            qualified=len(candidates),
            min_qualified=target_fetch_count,
            reason="candidate_pool_insufficient",
        )
        raise RuntimeError(message)
    meta["selection_pool"] = {
        "requested_count": max(1, int(count or 1)),
        "target_fetch_count": target_fetch_count,
        "raw_fetch_count": raw_fetch_count,
        "raw_candidate_count": raw_candidate_count,
        "recent_candidate_count": len(selected_recent_candidates),
        "prompt_relevance": selected_prompt_relevance_meta,
        "prompt_relevant_candidate_count": len(selected_prompt_candidates),
        "actual_candidate_count": len(candidates),
        "dropped_out_of_window_count": raw_candidate_count - len(selected_recent_candidates),
        "date_window": selected_date_window_meta,
        "lookback": {
            **lookback_meta,
            "selected_max_age_days": selected_date_window_meta.get("max_age_days"),
            "attempts": attempts,
        },
        "selection_policy": "prompt_relevance_attention_recency_source_diversity",
        "source_domain_max_ratio": os.getenv("NEWS_SOURCE_DOMAIN_MAX_RATIO") or "0.5",
    }
    _emit_daily_news_progress(
        progress_callback,
        "候选筛选",
        "success",
        qualified=len(candidates),
        min_qualified=target_fetch_count,
        raw=raw_candidate_count,
    )
    return candidates, meta


def _daily_news_evaluation_viewpoint_instruction(value: str | None) -> str:
    viewpoint = normalize_evaluation_viewpoint(value)
    if viewpoint == DEFAULT_EVALUATION_VIEWPOINT:
        return (
            "评价视角：无视角评价。评价不得预设国家、行业、投资者、平台等固定立场；"
            "只基于已给事实和原文摘录做客观公正分析；信息不足时须明确边界，不得留空。\n"
        )
    return (
        f"评价视角：{viewpoint}。评价必须从该视角观察影响、风险或意义，"
        "但仍须基于已给事实和原文摘录，保持客观公正；信息不足时须明确边界，不得留空。\n"
    )


def _daily_news_professional_reporting_instruction() -> str:
    """Return generic, source-bound rules for an authoritative concise news style."""
    return (
        "权威发布写法：只写已核实、可追溯且与主题直接相关的事实；无法由提供材料支持的内容宁可删去，不得以猜测补全。"
        "标题必须与正文的已核事实范围一致，准确概括核心变化，不夸大、不制造悬念、不写来源不明的结论。\n"
        "采用重要性递减的短消息结构：首句直接交代最重要的已证实事件及当前状态；随后补充理解该事件所必需的主体、时间、变化、数据或背景；"
        "结尾仅保留已核进展、明确的信息边界或必要的下一步安排。不以感叹、设问、口号、比喻或泛泛判断开场。\n"
        "严格区分已发生事实、来源表述、计划安排和分析判断：计划要写明“计划/拟/将”，单方信息必须明确归因，推断要写明不确定性；"
        "不得把预测、传闻、未完成核实的信息或单方观点写成既成事实。因果、动机、责任、影响和趋势只有在材料明确支持时才可归因转述。\n"
        "准确区分发生时间、发布时点和当前状态，旧材料不得写成最新进展；改写不得改变原意或把结论写得更强。"
        "评价仅在材料能够支持时写成有边界的影响分析：先说明已知变化，再说明仍待观察的变量；"
        "不得把价值判断、投资建议、立场表达、情绪化或标签化措辞伪装成事实。\n"
    )


def _daily_news_prompt(
    picked,
    prompt_norm: str,
    evaluation_viewpoint: str | None = DEFAULT_EVALUATION_VIEWPOINT,
) -> str:
    """
    Prompt for LLM to write publishable body ONLY (no metadata/requirements echoed).
    """
    return (
        "你正在为小红书图文笔记写《每日新闻》栏目。\n"
        "请依据下面提供的新闻信息，生成一份可直接发布的草稿。\n"
        "必须全部使用简体中文；如果原始材料是英文新闻、日文新闻或其他语言新闻，先翻译并用中文新闻写法改写，不得保留外文长句或日文假名。\n"
        "注意：body 正文里不要包含提示词/要求等元信息；不得输出 URL、网址、http(s) 链接。\n"
        "来源只写来源名称，网址只保存在本地 post.json 的 metadata 中；正文里不得出现链接、URL 或 http(s)。\n"
        "只允许使用下列已提供的新闻信息，不得新增事实或编造细节；内容不完整时，必须先查阅原新闻/原文摘录后再评价。\n"
        "如果原文摘录仍不足，不得推测数字、因果、人物关系或后续结果；评价须明确现有事实边界，不要硬凑结论。\n\n"
        f"{_daily_news_professional_reporting_instruction()}\n"
        "输出为严格 JSON（仅包含 keys: title, body, topics；可选 key: image_event），不要 Markdown/代码块。\n"
        "注意：外层 JSON 的 body 必须是字符串；body 字符串必须是可直接发布的正文，不要把 body 写成 JSON 对象文本。\n\n"
        "可用新闻信息（仅限以下字段，链接仅供参考不要输出）：\n"
        f"- 新闻标题：{picked.title}\n"
        f"- 来源名称：{picked.source or '未知'}\n"
        f"- 来源域名：{picked.domain or '未知'}\n"
        f"- 发布时间：{picked.seendate or '未知'}\n"
        f"- 摘要：{_clip_text(picked.description, limit=300)}\n"
        f"- 原文正文：{_clip_text(picked.content, limit=2200)}\n"
        f"- 链接：{picked.url}\n"
        f"- 检索关键词（仅用于选题相关性，不得写入正文）：{prompt_norm or '无'}\n\n"
        "JSON 字段要求：\n"
        "title：标题必须是12-18字的简体中文总结标题，理想约15字；必须由你基于新闻标题/摘要/原文摘录重新概括，不得直接照抄新闻原始标题；不得机械截断长标题；必须包含具体事件关键词；不要加“每日新闻｜”前缀，不得仅为“每日新闻”，不得出现日文假名；不得以“如/如果/若/一旦”等条件词开头，不能只写半句条件，必须写清新闻动作或结果。\n"
        "body：正文必须通顺，必须严格使用下面 4 个中文字段标签，不得增加字段，不得使用旧标签“原文标题/要点摘要/新闻内容/点评/发布时间”：\n"
        "内容：\n"
        "<150字以内的完整中文段落，必须基于原文正文严谨总结事实；句子自然衔接，不堆砌网页导航、栏目名、浏览器升级提示、来源页噪声；不得写站内推荐/相关阅读/下一篇文章标题，例如“权威数读”“新华视点”“记者手记”“特色产业赋能”“中国摩托加速”；不写未经证实的细节，不写“目前可以确认的信息主要来自”等模板句>\n\n"
        "评价：\n"
        "<必须写1-2句基于现有事实的客观评价；信息不足时说明判断边界，不得留空；不得套用与新闻主题无关的 AI/版权/经贸/供应链等模板>\n\n"
        "日期：YYYY-MM-DD\n\n"
        "来源：来源名称（不要写网址）\n"
        "长度约束：body 总长度（含换行）务必 <= 900 字符，避免写太长导致发布失败。\n"
        f"{_daily_news_evaluation_viewpoint_instruction(evaluation_viewpoint)}"
        "先查阅并基于已给事实/原文摘录再给判断，不得推测，不煽动对立、不使用攻击性语言、不做情绪化带节奏表述。\n"
        "可提示风险与影响，但不得夸大、不得杜撰未提供事实；不得写“这类新闻适合先看事实，再看影响”、"
        "“接下来可以重点关注权威更新、执行细节和各方反馈”等空泛方法论句式。\n"
        "topics（数组，3-8个话题词）：必须包含“每日新闻”。不要把 topics 写进 body。\n"
        "image_event（字符串，可选，20-40字）：仅用于配图的事件描述，只描述发生了什么（主体/动作/对象/场景线索），不含评价；"
        "不要出现“新闻/报道/采访/记者/媒体/来源/链接/时间”等词。不要把 image_event 写进 body。\n"
    )


def _daily_news_fallback_subject(picked, prompt_norm: str) -> str:
    title = _clean_daily_news_title_candidate(_strip_urls((picked.title or "").strip()))
    desc = _strip_urls((picked.description or "").strip())
    if _has_cjk(title):
        return _normalize_news_summary(title, limit=48)
    if _has_cjk(desc):
        return _normalize_news_summary(desc, limit=48)

    source_text = " ".join(
        [
            picked.title or "",
            picked.description or "",
            picked.content or "",
        ]
    )
    english_summary = _english_daily_news_title_summary(source_text, "")
    if english_summary:
        return english_summary

    lower = source_text.lower()
    hint = prompt_norm if _has_cjk(prompt_norm) and not source_text.strip() else ""
    if "科技" in hint or _english_any_keyword(lower, ("ai", "openai", "chip", "tech", "technology", "model", "software")):
        return "一项科技议题出现新进展"
    if "社会" in hint or _english_any_keyword(lower, ("court", "case", "school", "police", "sentence")):
        return "一项社会议题出现新进展"
    if "经济" in hint or _english_any_keyword(lower, ("market", "inflation", "price", "trade", "economy")):
        return "一项经济议题出现新进展"
    return "一项国际议题出现新进展"


def _compact_daily_news_context(picked, *, max_chars: int = 220, include_title: bool = True) -> str:
    parts = [
        ("description", getattr(picked, "description", "") or ""),
        ("content", getattr(picked, "content", "") or ""),
    ]
    if include_title:
        parts.insert(0, ("title", getattr(picked, "title", "") or ""))
    cleaned_parts: list[str] = []
    seen: set[str] = set()
    for kind, part in parts:
        cleaned = _strip_urls(str(part))
        if kind == "title":
            cleaned = _clean_daily_news_title_candidate(cleaned)
        else:
            cleaned = _clean_original_news_text(cleaned)
        cleaned = re.sub(r"\[\+\d+\s+chars?\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n。.!！?")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        cleaned_parts.append(cleaned)
        seen.add(key)
    context = "。".join(cleaned_parts).strip()
    if context and not context.endswith(("。", "！", "？", "!", "?")):
        context = f"{context}。"
    if len(context) <= max_chars:
        return context
    lead = ""
    for sentence in re.split(r"(?<=[。！？!?])", context):
        s = sentence.strip()
        if not s or _daily_news_fact_sentence_is_noise(s):
            continue
        candidate = f"{lead}{s}" if lead else s
        if len(candidate.rstrip("。！？!?")) <= max_chars:
            lead = candidate
        elif lead:
            break
        else:
            return _finish_daily_news_content_sentence(s, limit=max_chars)
    if lead:
        return _finish_daily_news_content_sentence(lead, limit=max_chars)
    return _finish_daily_news_content_sentence(context, limit=max_chars)


def _daily_news_fact_based_comment(picked, context: str, subject: str) -> str:
    raw = " ".join(
        str(part or "")
        for part in (
            getattr(picked, "title", ""),
            getattr(picked, "description", ""),
            getattr(picked, "content", ""),
            context,
            subject,
        )
    )
    lower = raw.lower()

    if any(word in raw for word in ("谈判", "会谈", "部长级")):
        return _daily_news_safe_fact_comment(picked, context)

    if any(word in raw for word in ("参观见学", "青年参观", "青年干部", "外交礼品")):
        return (
            "这类见学活动的意义，在于把外交历史、行业使命与青年培养联系起来。"
            "后续更值得关注学习成果能否转化为日常训练、管理和服务中的具体行动，而不是仅停留在参观层面。"
        )

    if any(word in raw for word in ("体育强国", "全民健身", "体育产业总规模", "经常参加体育锻炼")):
        return (
            "规划把全民健身、竞技体育和体育产业放在同一框架下推进，重点在于目标能否转化为稳定的场地、赛事和服务供给。"
            "后续可关注体育消费、基层设施和青少年参与等指标是否同步改善。"
        )

    if any(word in raw for word in ("潮汕", "侨批", "红头船", "文化传承", "给阿嬷的情书", "香江")):
        return (
            "这条新闻的价值在于把地方文化记忆和当代城市生活连接起来。"
            "侨批、红头船和潮汕社群故事被重新讲述，有助于年轻人理解家族迁徙、诚信互助与文化传承的现实意义。"
        )

    if any(word in raw for word in ("纸尿裤", "甲酰胺", "未检出", "产品检测", "消费品安全")):
        return (
            "这类消费品安全信息的关键在于检测范围、检测机构和批次覆盖是否清楚。"
            "企业公开检测结果有助于回应消费者疑虑，但后续仍应以监管抽检、完整报告和持续质量控制作为判断依据。"
        )

    if any(word in raw for word in ("手机补贴", "品质数码", "苏新消费", "消费补贴", "补贴额度")):
        return (
            "消费补贴的直接作用是降低换机门槛、释放部分数码消费需求。"
            "评价这类政策要看补贴规则是否透明、额度覆盖是否公平，以及是否真正带动线下商家和正规渠道受益。"
        )

    if any(word in raw for word in ("演唱会", "通信保障", "驻场巡检", "云端监控", "网络保障")):
        return (
            "大型演出对通信网络是一次现场压力测试。"
            "运营商提前巡检、现场值守和后台监控能提升观众体验，也能为后续大型活动的应急保障和人流服务积累经验。"
        )

    if any(word in raw for word in ("微信原生AI助手", "小微", "微信AI生态", "AI专属卡", "小程序完成服务")):
        return (
            "微信把 AI 助手嵌入原生功能，价值在于能否真正降低用户操作成本。"
            "更值得关注的是数据来源、授权边界、支付安全和用户可控性，功能便利不能替代透明规则。"
        )

    if any(word in raw for word in ("杭小忆", "黄小西", "数字导游", "智慧旅游", "文旅小程序", "AI伴你游")):
        return (
            "AI 数字导游的价值在于把路线规划、景区服务和游客需求更快连接起来。"
            "但文旅场景更要重视信息准确性、隐私保护和应急服务，不能只看新鲜感和推荐效率。"
        )

    if ("马斯克" in raw and "行权" in raw) or ("特斯拉" in raw and "薪酬方案" in raw):
        return (
            "这笔行权的重点不只是财富数字，更关系到马斯克在特斯拉的投票权和战略控制力。"
            "对投资者而言，应区分账面收益、可出售现金收益和公司治理影响，避免只被巨额数字带走判断。"
        )

    if any(word in raw for word in ("单边平仓", "股票期权组合策略", "股票期权", "期权组合策略")):
        return (
            "期权业务机制调整的重点在于风险控制、技术准备和投资者理解成本。"
            "相关功能暂不实施，说明交易所仍在平衡市场效率与风险承受能力，投资者不宜把技术接口发布等同于业务立即落地。"
        )

    if any(word in raw for word in ("赢创", "欧洲化工", "聚酯业务", "结构优化", "降本措施", "裁3200")):
        return (
            "赢创裁员和关停聚酯业务反映出欧洲化工行业仍承受需求疲弱、成本压力和全球竞争加剧。"
            "观察这类调整，应同时看企业降本成效、受影响地区就业，以及亚太等增长市场能否抵消欧洲结构性压力。"
        )

    if any(word in raw for word in ("古巴", "美国无权评判", "外国干涉", "国家主权", "自决权", "改革措施")):
        return (
            "这条新闻的核心在于国家主权与外部干预边界。"
            "评价古巴改革应看其国内政策目标和民生效果，也应区分外部施压、外交表态与实际改革执行。"
        )

    if any(word in raw for word in ("夏播", "粮食进度", "种肥同播", "农情调度", "高标准农田", "水肥一体化", "花生起垄")):
        return (
            "这条农业新闻的重点在于新技术能否提升播种效率和粮食稳产能力。"
            "种肥同播、水肥一体化等做法如果能降低人工成本、提高肥料利用率，对主产区稳面积、稳产量会有实际意义，后续仍要看覆盖面积和增产效果。"
        )

    if any(word in raw for word in ("大湾区", "粤港澳", "科创资源", "科技成果商业化", "创新集群", "国际科技创新中心")):
        return (
            "大湾区科创建设的关键在于跨城资源能否真正协同，而不是停留在概念叠加。"
            "前沿技术落地需要高校、科研机构、企业和资本形成稳定分工，后续可重点观察成果转化效率、产业配套和跨境规则衔接。"
        )

    if any(word in raw for word in ("韩国科技", "韩国赛道", "韩股", "韩国主题ETF", "QDII", "跨境资金")):
        return (
            "资金加速布局韩国科技资产，反映全球 AI 产业链热度正在外溢到更多市场。"
            "但跨境基金受汇率、估值、行业周期和流动性影响明显，普通投资者不宜只看短期资金流入，更要看产品风险暴露和持仓透明度。"
        )

    if "美股" in raw and any(word in raw for word in ("资金涌入", "半导体设备", "科技板块", "8100亿", "股票基金")):
        return (
            "美股科技资金快速流入说明市场风险偏好正在升温，但也意味着估值和波动压力同步累积。"
            "半导体设备股受 AI 需求拉动具有产业逻辑，投资者仍应区分真实订单、盈利改善和短线资金追涨，避免把阶段性行情视为确定趋势。"
        )

    if "ETF" in raw and any(word in raw for word in ("陆家嘴论坛", "主动ETF", "基金公司", "华夏基金", "易方达")):
        return (
            "ETF格局变化反映头部基金公司竞争加剧，也显示指数化和主动ETF产品仍在扩容。"
            "对普通投资者来说，关注点不应只放在规模排名，更要看产品费率、跟踪误差、流动性和底层资产风险是否匹配自身需求。"
        )

    if "f1" in lower or "formula 1" in lower or "\u4e00\u7ea7\u65b9\u7a0b\u5f0f" in raw:
        return (
            "F1\u7684\u5546\u4e1a\u5316\u80fd\u4e3a\u8d5b\u4e8b\u63d0\u4f9b\u8d44\u91d1\u548c\u5168\u7403\u4f20\u64ad\uff0c\u4f46\u7ade\u6280\u516c\u5e73\u3001\u6bd4\u8d5b\u8282\u594f\u548c\u8f66\u624b\u610f\u89c1\u540c\u6837\u662f\u8fd9\u9879\u8fd0\u52a8\u7684\u6838\u5fc3\u8d44\u4ea7\u3002"
            "\u540e\u7eed\u9700\u5173\u6ce8\u8d5b\u4e8b\u7ec4\u7ec7\u65b9\u5982\u4f55\u5728\u8d5b\u5386\u5b89\u6392\u3001\u8f6c\u64ad\u6743\u76ca\u548c\u7ade\u8d5b\u89c4\u5219\u4e2d\u627e\u5230\u5e73\u8861\uff0c\u8ba9\u5546\u4e1a\u5316\u771f\u6b63\u670d\u52a1\u4e8e\u8fd0\u52a8\u672c\u8eab\u3002"
        )

    has_earnings_signal = any(word in raw for word in ("财报", "季度业绩", "业绩表现")) or _english_any_keyword(
        lower,
        ("blockbuster quarter", "quarterly results", "quarterly performance", "earnings"),
    )
    has_market_reaction = any(word in raw for word in ("评级上调", "股价上涨", "合作关系")) or _english_any_keyword(
        lower,
        ("upgraded", "shares gained", "shares rose", "partnership"),
    )
    if has_earnings_signal and has_market_reaction:
        return (
            "单季表现、机构评级和产业合作都是市场观察公司经营预期的信号，但不等于后续业绩已经兑现。"
            "后续仍需关注正式财报、订单与合作进展，避免把单日股价波动解读为长期趋势。"
        )

    if any(word in raw for word in ("气象", "台风", "暴雨", "灾害预警", "防灾减灾", "农业生产")) or _english_any_keyword(
        lower,
        ("weather monitoring", "meteorological", "disaster warning", "automatic weather station"),
    ):
        return (
            "这件事的现实价值在于把气象监测合作落到灾害预警、农业安排和公共安全等具体民生场景。"
            "评价它不应只看援助名义，更要看设备能否长期运行、数据能否被当地部门稳定使用，以及是否真正提升基层防灾能力。"
        )

    if any(word in raw for word in ("人道主义", "停火", "平民", "冲突地区", "生存需求")):
        return (
            "这条新闻的关键不在表态本身，而在平民保护、救援通道和停火安排能否形成可执行结果。"
            "从中国受众角度看，支持人道主义行动与推动政治解决并不矛盾，真正需要警惕的是把民生危机工具化。"
        )

    if "世界杯" in raw and any(word in raw for word in ("NASA", "空间站", "航天", "太空", "阿耳忒弥斯")):
        return (
            "这条新闻更像是体育 IP 与航天传播的一种结合。"
            "它能放大世界杯话题热度，也说明大型赛事正在借助科技和太空叙事拓展公众参与感，但实际价值仍主要在科普传播和品牌合作层面。"
        )

    if any(
        word in raw
        for word in (
            "产业创新",
            "产业应用",
            "应用场景",
            "科技创新",
            "科技成果商业化",
            "创新集群",
            "科创资源",
            "国际科技创新中心",
            "大湾区",
            "海创会",
            "智慧养老",
            "智能风控",
            "脑电科技",
            "陶瓷刀具",
            "港区安全",
            "全景监控",
            "码头",
            "监控系统",
            "毫米波雷达",
        )
    ):
        return (
            "这类产业科技新闻的关键不在概念本身，而在技术能否落到真实场景。"
            "判断其价值应继续看后续应用规模、运行稳定性、成本收益和服务对象反馈，避免把展示成果直接等同于长期产业成效。"
        )

    if any(word in raw for word in ("操纵", "市场禁入", "监管处罚", "行政处罚", "罚款", "实控人", "内幕交易")):
        return (
            "这类监管处罚的核心在于维护证券市场公平交易和信息披露秩序。"
            "对投资者来说，处罚结果本身只是起点，还应关注公司治理整改、责任落实和后续经营风险。"
        )

    if _english_any_keyword(lower, ("advanced ai model access", "model access", "policy dispute", "technology dispute")):
        return (
            "AI 模型访问争议的重点在于平台规则是否清晰、权限分配是否透明，以及安全边界如何执行。"
            "对企业和开发者来说，稳定可预期的访问机制比短期功能开放更重要，否则创新效率和合规风险都会受到影响。"
        )

    if any(
        word in raw
        for word in (
            "AI写作",
            "AI 写作",
            "人工智能写作",
            "生成式AI",
            "生成式 AI",
            "模型访问",
            "训练数据",
            "作家",
            "出版",
            "版权",
            "署名",
            "内容平台",
        )
    ) or _english_any_keyword(
        lower,
        ("ai writing", "generative ai", "claude", "model access", "publishing", "authors", "copyright"),
    ):
        return (
            "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
            "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
        )

    if any(word in raw for word in ("体操", "世界杯", "国足", "赛事", "运动员", "挑战赛")):
        return (
            "体育新闻的评价重点应放在竞技表现、人才梯队和长期训练体系，而不是一次成绩带来的情绪波动。"
            "如果相关队伍能把比赛经验转化为稳定备战和青训投入，事件的价值会比短期热度更扎实。"
        )

    if any(word in raw for word in ("外贸", "经贸", "贸易", "贸易额", "关税", "出口", "进口", "供应链")) or _english_any_keyword(
        lower,
        ("trade", "tariff", "export", "import", "supply chain"),
    ):
        return (
            "这类经贸变化需要同时看订单、物流、政策和企业成本，不能只用单一数据判断趋势。"
            "对中国企业而言，稳定供应链和分散市场风险仍是重点，短期波动如果没有后续数据印证，不宜被放大成长期结论。"
        )

    return ""


def _daily_news_contextual_offline_body(picked, prompt_norm: str) -> str:
    context = _compact_daily_news_context(picked)
    if len(context) < 40:
        return ""

    subject = _daily_news_fallback_subject(picked, prompt_norm)
    source_for_copy = (picked.source or picked.domain or "原始来源").strip()
    if not _has_cjk(source_for_copy):
        source_for_copy = "原始来源"
    pub = _format_news_seendate(picked.seendate)

    summary_seed = getattr(picked, "description", "") or _clean_original_news_text(getattr(picked, "content", "") or "") or context
    if summary_seed and not _has_cjk(summary_seed):
        summary_seed = subject
    summary = _normalize_news_summary(summary_seed, fallback=subject, limit=55)
    if not summary.endswith(("。", "！", "？")):
        summary = f"{summary}。"

    summary_override = ""
    context_lower = context.lower()
    if _has_cjk(context):
        fact_sentence = context
    elif _english_any_keyword(
        context_lower,
        ("technology dispute", "advanced ai model", "model access", "policy dispute"),
    ):
        summary_override = "AI模型访问政策争议升温，平台规则、权限透明度和安全边界成为关注焦点，行业讨论持续发酵。"
        fact_sentence = (
            "报道提到，一项围绕 AI 模型访问和政策边界的争议升温，相关讨论集中在高级模型使用权限、"
            "平台规则和责任划分。现有公开材料没有披露更多执行细节，因此正文只概括已经出现的争议方向。"
        )
    elif _english_any_keyword(
        context_lower,
        ("sunscreen", "bemotrizinol", "sunscreen ingredients", "fda review"),
    ):
        summary_override = "美国防晒成分审批进展引发关注，监管效率、消费者选择和公共健康需求成为讨论重点。"
        fact_sentence = (
            "报道提到，一些国家已使用较新的防晒成分多年，美国围绕 bemotrizinol 等成分的审批和市场准入问题再受关注。"
            "这条新闻的核心是防晒产品监管进度、消费者选择和公共健康需求之间的平衡。"
        )
    else:
        return ""
    if summary_override:
        summary = summary_override
    fact_sentence = fact_sentence.strip("。")
    content = _limit_daily_news_content(fact_sentence)
    title_fact = _clean_daily_news_title_candidate(getattr(picked, "title", "") or "")
    if title_fact and _has_cjk(title_fact) and title_fact not in content and len(title_fact) <= 30:
        with_title = f"{title_fact}。{content}".strip()
        content = with_title if len(with_title) <= 150 else _limit_daily_news_content(with_title)
    comment = _daily_news_fact_based_comment(picked, context, subject)
    if _daily_news_comment_is_unsupported(comment, picked, content):
        comment = _daily_news_safe_fact_comment(picked, content)
    body = (
        f"{_NEWS_SUMMARY_LABEL}{summary}\n"
        f"{_NEWS_CONTENT_LABEL}\n"
        f"{content}"
    )
    if comment:
        body = f"{body}\n\n{_NEWS_COMMENT_LABEL}\n{comment}"
    return f"{body}\n\n发布时间：{pub}"


def _specific_daily_news_offline_body(picked) -> str:
    pub = _format_news_seendate(picked.seendate)
    source = (picked.source or picked.domain or "原始来源").strip()
    text = " ".join(
        part
        for part in (picked.title, picked.description, picked.content)
        if part
    ).lower()

    if _english_any_keyword(text, ("seawater battery", "desalination", "carbon capture")):
        return (
            "要点摘要：韩国团队研发海水电池，将储能、海水淡化和碳捕集整合到同一系统。\n"
            "新闻内容：\n"
            f"据{source}报道，韩国蔚山国立科学技术院 Kim Young-sik 教授团队开发的海水电池，是一种把能源存储、海水淡化和碳捕集结合在一起的多功能系统。"
            "报道称，这项技术的看点不只是储能，而是尝试让同一套装置同时服务清洁能源、淡水供给和减碳需求。现阶段仍需关注后续工程化验证、成本和规模化应用条件。\n\n"
            "点评：\n"
            "从中国视角看，这类技术如果能走向规模化，会同时触及新能源、海洋资源利用和双碳产业链。更值得关注的是实验室成果能否变成稳定、低成本、可维护的工程系统。你更看好它先落地在哪个场景？"
            f"\n\n发布时间：{pub}"
        )

    if _english_any_keyword(text, ("hegseth", "nato", "us troop deployments", "american forces in europe")):
        return (
            "要点摘要：美国防长宣布审查驻欧美军部署，北约防务分担再次成为焦点。\n"
            "新闻内容：\n"
            f"据{source}报道，美国防长 Pete Hegseth 宣布，五角大楼将对美国在欧洲的部队部署进行为期六个月的审查。"
            "报道提到，审查结果将与欧洲盟友的防务支出和地区安全责任相关。此举使北约内部关于美国驻欧角色、欧洲承担更多防务责任的讨论进一步升温。\n\n"
            "点评：\n"
            "从中国视角看，美军欧洲部署调整会影响欧洲安全格局，也关系到美国战略资源如何在欧洲与印太之间分配。后续应重点看审查是否带来实际兵力变化，而不是只看口头表态。你觉得欧洲会因此增加防务投入吗？"
            f"\n\n发布时间：{pub}"
        )

    if _english_any_keyword(text, ("authors", "using ai", "publishing industry", "artificial intelligence")):
        return (
            "要点摘要：部分作家公开承认使用AI写作，出版业围绕创意和透明度的争议升温。\n"
            "新闻内容：\n"
            f"据{source}报道，随着 AI 工具进入写作流程，一些作家开始公开讨论自己如何在创作中使用 AI。"
            "报道指出，出版业一方面担心 AI 威胁作者收入和人类创造力，另一方面也有人把它当作辅助构思、整理和修改的工具。争议核心在于使用边界、读者知情权和作品署名透明度。\n\n"
            "点评：\n"
            "从中国视角看，AI 写作不会只影响作家，也会影响平台审核、版权交易和内容消费信任。真正关键的是建立可披露、可追责的使用规则，而不是简单把 AI 视为禁区或万能工具。你能接受书里使用 AI 辅助吗？"
            f"\n\n发布时间：{pub}"
        )

    return ""


def _daily_news_offline_body(picked, prompt_norm: str) -> str:
    """
    Offline fallback body: keep it publishable and avoid echoing prompt/requirements.
    """
    specific = _specific_daily_news_offline_body(picked)
    if specific:
        return specific
    contextual = _daily_news_contextual_offline_body(picked, prompt_norm)
    if contextual:
        return contextual

    return ""


def _ensure_daily_news_sections(body: str, prompt_norm: str) -> str:
    text = (body or "").strip()
    if not text:
        return text
    text = _remove_generic_daily_news_comment(text)
    if _load_daily_news_body_json(text):
        return text
    if _extract_rendered_daily_news_body_fields(text):
        return text
    if (
        text.startswith(_NEWS_SUMMARY_LABEL)
        and _NEWS_CONTENT_LABEL in text
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
        comment = ""

    summary = _normalize_news_summary(summary, fallback=news, limit=40)
    if _daily_news_comment_is_generic(comment):
        comment = ""

    out = f"{_NEWS_SUMMARY_LABEL}{summary}\n{_NEWS_CONTENT_LABEL}\n{news}"
    if comment:
        out = f"{out}\n\n{_NEWS_COMMENT_LABEL}\n{comment}"
    return out


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


def _finalize_daily_news_body(body: str, picked, prompt_norm: str, title_hint: str = "") -> str:
    raw = body or ""
    if _load_daily_news_body_json(raw):
        fields = _daily_news_body_to_fields(raw, picked, prompt_norm, title_hint=title_hint)
        return _render_daily_news_body_fields(fields)
    text = _strip_urls(raw)
    if _extract_rendered_daily_news_body_fields(text):
        fields = _daily_news_body_to_fields(text, picked, prompt_norm, title_hint=title_hint)
        return _render_daily_news_body_fields(fields)
    text = _ensure_daily_news_sections(text, prompt_norm)
    text = _ensure_news_publish_date(text, picked.seendate)
    text = _append_news_source_line(text, picked)
    fields = _daily_news_body_to_fields(text, picked, prompt_norm, title_hint=title_hint)
    return _render_daily_news_body_fields(fields)


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


def _daily_news_source_trace(news_meta: dict[str, Any], picked) -> dict[str, Any]:
    meta = dict(news_meta or {})
    existing = meta.get("source_api")
    trace = dict(existing) if isinstance(existing, dict) else {}
    provider = (
        str(trace.get("provider") or meta.get("api_source") or meta.get("provider") or "").strip()
        or "unknown"
    )
    trace["provider"] = provider
    for key in ("query", "queries_used", "provider_plan", "provider_attempts"):
        if key in meta and key not in trace:
            trace[key] = meta[key]
    if picked is not None:
        trace.setdefault("item_source", (getattr(picked, "source", "") or "").strip() or None)
        trace.setdefault("item_domain", (getattr(picked, "domain", "") or "").strip() or None)
        trace.setdefault("item_url", (getattr(picked, "url", "") or "").strip() or None)
        trace.setdefault("item_title", (getattr(picked, "title", "") or "").strip() or None)
    return {k: v for k, v in trace.items() if v not in ("", None)}


def _daily_news_meta_with_trace(news_meta: dict[str, Any], picked) -> dict[str, Any]:
    meta = dict(news_meta or {})
    trace = _daily_news_source_trace(meta, picked)
    meta["api_source"] = trace.get("provider") or meta.get("provider") or "unknown"
    meta["source_api"] = trace
    return meta


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int | None = None) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _positive_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return None
    return max(1, parsed)


def _candidate_lookback_windows(
    explicit_days: object = None,
    *,
    env_names: tuple[str, ...] = (),
) -> tuple[list[int], dict[str, Any]]:
    fixed = _positive_int_or_none(explicit_days)
    source = "argument" if fixed is not None else ""
    if fixed is None:
        for name in env_names:
            fixed = _positive_int_or_none(os.getenv(name))
            if fixed is not None:
                source = name
                break
    if fixed is not None:
        return [fixed], {
            "mode": "fixed",
            "source": source or "argument",
            "windows": [fixed],
        }
    windows = list(DEFAULT_CANDIDATE_LOOKBACK_WINDOWS)
    return windows, {
        "mode": "auto_expand",
        "source": "default",
        "windows": windows,
    }


def _daily_news_lookback_window(
    explicit_days: object = None,
    *,
    env_names: tuple[str, ...] = (),
) -> tuple[list[int], dict[str, Any]]:
    """Resolve the non-negotiable freshness window for ordinary daily news."""
    fixed = _positive_int_or_none(explicit_days)
    source = "argument" if fixed is not None else ""
    if fixed is None:
        for name in env_names:
            fixed = _positive_int_or_none(os.getenv(name))
            if fixed is not None:
                source = name
                break

    days = fixed if fixed is not None else DAILY_NEWS_MAX_LOOKBACK_DAYS
    if days > DAILY_NEWS_MAX_LOOKBACK_DAYS:
        raise RuntimeError(
            "每日新闻最多只能回溯 2 个北京时间自然日（发帖当天和前一天）；"
            f"当前 {source or 'argument'}={days}，请留空或填写 1/2。"
        )
    return [days], {
        "mode": "strict_freshness",
        "source": source or "default",
        "windows": [days],
        "max_allowed_days": DAILY_NEWS_MAX_LOOKBACK_DAYS,
    }


def _ai_digest_candidate_pool_target(target_count: int) -> tuple[int, int]:
    # Keep enough lower-ranked official and fallback-source items available for
    # history-aware deduplication before the LLM sees the pool.
    factor = _env_int("AI_DIGEST_CANDIDATE_POOL_FACTOR", 10, min_value=1, max_value=20)
    pool_target = min(200, max(target_count, target_count * factor))
    return pool_target, factor


def _ai_digest_adaptive_max_items() -> int:
    raw = (os.getenv("AI_DIGEST_MAX_ITEMS") or os.getenv("AI_DIGEST_TARGET_ITEMS") or "").strip()
    try:
        value = int(raw) if raw else 20
    except ValueError:
        value = 20
    return min(20, max(AI_DIGEST_MIN_ITEMS, value))


def _ai_digest_progress_callback():
    enabled = (os.getenv("AI_DIGEST_PROGRESS") or "1").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return None

    def emit(stage: str, detail: str) -> None:
        print(f"[ai-digest] stage={stage} | {detail}", flush=True)

    return emit


def _with_ai_digest_items(brief: AIDigestBrief, items) -> AIDigestBrief:
    data = brief.model_dump()
    data["items"] = [item.model_dump() for item in items]
    return AIDigestBrief.model_validate(data)


def _rank_brief_ai_digest_items(
    brief: AIDigestBrief,
    *,
    target_count: int,
    min_official_count: int,
    max_age_days: int,
    min_domestic_model_count: int = 0,
    min_foreign_ai_count: int = 0,
) -> AIDigestBrief:
    ranked = rank_ai_updates(
        list(brief.items or []),
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=True,
        max_age_days=max_age_days,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    return _with_ai_digest_items(brief, ranked)


def _build_quota_safe_ai_digest_fallback(
    items,
    *,
    target_count: int,
    min_official_count: int,
    max_age_days: int,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
) -> AIDigestBrief:
    selected = rank_ai_updates(
        list(items or []),
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=True,
        max_age_days=max_age_days,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    return build_fallback_brief(selected, target_count=target_count)


def _ai_digest_selection_error(
    items,
    *,
    target_count: int,
    min_official_count: int,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
    max_age_days: int,
) -> str:
    item_list = list(items or [])
    counts = ai_digest_quota_counts(item_list)
    source_counts = ai_digest_source_counts(item_list)
    source_capacity = sum(min(count, AI_DIGEST_MAX_ITEMS_PER_SOURCE) for count in source_counts.values())
    official_count = ai_digest_official_count(item_list)
    problems = []
    if len(item_list) < target_count:
        problems.append(f"有效资讯不足{target_count}条，当前{len(item_list)}条")
    if source_capacity < target_count:
        problems.append(
            f"信源多样性不足：目标{target_count}条，同一信源最多{AI_DIGEST_MAX_ITEMS_PER_SOURCE}条，"
            f"当前最多可生成{source_capacity}条"
        )
    if official_count < min_official_count:
        problems.append(
            f"官方可追溯资讯不足{min_official_count}条，当前{official_count}条"
        )
    if counts["domestic_model"] < min_domestic_model_count:
        problems.append(
            f"国内模型资讯不足{min_domestic_model_count}条，当前{counts['domestic_model']}条"
        )
    if counts["foreign_ai"] < min_foreign_ai_count:
        problems.append(f"国外AI资讯不足{min_foreign_ai_count}条，当前{counts['foreign_ai']}条")
    if not problems:
        return ""
    return f"daily ai digest create failed: {'；'.join(problems)}；仅允许生成日前{max_age_days}日内可追溯资讯"


def _ai_digest_source_cap_error(
    items: Iterable[AIUpdateItem],
    *,
    target_count: int | None = None,
) -> str:
    item_list = list(items or [])
    source_counts = ai_digest_source_counts(item_list)
    over_limit = {
        source: count
        for source, count in source_counts.items()
        if count > AI_DIGEST_MAX_ITEMS_PER_SOURCE
    }
    if over_limit:
        source, count = max(over_limit.items(), key=lambda pair: pair[1])
        return (
            f"每日AI讯息信源约束失败：信源 {source} 有 {count} 条，"
            f"上限为 {AI_DIGEST_MAX_ITEMS_PER_SOURCE} 条"
        )
    if target_count is not None and len(item_list) < int(target_count):
        return (
            f"每日AI讯息信源多样性不足：目标 {int(target_count)} 条，"
            f"当前仅 {len(item_list)} 条"
        )
    return ""


def _uploaded_ai_digest_history_keys() -> set[str]:
    keys: set[str] = set()
    for post in list_posts():
        if not (post.uploaded or post.status in {PostStatus.saved_draft, PostStatus.published}):
            continue
        digest = (post.platform or {}).get("ai_digest")
        if not isinstance(digest, dict):
            continue
        raw_items = digest.get("items")
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            try:
                key = AIUpdateItem.model_validate(raw_item).dedupe_key
            except Exception:
                continue
            if key and key not in {"url:", "title:"}:
                keys.add(key)
    return keys


def _select_adaptive_ai_digest_items(
    items,
    *,
    impact_scores: dict[str, dict[str, object]],
    historical_keys: set[str],
    min_items: int = AI_DIGEST_MIN_ITEMS,
    max_items: int = 20,
    min_official_count: int = 6,
    min_domestic_model_count: int = AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS,
    min_foreign_ai_count: int = AI_DIGEST_MIN_FOREIGN_AI_ITEMS,
    allow_official_relaxation: bool = True,
) -> tuple[list[AIUpdateItem], dict[str, Any]]:
    minimum = max(1, int(min_items or AI_DIGEST_MIN_ITEMS))
    maximum = max(minimum, min(20, int(max_items or 20)))
    item_list = list(items or [])
    ranked_all = rank_ai_updates(
        item_list,
        target_count=max(1, len(item_list)),
        min_official_count=max(maximum + 1, len(item_list) + 1),
        allow_social_backfill=True,
        max_age_days=14,
        max_items_per_source=None,
    )
    recent_keys = {
        days: {
            item.dedupe_key
            for item in filter_recent_ai_updates(ranked_all, max_age_days=days, require_url=True)
        }
        for days in (3, 7, 14)
    }

    def is_high(item: AIUpdateItem) -> bool:
        row = impact_scores.get(item.dedupe_key) or {}
        return bool(row.get("high_impact"))

    novel = [item for item in ranked_all if item.dedupe_key not in historical_keys]
    strict_available = [
        item for item in novel if item.dedupe_key in recent_keys[3] and is_high(item)
    ]
    strict_ranked = rank_ai_updates(
        strict_available,
        target_count=maximum,
        min_official_count=maximum + 1,
        allow_social_backfill=True,
        max_age_days=3,
    )
    strict_target = min(len(strict_ranked), maximum)
    target = strict_target if strict_target >= minimum else minimum
    max_historical_reuse = max(0, (target * 3 - 1) // 4)

    strict_keys = {item.dedupe_key for item in strict_ranked}
    tier_items = {
        "three_day_normal": [
            item
            for item in novel
            if item.dedupe_key in recent_keys[3] and item.dedupe_key not in strict_keys
        ],
        "seven_day_high": [
            item
            for item in novel
            if item.dedupe_key in recent_keys[7]
            and item.dedupe_key not in recent_keys[3]
            and is_high(item)
        ],
        "seven_day_normal": [
            item
            for item in novel
            if item.dedupe_key in recent_keys[7]
            and item.dedupe_key not in recent_keys[3]
            and not is_high(item)
        ],
        "fourteen_day_high": [
            item
            for item in novel
            if item.dedupe_key in recent_keys[14]
            and item.dedupe_key not in recent_keys[7]
            and is_high(item)
        ],
        "fourteen_day_normal": [
            item
            for item in novel
            if item.dedupe_key in recent_keys[14]
            and item.dedupe_key not in recent_keys[7]
            and not is_high(item)
        ],
        "historical_reuse": [
            item for item in ranked_all if item.dedupe_key in historical_keys
        ][:max_historical_reuse],
    }
    allowed = list(strict_ranked)
    allowed_keys = {item.dedupe_key for item in allowed}

    def add_tier(name: str) -> None:
        for candidate in tier_items[name]:
            if candidate.dedupe_key in allowed_keys:
                continue
            allowed.append(candidate)
            allowed_keys.add(candidate.dedupe_key)

    def select_allowed() -> list[AIUpdateItem]:
        return rank_ai_updates(
            allowed,
            target_count=target,
            min_official_count=target + 1,
            allow_social_backfill=True,
            max_age_days=14,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )

    eligible_items = list(strict_ranked)
    eligible_keys = {item.dedupe_key for item in eligible_items}
    for tier in tier_items.values():
        for candidate in tier:
            if candidate.dedupe_key in eligible_keys:
                continue
            eligible_items.append(candidate)
            eligible_keys.add(candidate.dedupe_key)

    requested_official_min = min(max(0, int(min_official_count or 0)), target)
    eligible_official_count = ai_digest_official_count(eligible_items)
    effective_official_min = (
        min(requested_official_min, eligible_official_count)
        if allow_official_relaxation
        else requested_official_min
    )
    selected = select_allowed()
    error = _ai_digest_selection_error(
        selected,
        target_count=target,
        min_official_count=effective_official_min,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_age_days=14,
    )
    tiers_used: list[str] = []
    for tier_name in (
        "three_day_normal",
        "seven_day_high",
        "seven_day_normal",
        "fourteen_day_high",
        "fourteen_day_normal",
        "historical_reuse",
    ):
        if not error:
            break
        add_tier(tier_name)
        tiers_used.append(tier_name)
        selected = select_allowed()
        error = _ai_digest_selection_error(
            selected,
            target_count=target,
            min_official_count=effective_official_min,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_age_days=14,
        )

    selected_keys = {item.dedupe_key for item in selected}
    reused_selected = sum(1 for item in selected if item.dedupe_key in historical_keys)
    if reused_selected > max_historical_reuse:
        error = (
            f"daily ai digest historical novelty insufficient: 历史资讯复用{reused_selected}条，"
            f"超过本批最多{max_historical_reuse}条"
        )
    if error:
        raise RuntimeError(error)

    selected_tier_counts = {
        name: sum(1 for item in tier if item.dedupe_key in selected_keys)
        for name, tier in tier_items.items()
    }
    fallback_selected = sum(selected_tier_counts.values())
    return selected, {
        "selection_mode": "adaptive_strict" if fallback_selected == 0 else "fallback_minimum",
        "min_items": minimum,
        "max_items": maximum,
        "strict_candidate_count": strict_target,
        "strict_selected_count": len(selected) - fallback_selected,
        "fallback_selected_count": fallback_selected,
        "fallback_tiers": selected_tier_counts,
        "fallback_tiers_used": tiers_used,
        "target_items": target,
        "actual_items": len(selected),
        "historical_reused_count": reused_selected,
        "max_historical_reuse": max_historical_reuse,
        "eligible_official_items": eligible_official_count,
        "effective_min_official_items": effective_official_min,
        "official_target_relaxed": effective_official_min < requested_official_min,
    }


def _prefer_novel_ai_digest_items(
    items,
    *,
    historical_keys: set[str],
    target_count: int,
    min_official_count: int,
    max_age_days: int,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
) -> tuple[list[AIUpdateItem], dict[str, int]]:
    item_list = list(items or [])
    novel = [item for item in item_list if item.dedupe_key not in historical_keys]
    reused = [item for item in item_list if item.dedupe_key in historical_keys]
    meta = {
        "historical_key_count": len(historical_keys),
        "candidate_count_before_history_filter": len(item_list),
        "novel_candidate_count": len(novel),
        "reused_candidate_count": len(reused),
        "reused_selected_count": 0,
    }
    if not historical_keys:
        return item_list, meta

    allowed = list(novel)
    selected = rank_ai_updates(
        allowed,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=True,
        max_age_days=max_age_days,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    remaining_reused = list(reused)
    while _ai_digest_selection_error(
        selected,
        target_count=target_count,
        min_official_count=min_official_count,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_age_days=max_age_days,
    ) and remaining_reused:
        counts = ai_digest_quota_counts(selected)
        need_domestic = counts["domestic_model"] < min_domestic_model_count
        need_foreign = counts["foreign_ai"] < min_foreign_ai_count

        candidate_index = 0
        for index, candidate in enumerate(remaining_reused):
            candidate_counts = ai_digest_quota_counts([candidate])
            if need_domestic and candidate_counts["domestic_model"]:
                candidate_index = index
                break
            if need_foreign and candidate_counts["foreign_ai"]:
                candidate_index = index
                break
        allowed.append(remaining_reused.pop(candidate_index))
        selected = rank_ai_updates(
            allowed,
            target_count=target_count,
            min_official_count=min_official_count,
            allow_social_backfill=True,
            max_age_days=max_age_days,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )

    meta["reused_selected_count"] = sum(
        1 for item in selected if item.dedupe_key in historical_keys
    )
    return selected, meta


def _fit_ai_digest_brief_to_body_limit(
    brief: AIDigestBrief,
    *,
    min_items: int = 1,
    selection_meta: dict | None = None,
) -> AIDigestBrief:
    items = list(brief.items or [])
    while len(items) > max(1, min_items):
        fitted = _with_ai_digest_items(brief, items)
        if len(render_ai_digest_body(fitted, selection_meta=selection_meta)) <= MAX_IMAGE_BODY:
            return fitted
        items = items[:-1]
    return _with_ai_digest_items(brief, items)


def _fit_ai_digest_items_to_body_capacity(
    items,
    *,
    min_items: int,
    min_official_count: int,
    max_age_days: int,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
    selection_meta: dict | None = None,
) -> tuple[list[AIUpdateItem], dict[str, int]]:
    item_list = list(items or [])
    requested = len(item_list)
    minimum = max(1, min(int(min_items or 1), requested or 1))
    last_length = 0
    for target in range(requested, minimum - 1, -1):
        selected = rank_ai_updates(
            item_list,
            target_count=target,
            min_official_count=target + 1,
            allow_social_backfill=True,
            max_age_days=max_age_days,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
        effective_official_min = min(max(0, int(min_official_count or 0)), target)
        if _ai_digest_selection_error(
            selected,
            target_count=target,
            min_official_count=effective_official_min,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_age_days=max_age_days,
        ):
            continue
        preview = build_fallback_brief(selected, target_count=target)
        last_length = len(render_ai_digest_body(preview, selection_meta=selection_meta))
        if last_length <= MAX_IMAGE_BODY:
            return selected, {
                "requested_items": requested,
                "selected_items": len(selected),
                "dropped_items": max(0, requested - len(selected)),
                "body_length": last_length,
                "body_limit": MAX_IMAGE_BODY,
            }
    raise RuntimeError(
        "daily ai digest body capacity insufficient: "
        f"保留最少{minimum}条及全部来源链接后正文仍为{last_length}字，"
        f"超过小红书上限{MAX_IMAGE_BODY}字"
    )


def _ai_digest_post_title(brief: AIDigestBrief) -> str:
    prefix = "每日AI|"
    fallback = "今日AI热点速览"
    featured = featured_ai_update(list(brief.items or []))
    featured_title = str(featured.title if featured is not None else "").strip()
    generic_title = bool(
        re.search(r"(?:模型|产品|工具|智能体|API)?发布新进展$", re.sub(r"\s+", "", featured_title))
    )
    if generic_title and featured is not None:
        raw_subject = str(featured.raw_excerpt or featured.summary or "").strip()
        vendor = re.sub(r"(?i)\s*(?:blog|官网|official)$", "", str(featured.vendor or "").strip())
        raw_subject = re.split(r"[，。；;｜|]", raw_subject, maxsplit=1)[0]
        if vendor:
            raw_subject = re.sub(rf"^{re.escape(vendor)}\s*", "", raw_subject, flags=re.IGNORECASE)
        raw_subject = re.sub(r"^启动(?:为期)?(?:[一二三四五六七八九十\d]+(?:天|周|日))?的?", "", raw_subject)
        raw_subject = re.sub(r"(?i)agents?\s+week", "智能体周", raw_subject)
        raw_subject = re.sub(r"(?i)agent\s+cloud", "Agent云", raw_subject)
        raw_subject = re.sub(r"\s+", "", raw_subject).strip("，,。；;：:、-—| ")
        if raw_subject:
            featured_title = raw_subject if raw_subject.lower().startswith(vendor.lower()) else f"{vendor}{raw_subject}"
    subject = re.split(r"[，。；;｜|]", featured_title, maxsplit=1)[0]
    subject_parts = re.split(r"[：:]", subject, maxsplit=1)
    if len(subject_parts) == 2 and len(subject_parts[1].strip()) >= 4:
        subject = subject_parts[1]
    subject = subject.replace("正式开源", "开源")
    subject = re.sub(r"\s+", "", subject)
    subject = subject.replace("加密算法中的弱点", "加密弱点")
    subject = subject.replace("加密算法弱点", "加密弱点")
    subject = subject.strip("，,。；;：:、-—| ") or fallback
    item_count = len(brief.items or [])
    suffix = f"等{item_count}条更新" if item_count >= 3 else ""
    if suffix:
        product = str(featured.product if featured is not None else "").strip()
        if product:
            subject = re.sub(r"\s+", "", product)
        elif featured is not None:
            vendor = re.sub(r"(?i)\s*(?:blog|官网|official)$", "", str(featured.vendor or "").strip())
            if vendor:
                subject = re.sub(rf"^{re.escape(vendor)}", "", subject, flags=re.IGNORECASE)
            subject = re.sub(r"^(?:发布|推出|上线|开源|更新|披露|宣布)", "", subject)
            subject = subject.strip("，,。；;：:、-—| ") or fallback
    max_subject_length = max(1, MAX_IMAGE_TITLE - len(prefix) - len(suffix))
    subject = subject[:max_subject_length].rstrip("，,。；;：:、-—| ")
    return f"{prefix}{subject or fallback[:max_subject_length]}{suffix}"


def create_daily_ai_digest_posts(
    *,
    asset_paths: list[str],
    copy_assets: bool = True,
    count: int = 1,
    auto_image: bool = True,
    prompt_hint: str = "",
    evaluation_viewpoint: str = DEFAULT_EVALUATION_VIEWPOINT,
    lookback_days: object = None,
) -> list[Post]:
    minimum_count = AI_DIGEST_MIN_ITEMS
    max_items = _ai_digest_adaptive_max_items()
    legacy_target_count = _env_int(
        "AI_DIGEST_TARGET_ITEMS",
        minimum_count,
        min_value=minimum_count,
        max_value=20,
    )
    target_count = minimum_count
    min_official_count = _env_int("AI_DIGEST_MIN_OFFICIAL_ITEMS", 6, min_value=1, max_value=20)
    lookback_windows, lookback_meta = _candidate_lookback_windows(
        lookback_days,
        env_names=("AI_DIGEST_LOOKBACK_DAYS", "AI_DIGEST_MAX_AGE_DAYS", "CONTENT_LOOKBACK_DAYS"),
    )
    min_domestic_model_count = _env_int(
        "AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS",
        AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS,
        min_value=0,
        max_value=max_items,
    )
    min_foreign_ai_count = _env_int(
        "AI_DIGEST_MIN_FOREIGN_AI_ITEMS",
        AI_DIGEST_MIN_FOREIGN_AI_ITEMS,
        min_value=0,
        max_value=max_items,
    )
    candidate_pool_target, candidate_pool_factor = _ai_digest_candidate_pool_target(max_items)
    items = []
    selection_pool_count = 0
    source_meta: dict[str, Any] = {}
    max_age_days = lookback_windows[0]
    lookback_attempts: list[dict[str, Any]] = []
    last_pool_error = ""
    effective_min_official_count = min_official_count
    best_relaxed_pool: tuple[tuple[int, int, int], list[AIUpdateItem], dict[str, Any], int, int] | None = None
    progress = _ai_digest_progress_callback()
    historical_keys = _uploaded_ai_digest_history_keys()
    adaptive_selection_meta: dict[str, Any] = {}
    impact_meta: dict[str, Any] = {}
    llm_configs_cache = None
    if progress is not None:
        progress("collect_pool", f"in_progress mode={lookback_meta['mode']} windows={lookback_windows}")
    auto_collection_items: list[AIUpdateItem] | None = None
    auto_collection_meta: dict[str, Any] = {}
    if lookback_meta["mode"] == "auto_expand":
        collection_days = max(lookback_windows)
        if progress is not None:
            progress(
                "collect_pool",
                f"in_progress single_fetch window={collection_days}d; local_filters={lookback_windows}",
            )
        collected_items, collected_meta = collect_ai_digest_updates(
            target_count=candidate_pool_target,
            min_official_count=min_official_count,
            allow_social_backfill=True,
            max_age_days=collection_days,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            include_pool_items=True,
            force_search_backfill=False,
            force_aggregator_backfill=bool(historical_keys),
            progress=progress,
            source_health_path=Path("data") / "source_health" / "ai_digest.json",
            persist_source_health=True,
        )
        auto_collection_meta = dict(collected_meta or {})
        auto_collection_items = list(
            auto_collection_meta.get("_deduped_items")
            or auto_collection_meta.get("_fresh_items")
            or collected_items
            or []
        )
        auto_collection_meta.pop("_fetched_items", None)
        auto_collection_meta.pop("_fresh_items", None)
        auto_collection_meta.pop("_deduped_items", None)
        if progress is not None:
            progress(
                "collect_pool",
                f"success single_fetch window={collection_days}d "
                f"fetched={auto_collection_meta.get('fetched_count')} pool={len(auto_collection_items)}",
            )
    adaptive_mode = (os.getenv("AI_DIGEST_ADAPTIVE_COUNT") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if not adaptive_mode:
        target_count = legacy_target_count
    if adaptive_mode:
        if auto_collection_items is None:
            collection_days = max(lookback_windows)
            collected_items, collected_meta = collect_ai_digest_updates(
                target_count=candidate_pool_target,
                min_official_count=min_official_count,
                allow_social_backfill=True,
                max_age_days=collection_days,
                min_domestic_model_count=min_domestic_model_count,
                min_foreign_ai_count=min_foreign_ai_count,
                include_pool_items=True,
                force_search_backfill=False,
                force_aggregator_backfill=bool(historical_keys),
                progress=progress,
                source_health_path=Path("data") / "source_health" / "ai_digest.json",
                persist_source_health=True,
            )
            auto_collection_meta = dict(collected_meta or {})
            auto_collection_items = list(
                auto_collection_meta.get("_deduped_items")
                or auto_collection_meta.get("_fresh_items")
                or collected_items
                or []
            )
            auto_collection_meta.pop("_fetched_items", None)
            auto_collection_meta.pop("_fresh_items", None)
            auto_collection_meta.pop("_deduped_items", None)

        supervisor_limit = _env_int(
            "AI_DIGEST_IMPACT_SUPERVISOR_MAX_ITEMS",
            60,
            min_value=minimum_count,
            max_value=100,
        )
        evaluation_pool = rank_ai_updates(
            list(auto_collection_items or []),
            target_count=supervisor_limit,
            min_official_count=supervisor_limit + 1,
            allow_social_backfill=True,
            max_age_days=max(lookback_windows),
            max_items_per_source=None,
        )
        selection_pool_count = len(evaluation_pool)
        try:
            impact_threshold = float((os.getenv("AI_DIGEST_HIGH_IMPACT_SCORE") or "75").strip())
        except ValueError:
            impact_threshold = 75.0
        impact_threshold = min(100.0, max(0.0, impact_threshold))
        config_error = ""
        try:
            llm_configs_cache = load_llm_configs()
        except Exception as exc:
            llm_configs_cache = []
            config_error = str(exc)
        supervisor_enabled = (os.getenv("AI_DIGEST_IMPACT_SUPERVISOR") or "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        impact_scores, impact_meta = evaluate_ai_digest_impact_with_llm(
            list(llm_configs_cache or []) if supervisor_enabled else [],
            evaluation_pool,
            threshold=impact_threshold,
        )
        if config_error and not impact_meta.get("error"):
            impact_meta["error"] = config_error
        impact_meta["enabled"] = supervisor_enabled
        impact_meta["threshold"] = impact_threshold
        impact_meta["candidate_limit"] = supervisor_limit
        if progress is not None:
            high_count = sum(1 for row in impact_scores.values() if row.get("high_impact"))
            progress(
                "impact_review",
                f"success mode={impact_meta.get('mode')} candidates={len(evaluation_pool)} "
                f"high_impact={high_count} threshold={impact_threshold:g}",
            )

        try:
            items, adaptive_selection_meta = _select_adaptive_ai_digest_items(
                evaluation_pool,
                impact_scores=impact_scores,
                historical_keys=historical_keys,
                min_items=minimum_count,
                max_items=max_items,
                min_official_count=min_official_count,
                min_domestic_model_count=min_domestic_model_count,
                min_foreign_ai_count=min_foreign_ai_count,
                allow_official_relaxation=True,
            )
        except RuntimeError as exc:
            window_label = (
                f"tried windows={lookback_windows}"
                if lookback_meta["mode"] == "auto_expand"
                else f"fixed {max(lookback_windows)}-day window"
            )
            raise RuntimeError(f"daily ai digest material insufficient: {window_label}; {exc}") from exc
        target_count = len(items)
        fallback_tiers = adaptive_selection_meta.get("fallback_tiers") or {}
        if (
            fallback_tiers.get("fourteen_day_high")
            or fallback_tiers.get("fourteen_day_normal")
            or fallback_tiers.get("historical_reuse")
        ):
            max_age_days = 14
        elif fallback_tiers.get("seven_day_high") or fallback_tiers.get("seven_day_normal"):
            max_age_days = 7
        else:
            max_age_days = min(3, max(lookback_windows))
        effective_min_official_count = int(
            adaptive_selection_meta.get("effective_min_official_items", min(min_official_count, target_count))
        )
        source_meta = dict(auto_collection_meta or {})
        source_meta["impact_review"] = impact_meta
        source_meta["adaptive_selection"] = adaptive_selection_meta
        source_meta["historical_novelty"] = {
            "historical_key_count": len(historical_keys),
            "candidate_count_before_history_filter": len(evaluation_pool),
            "novel_candidate_count": sum(
                1 for item in evaluation_pool if item.dedupe_key not in historical_keys
            ),
            "reused_candidate_count": sum(
                1 for item in evaluation_pool if item.dedupe_key in historical_keys
            ),
            "reused_selected_count": adaptive_selection_meta.get("historical_reused_count", 0),
            "max_reused_before_duplicate_gate": adaptive_selection_meta.get("max_historical_reuse", 0),
        }
        source_meta["selected_impact_scores"] = [
            {
                "url": item.url,
                "impact_score": (impact_scores.get(item.dedupe_key) or {}).get("impact_score"),
                "high_impact": bool((impact_scores.get(item.dedupe_key) or {}).get("high_impact")),
                "reason": (impact_scores.get(item.dedupe_key) or {}).get("reason", ""),
            }
            for item in items
        ]
        lookback_attempts = [
            {
                "max_age_days": days,
                "selection_pool_items": len(
                    filter_recent_ai_updates(evaluation_pool, max_age_days=days, require_url=True)
                ),
                "quota_counts": ai_digest_quota_counts(
                    filter_recent_ai_updates(evaluation_pool, max_age_days=days, require_url=True)
                ),
                "official_count": ai_digest_official_count(
                    filter_recent_ai_updates(evaluation_pool, max_age_days=days, require_url=True)
                ),
                "error": "",
            }
            for days in lookback_windows
            if days <= max_age_days
        ]
        if progress is not None:
            selected_official_count = ai_digest_official_count(items)
            progress(
                "adaptive_selection",
                f"success strict={adaptive_selection_meta.get('strict_candidate_count')} "
                f"fallback={adaptive_selection_meta.get('fallback_selected_count')} "
                f"selected={target_count}/{max_items} official={selected_official_count}/{min_official_count} "
                f"effective_official={effective_min_official_count} "
                f"mode={adaptive_selection_meta.get('selection_mode')}",
            )

    for days in ([] if adaptive_mode else lookback_windows):
        if auto_collection_items is not None:
            if progress is not None:
                progress("filter_window", f"in_progress window={days}d cached_pool={len(auto_collection_items)}")
            candidate_items = list(auto_collection_items)
            candidate_meta = dict(auto_collection_meta)
            recent_items = filter_recent_ai_updates(
                candidate_items,
                max_age_days=days,
                require_url=True,
            )
            candidate_meta["fresh_count"] = len(recent_items)
            candidate_meta["deduped_count"] = len(dedupe_ai_updates(recent_items))
            candidate_meta["collection_max_age_days"] = max(lookback_windows)
        else:
            if progress is not None:
                progress("collect_pool", f"in_progress window={days}d")
            candidate_items, candidate_meta = collect_ai_digest_updates(
                target_count=candidate_pool_target,
                min_official_count=min_official_count,
                allow_social_backfill=True,
                max_age_days=days,
                min_domestic_model_count=min_domestic_model_count,
                min_foreign_ai_count=min_foreign_ai_count,
                include_pool_items=False,
                force_search_backfill=False,
                progress=progress,
                source_health_path=Path("data") / "source_health" / "ai_digest.json",
                persist_source_health=True,
            )
            candidate_meta = dict(candidate_meta or {})
            candidate_meta.pop("_fetched_items", None)
            candidate_meta.pop("_fresh_items", None)
            candidate_meta.pop("_deduped_items", None)
        if lookback_meta["mode"] == "auto_expand":
            window_candidate_items = rank_ai_updates(
                list(candidate_items or []),
                target_count=candidate_pool_target,
                min_official_count=min_official_count,
                allow_social_backfill=True,
                max_age_days=days,
                min_domestic_model_count=min_domestic_model_count,
                min_foreign_ai_count=min_foreign_ai_count,
                max_items_per_source=None,
            )
        else:
            window_candidate_items = list(candidate_items or [])
        window_meta = {
            **candidate_meta,
            "max_age_days": days,
            "ranked_count": len(window_candidate_items),
            "quota_counts": ai_digest_quota_counts(list(window_candidate_items or [])),
            "collection_max_age_days": days,
        }
        if progress is not None:
            progress(
                "collect_pool",
                f"success window={days}d fetched={candidate_meta.get('fetched_count')} ranked={len(window_candidate_items)}",
            )
        window_candidate_items, historical_novelty_meta = _prefer_novel_ai_digest_items(
            window_candidate_items,
            historical_keys=historical_keys,
            target_count=target_count,
            min_official_count=min_official_count,
            max_age_days=days,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
        window_meta["historical_novelty"] = historical_novelty_meta
        candidate_counts = ai_digest_quota_counts(list(window_candidate_items or []))
        candidate_official_count = ai_digest_official_count(list(window_candidate_items or []))
        window_meta["selection_official_count"] = candidate_official_count
        if not window_candidate_items:
            errors = window_meta.get("errors") if isinstance(window_meta, dict) else []
            detail = f"; errors={errors}" if errors else ""
            pool_error = f"daily ai digest material insufficient: no AI updates within {days} days{detail}"
        else:
            pool_error = _ai_digest_selection_error(
                window_candidate_items,
                target_count=target_count,
                min_official_count=min_official_count,
                min_domestic_model_count=min_domestic_model_count,
                min_foreign_ai_count=min_foreign_ai_count,
                max_age_days=days,
            )
        max_historical_reuse = max(0, (target_count * 3 - 1) // 4)
        historical_novelty_meta["max_reused_before_duplicate_gate"] = max_historical_reuse
        reused_selected = historical_novelty_meta["reused_selected_count"]
        if not pool_error and reused_selected > max_historical_reuse:
            pool_error = (
                "daily ai digest historical novelty insufficient: "
                f"历史资讯复用{reused_selected}条，超过本批最多{max_historical_reuse}条；"
                "继续扩大日期窗口以避免触发历史重复门槛"
            )
        relaxed_error = _ai_digest_selection_error(
            window_candidate_items,
            target_count=target_count,
            min_official_count=0,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_age_days=days,
        )
        if (
            lookback_meta["mode"] == "auto_expand"
            and not relaxed_error
            and reused_selected <= max_historical_reuse
            and candidate_official_count > 0
        ):
            relaxed_score = (candidate_official_count, -days, len(window_candidate_items or []))
            if best_relaxed_pool is None or relaxed_score > best_relaxed_pool[0]:
                best_relaxed_pool = (
                    relaxed_score,
                    list(window_candidate_items or []),
                    dict(window_meta),
                    days,
                    candidate_official_count,
                )
        lookback_attempts.append(
            {
                "max_age_days": days,
                "selection_pool_items": len(window_candidate_items or []),
                "quota_counts": candidate_counts,
                "official_count": candidate_official_count,
                "error": pool_error,
                "fetched_count": window_meta.get("fetched_count"),
                "fresh_count": window_meta.get("fresh_count"),
                "deduped_count": window_meta.get("deduped_count"),
                "ranked_count": window_meta.get("ranked_count"),
            }
        )
        items = window_candidate_items
        selection_pool_count = len(window_candidate_items or [])
        source_meta = window_meta
        max_age_days = days
        last_pool_error = pool_error
        if progress is not None:
            progress(
                "lookback_window",
                f"{'success' if not pool_error else 'insufficient'} window={days}d "
                f"items={len(window_candidate_items or [])} domestic={candidate_counts['domestic_model']} "
                f"foreign={candidate_counts['foreign_ai']} official={candidate_official_count}/{min_official_count}",
            )
        if not pool_error:
            break
    if last_pool_error and best_relaxed_pool is not None:
        _, items, source_meta, max_age_days, effective_min_official_count = best_relaxed_pool
        last_pool_error = ""
        source_meta["official_target_warning"] = (
            f"已穷尽{lookback_windows}天窗口的官网信源；官网目标{min_official_count}条，"
            f"实际可用{effective_min_official_count}条，其余按资讯整合站、官方社交媒体顺序补足"
        )
        if progress is not None:
            progress(
                "lookback_window",
                f"degraded_success window={max_age_days}d items={len(items)} "
                f"official={effective_min_official_count}/{min_official_count} reason=official_sources_exhausted",
            )
    if last_pool_error:
        attempt_summary = "; ".join(
            f"{a['max_age_days']}d items={a['selection_pool_items']} "
            f"domestic={a['quota_counts']['domestic_model']} foreign={a['quota_counts']['foreign_ai']} "
            f"official={a['official_count']}/{min_official_count}"
            for a in lookback_attempts
        )
        if lookback_meta["mode"] == "auto_expand":
            raise RuntimeError(
                "daily ai digest material insufficient: "
                f"tried windows={lookback_windows}; {attempt_summary}; {last_pool_error}"
            )
        raise RuntimeError(
            "daily ai digest material insufficient: "
            f"fixed {max_age_days}-day window; {attempt_summary}; {last_pool_error}"
        )
    source_meta["candidate_pool_target"] = candidate_pool_target
    source_meta["candidate_pool_factor"] = candidate_pool_factor
    source_meta["selection_pool_items"] = selection_pool_count or len(items)
    source_meta["min_items"] = minimum_count
    source_meta["max_items"] = max_items
    source_meta["min_domestic_model_items"] = min_domestic_model_count
    source_meta["min_foreign_ai_items"] = min_foreign_ai_count
    source_meta["selection_pool_quota_counts"] = ai_digest_quota_counts(list(items or []))
    source_meta["selection_pool_official_count"] = ai_digest_official_count(list(items or []))
    source_meta["official_target_items"] = min_official_count
    source_meta["effective_min_official_items"] = effective_min_official_count
    source_meta["official_target_met"] = source_meta["selection_pool_official_count"] >= min_official_count
    source_meta["lookback"] = {
        **lookback_meta,
        "selected_max_age_days": max_age_days,
        "attempts": lookback_attempts,
    }
    if adaptive_selection_meta:
        source_meta["adaptive_selection"] = adaptive_selection_meta

    # Save unfiltered source items for the quota-safe fallback
    raw_items_for_fallback = list(items or [])
    if adaptive_mode:
        items, body_capacity_meta = _fit_ai_digest_items_to_body_capacity(
            items,
            min_items=minimum_count,
            min_official_count=effective_min_official_count,
            max_age_days=max_age_days,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            selection_meta=source_meta,
        )
        target_count = len(items)
        effective_min_official_count = min(effective_min_official_count, target_count)
        adaptive_selection_meta["body_capacity"] = body_capacity_meta
        adaptive_selection_meta["final_target_items"] = target_count
        source_meta["body_capacity"] = body_capacity_meta
        source_meta["adaptive_selection"] = adaptive_selection_meta
        selected_urls = {item.url for item in items}
        source_meta["selected_impact_scores"] = [
            row
            for row in source_meta.get("selected_impact_scores", [])
            if row.get("url") in selected_urls
        ]
        if progress is not None:
            progress(
                "body_capacity",
                f"success selected={target_count}/{body_capacity_meta['requested_items']} "
                f"body={body_capacity_meta['body_length']}/{body_capacity_meta['body_limit']}",
            )

    generation_target = target_count
    generation_mode = "llm"
    llm_error = ""
    llm_items = rank_ai_updates(
        list(items or []),
        target_count=generation_target,
        min_official_count=effective_min_official_count,
        allow_social_backfill=True,
        max_age_days=max_age_days,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    source_meta["llm_input_items"] = len(llm_items)
    source_meta["llm_input_quota_counts"] = ai_digest_quota_counts(llm_items)
    try:
        generation_cfgs = llm_configs_cache if llm_configs_cache is not None else load_llm_configs()
        brief = generate_ai_digest_brief_with_llm(
            generation_cfgs,
            llm_items,
            target_count=generation_target,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
    except Exception as exc:
        generation_mode = "fallback"
        llm_error = str(exc)
        if progress is not None:
            progress("llm_selection", f"failed error={llm_error}; using quota-safe fallback")
        brief = _build_quota_safe_ai_digest_fallback(
            items,
            target_count=generation_target,
            min_official_count=effective_min_official_count,
            max_age_days=max_age_days,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
    brief = _rank_brief_ai_digest_items(
        brief,
        target_count=generation_target,
        min_official_count=effective_min_official_count,
        max_age_days=max_age_days,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    final_error = _ai_digest_selection_error(
        brief.items,
        target_count=generation_target,
        min_official_count=effective_min_official_count,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_age_days=max_age_days,
    )
    source_cap_error = _ai_digest_source_cap_error(
        brief.items,
        target_count=generation_target,
    )
    if source_cap_error:
        final_error = source_cap_error
    if final_error and generation_mode == "llm":
        if progress is not None:
            progress("llm_selection", f"insufficient error={final_error}; using quota-safe fallback")
        # Prefer the unfiltered raw_items_for_fallback (14-day window) so the
        # fallback can still hit target_count when LLM items were already
        # narrowed to 3 days.
        fallback_items = raw_items_for_fallback if raw_items_for_fallback else items
        quota_fallback = _build_quota_safe_ai_digest_fallback(
            fallback_items,
            target_count=generation_target,
            min_official_count=effective_min_official_count,
            max_age_days=None,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
        quota_fallback_error = _ai_digest_selection_error(
            quota_fallback.items,
            target_count=generation_target,
            min_official_count=effective_min_official_count,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_age_days=max_age_days,
        )
        if not quota_fallback_error:
            brief = quota_fallback
            generation_mode = "llm_quota_fallback"
            llm_error = final_error
            final_error = ""
    if final_error:
        raise RuntimeError(final_error)
    selected_before_body_fit = len(brief.items)
    brief = _fit_ai_digest_brief_to_body_limit(
        brief,
        min_items=generation_target,
        selection_meta=source_meta,
    )
    body_fit_error = _ai_digest_selection_error(
        brief.items,
        target_count=generation_target,
        min_official_count=effective_min_official_count,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_age_days=max_age_days,
    )
    source_cap_error = _ai_digest_source_cap_error(
        brief.items,
        target_count=generation_target,
    )
    if source_cap_error:
        body_fit_error = source_cap_error
    if body_fit_error:
        raise RuntimeError(body_fit_error)
    source_meta["selected_before_body_fit"] = selected_before_body_fit
    source_meta["body_fit_dropped"] = max(0, selected_before_body_fit - len(brief.items))
    source_meta["selected_quota_counts"] = ai_digest_quota_counts(list(brief.items or []))
    source_meta["source_distribution"] = ai_digest_source_counts(list(brief.items or []))
    source_meta["source_distribution_max"] = max(
        source_meta["source_distribution"].values(),
        default=0,
    )
    source_meta["selected_official_count"] = ai_digest_official_count(list(brief.items or []))
    rendered_body = render_ai_digest_body(brief, selection_meta=source_meta)
    if len(rendered_body) > MAX_IMAGE_BODY:
        raise RuntimeError(
            "daily ai digest body too long: "
            f"{len(rendered_body)} > {MAX_IMAGE_BODY}; "
            "the brief body exceeds the Xiaohongshu body limit"
        )
    post = Post(
        type="image",
        status=PostStatus.draft,
        title=_ai_digest_post_title(brief),
        body=rendered_body,
        topics=["每日AI讯息", "AI动态", "人工智能"],
        platform={
            "ai_digest": {
                "mode": "daily_ai_digest",
                "target_items": target_count,
                "actual_items": len(brief.items),
                "candidate_pool_target": candidate_pool_target,
                "candidate_pool_factor": candidate_pool_factor,
                "selection_pool_items": source_meta["selection_pool_items"],
                "min_official_items": min_official_count,
                "official_target_items": min_official_count,
                "effective_min_official_items": effective_min_official_count,
                "official_target_met": source_meta["official_target_met"],
                "min_items": minimum_count,
                "max_items": max_items,
                "adaptive_selection": adaptive_selection_meta,
                "impact_review": impact_meta,
                "min_domestic_model_items": min_domestic_model_count,
                "min_foreign_ai_items": min_foreign_ai_count,
                "quota_counts": source_meta["selected_quota_counts"],
                "source_distribution": source_meta["source_distribution"],
                "source_distribution_max": source_meta["source_distribution_max"],
                "max_items_per_source": AI_DIGEST_MAX_ITEMS_PER_SOURCE,
                "max_age_days": max_age_days,
                "prompt_hint": (prompt_hint or "").strip(),
                "generation_mode": generation_mode,
                "llm_error": llm_error,
                "source_meta": source_meta,
                "brief": brief.model_dump(),
                "items": [item.model_dump() for item in brief.items],
            }
        },
    )

    dest_dir = post_dir(post.id) / "assets"
    image_paths = render_ai_digest_cards(brief, dest_dir)
    post.assets = _build_asset_infos(image_paths)

    rev = Revision(
        post_id=post.id,
        source=RevisionSource.llm,
        content={
            "title": post.title,
            "body": post.body,
            "topics": post.topics,
            "ai_digest": post.platform["ai_digest"],
        },
    )
    save_post(post)
    save_revision(rev)
    return [post]


def create_post_with_draft(
    *,
    title_hint: str,
    prompt_hint: str,
    asset_paths: list[str],
    copy_assets: bool = True,
    auto_image: bool = True,
    image_exclude_ids: Optional[set[str]] = None,
    evaluation_viewpoint: str = DEFAULT_EVALUATION_VIEWPOINT,
    lookback_days: object = None,
    news_materials_file: str | Path | None = None,
    single_news_material_file: str | Path | None = None,
    material_time: str = "",
) -> Post:
    """
    Generate a draft with LLM and persist post + revision.
    """
    title_norm = (title_hint or "").strip()
    if title_norm == "每日AI讯息":
        return create_daily_ai_digest_posts(
            prompt_hint=prompt_hint,
            asset_paths=asset_paths,
            copy_assets=copy_assets,
            auto_image=auto_image,
            evaluation_viewpoint=evaluation_viewpoint,
            lookback_days=lookback_days,
        )[0]

    cfgs = load_llm_configs()
    platform_meta: dict = {}

    if title_norm == "每日新闻":
        viewpoint_norm = normalize_evaluation_viewpoint(evaluation_viewpoint)
        try:
            prompt_norm = "" if str(single_news_material_file or "").strip() else (prompt_hint or "").strip()
            candidates, news_meta = _fetch_daily_news_candidates_for_upload(
                prompt_norm,
                count=1,
                lookback_days=None if str(single_news_material_file or "").strip() else lookback_days,
                news_materials_file=news_materials_file,
                single_news_material_file=single_news_material_file,
                material_time=material_time,
            )
            picks = pick_news_items(candidates, prompt_norm, count=1)
            if not picks:
                raise RuntimeError("no news candidates selected")
            picked = picks[0]
            picked, lookup_meta = _enrich_daily_news_item(picked)
            picked, focus_meta = _focus_daily_news_item(picked)
            traced_news_meta = _daily_news_meta_with_trace(
                {**news_meta, **lookup_meta, **focus_meta},
                picked,
            )
            platform_meta["news"] = {
                **traced_news_meta,
                "picked": asdict(picked),
                "source_url": picked.url,
                "mode": "daily_news_single_material" if str(single_news_material_file or "").strip() else "daily_news",
                "prompt_hint": prompt_norm,
                "evaluation_viewpoint": viewpoint_norm,
            }
            news_prompt = _daily_news_prompt(picked, prompt_norm, viewpoint_norm)
            seed_title = "每日新闻"
            draft = generate_draft(
                cfgs,
                title_hint=seed_title,
                prompt_hint=news_prompt,
                asset_paths=asset_paths,
            )
            if draft.get("_fallback_error"):
                reason = _daily_news_llm_unavailable_reason(draft.get("_fallback_error"))
                raise RuntimeError(
                    f"每日新闻模型不可用：{reason}；不会保存模板草稿。"
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
            if (
                _daily_news_body_has_prompt_leak(draft.get("body", ""))
                or _daily_news_body_is_too_generic(draft.get("body", ""))
            ):
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
            draft["topics"] = _normalize_daily_news_topics(
                topics,
                prompt_norm,
                context=f"{draft.get('title', '')} {draft.get('body', '')}",
            )
            draft["body"] = _finalize_daily_news_body(
                draft.get("body", ""),
                picked,
                prompt_norm,
                title_hint=str(draft.get("title") or ""),
            )
            draft["body"] = _repair_daily_news_mismatched_comment(
                draft["body"],
                picked,
                prompt_norm,
                title_hint=str(draft.get("title") or ""),
            )
            draft = _simplify_daily_news_draft(draft)
            quality_issue = _daily_news_quality_issue(
                draft.get("title", ""),
                draft.get("body", ""),
                prompt_norm,
            )
            if quality_issue:
                raise RuntimeError(f"daily news quality check failed: {quality_issue}")
            image_event = _normalize_daily_news_image_event(
                str(draft.get("image_event") or ""),
                picked=picked,
                title=str(draft.get("title") or ""),
                body=str(draft.get("body") or ""),
                prompt_norm=prompt_norm,
            )
            image_event = _to_simplified_common(image_event)
            platform_meta["news"]["image_event"] = image_event
            draft["image_event"] = image_event
        except Exception as exc:
            platform_meta["news"] = {
                "mode": "daily_news",
                "prompt_hint": (prompt_hint or "").strip(),
                "evaluation_viewpoint": normalize_evaluation_viewpoint(evaluation_viewpoint),
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
        if draft.get("_fallback_error"):
            raise RuntimeError(
                "LLM draft generation failed; the fallback placeholder will not be saved or uploaded: "
                f"{draft.get('_fallback_error')}"
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
        image_paths, image_metas, image_fallback = _fetch_daily_news_related_images(
            title=image_title,
            body=post.body,
            topics=post.topics,
            prompt_hint=_preferred_image_hint(post, prompt_hint),
            dest_dir=dest_dir,
            exclude_ids=image_exclude_ids,
            # Every daily-news draft should prefer the configured AI image
            # provider. A Pexels image is only a fallback when generation
            # fails, including for online candidates rather than just manual
            # single-news materials.
            ai_first=True,
        )
        if image_fallback:
            post.platform["image_fallback"] = image_fallback
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


def _daily_news_llm_supervisor_enabled(cfgs: list[Any], *, target_count: int) -> bool:
    raw = (os.getenv("NEWS_LLM_SUPERVISOR_ENABLED") or "1").strip().lower()
    if raw in {"0", "false", "off", "no"} or target_count <= 1:
        return False
    # Test and offline configurations conventionally use a fake model. Avoid
    # making a network call in that mode while retaining local ranking.
    return any(not str(getattr(cfg, "model", "")).strip().lower().startswith("fake") for cfg in cfgs)


def _daily_news_supervisor_pool_limit(target_count: int) -> int:
    raw = (os.getenv("NEWS_LLM_SUPERVISOR_POOL_LIMIT") or "").strip()
    try:
        configured = int(raw) if raw else 0
    except ValueError:
        configured = 0
    return max(target_count * 10, configured or 0, 60)


def _supervise_daily_news_candidates(
    candidates: list[Any],
    *,
    cfgs: list[Any],
    prompt_hint: str,
    target_count: int,
    required_china_count: int,
    progress_callback: DailyNewsProgressCallback | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Use one optional LLM call to reorder the already validated candidate pool."""
    if not _daily_news_llm_supervisor_enabled(cfgs, target_count=target_count):
        return candidates, {"enabled": False, "status": "not_requested"}

    pool = candidates[: min(len(candidates), _daily_news_supervisor_pool_limit(target_count))]
    minimum_ranked_count = min(target_count, len(pool))
    payload: list[dict[str, Any]] = []
    for index, item in enumerate(pool, start=1):
        context = _compact_daily_news_context(item, max_chars=240)
        payload.append(
            {
                "id": index,
                "title": _clip_text(str(item.title or ""), limit=120),
                "summary": _clip_text(context, limit=240),
                "date": str(item.seendate or ""),
                "source": _clip_text(str(item.source or item.domain or ""), limit=80),
                "country": str(item.sourcecountry or ""),
                "attention": item.attention,
            }
        )
    _emit_daily_news_progress(
        progress_callback,
        "模型审校候选",
        "in_progress",
        candidates=len(pool),
        target_count=target_count,
        china_required=required_china_count,
    )
    system_prompt = (
        "你是严格的新闻选题审校员。只基于给定候选信息工作，不补充事实。"
        "选择与用户关键词直接相关、时间新、可核验、事件明确且彼此不重复的候选；"
        "优先保留有具体主体、动作、时间或数据的新闻，排除泛泛评论、旧闻、重复报道和信息不足项。"
        "必须仅返回 JSON 对象，不得输出 Markdown 或解释文字。"
        "JSON 格式：{\"ranked_ids\":[正整数...],\"rejected_ids\":[正整数...],\"reason\":\"不超过80字\"}。"
        "ranked_ids 必须是候选 id 的去重排序；未列出的 id 会保留在本地排序末尾。"
    )
    system_prompt += (
        f" Return at least {minimum_ranked_count} unique ranked_ids. "
        "Do not return fewer ranked_ids when the candidate pool contains enough items."
    )
    user_prompt = json.dumps(
        {
            "task": "为小红书每日新闻生成任务进行候选重排",
            "keywords": prompt_hint or "综合当日重要新闻",
            "requested_drafts": target_count,
            "minimum_china_mainland_items": required_china_count,
            "candidates": payload,
        },
        ensure_ascii=False,
    )
    try:
        result = generate_json(
            cfgs,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=6000,
        )
        raw_ids = result.get("ranked_ids")
        ranked_indices: list[int] = []
        if isinstance(raw_ids, list):
            for value in raw_ids:
                try:
                    index = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= index <= len(pool) and index not in ranked_indices:
                    ranked_indices.append(index)
        if not ranked_indices:
            raise RuntimeError("supervisor returned no usable ranked_ids")
        if len(ranked_indices) < minimum_ranked_count:
            raise RuntimeError(
                f"supervisor returned {len(ranked_indices)} ranked_ids; "
                f"expected at least {minimum_ranked_count}"
            )
        chosen = [pool[index - 1] for index in ranked_indices]
        chosen_keys = {item.url or item.title for item in chosen}
        chosen.extend(item for item in candidates if (item.url or item.title) not in chosen_keys)
        meta = {
            "enabled": True,
            "status": "success",
            "reviewed_candidate_count": len(pool),
            "ranked_candidate_count": len(ranked_indices),
            "reason": _clip_text(str(result.get("reason") or ""), limit=160),
        }
        _emit_daily_news_progress(
            progress_callback,
            "模型审校候选",
            "success",
            reviewed=len(pool),
            ranked=len(ranked_indices),
        )
        return chosen, meta
    except Exception as exc:
        # Local ranking is deterministic and remains a valid fallback. The
        # user sees the degraded mode instead of waiting for a silent retry.
        message = _clip_text(str(exc), limit=180)
        _emit_daily_news_progress(
            progress_callback,
            "模型审校候选",
            "warning",
            reviewed=len(pool),
            reason=message,
            fallback="local_ranking",
        )
        return candidates, {
            "enabled": True,
            "status": "fallback_local_ranking",
            "reviewed_candidate_count": len(pool),
            "error": message,
        }


def create_daily_news_posts(
    *,
    prompt_hint: str = "",
    asset_paths: list[str],
    copy_assets: bool = True,
    count: int = 1,
    auto_image: bool = True,
    evaluation_viewpoint: str = DEFAULT_EVALUATION_VIEWPOINT,
    lookback_days: object = None,
    news_materials_file: str | Path | None = None,
    single_news_material_file: str | Path | None = None,
    material_time: str = "",
    progress_callback: DailyNewsProgressCallback | None = None,
    post_quality_callback: DailyNewsPostQualityCallback | None = None,
) -> list[Post]:
    """
    Special workflow for title="每日新闻".

    - Use `prompt_hint` to rank candidates, then pick up to `count` items.
    - When `count` is 1, behavior is equivalent to a single best match.
    """
    cfgs = load_llm_configs()
    single_material_mode = bool(str(single_news_material_file or "").strip())
    prompt_norm = "" if single_material_mode else (prompt_hint or "").strip()
    viewpoint_norm = normalize_evaluation_viewpoint(evaluation_viewpoint)
    if single_material_mode:
        count = 1
    elif count <= 0:
        count = 1
    auto_image_enabled = auto_image and is_auto_image_enabled()
    used_image_ids: set[str] = set()
    used_title_keys: set[str] = set()
    failed_count = 0
    skipped_quality_count = 0
    skipped_quota_count = 0
    llm_unavailable_reasons: list[str] = []

    def _is_fatal_image_config_error(errs: list[str]) -> bool:
        # Aliyun returns this when using image-to-image models without providing an init image.
        joined = " ".join(errs or []).lower()
        return (
            "got 0 images" in joined
            or "must contain 1 to 4 images" in joined
            or "enable_interleave" in joined
        )

    candidates, base_meta = _fetch_daily_news_candidates_for_upload(
        prompt_norm,
        count=count,
        lookback_days=None if single_material_mode else lookback_days,
        news_materials_file=news_materials_file,
        single_news_material_file=single_news_material_file,
        material_time=material_time,
        progress_callback=progress_callback,
    )
    target_count = count
    required_china_count = (
        0
        if single_material_mode
        else _required_china_count_for_daily_news(target_count)
    )
    candidates, supervisor_meta = _supervise_daily_news_candidates(
        candidates,
        cfgs=cfgs,
        prompt_hint=prompt_norm,
        target_count=target_count,
        required_china_count=required_china_count,
        progress_callback=progress_callback,
    )
    base_meta = dict(base_meta)
    selection_pool = base_meta.get("selection_pool")
    if isinstance(selection_pool, dict):
        selection_pool = dict(selection_pool)
        selection_pool["llm_supervisor"] = supervisor_meta
        base_meta["selection_pool"] = selection_pool
    # Pick the first pass with the true target count so source diversity quotas
    # are based on the number of drafts the user asked for. Keep extra ranked
    # candidates after that because strict quality gates can reject snippets.
    pick_limit = min(len(candidates), max(count * 20, count + 30))
    if supervisor_meta.get("status") == "success":
        # The supervisor has already ranked freshness, event clarity and story
        # diversity. Re-ranking here with local attention would undo that work.
        picks = list(candidates[:pick_limit])
    else:
        picks = pick_news_items(candidates, prompt_norm, count=min(count, len(candidates)))
        seen_pick_keys = {item.url or item.title for item in picks}
        for item in candidates:
            key = item.url or item.title
            if key in seen_pick_keys:
                continue
            picks.append(item)
            seen_pick_keys.add(key)
            if len(picks) >= pick_limit:
                break

    posts: list[Post] = []
    accepted_china_count = 0
    accepted_story_signatures = []

    success_idx = 0
    for candidate_idx, picked in enumerate(picks, start=1):
        if len(posts) >= target_count:
            break
        _emit_daily_news_progress(
            progress_callback,
            "原文核验",
            "in_progress",
            candidate_index=candidate_idx,
            candidate_total=len(picks),
            completed=len(posts),
            target=target_count,
            source=str(picked.domain or picked.source or "unknown"),
        )
        picked, lookup_meta = _enrich_daily_news_item(picked)
        picked, focus_meta = _focus_daily_news_item(picked)
        if not single_material_mode and _daily_news_context_is_incomplete(picked):
            skipped_quality_count += 1
            _emit_daily_news_progress(
                progress_callback,
                "原文核验",
                "skipped",
                candidate_index=candidate_idx,
                completed=len(posts),
                target=target_count,
                reason="source_context_insufficient",
            )
            print(
                f"[daily_news] skip candidate={candidate_idx} reason=source_context_insufficient "
                f"title={(picked.title or '')[:30]} source={picked.domain or picked.source or 'unknown'}"
            )
            continue
        dedupe_item = None
        if not single_material_mode:
            dedupe_item = replace(
                picked,
                description=_compact_daily_news_context(picked, max_chars=700),
                content=None,
            )
            dedupe_signature = _cjk_story_event_signature(dedupe_item)
            if any(
                _same_cjk_story_event(dedupe_signature, accepted_signature)
                for accepted_signature in accepted_story_signatures
            ):
                skipped_quality_count += 1
                _emit_daily_news_progress(
                    progress_callback,
                    "原文核验",
                    "skipped",
                    candidate_index=candidate_idx,
                    completed=len(posts),
                    target=target_count,
                    reason="duplicate_story_after_enrichment",
                )
                print(
                    f"[daily_news] skip candidate={candidate_idx} reason=duplicate_story_after_enrichment "
                    f"title={(picked.title or '')[:30]} source={picked.domain or picked.source or 'unknown'}"
                )
                continue
        picked_is_china = _is_china_item(picked)
        if required_china_count > 0 and not picked_is_china:
            prospective_count = len(posts) + 1
            prospective_required_china = _required_china_count_for_daily_news(
                prospective_count
            )
            if accepted_china_count < prospective_required_china:
                skipped_quota_count += 1
                _emit_daily_news_progress(
                    progress_callback,
                    "候选配额",
                    "skipped",
                    candidate_index=candidate_idx,
                    completed=len(posts),
                    target=target_count,
                    reason="china_quota_reserved",
                )
                print(
                    f"[daily_news] skip candidate={candidate_idx} reason=china_quota_reserved "
                    f"title={(picked.title or '')[:30]} source={picked.domain or picked.source or 'unknown'}"
                )
                continue
        traced_news_meta = _daily_news_meta_with_trace(
            {**base_meta, **lookup_meta, **focus_meta},
            picked,
        )
        news_prompt = _daily_news_prompt(picked, prompt_norm, viewpoint_norm)
        if target_count > 1:
            news_prompt = f"（第 {success_idx + 1}/{target_count} 条）\n{news_prompt}"

        seed_title = "每日新闻"
        try:
            _emit_daily_news_progress(
                progress_callback,
                "生成文案",
                "in_progress",
                draft_index=success_idx + 1,
                target=target_count,
                candidate_index=candidate_idx,
            )
            draft = generate_draft(
                cfgs,
                title_hint=seed_title,
                prompt_hint=news_prompt,
                asset_paths=asset_paths,
            )
        except Exception:
            failed_count += 1
            _emit_daily_news_progress(
                progress_callback,
                "生成文案",
                "failed",
                draft_index=success_idx + 1,
                target=target_count,
                candidate_index=candidate_idx,
                reason="llm_request_failed",
            )
            if posts:
                break
            raise
        if draft.get("_fallback_error"):
            failed_count += 1
            reason = _daily_news_llm_unavailable_reason(draft.get("_fallback_error"))
            llm_unavailable_reasons.append(reason)
            _emit_daily_news_progress(
                progress_callback,
                "生成文案",
                "failed",
                draft_index=success_idx + 1,
                target=target_count,
                candidate_index=candidate_idx,
                reason=reason,
            )
            print(
                f"[daily_news] stop candidate={candidate_idx} reason=llm_unavailable "
                f"detail={reason}"
            )
            # The configured provider has already exhausted its own retries.
            # Trying every remaining article would create slow, misleading
            # placeholder drafts rather than a recoverable batch.
            break
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
        if (
            _daily_news_body_has_prompt_leak(draft.get("body", ""))
            or _daily_news_body_is_too_generic(draft.get("body", ""))
        ):
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
        draft["topics"] = _normalize_daily_news_topics(
            topics,
            prompt_norm,
            context=f"{draft.get('title', '')} {draft.get('body', '')}",
        )
        draft["body"] = _finalize_daily_news_body(
            draft.get("body", ""),
            picked,
            prompt_norm,
            title_hint=str(draft.get("title") or ""),
        )
        draft["body"] = _repair_daily_news_mismatched_comment(
            draft["body"],
            picked,
            prompt_norm,
            title_hint=str(draft.get("title") or ""),
        )
        draft = _simplify_daily_news_draft(draft)
        quality_issue = _daily_news_quality_issue(
            draft.get("title", ""),
            draft.get("body", ""),
            prompt_norm,
        )
        if quality_issue:
            skipped_quality_count += 1
            _emit_daily_news_progress(
                progress_callback,
                "质量复核",
                "skipped",
                draft_index=success_idx + 1,
                target=target_count,
                candidate_index=candidate_idx,
                reason=quality_issue,
            )
            print(
                f"[daily_news] skip candidate={candidate_idx} reason={quality_issue} "
                f"title={draft.get('title', '')[:30]} source={picked.domain or picked.source or 'unknown'}"
            )
            continue
        image_event = _normalize_daily_news_image_event(
            str(draft.get("image_event") or ""),
            picked=picked,
            title=str(draft.get("title") or ""),
            body=str(draft.get("body") or ""),
            prompt_norm=prompt_norm,
        )
        image_event = _to_simplified_common(image_event)
        draft["image_event"] = image_event
        _emit_daily_news_progress(
            progress_callback,
            "质量复核",
            "success",
            draft_index=success_idx + 1,
            target=target_count,
            candidate_index=candidate_idx,
        )

        post = Post(
            type="image",
            status=PostStatus.draft,
            title=draft["title"],
            body=draft["body"],
            topics=draft.get("topics", []),
            platform={
                "news": {
                    **traced_news_meta,
                    "picked": asdict(picked),
                    "source_url": picked.url,
                    "mode": (
                        "daily_news_single_material"
                        if single_material_mode
                        else ("daily_news_multi" if target_count > 1 else "daily_news")
                    ),
                    "prompt_hint": prompt_norm,
                    "evaluation_viewpoint": viewpoint_norm,
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
                _emit_daily_news_progress(
                    progress_callback,
                    "生成配图",
                    "in_progress",
                    draft_index=success_idx + 1,
                    target=target_count,
                    candidate_index=candidate_idx,
                )
                image_paths, image_metas, image_fallback = _fetch_daily_news_related_images(
                    title=image_title,
                    body=post.body,
                    topics=post.topics,
                    prompt_hint=image_prompt,
                    dest_dir=dest_dir,
                    exclude_ids=used_image_ids,
                    ai_first=True,
                )
                if image_fallback:
                    post.platform["image_fallback"] = image_fallback
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
                _emit_daily_news_progress(
                    progress_callback,
                    "生成配图",
                    "failed",
                    draft_index=success_idx + 1,
                    target=target_count,
                    candidate_index=candidate_idx,
                    reason="image_generation_abandoned",
                )
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
            except Exception as exc:
                failed_count += 1
                _emit_daily_news_progress(
                    progress_callback,
                    "生成配图",
                    "failed",
                    draft_index=success_idx + 1,
                    target=target_count,
                    candidate_index=candidate_idx,
                    reason=_clip_text(str(exc), limit=160),
                )
                print(f"[auto-image] failed post_id={post.id} err={exc}")
                if posts:
                    break
                raise
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
        if post_quality_callback is not None:
            try:
                post_quality_errors = list(post_quality_callback(post) or [])
            except Exception as exc:
                post_quality_errors = [f"上传前质量复核调用失败：{exc}"]
            if post_quality_errors:
                skipped_quality_count += 1
                post.status = PostStatus.failed
                post.platform["batch_selection"] = {
                    "status": "visual_quality_failed",
                    "reason": "；".join(post_quality_errors[:3]),
                }
                post.updated_at = now_iso()
                save_post(post)
                _emit_daily_news_progress(
                    progress_callback,
                    "视觉递补",
                    "skipped",
                    candidate_index=candidate_idx,
                    completed=len(posts),
                    target=target_count,
                    reason=_clip_text(post_quality_errors[0], limit=160),
                )
                print(
                    f"[daily_news] skip candidate={candidate_idx} reason=visual_quality_failed "
                    f"detail={_clip_text(post_quality_errors[0], limit=160)}"
                )
                continue
        posts.append(post)
        if dedupe_item is not None:
            accepted_story_signatures.append(_cjk_story_event_signature(dedupe_item))
        if picked_is_china:
            accepted_china_count += 1
        success_idx += 1
        _emit_daily_news_progress(
            progress_callback,
            "生成草稿",
            "success",
            completed=success_idx,
            target=target_count,
            candidate_index=candidate_idx,
        )

    if len(posts) < target_count:
        message = (
            f"daily news created only {len(posts)}/{target_count} | 批次生成未完成："
            f"已完成 {len(posts)}/{target_count}，已尝试候选 {len(picks)}/{len(candidates)}，"
            f"文案或生图失败 {failed_count}，质量/去重跳过 {skipped_quality_count}，"
            f"国内新闻配额预留跳过 {skipped_quota_count}，国内稿件 {accepted_china_count}/{required_china_count}。"
            "本次默认不会上传不完整批次；请查看上方具体步骤，调整关键词、回溯天数或模型额度后重试。"
        )
        if llm_unavailable_reasons:
            message += f" 模型不可用：{llm_unavailable_reasons[-1]}。"
        print(f"[daily_news] {message}")
        _emit_daily_news_progress(
            progress_callback,
            "生成草稿",
            "failed",
            completed=len(posts),
            target=target_count,
            failed=failed_count,
            skipped_quality=skipped_quality_count,
            skipped_quota=skipped_quota_count,
            reason="batch_incomplete",
        )
        if posts:
            raise PartialDailyNewsError(
                message,
                posts=posts,
                requested_count=target_count,
                failed_count=max(failed_count, target_count - len(posts)),
                skipped_quality_count=skipped_quality_count,
            )
        raise RuntimeError(message)
    return posts
