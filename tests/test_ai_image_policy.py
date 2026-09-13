from __future__ import annotations

from pathlib import Path

import pytest

from src.workflow import create_post


def test_ai_required_news_image_never_falls_back_to_pexels(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    def fake_fetch(*, provider=None, **_kwargs):
        calls.append(str(provider or "default"))
        if provider == "minimax":
            raise RuntimeError("subscription image request failed")
        raise AssertionError("Pexels fallback must not run for ai_required")

    monkeypatch.setattr(create_post, "fetch_and_download_related_images", fake_fetch)

    with pytest.raises(RuntimeError, match="AI image required"):
        create_post._fetch_daily_news_related_images(
            title="Test news",
            body="Concrete event details",
            topics=["technology"],
            prompt_hint="A concrete news event",
            dest_dir=tmp_path,
            ai_first=True,
            provider="minimax",
            image_policy="ai_required",
        )

    assert calls == ["minimax"]
