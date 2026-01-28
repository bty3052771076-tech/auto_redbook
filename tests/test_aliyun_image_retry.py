from __future__ import annotations

from pathlib import Path

import pytest

from src.images.auto_image import ImageGenerationAbandoned, fetch_and_download_related_images
from src.images.aliyun_images import AliyunImageResult
from src.images import aliyun_images


def test_aliyun_image_retries_then_succeeds(monkeypatch, tmp_path: Path):
    calls = {"n": 0}

    def fake_generate_aliyun_image(*, post_id, prompt, dest_dir, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("timed out")
        out = dest_dir / "ok.png"
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)
        return AliyunImageResult(path=out, meta={"mode": "aliyun_image", "provider": "aliyun"})

    monkeypatch.setattr(aliyun_images, "generate_aliyun_image", fake_generate_aliyun_image)
    monkeypatch.setenv("ALIYUN_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("ALIYUN_IMAGE_RETRY_SLEEP_S", "0")

    paths, metas = fetch_and_download_related_images(
        title="每日新闻｜测试",
        body="新闻内容：...\n我的点评：...\n来源：https://example.com",
        topics=["每日新闻", "科技"],
        prompt_hint="美国时政",
        dest_dir=tmp_path,
        provider="aliyun",
        count=1,
    )

    assert calls["n"] == 3
    assert len(paths) == 1
    assert paths[0].exists()
    assert metas[0].get("attempt") == 3


def test_aliyun_image_gives_up_after_max_attempts(monkeypatch, tmp_path: Path):
    calls = {"n": 0}

    def fake_generate_aliyun_image(*, post_id, prompt, dest_dir, **kwargs):
        calls["n"] += 1
        raise RuntimeError("timed out")

    monkeypatch.setattr(aliyun_images, "generate_aliyun_image", fake_generate_aliyun_image)
    monkeypatch.setenv("ALIYUN_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("ALIYUN_IMAGE_RETRY_SLEEP_S", "0")

    with pytest.raises(ImageGenerationAbandoned) as exc:
        fetch_and_download_related_images(
            title="每日新闻｜测试",
            body="正文",
            topics=["科技"],
            prompt_hint="美国时政",
            dest_dir=tmp_path,
            provider="aliyun",
            count=1,
        )

    assert calls["n"] == 3
    assert exc.value.attempts == 3


def test_aliyun_image_does_not_retry_on_auth_error(monkeypatch, tmp_path: Path):
    calls = {"n": 0}

    def fake_generate_aliyun_image(*, post_id, prompt, dest_dir, **kwargs):
        calls["n"] += 1
        raise RuntimeError("api_key missing")

    monkeypatch.setattr(aliyun_images, "generate_aliyun_image", fake_generate_aliyun_image)
    monkeypatch.setenv("ALIYUN_IMAGE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("ALIYUN_IMAGE_RETRY_SLEEP_S", "0")

    with pytest.raises(RuntimeError):
        fetch_and_download_related_images(
            title="每日新闻｜测试",
            body="正文",
            topics=["科技"],
            prompt_hint="美国时政",
            dest_dir=tmp_path,
            provider="aliyun",
            count=1,
        )

    assert calls["n"] == 1

