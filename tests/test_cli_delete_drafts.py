from typer.testing import CliRunner

import apps.cli as cli


def test_delete_drafts_prints_preview_errors_and_does_not_say_empty(monkeypatch):
    def fake_run_delete_drafts_sync(**kwargs):
        return {
            "draft_type": kwargs.get("draft_type", "image"),
            "total": 0,
            "items": [],
            "errors": ["draft box not found"],
        }

    monkeypatch.setattr(cli, "run_delete_drafts_sync", fake_run_delete_drafts_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "delete-drafts",
            "--draft-type",
            "image",
            "--draft-location",
            "publish",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "type=image total=0" in result.output
    assert "errors:" in result.output
    assert "draft box not found" in result.output
    assert "预览草稿失败，未执行删除" in result.output
    assert "未找到草稿" not in result.output
