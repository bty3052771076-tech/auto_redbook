from src.publish.draft_inventory import (
    LocalDraftRecord,
    PlatformDraftRecord,
    match_draft_inventory,
    normalize_draft_title,
)


def _local(post_id: str, title: str, saved_at: str = "") -> LocalDraftRecord:
    return LocalDraftRecord(post_id=post_id, title=title, saved_at=saved_at)


def _platform(index: int, title: str, saved_at: str = "") -> PlatformDraftRecord:
    return PlatformDraftRecord(index=index, title=title, saved_at=saved_at)


def test_inventory_matches_exact_normalized_title_only():
    result = match_draft_inventory(
        [_local("one", " Daily AI | Model update ")],
        [_platform(3, "Daily AI|Model update")],
    )

    assert [item.local.post_id for item in result.matched] == ["one"]
    assert result.local_missing_on_platform == []
    assert result.platform_without_local == []
    assert result.ambiguous == []


def test_inventory_reports_local_only_and_platform_only_records():
    result = match_draft_inventory(
        [_local("local", "Local title"), _local("missing", "Not on platform")],
        [_platform(1, "Local title"), _platform(2, "Platform-only")],
    )

    assert [item.local.post_id for item in result.matched] == ["local"]
    assert [item.post_id for item in result.local_missing_on_platform] == ["missing"]
    assert [item.title for item in result.platform_without_local] == ["Platform-only"]


def test_duplicate_titles_use_unique_nearest_saved_time():
    result = match_draft_inventory(
        [_local("one", "Same", "2026-08-20T10:01:00+08:00")],
        [
            _platform(1, "Same", "2026-08-20T09:00:00+08:00"),
            _platform(2, "Same", "2026-08-20T10:01:05+08:00"),
        ],
    )

    assert [item.platform.index for item in result.matched] == [2]


def test_duplicate_titles_without_unique_time_are_ambiguous():
    result = match_draft_inventory(
        [_local("one", "Same"), _local("two", "Same")],
        [_platform(1, "Same"), _platform(2, "Same")],
    )

    assert result.matched == []
    assert [item.post_id for item in result.ambiguous] == ["one", "two"]


def test_normalization_does_not_enable_substring_matching():
    assert normalize_draft_title("ＡＩ｜模型  3") == "ai|模型3"
    assert normalize_draft_title("AI：模型 3") == normalize_draft_title("AI:模型3")
    result = match_draft_inventory(
        [_local("one", "Model update")],
        [_platform(1, "Model update extended")],
    )
    assert result.matched == []
    assert [item.post_id for item in result.local_missing_on_platform] == ["one"]
