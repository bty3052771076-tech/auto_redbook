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


def extract_job_keywords(text: str, kinds: list[str]) -> dict[str, list[str]]:
    result = {kind: [] for kind in kinds}
    default = "daily_news" if "daily_news" in kinds else kinds[0] if kinds else ""
    for match in re.finditer(r"(?:关键词|关键字|检索词)(?:为|是)?\s*[:：=]\s*([^；;。\n]+)", text):
        prefix = text[:match.start()]
        locations = [(prefix.rfind(alias), kind) for kind in kinds for alias in JOB_ALIASES[kind]]
        location, scope = max(locations, default=(-1, default))
        scope = scope if location >= 0 else default
        value = re.split(r"[,，]\s*(?:请|需要|并|优先|至少|尽量|不要|不上传|仅|只|速度|保存|上传|生成|开启|关闭|使用|通过|检查|核验|查重)", match[1], maxsplit=1)[0]
        if scope:
            for word in split_keywords(value):
                if word not in result[scope]:
                    result[scope].append(word)
    if "daily_news" in kinds and not result["daily_news"]:
        match = re.search(r"(?:关于|有关)\s*(.+?)\s*的?每日新闻", text)
        if match:
            result["daily_news"] = split_keywords(match[1].removesuffix("的"))
        else:
            match = re.search(r"(?:围绕|聚焦)\s*([^；;。\n]+?)\s*(?:生成|制作|写)\s*[^；;。\n]*?每日新闻", text)
            if match:
                result["daily_news"] = split_keywords(match[1])
    return result


def enrich_local_plan(plan: dict, text: str) -> dict:
    result = deepcopy(plan)
    result["recognition_source"] = "rules"
    result["skip_quota_sync"] = True
    by_kind = extract_job_keywords(text, [job["kind"] for job in result["jobs"]])
    for job in result["jobs"]:
        job["keywords"] = by_kind[job["kind"]]
        job["topic_brief"] = ""
        if job["keywords"]:
            job["prompt"] = " ".join(job["keywords"])
    if re.search(r"最快|速度优先|尽快|快速模式", text):
        result["performance_mode"] = "speed"
    elif re.search(r"速度与稳定平衡|平衡模式", text):
        result["performance_mode"] = "balanced"
    topic_lines = [f"{job['title']}关键词：{'、'.join(job['keywords'])}" for job in result["jobs"] if job["keywords"]]
    if topic_lines:
        result["assistant_summary"] += "\n" + "\n".join(topic_lines)
    return result
