from pathlib import Path
from typer.testing import CliRunner
from apps import cli
from src.sources import diagnostics


def test_check_sources_runs_daily_and_ai_collection_without_creating_posts(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    calls = []
    def fake_check(collection, **kwargs):
        calls.append((collection, kwargs))
        return {"rows": [], "elapsed_seconds": 0.1}
    monkeypatch.setattr(diagnostics, "run_source_diagnostics", fake_check)
    result = CliRunner().invoke(cli.app, ["check-sources", "--collection", "all", "--keywords", "World Cup"])
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "all"
    assert calls[0][1]["keywords"] == "World Cup"
    assert "检查完成" in result.output
    assert not (tmp_path / "data/posts").exists()


def test_check_sources_can_limit_to_one_collection(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    calls = []
    def fake_check(collection, **kwargs):
        calls.append(collection)
        return {"rows": [], "elapsed_seconds": 0.1}
    monkeypatch.setattr(diagnostics, "run_source_diagnostics", fake_check)
    result = CliRunner().invoke(cli.app, ["check-sources", "--collection", "ai_digest"])
    assert result.exit_code == 0, result.output
    assert calls == ["ai_digest"]


def test_check_sources_keeps_prompt_as_legacy_alias(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    calls = []
    def fake_check(collection, **kwargs):
        calls.append(kwargs["keywords"])
        return {"rows": [], "elapsed_seconds": 0.1}
    monkeypatch.setattr(diagnostics, "run_source_diagnostics", fake_check)
    result = CliRunner().invoke(cli.app, ["check-sources", "--collection", "daily_news", "--prompt", "legacy"])
    assert result.exit_code == 0, result.output
    assert calls == ["legacy"]
