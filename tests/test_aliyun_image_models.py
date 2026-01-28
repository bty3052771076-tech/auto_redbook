from __future__ import annotations

from pathlib import Path

from src.images import aliyun_images


def test_wan26_forces_n_to_1(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ALIYUN_IMAGE_API_KEY", "dummy")
    monkeypatch.setenv("ALIYUN_IMAGE_BASE_URL", "https://example.com")
    monkeypatch.setenv("ALIYUN_IMAGE_MODEL", "wan2.6-t2i")

    seen: dict[str, object] = {}

    def fake_post_json(*, url, payload, headers, timeout_s):
        seen["url"] = url
        seen["payload"] = payload
        return {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://example.com/out.png"}]}}
                ]
            },
            "request_id": "req",
        }

    def fake_download_bytes(*, url, timeout_s):
        return b"\x89PNG\r\n\x1a\n" + b"x" * 64

    monkeypatch.setattr(aliyun_images, "_http_post_json", fake_post_json)
    monkeypatch.setattr(aliyun_images, "_download_bytes", fake_download_bytes)

    res = aliyun_images.generate_aliyun_image(post_id="p", prompt="hi", dest_dir=tmp_path)

    assert str(seen["url"]).endswith("/api/v1/services/aigc/multimodal-generation/generation")
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["parameters"]["n"] == 1
    assert res.path.exists()
    assert res.path.suffix == ".png"


def test_z_image_does_not_send_negative_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ALIYUN_IMAGE_API_KEY", "dummy")
    monkeypatch.setenv("ALIYUN_IMAGE_BASE_URL", "https://example.com")
    monkeypatch.setenv("ALIYUN_IMAGE_MODEL", "z-image-turbo")
    monkeypatch.setenv("ALIYUN_IMAGE_NEGATIVE_PROMPT", "watermark, text")

    seen: dict[str, object] = {}

    def fake_post_json(*, url, payload, headers, timeout_s):
        seen["payload"] = payload
        return {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://example.com/out.png"}]}}
                ]
            }
        }

    def fake_download_bytes(*, url, timeout_s):
        return b"\x89PNG\r\n\x1a\n" + b"x" * 64

    monkeypatch.setattr(aliyun_images, "_http_post_json", fake_post_json)
    monkeypatch.setattr(aliyun_images, "_download_bytes", fake_download_bytes)

    aliyun_images.generate_aliyun_image(post_id="p", prompt="hi", dest_dir=tmp_path)

    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert "negative_prompt" not in payload["parameters"]


def test_wan25_auto_uses_async_text2image_and_polls(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ALIYUN_IMAGE_API_KEY", "dummy")
    monkeypatch.setenv("ALIYUN_IMAGE_BASE_URL", "https://example.com")
    monkeypatch.setenv("ALIYUN_IMAGE_MODEL", "wan2.5-t2i")
    monkeypatch.setenv("ALIYUN_IMAGE_POLL_INTERVAL_S", "0")

    seen: dict[str, object] = {"get_calls": 0}

    def fake_post_json(*, url, payload, headers, timeout_s):
        seen["post_url"] = url
        seen["post_payload"] = payload
        return {"output": {"task_id": "task123", "task_status": "PENDING"}, "request_id": "req"}

    def fake_get_json(*, url, headers, timeout_s):
        seen["get_calls"] = int(seen["get_calls"]) + 1
        seen["get_url"] = url
        return {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://example.com/out.png"}]}}

    def fake_download_bytes(*, url, timeout_s):
        return b"\x89PNG\r\n\x1a\n" + b"x" * 64

    monkeypatch.setattr(aliyun_images, "_http_post_json", fake_post_json)
    monkeypatch.setattr(aliyun_images, "_http_get_json", fake_get_json)
    monkeypatch.setattr(aliyun_images, "_download_bytes", fake_download_bytes)

    res = aliyun_images.generate_aliyun_image(post_id="p", prompt="hi", dest_dir=tmp_path)

    assert str(seen["post_url"]).endswith("/api/v1/services/aigc/text2image/image-synthesis")
    assert str(seen["get_url"]).endswith("/api/v1/tasks/task123")
    assert int(seen["get_calls"]) >= 1
    assert res.meta["task_id"] == "task123"
    assert res.meta["method"].startswith("text2image_synthesis_async")

