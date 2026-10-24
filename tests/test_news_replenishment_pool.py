import importlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.news.daily_news import NewsItem


create_post = importlib.import_module("src.workflow.create_post")
EXCLUDED_KEY = "url:https://completed.example/old-goal"


@pytest.mark.parametrize(
    "count,excluded,multiplier,raw_override,preferred,raw_capacity",
    [
        pytest.param(1, None, None, None, 1, 20, id="initial-single"),
        pytest.param(1, set(), None, None, 1, 20, id="single-empty-exclusions"),
        pytest.param(2, None, None, None, 20, 40, id="initial-two"),
        pytest.param(2, set(), None, None, 20, 40, id="two-empty-exclusions"),
        pytest.param(2, {EXCLUDED_KEY}, None, None, 100, 200, id="refill-two"),
        pytest.param(1, {EXCLUDED_KEY}, None, None, 100, 200, id="refill-single"),
        pytest.param(2, {EXCLUDED_KEY}, "1", "1", 10, 200, id="refill-low-limits"),
        pytest.param(2, {EXCLUDED_KEY}, "12", "350", 120, 350, id="refill-higher-limits"),
    ],
)
def test_fetch_preserves_replenishment_pool_without_increasing_goal(
    monkeypatch, tmp_path, count, excluded, multiplier, raw_override, preferred, raw_capacity
):
    monkeypatch.chdir(tmp_path)
    for name in (
        "NEWS_MATERIALS_FILE",
        "NEWS_LOOKBACK_DAYS",
        "CONTENT_LOOKBACK_DAYS",
        "NEWS_UPLOAD_QUALIFIED_POOL_MULTIPLIER",
        "NEWS_UPLOAD_RAW_MAX_RECORDS",
        "NEWS_RAW_MAX_RECORDS",
        "NEWS_SOURCE_CONTEXT_MIN_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DAILY_NEWS_SELECTION_POLICY", "soft")
    if multiplier is not None:
        monkeypatch.setenv("NEWS_UPLOAD_QUALIFIED_POOL_MULTIPLIER", multiplier)
    if raw_override is not None:
        monkeypatch.setenv("NEWS_UPLOAD_RAW_MAX_RECORDS", raw_override)

    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    reporting = [
        (
            "Doctors complete a clinical trial of a malaria vaccine",
            "Hospital researchers monitored patients through a full season of treatment. "
            "The clinical team reported fewer infections among vaccinated participants and "
            "published safety observations alongside the trial protocol for independent review.",
        ),
        (
            "Astronomers launch a satellite to study distant galaxies",
            "The orbital observatory deployed its telescope after reaching the planned altitude. "
            "Engineers verified the instruments before releasing the first calibration images. "
            "Scientists will use the measurements to examine stars beyond the Milky Way.",
        ),
        (
            "Farmers harvest grapes after installing precision irrigation",
            "Vineyard growers replaced flood watering with sensors that measure soil moisture. "
            "The agricultural cooperative documented lower water consumption during the harvest. "
            "Its field report compares grape quality across several independently managed farms.",
        ),
    ]
    stories = [
        NewsItem(
            title=title,
            description=description,
            url=f"https://source{index}.example/story",
            domain=f"source{index}.example",
            language="en",
            seendate=now.isoformat(),
        )
        for index, (title, description) in enumerate(reporting)
    ]
    completed = replace(
        stories[0], title="Previously completed original goal story",
        url=EXCLUDED_KEY.removeprefix("url:"), domain="completed.example",
    )
    stale = replace(
        stories[1], title="Archived observatory announcement",
        url="https://archive.example/expired", seendate=(now - timedelta(days=7)).isoformat(),
    )
    future = replace(
        stories[2], title="Future agricultural announcement",
        url="https://future.example/future", seendate=(now + timedelta(days=1)).isoformat(),
    )
    duplicate = replace(stories[0], url="https://syndication.example/copy")
    calls = []
    events = []
    holder = {}

    def fetch(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return [completed, stale, future, *stories, duplicate], {"provider": "fixture"}

    def prepare(items, progress_callback=None):
        return {index: (item, {}, {}, item) for index, item in enumerate(items, 1)}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fetch)
    monkeypatch.setattr(create_post, "_prefetch_daily_news_context", prepare)
    monkeypatch.setattr(create_post, "list_posts", lambda: [])

    selected, meta = create_post._fetch_daily_news_candidates_for_upload(
        "", count=count, lookback_days=1, exclude_story_keys=excluded,
        discovery_holder=holder,
        progress_callback=lambda stage, status, detail: events.append((stage, status, detail)),
    )

    assert len(calls) == 1
    assert calls[0][1]["max_records"] == raw_capacity
    assert calls[0][1]["search_days"] == 1
    assert calls[0][1]["tz_name"] == "Asia/Shanghai"
    session = holder["session"]
    assert session.count == count
    assert session.preferred_target == preferred
    assert session.excluded_story_keys == (excluded or set())
    assert meta["selection_pool"]["requested_count"] == count
    assert meta["selection_pool"]["target_fetch_count"] == preferred
    assert meta["selection_pool"]["raw_fetch_count"] == raw_capacity
    assert meta["selection_pool"]["lookback"]["selected_max_age_days"] == 1
    # Discovery still returns the requested main batch plus its existing one-item reserve.
    assert len(selected) == count + 1
    ready = events[-1][2]
    assert (ready["main"], ready["target"], ready["reserve"]) == (count, count, 1)
    assert not {stale.url, future.url} & {item.url for item in selected}
    assert len({item.title for item in selected}) == len(selected)
    if excluded:
        assert completed.url not in {item.url for item in selected}
        assert excluded == {EXCLUDED_KEY}
    assert session.record_path.resolve().is_relative_to(tmp_path)
