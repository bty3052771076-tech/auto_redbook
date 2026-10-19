from datetime import datetime, timezone

import pytest

from src.ai_digest import collect
from src.ai_digest.fetchers import parse_official_html
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import (
    ai_update_category,
    ai_update_history_key,
    ai_update_quality_issues,
    rank_ai_updates,
)
from src.ai_digest.sources import AIDigestSource


NOW = datetime(2026, 10, 18, 4, tzinfo=timezone.utc)
URL = "https://api-docs.deepseek.com/updates/"
# Minimal structure observed on the official changelog on 2026-10-18.
HTML = """
<nav><a href="#date-2026-10-17">Date: 2026-10-17</a></nav>
<article><h1>Change Log</h1>
<h2 id="date-2026-10-17">Date: 2026-10-17<a href="#date-2026-10-17">&#8203;</a></h2>
<h3 id="search-api">Opening up the in-house search API</h3>
<p>DeepSeek opens its in-house Search and Fetch API for multilingual web search.</p>
<h3 id="deepseek-v41-flash-1017-update">DeepSeek-V4.1-Flash-1017 Update</h3>
<p>DeepSeek V4.1 Flash has been upgraded to DeepSeek-V4.1-Flash-1017.
The official web and APP models have also been updated to the new version.
The API calling method and pricing remain unchanged.
Use <code>deepseek-flash</code> to access the latest model.</p>
<ul><li>HLE (w/o tools): 42.6</li><li>DeepSWE v1.1: 77.0</li></ul>
<h2 id="date-2026-09-10">Date: 2026-09-10</h2>
<h3 id="deepseek-v41-flash-release">DeepSeek-V4.1-Flash Release</h3>
<p>Today we officially release DeepSeek-V4.1-Flash with native visual understanding.</p>
</article>
<aside><a href="#date-2026-10-17">Date: 2026-10-17</a>
<h2>Date: 2026-10-18</h2><h3>Fake model release</h3>
<p>Navigation is not a new release.</p></aside>
"""


def release_items():
    return parse_official_html(HTML, source_name="DeepSeek", vendor="DeepSeek", base_url=URL)


def item(title, *, day="2026-10-18", vendor="Example", url="https://example.com/update", product=""):
    return AIUpdateItem(title=title, source_type="official", source_name=vendor, vendor=vendor,
        url=url, product=product, published_at=day,
        summary=title + ". Developers can now use this AI update through the official API.",
        raw_excerpt=title + ". Developers can now use this AI update through the official API.")


def test_changelog_uses_entry_heading_body_and_local_date_not_toc():
    items = release_items()
    assert [i.title for i in items] == [
        "Opening up the in-house search API",
        "DeepSeek-V4.1-Flash-1017 Update",
        "DeepSeek-V4.1-Flash Release",
    ]
    update = items[1]
    assert update.published_at == "2026-10-17"
    assert update.url == URL + "#deepseek-v41-flash-1017-update"
    assert "pricing remain unchanged" in update.summary
    assert "DeepSWE v1.1: 77.0" in update.raw_excerpt
    assert "web and APP" in update.raw_excerpt
    assert "Today we officially release" not in update.raw_excerpt
    assert items[2].published_at == "2026-09-10"
    assert not ai_update_quality_issues(update)
    assert ai_update_category(update) == "model_release"


def test_changelog_does_not_promote_september_release_to_october():
    ranked = rank_ai_updates(release_items(), target_count=10, min_official_count=1,
        max_age_days=2, now=NOW)
    assert any("1017" in i.title for i in ranked)
    assert all(i.published_at == "2026-10-17" for i in ranked)
    assert not any(i.title == "DeepSeek-V4.1-Flash Release" for i in ranked)


def test_toc_alone_never_becomes_a_release():
    html = '<aside><h2>Date: 2026-10-17</h2><h3>DeepSeek-V4.1-Flash-1017 Update</h3></aside>'
    assert not rank_ai_updates(parse_official_html(html, source_name="DeepSeek",
        vendor="DeepSeek", base_url=URL), max_age_days=2, now=NOW)


def test_releases_keep_priority_across_date_groups_and_count_limit():
    newest = item("Qwen4 model released with open weights", vendor="Qwen",
        product="Qwen4", url="https://qwen.ai/blog/qwen4")
    tool = item("Agent Toolkit adds AI workspace export", vendor="Toolkit",
        url="https://example.com/export")
    older = item("DeepSeek-V4.1-Flash-1017 Update", day="2026-10-17", vendor="DeepSeek",
        product="DeepSeek-V4.1-Flash-1017", url=URL + "#deepseek-v41-flash-1017-update")
    ranked = rank_ai_updates([tool, newest, older], target_count=2, min_official_count=1,
        max_age_days=2, now=NOW)
    assert [i.title for i in ranked] == [newest.title, older.title]


@pytest.mark.parametrize("product", ["", "DeepSeek-V4.1-Flash"])
def test_dated_model_revision_is_not_duplicate_of_initial_release(product):
    initial = item("DeepSeek-V4.1-Flash Release", day="2026-09-10", vendor="DeepSeek",
        product=product, url=URL)
    initial.raw_excerpt = "Today we release DeepSeek-V4.1-Flash through the official API."
    update = item("DeepSeek-V4.1-Flash-1017 Update", day="2026-10-17", vendor="DeepSeek",
        product=product, url=URL)
    update.raw_excerpt = "Today we release DeepSeek-V4.1-Flash-1017 through the official API."
    assert ai_update_history_key(initial) != ai_update_history_key(update)
    mirror = update.model_copy(update={"url": "https://deepseek.com/news/update-1017",
        "title": "DeepSeek-V4.1-Flash-1017 released", "product": ""})
    assert ai_update_history_key(mirror) == ai_update_history_key(update)


def test_collection_keeps_new_model_update_after_quality_and_history_gates(monkeypatch):
    source = AIDigestSource("deepseek", "official", URL, "DeepSeek", "html", tier="official_stream")
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: HTML)
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")
    previous = item("DeepSeek-V4.1-Flash Release", day="2026-09-10", vendor="DeepSeek", url=URL)
    previous.raw_excerpt = "Today we release DeepSeek-V4.1-Flash through the official API."
    selected, _ = collect.collect_ai_digest_updates(sources=[source], target_count=10,
        min_official_count=1, max_age_days=2, now=NOW, persist_source_health=False,
        include_pool_items=True, exclude_history_keys={ai_update_history_key(previous)})
    updates = [i for i in selected if "1017" in i.title]
    assert len(updates) == 1
    assert updates[0].source_type == "official"
    assert updates[0].published_at == "2026-10-17"
    repeated, _ = collect.collect_ai_digest_updates(sources=[source], target_count=10,
        min_official_count=1, max_age_days=2, now=NOW, persist_source_health=False,
        include_pool_items=True, exclude_history_keys={ai_update_history_key(updates[0])})
    assert not any("1017" in i.title for i in repeated)
