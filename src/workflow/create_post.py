from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List

from src.config import load_llm_config
from src.llm.generate import generate_draft
from src.storage.files import copy_assets_into_post, save_post, save_revision
from src.storage.models import AssetInfo, Post, PostStatus, Revision, RevisionSource


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_asset_infos(paths: Iterable[Path]) -> List[AssetInfo]:
    infos: List[AssetInfo] = []
    for p in paths:
        if not p.exists():
            continue
        infos.append(
            AssetInfo(
                path=str(p),
                kind="image",
                size_bytes=p.stat().st_size,
                sha256=_sha256(p),
                validated=True,
            )
        )
    return infos


def create_post_with_draft(
    *,
    title_hint: str,
    prompt_hint: str,
    asset_paths: list[str],
    copy_assets: bool = True,
) -> Post:
    """
    Generate a draft with LLM and persist post + revision.
    """
    cfg = load_llm_config()
    draft = generate_draft(cfg, title_hint=title_hint, prompt_hint=prompt_hint, asset_paths=asset_paths)

    post = Post(
        type="image",
        status=PostStatus.draft,
        title=draft["title"],
        body=draft["body"],
        topics=draft.get("topics", []),
    )

    assets_paths = [Path(p) for p in asset_paths]
    if copy_assets:
        copied = copy_assets_into_post(post.id, assets_paths)
        asset_infos = _build_asset_infos(copied)
    else:
        asset_infos = _build_asset_infos(assets_paths)
    post.assets = asset_infos

    rev = Revision(
        post_id=post.id,
        source=RevisionSource.llm,
        content=draft,
    )

    save_post(post)
    save_revision(rev)

    return post
