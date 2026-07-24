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


def test_validate_rejects_recoverable_utf8_as_gbk_mojibake(tmp_path: Path):
    asset = tmp_path / "a.jpg"
    asset.write_bytes(b"hello")
    corrupted_title = "\u6bcf\u65e5\u65b0\u95fb".encode("utf-8").decode("gb18030")
    post = Post(type=PostType.image, title=corrupted_title, body="\u6b63\u5e38\u6b63\u6587", assets=[_asset(asset)])

    result = validate_post(post)

    assert not result.ok
    assert "title contains UTF-8/GBK mojibake" in result.errors


def test_validate_rejects_generation_failure_placeholder(tmp_path: Path):
    asset = tmp_path / "a.jpg"
    asset.write_bytes(b"hello")
    post = Post(
        type=PostType.image,
        title="\u6b63\u5e38\u6807\u9898",
        body="\uff08\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\uff09",
        assets=[_asset(asset)],
    )

    result = validate_post(post)

    assert not result.ok
    assert "body is a generation-failure placeholder" in result.errors
