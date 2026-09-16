"""GitHub Status incident entries must never enter the AI digest."""

from src.ai_digest.sources import default_ai_digest_sources


def test_github_status_source_is_not_collected():
    """The github-status RSS is no longer part of the source list."""
    names = [source.name for source in default_ai_digest_sources()]
    assert "github-status" not in names
    assert not any("githubstatus.com" in str(source.url) for source in default_ai_digest_sources())
