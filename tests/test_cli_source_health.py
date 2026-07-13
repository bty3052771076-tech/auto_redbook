from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from apps import cli


def test_check_sources_runs_daily_and_ai_collection_without_creating_posts(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, dict]] = []

    def fake_daily(prompt, **kwargs):
        calls.append(("daily_news", {"prompt": prompt, **kwargs}))
        return [], {"source_health": {"attempts": [{"source_name": "google_rss", "status": "success"}]}}

    def fake_ai(**kwargs):
        calls.append(("ai_digest", kwargs))
        return [], {"source_health": {"attempts": [{"source_name": "openai", "status": "success"}]}}

    monkeypatch.setattr(cli, "fetch_daily_news_candidates", fake_daily, raising=False)
    monkeypatch.setattr(cli, "collect_ai_digest_updates", fake_ai, raising=False)

    result = CliRunner().invoke(cli.app, ["check-sources", "--collection", "all", "--prompt", "World Cup"])

    assert result.exit_code == 0, result.output
    assert [name for name, _kwargs in calls] == ["daily_news", "ai_digest"]
    assert calls[0][1]["source_health_path"] == Path("data") / "source_health" / "daily_news.json"
    assert calls[1][1]["source_health_path"] == Path("data") / "source_health" / "ai_digest.json"
    assert "检查完成" in result.output


def test_check_sources_can_limit_to_one_collection(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(
        cli,
        "collect_ai_digest_updates",
        lambda **_kwargs: calls.append("ai_digest") or ([], {"source_health": {"attempts": []}}),
        raising=False,
    )

    result = CliRunner().invoke(cli.app, ["check-sources", "--collection", "ai_digest"])

    assert result.exit_code == 0, result.output
    assert calls == ["ai_digest"]
