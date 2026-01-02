from src.images.auto_image import (
    ImageItem,
    _pexels_query_hint,
    build_image_query,
    is_auto_image_enabled,
    pick_best_image,
)


def test_is_auto_image_enabled_defaults_true(monkeypatch):
    monkeypatch.delenv("AUTO_IMAGE", raising=False)
    assert is_auto_image_enabled() is True


def test_is_auto_image_enabled_false_values(monkeypatch):
    monkeypatch.setenv("AUTO_IMAGE", "0")
    assert is_auto_image_enabled() is False
    monkeypatch.setenv("AUTO_IMAGE", "false")
    assert is_auto_image_enabled() is False


def test_build_image_query_prefers_delimited_title():
    q = build_image_query(
        title="每日新闻｜新能源车销量创新高",
        body="",
        topics=[],
        prompt_hint="",
    )
    assert "每日新闻" not in q
    assert "新能源" in q


def test_build_image_query_includes_topics():
    q = build_image_query(
        title="AI 芯片公司融资",
        body="",
        topics=["科技", "#芯片", "AI", "融资", "多余"],
        prompt_hint="",
    )
    assert "AI" in q
    assert "芯片" in q
    assert "科技" in q


def test_pexels_query_hint_maps_us_politics():
    q = _pexels_query_hint("美国时政")
    assert "USA" in q
    assert "politics" in q


def test_pick_best_image_prefers_alt_match():
    items = [
        ImageItem(
            provider="pexels",
            id="1",
            page_url="https://example.com/1",
            download_url="https://example.com/1.jpg",
            alt="a dog in the park",
            width=1000,
            height=1500,
        ),
        ImageItem(
            provider="pexels",
            id="2",
            page_url="https://example.com/2",
            download_url="https://example.com/2.jpg",
            alt="a cat on a sofa",
            width=1000,
            height=1500,
        ),
    ]
    picked = pick_best_image(items, "cat sofa")
    assert picked.id == "2"


def test_pick_best_image_tiebreaker_by_area():
    items = [
        ImageItem(
            provider="pexels",
            id="1",
            page_url="https://example.com/1",
            download_url="https://example.com/1.jpg",
            alt="abstract",
            width=800,
            height=1200,
        ),
        ImageItem(
            provider="pexels",
            id="2",
            page_url="https://example.com/2",
            download_url="https://example.com/2.jpg",
            alt="abstract",
            width=1000,
            height=1500,
        ),
    ]
    picked = pick_best_image(items, "abstract")
    assert picked.id == "2"
