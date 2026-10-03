from pathlib import Path
from types import SimpleNamespace

import pytest

from src.images.opencodex_images import SubscriptionImageResult
from src.wool import image_edit


def test_wool_edit_uses_runtime_assets_from_other_cwd(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    assets = runtime / "assets/wool"
    reference = assets / "参考原图/HJKRyImbkAANc_Q.jpg"
    persona = assets / "人设图/ZCode.png"
    for path in (reference, persona):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset existence fixture")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(runtime))
    monkeypatch.delenv("WOOL_ASSET_ROOT", raising=False)
    monkeypatch.delenv("WOOL_REFERENCE_IMAGE", raising=False)
    requests = []

    def generate(**kwargs):
        requests.append(kwargs)
        return SubscriptionImageResult(Path("result.png"), {"provider": "opencodex"})

    monkeypatch.setattr(image_edit, "generate_subscription_image", generate)
    _, meta = image_edit.create_wool_image(
        post_id="test", offers=[SimpleNamespace(provider="ZCode")], issue_date="2026-10-03"
    )
    assert requests[0]["reference_paths"] == [reference, persona]
    assert requests[0]["dest_dir"] == runtime / "data/cache/wool-images/2026-10-03"
    assert requests[0]["allow_minimax_fallback"] is False
    assert meta["cover_provider"] == "ZCode"


def test_missing_wool_resource_fails_before_image_submission(monkeypatch, tmp_path):
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.delenv("WOOL_ASSET_ROOT", raising=False)
    monkeypatch.delenv("WOOL_REFERENCE_IMAGE", raising=False)
    monkeypatch.setattr(image_edit, "generate_subscription_image", lambda **kwargs: pytest.fail("must not submit"))
    with pytest.raises(RuntimeError, match="WOOL_IMAGE_RESOURCE_MISSING") as error:
        image_edit.create_wool_image(
            post_id="test", offers=[SimpleNamespace(provider="ZCode")], issue_date="2026-10-03"
        )
    assert str(tmp_path) in str(error.value)


def test_no_verified_offers_does_not_require_reference_assets(monkeypatch, tmp_path):
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    requests = []

    def generate(**kwargs):
        requests.append(kwargs)
        return SubscriptionImageResult(Path("result.png"), {"provider": "opencodex"})

    monkeypatch.setattr(image_edit, "generate_subscription_image", generate)
    _, meta = image_edit.create_wool_image(post_id="test", offers=[], issue_date="2026-10-03")
    assert "reference_paths" not in requests[0]
    assert meta["asset_mode"] == "no_offer_neutral_ai_illustration"
