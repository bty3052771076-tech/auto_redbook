from __future__ import annotations

from pathlib import Path

from src.images import volcengine_images


def test_volcengine_seedream_defaults_match_live_lite_model_requirements():
    assert volcengine_images.DEFAULT_MODEL == "doubao-seedream-5-0-lite-260128"
    width, height = [int(part) for part in volcengine_images.DEFAULT_SIZE.split("x")]
    assert width * height >= 3_686_400


def test_volcengine_image_generation_posts_seedream_payload(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOLCENGINE_IMAGE_API_KEY", "dummy")
    monkeypatch.setenv("VOLCENGINE_IMAGE_BASE_URL", "https://ark.example/api/v3")
    monkeypatch.setenv("VOLCENGINE_IMAGE_MODEL", "doubao-seedream-5-0-lite-260128")
    monkeypatch.setenv("VOLCENGINE_IMAGE_SIZE", "1440x2560")

    seen: dict[str, object] = {}

    def fake_post_json(*, url, payload, headers, timeout_s):
        seen["url"] = url
        seen["payload"] = payload
        seen["headers"] = headers
        return {
            "created": 1782880000,
            "data": [{"url": "https://example.com/out.png", "size": "1440x2560"}],
            "usage": {"generated_images": 1},
        }

    def fake_download_bytes(*, url, timeout_s, api_key=None):
        seen["download_url"] = url
        seen["download_api_key"] = api_key
        return b"\x89PNG\r\n\x1a\n" + b"x" * 64

    monkeypatch.setattr(volcengine_images, "_http_post_json", fake_post_json)
    monkeypatch.setattr(volcengine_images, "_download_bytes", fake_download_bytes)

    res = volcengine_images.generate_volcengine_image(
        post_id="p",
        prompt="hi",
        dest_dir=tmp_path,
    )

    assert str(seen["url"]).endswith("/images/generations")
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "doubao-seedream-5-0-lite-260128"
    assert payload["prompt"] == "hi"
    assert payload["size"] == "1440x2560"
    assert payload["response_format"] == "url"
    assert payload["watermark"] is False
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer dummy"
    assert res.path.exists()
    assert res.meta["provider"] == "volcengine"
    assert res.meta["model"] == "doubao-seedream-5-0-lite-260128"


def test_volcengine_image_model_list_fallback_on_quota(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOLCENGINE_IMAGE_API_KEY", "dummy")
    monkeypatch.setenv("VOLCENGINE_IMAGE_BASE_URL", "https://ark.example/api/v3")
    monkeypatch.setenv(
        "VOLCENGINE_IMAGE_MODELS",
        "doubao-seedream-5-0-260128,doubao-seedream-4-5-251128",
    )

    calls: list[str] = []

    def fake_post_json(*, url, payload, headers, timeout_s):
        model = str(payload.get("model"))
        calls.append(model)
        if model == "doubao-seedream-5-0-260128":
            raise volcengine_images.VolcengineImageAPIError(
                url=url,
                status=429,
                code="QuotaExceeded",
                message="out of quota",
            )
        return {"data": [{"url": "https://example.com/out.png"}]}

    monkeypatch.setattr(volcengine_images, "_http_post_json", fake_post_json)
    monkeypatch.setattr(
        volcengine_images,
        "_download_bytes",
        lambda *, url, timeout_s, api_key=None: b"\x89PNG\r\n\x1a\n" + b"x" * 64,
    )

    res = volcengine_images.generate_volcengine_image(post_id="p", prompt="hi", dest_dir=tmp_path)

    assert calls == ["doubao-seedream-5-0-260128", "doubao-seedream-4-5-251128"]
    assert res.meta["model"] == "doubao-seedream-4-5-251128"
