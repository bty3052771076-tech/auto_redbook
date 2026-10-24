from datetime import datetime, timezone

import pytest

from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import (
    ai_update_category,
    ai_update_history_key,
    ai_update_quality_issues,
    dedupe_ai_updates,
    rank_ai_updates,
)


def _release(repo, tag, notes="Bug fixes and stability improvements.", **overrides):
    data = dict(
        title=f"Release {tag}",
        summary=notes,
        raw_excerpt=notes,
        product="GitHub Release",
        vendor="OpenAI" if repo == "openai/codex" else "Anthropic",
        source_name=repo,
        source_type="github",
        url=f"https://github.com/{repo}/releases/tag/{tag}",
        published_at="2026-10-23T01:00:00Z",
    )
    data.update(overrides)
    return AIUpdateItem(**data)


@pytest.mark.parametrize("repo,tag", [
    ("openai/codex", "rust-v0.115.0-alpha.4"),
    ("anthropics/claude-code", "v2.1.290"),
])
def test_cli_releases_are_tools_even_when_notes_mention_model_releases(repo, tag):
    item = _release(repo, tag, "Added support for the newly released GPT-5 model.")
    assert ai_update_category(item) == "technical_tool"


@pytest.mark.parametrize("product", ["Codex CLI", "Claude Code"])
def test_named_cli_release_on_official_page_is_not_a_model(product):
    item = AIUpdateItem(
        title=f"{product} v2.1.290 released",
        product=product,
        summary="Added hooks for sandbox permission checks.",
        url="https://example.com/changelog",
    )
    assert ai_update_category(item) == "technical_tool"


@pytest.mark.parametrize("repo,tags", [
    ("openai/codex", ["rust-v0.115.0-alpha.1", "rust-v0.115.0-alpha.2", "rust-v0.115.0-alpha.3"]),
    ("openai/codex", ["rust-v0.115.0-beta.1", "rust-v0.115.0-beta.2", "rust-v0.115.0-beta.3"]),
    ("anthropics/claude-code", ["v2.1.288", "v2.1.289", "v2.1.290"]),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_routine_release_stream_keeps_latest_and_all_evidence(repo, tags, reverse):
    items = [
        _release(repo, tag, published_at=f"2026-10-23T0{index + 1}:00:00Z")
        for index, tag in enumerate(tags)
    ]
    items[0] = items[0].model_copy(update={
        "confidence_score": 0.99,
        "evidence_urls": ["https://example.com/confirmation"],
        "tags": ["reviewed"],
    })
    before = [item.model_dump() for item in items]
    result = dedupe_ai_updates(list(reversed(items)) if reverse else items)
    assert len(result) == 1
    assert result[0].url == f"https://github.com/{repo}/releases/tag/{tags[2]}"
    assert result[0].published_at == "2026-10-23T03:00:00Z"
    assert {items[0].url, items[1].url, "https://example.com/confirmation"} <= set(result[0].evidence_urls)
    assert "reviewed" in result[0].tags
    assert [item.model_dump() for item in items] == before


def test_repeated_concrete_change_across_patch_tags_is_one_editorial_event():
    notes = "Fixed Windows terminal crash when restoring a suspended sandbox session."
    old = _release("anthropics/claude-code", "v2.1.289", notes)
    new = _release("anthropics/claude-code", "v2.1.290", notes, published_at="2026-10-23T03:00:00Z")
    result = dedupe_ai_updates([old, new])
    assert len(result) == 1
    assert result[0].url.endswith("/v2.1.290")
    assert old.url in result[0].evidence_urls


def test_independent_changes_in_same_product_are_not_limited_by_vendor_quota():
    notes = [
        "Added MCP server authentication through OAuth device flow.",
        "Fixed Windows terminal crash when resuming sandbox sessions.",
        "Added team billing export with per-project usage reports.",
        "Added repository-wide code search with symbol navigation.",
        "Added offline session replay for interrupted tool calls.",
    ]
    items = [
        _release("anthropics/claude-code", f"v2.1.{288 + index}", note)
        for index, note in enumerate(notes)
    ]
    ranked = rank_ai_updates(items, target_count=20, min_official_count=0)
    assert {item.url for item in ranked} == {
        "https://github.com/anthropics/claude-code/releases/tag/v2.1.288",
        "https://github.com/anthropics/claude-code/releases/tag/v2.1.289",
        "https://github.com/anthropics/claude-code/releases/tag/v2.1.290",
        "https://github.com/anthropics/claude-code/releases/tag/v2.1.291",
        "https://github.com/anthropics/claude-code/releases/tag/v2.1.292",
    }


def test_same_generic_headline_does_not_merge_independent_patch_changes():
    one = _release("openai/codex", "rust-v0.115.0-alpha.1", "Added remote sandbox execution.", title="Codex CLI update")
    two = _release("openai/codex", "rust-v0.115.0-alpha.2", "Added SSO authentication.", title="Codex CLI update")
    assert len(dedupe_ai_updates([one, two])) == 2


def test_different_repositories_with_identical_notes_are_independent():
    one = _release("openai/codex", "v2.1.290")
    two = _release("anthropics/claude-code", "v2.1.290")
    assert len(dedupe_ai_updates([one, two])) == 2


def test_major_and_minor_release_lines_are_not_collapsed():
    items = [_release("anthropics/claude-code", tag) for tag in ["v2.1.290", "v2.2.0", "v3.0.0"]]
    assert len(dedupe_ai_updates(items)) == 3


def test_undated_release_tags_are_not_assumed_to_share_a_briefing_window():
    one = _release("anthropics/claude-code", "v2.1.289", published_at="")
    two = _release("anthropics/claude-code", "v2.1.290", published_at="")
    assert len(dedupe_ai_updates([one, two])) == 2


@pytest.mark.parametrize("notes", [
    "Release 0.115.0-alpha.4",
    "Bug fixes and improvements.",
    "Maintenance release with various bug fixes and stability improvements.",
    "修复若干问题，优化性能和稳定性。",
])
def test_version_or_generic_maintenance_only_cannot_reach_featured_news(notes):
    item = _release("openai/codex", "rust-v0.115.0-alpha.4", notes)
    assert ai_update_quality_issues(item)
    assert rank_ai_updates([item], target_count=1, min_official_count=0) == []


@pytest.mark.parametrize("notes", [
    "Added MCP server authentication through OAuth device flow.",
    "Fixed Windows terminal crash when restoring sandbox sessions.",
    "新增沙箱权限钩子，支持在执行命令前拦截高风险操作。",
])
def test_specific_feature_or_targeted_bugfix_remains_eligible(notes):
    item = _release("openai/codex", "rust-v0.115.0-alpha.4", notes)
    assert ai_update_quality_issues(item) == ()
    assert len(rank_ai_updates([item], min_official_count=0)) == 1


def test_real_model_variants_and_codex_model_are_not_tool_release_streams():
    items = [
        _release("QwenLM/Qwen3", "v3.0.0-mini", "Qwen3 Mini released with open weights.", title="Qwen3 Mini released", product="Qwen3 Mini"),
        _release("QwenLM/Qwen3", "v3.0.0-max", "Qwen3 Max released with open weights.", title="Qwen3 Max released", product="Qwen3 Max"),
        AIUpdateItem(title="GPT-5-Codex model released", product="GPT-5-Codex",
                     summary="A new coding model is available through the API.",
                     url="https://openai.com/index/gpt-5-codex"),
    ]
    assert [ai_update_category(item) for item in items] == ["model_release"] * 3
    assert len(dedupe_ai_updates(items)) == 3


def test_same_tag_with_rewritten_title_still_dedupes_and_preserves_history_key():
    original = _release("anthropics/claude-code", "v2.1.290", "Added agent.spawn for teammates.")
    reviewed = original.model_copy(update={"title": "Claude Code adds agent.spawn"})
    result = dedupe_ai_updates([original, reviewed])
    assert len(result) == 1
    assert ai_update_history_key(result[0]) == ai_update_history_key(original)
    assert result[0].url == original.url


def test_ranked_repeated_specific_change_keeps_newest_source_not_old_confidence():
    old = _release("openai/codex", "rust-v0.115.0-alpha.1",
                   "Added remote sandbox execution.", confidence_score=0.99)
    new = _release("openai/codex", "rust-v0.115.0-alpha.2",
                   "Added remote sandbox execution.", published_at="2026-10-23T03:00:00Z")
    ranked = rank_ai_updates([old, new], target_count=20, min_official_count=0,
                             now=datetime(2026, 10, 23, 4, tzinfo=timezone.utc), max_age_days=2)
    assert len(ranked) == 1
    assert ranked[0].url == new.url
    assert old.url in ranked[0].evidence_urls


def test_dependency_versions_in_changes_are_not_erased_as_release_labels():
    one = _release("openai/codex", "rust-v0.115.0-alpha.1", "Added Python 3.12.0 runtime support.")
    two = _release("openai/codex", "rust-v0.115.0-alpha.2", "Added Python 3.13.0 runtime support.")
    assert len(dedupe_ai_updates([one, two])) == 2


def test_official_versioned_tool_updates_with_same_headline_remain_independent():
    one = _release("anthropics/claude-code", "v2.1.289", "Added MCP authentication.",
                   title="Claude Code update", product="Claude Code v2.1.289",
                   url="https://example.com/claude-code-mcp", source_type="official")
    two = _release("anthropics/claude-code", "v2.1.290", "Added billing export.",
                   title="Claude Code update", product="Claude Code v2.1.290",
                   url="https://example.com/claude-code-billing", source_type="official")
    assert len(dedupe_ai_updates([one, two])) == 2


def test_newer_media_mirror_does_not_displace_official_release_provenance():
    official = _release("anthropics/claude-code", "v2.1.289", "Added MCP authentication.")
    media = _release("anthropics/claude-code", "v2.1.290", "Added MCP authentication.",
                     title="Claude Code v2.1.290 released",
                     url="https://example.com/report", source_type="aggregator",
                     published_at="2026-10-23T03:00:00Z")
    result = dedupe_ai_updates([official, media])
    assert len(result) == 1
    assert result[0].url == official.url
    assert result[0].source_type == "github"
    assert media.url in result[0].evidence_urls


def test_case_insensitive_prerelease_stage_is_a_valid_release_stream():
    one = _release("openai/codex", "rust-v0.115.0-ALPHA.1")
    two = _release("openai/codex", "rust-v0.115.0-ALPHA.2")
    result = dedupe_ai_updates([one, two])
    assert len(result) == 1
    assert result[0].url == two.url

def test_unversioned_tool_article_mirrors_keep_existing_cross_source_dedupe():
    official = AIUpdateItem(
        title="Claude Code update", product="Claude Code",
        summary="Added remote execution for agent sessions.",
        url="https://anthropic.com/news/code",
    )
    detail = official.model_copy(update={"title": "Claude Code update details"})
    social = official.model_copy(update={
        "source_type": "social", "url": "https://x.com/AnthropicAI/status/1",
    })
    result = dedupe_ai_updates([social, detail, official])
    assert len(result) == 1
    assert result[0].source_type == "official"
    assert social.url in result[0].evidence_urls


def test_changed_action_on_same_target_is_not_an_equivalent_patch():
    one = _release("openai/codex", "rust-v0.115.0-alpha.1", "Added remote sandbox execution.")
    two = _release("openai/codex", "rust-v0.115.0-alpha.2", "Removed remote sandbox execution.")
    assert len(dedupe_ai_updates([one, two])) == 2


@pytest.mark.parametrize("notes", [
    "Small bug fixes.",
    "修复bug，优化稳定性。",
    "Release0.115.0-alpha.4",
])
def test_other_label_only_release_formats_are_also_filtered(notes):
    item = _release("openai/codex", "rust-v0.115.0-alpha.4", notes)
    assert ai_update_quality_issues(item)


def test_same_time_equivalent_patches_prefer_newer_version():
    one = _release("anthropics/claude-code", "v2.1.289")
    two = _release("anthropics/claude-code", "v2.1.290")
    result = dedupe_ai_updates([one, two])
    assert len(result) == 1
    assert result[0].url == two.url


def test_versioned_official_tool_articles_keep_independent_events():
    one = _release("anthropics/claude-code", "v2.1.289", "Added MCP authentication.",
                   title="Claude Code v2.1.289 released",
                   url="https://example.com/claude-code-mcp", source_type="official")
    two = _release("anthropics/claude-code", "v2.1.290", "Added team billing export.",
                   title="Claude Code v2.1.290 released",
                   url="https://example.com/claude-code-billing", source_type="official")
    assert len(dedupe_ai_updates([one, two])) == 2


@pytest.mark.parametrize("data", [
    {
        "title": "OpenAI Codex 发布 rust-v0.163.0-alpha.11.2",
        "summary": "OpenAI 在 Codex 官方 GitHub 发布 rust-v0.163.0-alpha.11.2 预发布版本。",
        "raw_excerpt": "Release 0.163.0-alpha.11.2",
        "url": "https://github.com/openai/codex/releases/tag/rust-v0.163.0-alpha.11.2",
        "published_at": "2026-10-22T06:47:07Z",
        "product": "",
        "vendor": "OpenAI",
        "source_type": "github",
    },
    {
        "title": "Claude Code v2.1.308 进行错误修复与可靠性改进",
        "summary": "Anthropic 发布 Claude Code v2.1.308，主要进行错误修复并提升可靠性。该版本属于 Claude Code 官方 GitHub 项目的版本更新。",
        "raw_excerpt": "## What's changed - Bug fixes and reliability improvements",
        "url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.308",
        "published_at": "2026-10-22T04:34:55Z",
        "product": "GitHub Release",
        "vendor": "Anthropic",
        "source_type": "github",
    },
])
def test_real_release_rewrites_cannot_turn_labels_into_substantive_news(data):
    item = AIUpdateItem(**data)
    assert "non_substantive_release" in ai_update_quality_issues(item)
    assert rank_ai_updates([item], min_official_count=0) == []


def test_generated_specific_claim_cannot_override_label_only_source_evidence():
    item = _release(
        "openai/codex", "rust-v0.163.0-alpha.11.2",
        title="Codex CLI adds MCP authentication",
        summary="Added OAuth device authorization for remote MCP servers.",
        raw_excerpt="Release 0.163.0-alpha.11.2",
    )
    assert "non_substantive_release" in ai_update_quality_issues(item)


def test_editorial_equivalence_uses_raw_evidence_not_different_writer_expansions():
    one = _release(
        "anthropics/claude-code", "v2.1.307", "Fixed MCP connections after Windows resumes from sleep.",
        title="Claude Code fixes Windows MCP sessions",
        summary="Claude Code restores sleeping Windows MCP connections.",
    )
    two = _release(
        "anthropics/claude-code", "v2.1.308", "Fixed MCP connections after Windows resumes from sleep.",
        title="Claude Code improves MCP recovery",
        summary="Anthropic improved MCP reconnection following Windows sleep.",
    )
    result = dedupe_ai_updates([one, two])
    assert len(result) == 1
    assert result[0].url == two.url
    assert one.url in result[0].evidence_urls


def test_multisegment_alpha_serials_dedupe_and_sort_numerically():
    one = _release("openai/codex", "rust-v0.163.0-alpha.11.9", "Release 0.163.0-alpha.11.9")
    two = _release("openai/codex", "rust-v0.163.0-alpha.11.10", "Release 0.163.0-alpha.11.10")
    result = dedupe_ai_updates([one, two])
    assert len(result) == 1
    assert result[0].url == two.url
    assert one.url in result[0].evidence_urls


@pytest.mark.parametrize("excerpt", [None, "OpenAI 在 Codex 官方 GitHub 发布 rust-v0.163.0-alpha.11.2 预发布版本。"])
def test_chinese_prerelease_template_is_not_a_concrete_change(excerpt):
    item = _release(
        "openai/codex", "rust-v0.163.0-alpha.11.2",
        title="OpenAI Codex 发布 rust-v0.163.0-alpha.11.2",
        summary="OpenAI 在 Codex 官方 GitHub 发布 rust-v0.163.0-alpha.11.2 预发布版本。",
        raw_excerpt=excerpt or "",
    )
    assert "non_substantive_release" in ai_update_quality_issues(item)


@pytest.mark.parametrize("excerpt", [None, "修复与可靠性改进"])
def test_chinese_generic_maintenance_template_is_not_a_concrete_change(excerpt):
    item = _release(
        "anthropics/claude-code", "v2.1.308",
        title="Claude Code v2.1.308 进行错误修复与可靠性改进",
        summary="Anthropic 发布 Claude Code v2.1.308，主要进行错误修复并提升可靠性。该版本属于 Claude Code 官方 GitHub 项目的版本更新。",
        raw_excerpt=excerpt or "",
    )
    assert "non_substantive_release" in ai_update_quality_issues(item)


@pytest.mark.parametrize("notes", [
    "## What's changed - Fixed reliability of MCP connections after Windows resumes from sleep.",
    "修复 Windows 休眠恢复后 MCP 连接的可靠性问题。",
    "修复云会话未携带会话环境变量时错误显示未登录的问题。",
])
@pytest.mark.parametrize("has_excerpt", [False, True])
def test_specific_conditions_and_targets_survive_raw_evidence_priority(notes, has_excerpt):
    item = _release(
        "anthropics/claude-code", "v2.1.308", notes,
        raw_excerpt=notes if has_excerpt else "",
    )
    assert ai_update_quality_issues(item) == ()
    assert len(rank_ai_updates([item], min_official_count=0)) == 1
