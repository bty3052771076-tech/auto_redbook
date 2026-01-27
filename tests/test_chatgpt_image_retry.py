import pytest

from src.images.auto_image import ImageGenerationAbandoned, fetch_and_download_related_images
from src.images.chatgpt_images import ChatGPTImageResult
from src.images import chatgpt_images


def test_chatgpt_image_retry_on_timeout(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_generate_chatgpt_image(*, post_id: str, prompt: str, dest_dir, timeout_s: float):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("等待生成图片超时(180s)：no image")
        out = tmp_path / "ok.png"
        out.write_bytes(b"x" * 20000)
        return ChatGPTImageResult(path=out, meta={"mode": "chatgpt_images"})

    monkeypatch.setattr(chatgpt_images, "generate_chatgpt_image", fake_generate_chatgpt_image)
    monkeypatch.setenv("CHATGPT_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CHATGPT_IMAGE_RETRY_SLEEP_S", "0")

    paths, metas = fetch_and_download_related_images(
        title="测试标题",
        body="测试正文",
        topics=["每日新闻"],
        prompt_hint="",
        dest_dir=tmp_path,
        provider="chatgpt_images",
        count=1,
    )

    assert calls["n"] == 3
    assert len(paths) == 1
    assert metas[0]["attempt"] == 3
    assert metas[0]["attempt_max"] == 3


def test_chatgpt_image_give_up_after_max_attempts(monkeypatch, tmp_path):
    def fake_generate_chatgpt_image(*, post_id: str, prompt: str, dest_dir, timeout_s: float):
        raise RuntimeError("等待生成图片超时(180s)：no image")

    monkeypatch.setattr(chatgpt_images, "generate_chatgpt_image", fake_generate_chatgpt_image)
    monkeypatch.setenv("CHATGPT_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CHATGPT_IMAGE_RETRY_SLEEP_S", "0")

    with pytest.raises(ImageGenerationAbandoned) as exc:
        fetch_and_download_related_images(
            title="测试标题",
            body="测试正文",
            topics=["每日新闻"],
            prompt_hint="",
            dest_dir=tmp_path,
            provider="chatgpt_images",
            count=1,
        )

    assert exc.value.attempts == 3


def test_chatgpt_image_retry_on_send_failure(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_generate_chatgpt_image(*, post_id: str, prompt: str, dest_dir, timeout_s: float):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("未能触发生成（发送按钮/快捷键均失败）")
        out = tmp_path / "ok.png"
        out.write_bytes(b"x" * 20000)
        return ChatGPTImageResult(path=out, meta={"mode": "chatgpt_images"})

    monkeypatch.setattr(chatgpt_images, "generate_chatgpt_image", fake_generate_chatgpt_image)
    monkeypatch.setenv("CHATGPT_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CHATGPT_IMAGE_RETRY_SLEEP_S", "0")

    paths, metas = fetch_and_download_related_images(
        title="测试标题",
        body="测试正文",
        topics=["每日新闻"],
        prompt_hint="",
        dest_dir=tmp_path,
        provider="chatgpt_images",
        count=1,
    )

    assert calls["n"] == 2
    assert len(paths) == 1
    assert metas[0]["attempt"] == 2


def test_chatgpt_image_does_not_retry_non_timeout_error(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_generate_chatgpt_image(*, post_id: str, prompt: str, dest_dir, timeout_s: float):
        calls["n"] += 1
        raise RuntimeError("ChatGPT 未登录")

    monkeypatch.setattr(chatgpt_images, "generate_chatgpt_image", fake_generate_chatgpt_image)
    monkeypatch.setenv("CHATGPT_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("CHATGPT_IMAGE_RETRY_SLEEP_S", "0")

    with pytest.raises(RuntimeError):
        fetch_and_download_related_images(
            title="测试标题",
            body="测试正文",
            topics=["每日新闻"],
            prompt_hint="",
            dest_dir=tmp_path,
            provider="chatgpt_images",
            count=1,
        )

    assert calls["n"] == 1
