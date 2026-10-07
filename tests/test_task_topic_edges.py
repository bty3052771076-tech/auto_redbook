import pytest

from src.agent.task_intent import extract_job_keywords


def test_explicit_ai_column_is_not_reassigned_by_generic_news_suffix():
    result = extract_job_keywords(
        "生成3条每日新闻；每日AI资讯优先关注模型发布新闻",
        ["daily_news", "daily_ai_digest"])
    assert result == {"daily_news": [], "daily_ai_digest": ["模型发布"]}


def test_repeated_keyword_markers_preserve_quoted_multiword_entities():
    result = extract_job_keywords(
        '生成3条每日新闻，关键词：“人工智能 芯片”；关键词：能源',
        ["daily_news"])
    assert result == {"daily_news": ["人工智能 芯片", "能源"]}


def test_repeated_keyword_markers_cannot_bypass_total_keyword_limit():
    text = "生成3条每日新闻，关键词：" + "、".join(f"主题{index}" for index in range(10))
    text += "；关键词：" + "、".join(f"主题{index}" for index in range(10, 17))
    with pytest.raises(ValueError, match="最多16个"):
        extract_job_keywords(text, ["daily_news"])
