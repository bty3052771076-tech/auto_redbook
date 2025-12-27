from pathlib import Path

from src.storage.models import AssetInfo, Post, PostType
from src.validation import validate_post


def _asset(path: Path) -> AssetInfo:
    return AssetInfo(path=str(path), size_bytes=path.stat().st_size, validated=True)


def test_validate_image_post_ok(tmp_path: Path):
    asset = tmp_path / "a.jpg"
    asset.write_bytes(b"hello")
    post = Post(type=PostType.image, title="t", body="b", assets=[_asset(asset)])
    result = validate_post(post)
    assert result.ok


def test_validate_title_too_long(tmp_path: Path):
    asset = tmp_path / "a.jpg"
    asset.write_bytes(b"hello")
    post = Post(type=PostType.image, title="x" * 21, body="b", assets=[_asset(asset)])
    result = validate_post(post)
    assert not result.ok
    assert any("title too long" in err for err in result.errors)


def test_validate_missing_asset(tmp_path: Path):
    missing = tmp_path / "missing.jpg"
    post = Post(type=PostType.image, title="t", body="b", assets=[AssetInfo(path=str(missing))])
    result = validate_post(post)
    assert not result.ok
    assert any("asset not found" in err for err in result.errors)
