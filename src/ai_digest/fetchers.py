from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin
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


def _extract_release_date(text: str) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if not value:
        return ""
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
    "联系我们",
    "隐私",
)

_OFFICIAL_HTML_HARD_NOISE = (
    "模型上下架",
    "服务协议",
    "监控告警",
)

_OFFICIAL_HTML_RELEASE_SIGNALS = (
    "发布",
    "更新",
    "上新",
    "升级",
    "开源",
    "推出",
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

    for line in _html_lines(html_text):
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
        return items

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

    return items


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
