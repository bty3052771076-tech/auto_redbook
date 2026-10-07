"""Local topic extraction shared by rule plans and recognition validation."""

from __future__ import annotations

from copy import deepcopy
import re


JOB_ALIASES = {
    "daily_news": ("每日新闻",),
    "daily_ai_digest": ("每日AI讯息", "每日AI资讯"),
    "daily_wool": ("每日羊毛", "AI羊毛", "每日AI鸡蛋", "AI鸡蛋", "每日AI福利", "AI福利"),
    "daily_wow": ("每日我去",),
    "daily_global_map": ("每日全球事件关注图", "今日全球事件关注图", "全球事件热力图", "全球新闻热力图"),
}


def split_keywords(value: str) -> list[str]:
    # Commas are separators; quoted multi-word subjects remain one keyword.
    parts = re.findall(r'[“"‘\']([^”"’\']+)[”"’\']|([^、,，;；\s]+)', value)
    result = []
    for quoted, plain in parts:
        word = (quoted or plain).strip(" :：。.!！")
        if word and word not in result:
            result.append(word)
    if len(result) > 16 or any(len(word) > 80 for word in result):
        raise ValueError("关键词最多16个，每个不超过80字；请精简后重新发送")
    return result


def _topic_scope(text: str, position: int, kinds: list[str]) -> str:
    default = "daily_news" if "daily_news" in kinds else kinds[0] if kinds else ""
    locations = [(text[:position].rfind(alias), kind) for kind in kinds for alias in JOB_ALIASES[kind]]
    location, scope = max(locations, default=(-1, default))
    return scope if location >= 0 else default


def _topic_value(text: str, start: int) -> str:
    value = re.split(r"[；;。\n]", text[start:], maxsplit=1)[0]
    aliases = "|".join(re.escape(alias) for names in JOB_ALIASES.values() for alias in names)
    boundary = (
        r"[,，]\s*(?:(?:请|需要|并|优先|至少|尽量|不要|不上传|仅|只|速度|保存|上传|生成|开启|关闭|使用|通过|检查|核验|查重|关键词|关键字|检索词)"
        r"|(?:\d+|[一二两三四五六七八九十]+)\s*(?:条|篇))"
        rf"|(?:{aliases})"
    )
    return re.split(boundary, value, maxsplit=1)[0].strip(" ,，")


def extract_job_topics(text: str, kinds: list[str]) -> dict[str, dict]:
    result = {kind: {"keywords": [], "keyword_mode": "default", "topic_brief": ""} for kind in kinds}

    def add(scope: str, value: str, mode: str, brief: str = ""):
        if not scope:
            return
        topic = result[scope]
        words = list(dict.fromkeys([*topic["keywords"], *split_keywords(value)]))
        if len(words) > 16:
            raise ValueError("关键词最多16个，每个不超过80字；请精简后重新发送")
        topic["keywords"] = words
        if mode == "filter" or topic["keyword_mode"] == "default":
            topic["keyword_mode"] = mode
        if brief and brief not in topic["topic_brief"]:
            topic["topic_brief"] = "\n".join(filter(None, [topic["topic_brief"], brief]))

    marker = r"(?:关键词|关键字|检索词)(?:(?:为|是)\s*[:：=]?|\s*[:：=])\s*"
    for match in re.finditer(marker, text):
        prefix = re.split(r"[,，；;。\n]", text[:match.start()])[-1]
        if re.search(r"(?:不要|无需|不需要|禁止).{0,8}$", prefix):
            continue
        add(_topic_scope(text, match.start(), kinds), _topic_value(text, match.end()), "filter")

    for match in re.finditer(r"(?:优先|主要|重点)(?:关注|筛选|选择|考虑)\s*", text):
        prefix = re.split(r"[,，；;。\n]", text[:match.start()])[-1]
        if re.search(r"(?:不要|无需|不需要|禁止).{0,8}$", prefix):
            continue
        value = _topic_value(text, match.end())
        scope = _topic_scope(text, match.start(), kinds)
        explicit_column = any(alias in prefix for names in JOB_ALIASES.values() for alias in names)
        if value.endswith("新闻") and "daily_news" in kinds and not explicit_column:
            scope = "daily_news"
        add(scope, value.removesuffix("新闻").removesuffix("的"), "preference", match[0] + value)

    # A partial inclusion applies to the news selection, not to every requested post.
    inclusion = r"(?:至少|必须)\s*(?:包含|包括|有)\s*(?:\d+|[一二两三四五六七八九十]+)\s*(?:条|篇)\s*([^，,；;。\n]+?)新闻"
    for match in re.finditer(inclusion, text):
        prefix = re.split(r"[,，；;。\n]", text[:match.start()])[-1]
        if "daily_news" in kinds and not re.search(r"(?:不要|无需|不需要|禁止).{0,8}$", prefix):
            add("daily_news", match[1].removesuffix("的"), "preference", match[0])

    if "daily_news" in kinds and not result["daily_news"]["keywords"]:
        match = re.search(r"(?:关于|有关)\s*(.+?)\s*的?每日新闻", text)
        if not match:
            match = re.search(r"(?:围绕|聚焦)\s*([^；;。\n]+?)\s*(?:生成|制作|写)\s*[^；;。\n]*?每日新闻", text)
        if match:
            add("daily_news", match[1].removesuffix("的"), "filter")
    return result


def extract_job_keywords(text: str, kinds: list[str]) -> dict[str, list[str]]:
    return {kind: topic["keywords"] for kind, topic in extract_job_topics(text, kinds).items()}


def enrich_local_plan(plan: dict, text: str) -> dict:
    result = deepcopy(plan)
    result["recognition_source"] = "rules"
    result["skip_quota_sync"] = True
    by_kind = extract_job_topics(text, [job["kind"] for job in result["jobs"]])
    for job in result["jobs"]:
        topic = by_kind[job["kind"]]
        job.update(topic)
        if job["keyword_mode"] == "filter" and job["keywords"]:
            job["prompt"] = " ".join(job["keywords"])
        if job["topic_brief"]:
            job["prompt"] += "\n选题要求：" + job["topic_brief"]
    if re.search(r"最快|速度优先|尽快|快速模式", text):
        result["performance_mode"] = "speed"
    elif re.search(r"速度与稳定平衡|平衡模式", text):
        result["performance_mode"] = "balanced"
    topic_lines = [
        f"{job['title']}{'选题偏向' if job['keyword_mode'] == 'preference' else '关键词'}：{'、'.join(job['keywords'])}"
        for job in result["jobs"] if job["keywords"]
    ]
    if topic_lines:
        result["assistant_summary"] += "\n" + "\n".join(topic_lines)
    return result
