"""Length targets for fact-first daily news, without sentence slicing."""

import json
import re
from typing import Any


def _count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def assess_news_length(content: str, comment: str, draft: dict[str, Any], picked) -> dict[str, Any]:
    source = re.sub(r"\s+", "", (
        str(getattr(picked, "title", "") or "") + "\n"
        + str(getattr(picked, "description", "") or "")[:300] + "\n"
        + str(getattr(picked, "content", "") or "")[:2200]
    ))
    evidence = draft.get("complexity_evidence")
    verified = []
    if isinstance(evidence, list):
        for value in evidence:
            if not isinstance(value, str):
                continue
            snippet = re.sub(r"\s+", "", value)
            if len(snippet) >= 8 and snippet in source and snippet not in verified:
                verified.append(snippet)
    reason = str(draft.get("complexity_reason") or "").strip()
    complex_event = draft.get("complexity") == "complex" and bool(reason) and len(verified) >= 2
    limit = 300 if complex_event else 220
    content_chars, comment_chars = _count(content), _count(comment)
    issue = "content_too_long" if content_chars > limit else (
        "comment_too_long" if comment_chars > 40 else ""
    )
    warnings = []
    if content_chars < 150:
        warnings.append("content_below_target")
    if comment_chars < 20:
        warnings.append("comment_below_target")
    return {
        "version": "concise-news-v1",
        "complexity": "complex" if complex_event else "normal",
        "complexity_reason": reason if complex_event else "",
        "complexity_evidence": verified if complex_event else [],
        "content_chars": content_chars, "content_limit": limit,
        "comment_chars": comment_chars, "comment_limit": 40,
        "issue": issue, "status": "needs_resummary" if issue else "accepted",
        "warnings": warnings,
    }


def news_length_instruction() -> str:
    return (
        "\n每日新闻前置篇幅规则（首次写稿就满足，不先写长稿等待压缩）：\n"
        "普通新闻内容目标150–220字，优先写180–200字，硬上限220字；"
        "只有复杂事件在保留必要因果、各方关键动作与结果时可以延长，最多300字，"
        "不能仅因原文较长而延长。\n"
        "评价目标20–40字，优先写25–30字，硬上限40字，限一个短句，最多一个逗号。"
        "直接影响、具体信息边界二选一，只说明一个要点；不并列意义、风险、条件和建议，"
        "不罗列多个待确认变量，不在评价里补述新闻事实或背景。\n"
        "按非空白字符计数（含标点、数字、外文），不计内容/评价标签、日期和来源。"
        "材料不足时允许低于目标，不补写事实或空话。先交代核心事件，再保留理解事件不可缺少的事实；"
        "写作前先选定一个主事件，不是逐句改写原文。普通新闻按三个短句组织："
        "第一句交代主体、动作、对象；第二句只保留最关键的证据或原因；第三句交代结果、当前状态或必要回应。"
        "每句优先45–65字，总体仍不得超过220字；材料稀疏时允许更少的完整句子和更短篇幅。"
        "复杂事件确需更多篇幅时另按上述依据规则处理，不要求凑齐材料没有的要素。"
        "不转述全部原文，不逐项复述清单，删除重复背景、次要程序和重复评价，"
        "但不得遗漏会改变主事件含义的结果或限定。"
        "提交前内部检查内容和评价的篇幅，超出时先重新概括再输出完整JSON，不输出检查过程。"
        "压缩必须重新总结，禁止按字符截断或用省略号代替句尾。"
        "保留主体、动作、对象、关键数字、来源归因及否定/计划/已完成等状态。"
        "外层JSON另提供complexity（normal或complex）、complexity_reason、complexity_evidence（原文短语数组）；"
        "普通事件填normal、空原因和空数组；复杂事件须说明为何不能在220字内交代完整，"
        "并提供至少两个不同、每个至少8字的原文依据，不得编造依据；这些字段不得写进body。\n"
    )


def news_length_rewrite_instruction(draft: dict[str, Any]) -> str:
    previous = {key: draft.get(key, "") for key in (
        "title", "body", "topics", "image_event", "complexity",
        "complexity_reason", "complexity_evidence",
    )}
    return (
        "\n上一版完整草稿（仅供重新总结，不是新增事实来源）：\n"
        + json.dumps(previous, ensure_ascii=False) + "\n"
        + news_length_instruction()
        + "请对照上述原始材料重新总结整稿，不逐句删尾、不直接截断；"
        "保留新闻全貌与关键事实，不把计划写成完成，不删除关键否定或必要归因。"
        "同时更新image_event，使其第一完整句逐字复制压缩后内容的第一完整事实句。"
        "只输出完整新草稿JSON，不输出压缩说明。\n"
    )
