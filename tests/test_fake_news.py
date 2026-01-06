from pathlib import Path

from src.config import LLMConfig
from src.workflow import create_post as create_post_mod


def _stub_config():
    return LLMConfig(model="fake", api_key="fake-key", base_url="http://localhost")


def test_fake_news_adds_disclaimer_and_metadata(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_generate_draft(cfg, *, title_hint, prompt_hint, asset_paths, max_title=20, max_body=1000):
        captured["title_hint"] = title_hint
        captured["prompt_hint"] = prompt_hint
        return {
            "title": "吕布董卓绝恋曝光",
            "body": "这是一个离谱又欢乐的假新闻正文。",
            "topics": ["搞笑历史"],
        }

    monkeypatch.setattr(create_post_mod, "load_llm_config", _stub_config)
    monkeypatch.setattr(create_post_mod, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(create_post_mod, "save_post", lambda post: None)
    monkeypatch.setattr(create_post_mod, "save_revision", lambda rev: None)

    asset = tmp_path / "a.png"
    asset.write_bytes(b"x")

    post = create_post_mod.create_post_with_draft(
        title_hint="每日假新闻",
        prompt_hint="吕布和董卓是一对苦命鸳鸯",
        asset_paths=[str(asset)],
        copy_assets=False,
        auto_image=False,
    )

    assert post.platform["fake_news"]["is_fiction"] is True
    assert post.platform["fake_news"]["tone"] == "humor"
    assert "每日假新闻" in post.topics
    assert "本文纯属虚构" in post.body
    assert captured["title_hint"] == "每日假新闻"
    assert "每日假新闻" in captured["prompt_hint"]
    assert "吕布和董卓" in captured["prompt_hint"]


def test_fake_news_keeps_single_disclaimer(monkeypatch, tmp_path: Path):
    def fake_generate_draft(cfg, *, title_hint, prompt_hint, asset_paths, max_title=20, max_body=1000):
        return {
            "title": "假新闻标题",
            "body": "先来一段正文。\n本文纯属虚构，仅供娱乐。",
            "topics": [],
        }

    monkeypatch.setattr(create_post_mod, "load_llm_config", _stub_config)
    monkeypatch.setattr(create_post_mod, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(create_post_mod, "save_post", lambda post: None)
    monkeypatch.setattr(create_post_mod, "save_revision", lambda rev: None)

    asset = tmp_path / "b.png"
    asset.write_bytes(b"x")

    post = create_post_mod.create_post_with_draft(
        title_hint="每日假新闻",
        prompt_hint="随便一个主题",
        asset_paths=[str(asset)],
        copy_assets=False,
        auto_image=False,
    )

    assert post.body.count("本文纯属虚构") == 1
