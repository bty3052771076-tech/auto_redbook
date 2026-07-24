import pytest

from apps import cli
from src.storage.models import Post
from src.workflow import create_post


def test_empty_assets_glob_is_an_auto_image_sentinel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    empty_dir = tmp_path / "assets" / "empty"
    empty_dir.mkdir(parents=True)
    (empty_dir / "stale.png").write_bytes(b"stale")

    assert cli._initial_asset_paths("assets/empty/*") == []
    assert cli._is_auto_image_sentinel_glob("assets\\empty\\*")


def test_cli_text_repair_restores_corrupted_daily_news_title(capsys):
    original = "\u6bcf\u65e5\u65b0\u95fb"
    corrupted = original.encode("utf-8").decode("gb18030")

    assert cli._repair_cli_text(corrupted, field="title") == original
    assert "repaired UTF-8/GBK mojibake" in capsys.readouterr().out


def test_upload_fingerprint_treats_whitespace_and_punctuation_variants_as_duplicate():
    first = Post(title="\u6bcf\u65e5\u65b0\u95fb", body="\u8d22\u7ecf\u4ea7\u4e1a\u901f\u89c8\uff0c\u5e02\u573a\u53d8\u5316\u3002")
    second = Post(title="\u6bcf\u65e5\u65b0\u95fb!", body="\u8d22\u7ecf\u4ea7\u4e1a\u901f\u89c8 \u5e02\u573a\u53d8\u5316")

    assert cli._post_upload_fingerprint(first) == cli._post_upload_fingerprint(second)


def test_generic_llm_fallback_is_not_saved_as_a_draft(monkeypatch):
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [])
    monkeypatch.setattr(
        create_post,
        "generate_draft",
        lambda *_args, **_kwargs: {
            "title": "\u6d4b\u8bd5",
            "body": "\uff08\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\uff09",
            "topics": [],
            "_fallback_error": "429 RATE_LIMIT_EXCEEDED",
        },
    )

    with pytest.raises(RuntimeError, match="fallback placeholder will not be saved or uploaded"):
        create_post.create_post_with_draft(
            title_hint="\u666e\u901a\u65b0\u95fb",
            prompt_hint="\u6d4b\u8bd5",
            asset_paths=[],
            auto_image=False,
        )
