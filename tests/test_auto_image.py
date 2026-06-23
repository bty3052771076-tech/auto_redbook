from src.images.auto_image import (
    ImageItem,
    _body_snippet_for_prompt,
    _build_aliyun_image_prompt,
    _download_image,
    _pexels_query_hint,
    _pexels_search_photos,
    build_image_query,
    is_auto_image_enabled,
    pick_best_image,
    pick_top_images,
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


def test_build_image_query_skips_news_topics():
    q = build_image_query(
        title="委内瑞拉石油危机",
        body="",
        topics=["国际新闻", "每日新闻", "能源", "经济"],
        prompt_hint="",
    )
    assert "新闻" not in q
    assert "能源" in q


def test_build_image_query_compresses_long_english_title():
    q = build_image_query(
        title="Trump declares US in charge of Venezuela and Maduro goes to court",
        body="",
        topics=[],
        prompt_hint="",
    )
    assert "trump" in q.lower()
    assert "venezuela" in q.lower()
    assert "court" not in q.lower()


def test_body_snippet_for_prompt_reads_daily_news_json_body():
    body = (
        '{\n'
        '  "原文标题": "AI芯片新品发布",\n'
        '  "内容": "这家芯片企业披露新一代人工智能加速器，面向推理计算场景。",\n'
        '  "评价": "AI芯片竞争会影响算力供给和应用成本。",\n'
        '  "日期": "2026-06-19",\n'
        '  "来源": "Example News"\n'
        '}'
    )

    snippet = _body_snippet_for_prompt(body)

    assert "人工智能加速器" in snippet
    assert "算力供给" in snippet
    assert "原文标题" not in snippet
    assert "Example News" not in snippet


def test_body_snippet_for_prompt_reads_rendered_daily_news_body():
    body = (
        "原文标题：AI芯片新品发布\n\n"
        "内容：\n"
        "这家芯片企业披露新一代人工智能加速器，面向推理计算场景。\n\n"
        "评价：\n"
        "AI芯片竞争会影响算力供给和应用成本。\n\n"
        "日期：2026-06-19\n"
        "来源：Example News"
    )

    snippet = _body_snippet_for_prompt(body)

    assert "人工智能加速器" in snippet
    assert "算力供给" in snippet
    assert "原文标题" not in snippet
    assert "日期" not in snippet
    assert "Example News" not in snippet


def test_pexels_query_hint_maps_us_politics():
    q = _pexels_query_hint("美国时政")
    assert "USA" in q
    assert "politics" in q


def test_pexels_query_hint_includes_entities():
    q = _pexels_query_hint("巴基斯坦 利比亚 军事协议")
    assert "Pakistan" in q
    assert "Libya" in q
    assert "military" in q


def test_pexels_query_hint_avoids_news_when_specific():
    q = _pexels_query_hint("国际新闻 政治")
    assert "international" in q
    assert "politics" in q
    assert "news" not in q


def test_pexels_query_hint_uses_news_when_only_news():
    q = _pexels_query_hint("新闻")
    assert q == "news"


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


def test_pick_top_images_prefers_diverse_results():
    items = [
        ImageItem(
            provider="pexels",
            id="1",
            page_url="https://example.com/1",
            download_url="https://example.com/1.jpg",
            alt="venezuela oil industry",
            width=1000,
            height=1500,
        ),
        ImageItem(
            provider="pexels",
            id="2",
            page_url="https://example.com/2",
            download_url="https://example.com/2.jpg",
            alt="venezuela oil industry",
            width=1000,
            height=1500,
        ),
        ImageItem(
            provider="pexels",
            id="3",
            page_url="https://example.com/3",
            download_url="https://example.com/3.jpg",
            alt="venezuela election politics",
            width=1000,
            height=1500,
        ),
    ]
    picked = pick_top_images(items, "venezuela oil", count=2)
    assert [p.id for p in picked] == ["1", "3"]


def test_pick_top_images_respects_exclude_ids():
    items = [
        ImageItem(
            provider="pexels",
            id="1",
            page_url="https://example.com/1",
            download_url="https://example.com/1.jpg",
            alt="coffee shop interior",
            width=1000,
            height=1500,
        ),
        ImageItem(
            provider="pexels",
            id="2",
            page_url="https://example.com/2",
            download_url="https://example.com/2.jpg",
            alt="coffee shop interior",
            width=1000,
            height=1500,
        ),
    ]
    picked = pick_top_images(items, "coffee", count=1, exclude_ids={"1"})
    assert picked[0].id == "2"


def test_pexels_search_uses_explicit_https_context(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"photos":[]}'

    def fake_urlopen(req, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    _pexels_search_photos(
        api_key="key",
        base_url="https://api.pexels.com",
        query="lifestyle",
        per_page=1,
        orientation="portrait",
        timeout_s=1,
    )

    assert captured.get("context") is not None


def test_download_image_uses_explicit_https_context(monkeypatch, tmp_path):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"image-bytes"

    def fake_urlopen(req, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    _download_image(
        url="https://images.pexels.com/photos/test.jpg",
        dest_path=tmp_path / "test.jpg",
        timeout_s=1,
    )

    assert captured.get("context") is not None


def test_build_aliyun_image_prompt_forbids_text():
    prompt = _build_aliyun_image_prompt(
        title="每日新闻｜新能源车销量创新高",
        body="",
        topics=[],
        prompt_hint="新能源车销量创新高",
    )
    assert "不要出现任何文字" in prompt
    assert "水印" in prompt
