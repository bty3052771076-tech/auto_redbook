import base64

from src.images import chatgpt_images
from src.images.chatgpt_images import build_chatgpt_image_prompt


def test_build_chatgpt_image_prompt_strips_daily_news_prefix():
    prompt = build_chatgpt_image_prompt(
        title="每日新闻｜特朗普欲推动美企入委内瑞拉",
        body="",
        topics=["每日新闻", "美国时政"],
        prompt_hint="特朗普欲推动美企入委内瑞拉",
    )
    assert "每日新闻｜" not in prompt
    assert "新闻主题：" in prompt


def test_build_chatgpt_image_prompt_includes_safety_constraints():
    prompt = build_chatgpt_image_prompt(
        title="测试标题",
        body="",
        topics=[],
        prompt_hint="",
    )
    assert "不要出现任何文字" in prompt
    assert "不要生成可识别的真实人物肖像" in prompt


def test_parse_data_url_base64_png():
    payload = base64.b64encode(b"hello").decode("ascii")
    mime, data = chatgpt_images._parse_data_url(f"data:image/png;base64,{payload}")  # type: ignore[attr-defined]
    assert mime == "image/png"
    assert data == b"hello"
