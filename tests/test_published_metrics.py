from src.publish.playwright_steps import (
    _classify_xhs_page_state,
    _published_metrics_collection_status,
    _parse_metric_number,
    _parse_published_metric_text,
    _parse_published_total_text,
    _published_metrics_collect_cap,
    _published_url_candidates,
    _wait_for_xhs_ready,
    _merge_published_metric_cards,
    _remember_published_note_target,
)
import pytest


def test_parse_metric_number_supports_chinese_and_short_units():
    assert _parse_metric_number("1.2万") == 12000
    assert _parse_metric_number("3k") == 3000
    assert _parse_metric_number("1,234") == 1234


def test_parse_published_metric_text_extracts_title_and_counts():
    parsed = _parse_published_metric_text(
        "中国科技新闻标题\n点赞 12\n评论：3\n收藏 4\n2026-06-27"
    )

    assert parsed["title"] == "中国科技新闻标题"
    assert parsed["likes"] == 12
    assert parsed["comments"] == 3
    assert parsed["favorites"] == 4


def test_parse_published_metric_text_extracts_note_manager_stats_row():
    parsed = _parse_published_metric_text(
        "七孩父亲在妻产四胞胎后离奇去世\n2026-06-27 08:19\n33\n1\n2\n3\n4"
    )

    assert parsed["title"] == "七孩父亲在妻产四胞胎后离奇去世"
    assert parsed["published_at"] == "2026-06-27"
    assert parsed["likes"] == 1
    assert parsed["comments"] == 2
    assert parsed["favorites"] == 3


def test_parse_published_metric_text_allows_metric_words_inside_title():
    parsed = _parse_published_metric_text(
        "库克点赞印度市场\n2026-02-01 12:45\n13\n0\n0\n0\n0"
    )

    assert parsed["title"] == "库克点赞印度市场"
    assert parsed["published_at"] == "2026-02-01"
    assert parsed["likes"] == 0
    assert parsed["comments"] == 0
    assert parsed["favorites"] == 0

    browser_title = _parse_published_metric_text(
        "思科与Island浏览器实现零信任\n2026-06-23 11:53\n15\n0\n0\n0\n0"
    )

    assert browser_title["title"] == "思科与Island浏览器实现零信任"
    assert browser_title["likes"] == 0


def test_parse_published_metric_text_skips_status_and_action_lines():
    parsed = _parse_published_metric_text(
        "未通过\nAI冲击印度IT股暴跌\n查看修改建议\n2026-02-26 09:58\n4\n0\n0\n0\n0"
    )

    assert parsed["title"] == "AI冲击印度IT股暴跌"
    assert parsed["published_at"] == "2026-02-26"
    assert parsed["likes"] == 0


def test_merge_published_metric_cards_keeps_same_title_on_different_dates():
    metrics = _merge_published_metric_cards(
        [
            {"text": "同一标题\n2026-02-01 12:45\n13\n0\n0\n0\n0", "href": ""},
            {"text": "同一标题\n2026-02-02 12:45\n15\n1\n0\n0\n0", "href": ""},
        ]
    )

    assert len(metrics) == 2
    assert {metric.published_at for metric in metrics} == {"2026-02-01", "2026-02-02"}


def test_published_metrics_defaults_prefer_current_note_manager_route():
    assert _published_url_candidates()[0] == "https://creator.xiaohongshu.com/new/note-manager"


def test_published_metrics_default_routes_exclude_legacy_and_editor_pages():
    candidates = _published_url_candidates()

    assert candidates == ["https://creator.xiaohongshu.com/new/note-manager"]
    assert all("/creator/notes" not in url for url in candidates)
    assert all("/publish/publish" not in url for url in candidates)


def test_published_metrics_collect_cap_is_configurable(monkeypatch):
    assert _published_metrics_collect_cap() >= 1000

    monkeypatch.setenv("XHS_METRICS_MAX_ITEMS", "25")

    assert _published_metrics_collect_cap() == 25


def test_parse_published_total_text():
    assert _parse_published_total_text("全部 297\n已发布\n审核中") == 297
    assert _parse_published_total_text("没有总数") == 0


def test_published_metrics_collection_status_requires_target_total_when_unlimited():
    status = _published_metrics_collection_status(collected=317, target_total=322, limit=0)

    assert status["complete"] is False
    assert status["missing_count"] == 5
    assert "fetched=317 target=322 missing=5" in status["message"]


def test_published_metrics_collection_status_rejects_unknown_target_when_unlimited():
    status = _published_metrics_collection_status(collected=330, target_total=0, limit=0)

    assert status["complete"] is False
    assert status["required_total"] == 0
    assert status["missing_count"] == 0
    assert "target=unknown" in status["message"]


def test_published_metrics_collection_status_treats_limit_as_requested_scope():
    status = _published_metrics_collection_status(collected=50, target_total=322, limit=50)

    assert status["complete"] is True
    assert status["required_total"] == 50


def test_remember_published_note_target_keeps_largest_observed_total():
    result = {"target_total": 0}

    assert _remember_published_note_target(result, 0) == 0
    assert _remember_published_note_target(result, 335) == 335
    assert result["target_total"] == 335
    assert _remember_published_note_target(result, 322) == 335
    assert result["target_total"] == 335


def test_xhs_not_found_page_is_not_ready_even_with_creator_shell_text():
    state = _classify_xhs_page_state(
        "https://creator.xiaohongshu.com/creator/notes?source=publish",
        "你访问的页面不见了",
        "小红书创作服务平台\n图文笔记\n上传图文",
    )

    assert state == "not_found"


def test_wait_for_xhs_ready_fails_fast_on_not_found_page():
    calls = {"sleep": 0}
    ticks = iter([0, 0, 601])

    def reader(_page):
        return (
            "not_found",
            "state=not_found url=https://creator.xiaohongshu.com/creator/notes?source=publish title=你访问的页面不见了",
        )

    def sleep_fn(_seconds):
        calls["sleep"] += 1

    with pytest.raises(RuntimeError, match="page unavailable"):
        _wait_for_xhs_ready(
            object(),
            login_hold=600,
            state_reader=reader,
            sleep_fn=sleep_fn,
            monotonic_fn=lambda: next(ticks),
        )

    assert calls["sleep"] == 0
