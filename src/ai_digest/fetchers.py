from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from .models import AIUpdateItem


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?</\1>", " ", text or "")
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_datetime(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return text


_ENGLISH_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_ENGLISH_MONTH_PATTERN = "|".join(sorted(_ENGLISH_MONTHS, key=len, reverse=True))


def _english_release_date(value: str) -> str:
    patterns = (
        rf"\b(?P<month>{_ENGLISH_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(?P<year>20\d{{2}})\b",
        rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_ENGLISH_MONTH_PATTERN})\.?[,]?\s+(?P<year>20\d{{2}})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        month = _ENGLISH_MONTHS.get(match.group("month").lower())
        if month is None:
            continue
        try:
            return datetime(int(match.group("year")), month, int(match.group("day"))).date().isoformat()
        except ValueError:
            continue
    return ""


def _extract_release_date(text: str) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if not value:
        return ""
    english_date = _english_release_date(value)
    if english_date:
        return english_date
    match = re.search(r"(?P<y>20\d{2})[年/-](?P<m>\d{1,2})[月/-](?P<d>\d{1,2})日?", value)
    if match:
        return f"{int(match.group('y')):04d}-{int(match.group('m')):02d}-{int(match.group('d')):02d}"
    match = re.search(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日", value)
    if not match:
        return ""
    today = datetime.now(timezone.utc).date()
    year = today.year
    month = int(match.group("m"))
    day = int(match.group("d"))
    try:
        candidate = datetime(year, month, day).date()
    except ValueError:
        return ""
    if candidate > today:
        year -= 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _date_from_match(match: re.Match[str]) -> str:
    return f"{int(match.group('y')):04d}-{int(match.group('m')):02d}-{int(match.group('d')):02d}"


def _extract_page_release_date(html_text: str) -> str:
    raw = html_text or ""
    patterns = (
        r"(?is)\bdatePublished\b.{0,120}?(?P<y>20\d{2})[-/年](?P<m>\d{1,2})[-/月](?P<d>\d{1,2})",
        r"(?is)\bDate\b.{0,240}?(?P<y>20\d{2})[-/年](?P<m>\d{1,2})[-/月](?P<d>\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return _date_from_match(match)

    published_ms = re.search(r'\\?"published_at\\?"\s*:\s*(?P<ts>\d{12,14})', raw)
    if published_ms:
        try:
            dt = datetime.fromtimestamp(int(published_ms.group("ts")) / 1000, tz=timezone.utc)
            return dt.date().isoformat()
        except (OverflowError, ValueError, OSError):
            pass

    return ""


def _child_text(node, tag_names: list[str]) -> str:
    for tag in tag_names:
        found = node.find(tag)
        if found is not None and (found.text or "").strip():
            return (found.text or "").strip()
    for child in list(node):
        short = child.tag.rsplit("}", 1)[-1].lower()
        if short in {name.lower() for name in tag_names} and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def parse_rss_feed(
    xml_text: str,
    *,
    source_name: str,
    vendor: str,
) -> list[AIUpdateItem]:
    root = ET.fromstring(xml_text)
    nodes = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items: list[AIUpdateItem] = []
    for node in nodes:
        title = _strip_html(_child_text(node, ["title"]))
        link = _child_text(node, ["link"])
        if not link:
            link_node = node.find("{http://www.w3.org/2005/Atom}link")
            if link_node is not None:
                link = str(link_node.attrib.get("href") or "")
        published = _parse_datetime(_child_text(node, ["pubDate", "published", "updated"]))
        description = _strip_html(_child_text(node, ["description", "summary", "content"]))
        if not title:
            continue
        items.append(
            AIUpdateItem(
                title=title,
                summary=description[:220],
                source_name=source_name,
                source_type="official",
                url=link,
                published_at=published,
                vendor=vendor,
                product="",
                raw_excerpt=description,
                tags=["AI", vendor],
            )
        )
    return items


def parse_github_releases_json(
    payload: str,
    *,
    source_name: str,
    vendor: str,
) -> list[AIUpdateItem]:
    raw = json.loads(payload)
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("releases") or []
    items: list[AIUpdateItem] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("name") or entry.get("tag_name") or "").strip()
        if not title:
            continue
        body = _strip_html(str(entry.get("body") or ""))
        items.append(
            AIUpdateItem(
                title=title,
                summary=body[:220],
                source_name=source_name,
                source_type="github",
                url=str(entry.get("html_url") or ""),
                published_at=str(entry.get("published_at") or entry.get("created_at") or ""),
                vendor=vendor,
                product="GitHub Release",
                raw_excerpt=body,
                tags=["AI", "GitHub", vendor],
            )
        )
    return items


_OFFICIAL_HTML_KEYWORDS = (
    "glm",
    "ernie",
    "qwen",
    "kimi",
    "doubao",
    "minimax",
    "abab",
    "文心",
    "千帆",
    "豆包",
    "智谱",
    "通义",
    "模型",
    "大模型",
    "发布",
    "更新",
    "上新",
    "升级",
    "推理",
    "多模态",
    "视觉",
    "语音",
)

_OFFICIAL_HTML_EN_KEYWORD_RE = re.compile(
    r"\b(?:ai|api|glm|ernie|qwen|kimi|doubao|minimax|abab|model|models|release|releases|changelog|agent)\b",
    re.IGNORECASE,
)

_OFFICIAL_HTML_NOISE = (
    "use this file",
    "available pages",
    "exploring further",
    "home page",
    "home models blog",
    "api docs",
    "blogs",
    "开放文档",
    "文档指南",
    "api参考",
    "订阅",
    "资源",
    "登录",
    "注册",
    "控制台",
    "用户指南",
    "计费说明",
    "服务计费",
    "默认参数",
    "调用文档",
    "接入指南",
    "快速开始",
    "复制",
    "下载",
    "反馈",
    "收藏",
    "上一页",
    "下一页",
    "目录",
    "frontier ai llms",
    "assistants, agents, services",
    "latest models",
    "products solutions",
    "模型能力总览",
    "开放平台文档中心",
    "联系我们",
    "隐私",
)

_OFFICIAL_HTML_HARD_NOISE = (
    "模型上下架",
    "服务协议",
    "监控告警",
    "release notes",
    "terms of service",
    "license terms",
    "responsible ai development policy",
    "training data disclosure",
    "select a category",
    "customer stories models news products research",
)

_OFFICIAL_HTML_RELEASE_SIGNALS = (
    "发布",
    "更新",
    "上新",
    "升级",
    "开源",
    "推出",
    "适配",
    "新增",
    "提升",
    "release",
    "released",
    "launch",
    "launched",
    "announce",
    "announced",
    "changelog",
)


def _html_lines(html_text: str) -> list[str]:
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html_text or "")
    cleaned = re.sub(r"(?i)</(?:p|li|h[1-6]|td|th|tr|div|section|article)>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    lines: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\r\n]+", cleaned):
        line = re.sub(r"\s+", " ", raw).strip(" -|·\t")
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def _official_article_body_html(html_text: str) -> str:
    """Return a site's explicit article body, without nearby navigation chrome."""
    raw = html_text or ""
    match = re.search(
        r"(?is)<(?P<tag>div|article|main)\b(?=[^>]*\bclass\s*=\s*(?:\"[^\"]*\bpost__body\b[^\"]*\"|'[^']*\bpost__body\b[^']*'))[^>]*>",
        raw,
    )
    if not match:
        return raw

    tag = match.group("tag")
    depth = 1
    token_pattern = re.compile(rf"(?is)</?{re.escape(tag)}\b[^>]*>")
    for token in token_pattern.finditer(raw, match.end()):
        if token.group(0).lstrip().startswith("</"):
            depth -= 1
            if depth == 0:
                return raw[match.end() : token.start()]
        elif not token.group(0).rstrip().endswith("/>"):
            depth += 1
    return raw[match.end() :]


def _looks_like_official_ai_update(text: str, vendor: str) -> bool:
    value = re.sub(r"\s+", " ", text or "").strip()
    if len(value) < 8 or len(value) > 260:
        return False
    low = value.lower()
    has_release_signal = any(signal in low or signal in value for signal in _OFFICIAL_HTML_RELEASE_SIGNALS)
    if any(noise in low or noise in value for noise in _OFFICIAL_HTML_HARD_NOISE):
        return False
    if any(noise in low or noise in value for noise in _OFFICIAL_HTML_NOISE) and not has_release_signal:
        return False
    return (
        bool(_OFFICIAL_HTML_EN_KEYWORD_RE.search(value))
        or any(keyword in value for keyword in _OFFICIAL_HTML_KEYWORDS)
    )


def _official_release_signal_score(item: AIUpdateItem) -> int:
    title = item.title or ""
    low = title.lower()
    score = 0
    if any(signal in low or signal in title for signal in _OFFICIAL_HTML_RELEASE_SIGNALS):
        score += 3
    if re.search(r"\b(?:glm|qwen|kimi|doubao|seed|deepseek|minimax|ernie|abab)[-\w.]*\b", title, re.IGNORECASE):
        score += 2
    if any(marker in title for marker in ("模型", "大模型", "Agent", "智能体", "API")):
        score += 1
    return score


def _limit_page_release_items(items: list[AIUpdateItem], page_release_date: str) -> list[AIUpdateItem]:
    if not page_release_date or len(items) <= 1:
        return items
    dated = [item for item in items if item.published_at == page_release_date]
    if not dated:
        return items
    ranked = sorted(
        dated,
        key=lambda item: (_official_release_signal_score(item), -len(item.title or "")),
        reverse=True,
    )
    selected = [item for item in ranked if _official_release_signal_score(item) > 0]
    return selected[:1] or ranked[:1]


def _with_published_at(item: AIUpdateItem, published_at: str) -> AIUpdateItem:
    data = item.model_dump()
    data["published_at"] = published_at
    return AIUpdateItem.model_validate(data)


def _apply_page_release_date(items: list[AIUpdateItem], page_release_date: str) -> list[AIUpdateItem]:
    """Use article-level dates only when item-level dates are absent.

    Listing pages and home pages often expose a page render time that is not the
    release time of each visible model update. Keep undated snippets undated
    unless an explicit article date is available, and then attach it to only the
    strongest release-like candidate.
    """
    if not page_release_date or not items:
        return items
    if any(item.published_at for item in items):
        return _limit_page_release_items(items, page_release_date)
    ranked = sorted(
        items,
        key=lambda item: (_official_release_signal_score(item), -len(item.title or "")),
        reverse=True,
    )
    selected = ranked[:1] if len(ranked) > 1 else ranked
    if not selected or _official_release_signal_score(selected[0]) <= 0:
        return items
    return [_with_published_at(item, page_release_date) for item in selected]


def parse_official_html(
    html_text: str,
    *,
    source_name: str,
    vendor: str,
    base_url: str = "",
) -> list[AIUpdateItem]:
    """Extract release/update-like snippets from official product documentation pages."""
    items: list[AIUpdateItem] = []
    seen_titles: set[str] = set()
    current_date = ""
    page_release_date = _extract_page_release_date(html_text)
    article_html = _official_article_body_html(html_text)

    for line in _html_lines(article_html):
        line_date = _extract_release_date(line)
        if line_date:
            current_date = line_date
        if not _looks_like_official_ai_update(line, vendor):
            continue
        title = line[:90].strip()
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        items.append(
            AIUpdateItem(
                title=title,
                summary=line[:220],
                source_name=source_name,
                source_type="official",
                url=base_url,
                published_at=line_date or current_date,
                vendor=vendor,
                product="",
                raw_excerpt=line,
                tags=["AI", "official", vendor],
            )
        )
        if len(items) >= 30:
            break

    if items:
        return _apply_page_release_date(items, page_release_date)

    parser = _LinkCollector()
    parser.feed(html_text or "")
    for href, text in parser.links:
        if not _looks_like_official_ai_update(text, vendor):
            continue
        title = text[:90].strip()
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        items.append(
            AIUpdateItem(
                title=title,
                summary=text[:220],
                source_name=source_name,
                source_type="official",
                url=urljoin(base_url, href),
                published_at=_extract_release_date(text),
                vendor=vendor,
                product="",
                raw_excerpt=text,
                tags=["AI", "official", vendor],
            )
        )
        if len(items) >= 30:
            break

    return _apply_page_release_date(items, page_release_date)


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        self._href = str(attrs_dict.get("href") or "")
        self._text_parts = []

    def handle_data(self, data):
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._href:
            return
        text = re.sub(r"\s+", " ", unescape(" ".join(self._text_parts))).strip()
        self.links.append((self._href, text))
        self._href = ""
        self._text_parts = []


def parse_social_search_html(
    html_text: str,
    *,
    source_name: str,
    vendor: str,
    base_url: str = "",
) -> list[AIUpdateItem]:
    parser = _LinkCollector()
    parser.feed(html_text or "")
    items: list[AIUpdateItem] = []
    seen: set[str] = set()
    for href, text in parser.links:
        url = urljoin(base_url, href)
        if not re.search(r"(?:x\.com|twitter\.com|youtube\.com|reddit\.com|news\.ycombinator\.com)", url):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = text[:80].strip() or url
        items.append(
            AIUpdateItem(
                title=title,
                summary=text[:220],
                source_name=source_name,
                source_type="social",
                url=url,
                published_at="",
                vendor=vendor,
                product="",
                raw_excerpt=text,
                tags=["AI", "social", vendor],
            )
        )
    return items


def parse_x_profile_html(
    html_text: str,
    *,
    source_name: str,
    vendor: str,
) -> list[AIUpdateItem]:
    """Parse X public syndication timelines without a logged-in browser."""
    match = re.search(
        r'(?is)<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(?P<payload>.*?)</script>',
        html_text or "",
    )
    if not match:
        return []
    try:
        payload = json.loads(unescape(match.group("payload")))
        entries = payload["props"]["pageProps"]["timeline"]["entries"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return []

    items: list[AIUpdateItem] = []
    seen_urls: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        tweet = ((entry or {}).get("content") or {}).get("tweet") or {}
        if not isinstance(tweet, dict):
            continue
        text = re.sub(r"\s+", " ", str(tweet.get("full_text") or tweet.get("text") or "")).strip()
        permalink = str(tweet.get("permalink") or "").strip()
        if not text or not permalink:
            continue
        url = urljoin("https://x.com", permalink)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        user = tweet.get("user") or {}
        display_name = str(user.get("name") or source_name).strip()
        screen_name = str(user.get("screen_name") or "").strip()
        profile_name = f"X：{display_name} (@{screen_name})" if screen_name else f"X：{display_name}"
        items.append(
            AIUpdateItem(
                title=text[:120],
                summary=text[:220],
                source_name=profile_name,
                source_type="social",
                url=url,
                published_at=_parse_datetime(str(tweet.get("created_at") or "")),
                vendor=vendor,
                raw_excerpt=text,
                verification_status="social_only",
                tags=["AI", "social", vendor],
            )
        )
    return items


_AIHOT_SOURCE_LINE_RE = re.compile(
    r"(?:官方|公众号|RSS|GitHub|News|网页|博客|Blog|X：|MarkTechPost|The Decoder|TechCrunch|IT之家|Google|Claude Code)",
    re.IGNORECASE,
)
_AIHOT_NOISE_TITLES = (
    "AI HOT",
    "今日看点",
    "内容",
    "精选",
    "全部",
    "日报",
    "周报",
    "月报",
    "更多",
)


def _next_flight_payload_text(html_text: str) -> str:
    chunks: list[str] = []
    pattern = re.compile(
        r"(?is)<script[^>]*>\s*self\.__next_f\.push\((?P<payload>\[.*?\])\)\s*</script>"
    )
    for match in pattern.finditer(html_text or ""):
        try:
            payload = json.loads(unescape(match.group("payload")))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], str):
            chunks.append(payload[1])
    return "\n".join(chunks)


def _decode_embedded_json_string(value: str) -> str:
    try:
        return str(json.loads(f'"{value}"')).strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        return value.strip()


def _aihot_structured_entries(html_text: str) -> list[tuple[str, str, str, str]]:
    payload = _next_flight_payload_text(html_text)
    if not payload:
        return []
    field_pattern = re.compile(
        r'"className":"m-daily-entry-(?P<kind>title|sum|src)"'
        r'(?P<attrs>(?:(?!"className":"m-daily-entry-).){0,600}?)'
        r'"children":"(?P<value>(?:\\.|[^"\\])*)"'
    )
    entries: list[tuple[str, str, str, str]] = []
    pending: dict[str, str] = {}
    for match in field_pattern.finditer(payload):
        kind = match.group("kind")
        value = _decode_embedded_json_string(match.group("value"))
        if kind == "title":
            href_match = re.search(r'"href":"(?P<href>(?:\\.|[^"\\])*)"', match.group("attrs"))
            pending = {
                "title": value,
                "detail_href": _decode_embedded_json_string(href_match.group("href")) if href_match else "",
            }
            continue
        if kind == "sum" and pending.get("title"):
            pending["summary"] = value
            continue
        if kind == "src" and pending.get("title") and pending.get("summary"):
            entries.append((pending["title"], value, pending["summary"], pending.get("detail_href", "")))
            pending = {}
    return entries


def _aihot_vendor(title: str, source_line: str) -> str:
    text = f"{title} {source_line}"
    mapping = (
        ("美团", "美团 LongCat"),
        ("LongCat", "美团 LongCat"),
        ("智谱", "智谱 GLM"),
        ("GLM", "智谱 GLM"),
        ("阿里", "阿里/Qwen"),
        ("Qwen", "阿里/Qwen"),
        ("豆包", "火山方舟/豆包"),
        ("Doubao", "火山方舟/豆包"),
        ("MiniMax", "MiniMax"),
        ("Kimi", "月之暗面 Kimi"),
        ("DeepSeek", "DeepSeek"),
        ("OpenAI", "OpenAI"),
        ("GPT", "OpenAI"),
        ("Anthropic", "Anthropic"),
        ("Claude", "Anthropic"),
        ("Google", "Google"),
        ("Gemini", "Google DeepMind"),
        ("NVIDIA", "NVIDIA"),
        ("xAI", "xAI"),
        ("Grok", "xAI"),
        ("Meta", "Meta AI"),
        ("Mistral", "Mistral AI"),
        ("Hugging Face", "Hugging Face"),
    )
    for marker, vendor in mapping:
        if marker.lower() in text.lower():
            return vendor
    if "：" in source_line:
        return source_line.split("：", 1)[0].strip()
    return source_line[:40].strip() or "AI HOT"


def _aihot_external_url(text: str, *, aggregator_url: str) -> str:
    aggregator_host = urlsplit(aggregator_url).netloc.lower()
    for match in re.finditer(r"https?://[^\s，。；;）)】\]<>\"']+", text or ""):
        url = match.group(0).rstrip(".,;:!?")
        if urlsplit(url).netloc.lower() == aggregator_host:
            continue
        return url
    return ""


def _aihot_rendered_detail_hrefs(html_text: str) -> dict[str, str]:
    parser = _LinkCollector()
    parser.feed(html_text or "")
    detail_hrefs: dict[str, str] = {}
    for href, text in parser.links:
        path = urlsplit(href or "").path
        title_key = re.sub(r"\s+", "", text or "").lower()
        if path.startswith("/items/") and title_key:
            detail_hrefs.setdefault(title_key, href)
    return detail_hrefs


def parse_aihot_daily_html(
    html_text: str,
    *,
    source_name: str,
    vendor: str,
    base_url: str,
    published_date: str,
) -> list[AIUpdateItem]:
    structured_entries = _aihot_structured_entries(html_text)
    rendered_detail_hrefs = _aihot_rendered_detail_hrefs(html_text)
    uses_structured_entries = bool(structured_entries)
    if structured_entries:
        candidates = structured_entries
    else:
        lines = _html_lines(html_text)
        candidates = []
        for idx in range(0, max(0, len(lines) - 2)):
            title = lines[idx].strip()
            second = lines[idx + 1].strip()
            third = lines[idx + 2].strip()
            if _AIHOT_SOURCE_LINE_RE.search(second):
                candidates.append((title, second, third, ""))
    items: list[AIUpdateItem] = []
    seen_titles: set[str] = set()
    for title, source_line, summary, detail_href in candidates:
        title = title.strip()
        source_line = source_line.strip()
        summary = summary.strip()
        if not (6 <= len(title) <= 120):
            continue
        if title.startswith("#") or title.startswith("##"):
            continue
        if "2026 年" in title or re.search(r"\b\d{1,2}\s*日\b.*\b\d{1,2}\s*日\b", title):
            continue
        if any(title == marker or title.startswith(marker + " ") for marker in _AIHOT_NOISE_TITLES):
            continue
        if not _AIHOT_SOURCE_LINE_RE.search(source_line):
            continue
        if len(summary) < 28 or (
            not uses_structured_entries
            and len(summary) < 50
            and _AIHOT_SOURCE_LINE_RE.search(summary)
        ):
            continue
        title_key = re.sub(r"\s+", "", title).lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        item_vendor = _aihot_vendor(title, source_line) or vendor
        detail_href = detail_href or rendered_detail_hrefs.get(title_key, "")
        entry_url = urljoin(base_url, detail_href) if detail_href else f"{base_url}?item={len(items) + 1}"
        primary_url = _aihot_external_url(
            f"{summary} {source_line}",
            aggregator_url=base_url,
        )
        items.append(
            AIUpdateItem(
                title=title,
                summary=summary[:220],
                source_name=(
                    f"{item_vendor} 原始页面（AI HOT 汇总）"
                    if primary_url
                    else source_line[:80]
                ),
                source_type="aggregator",
                url=primary_url or entry_url,
                # The aggregator supplies a calendar date, not a publication time.
                published_at=published_date,
                vendor=item_vendor,
                product="",
                raw_excerpt=summary,
                confidence_score=0.72,
                verification_status="aggregator_only",
                evidence_urls=[entry_url] if primary_url else [],
                tags=["AI", source_name, item_vendor],
            )
        )
    return items
