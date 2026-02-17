from src.llm.generate import _parse_json_text


def test_parse_json_text_recovers_from_malformed_body_quotes():
    text = """
{
  "title": "每日新闻｜测试事件",
  "body": "这是一段正文，包含"关键说法"并继续展开分析。
第二段继续补充。",
  "topics": ["每日新闻", "国际观察"],
  "image_event": "会议现场交谈"
}
"""
    data = _parse_json_text(text)
    assert isinstance(data, dict)
    assert data.get("title") == "每日新闻｜测试事件"
    assert "关键说法" in (data.get("body") or "")
    assert "每日新闻" in (data.get("topics") or [])
    assert data.get("image_event") == "会议现场交谈"


def test_parse_json_text_accepts_list_content_payload():
    payload = [
        {
            "type": "text",
            "text": '{"title":"标题A","body":"正文A","topics":["话题A","话题B"]}',
        }
    ]
    data = _parse_json_text(payload)
    assert isinstance(data, dict)
    assert data.get("title") == "标题A"
    assert data.get("body") == "正文A"
    assert data.get("topics") == ["话题A", "话题B"]

