from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List

from src.config import load_llm_config
from src.images.auto_image import fetch_and_download_related_image, is_auto_image_enabled
from src.llm.generate import generate_draft
from src.news.daily_news import (
    fetch_and_pick_daily_news,
    fetch_daily_news_candidates,
    pick_news_items,
)
from src.storage.files import copy_assets_into_post, post_dir, save_post, save_revision
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


def _shorten_daily_news_title(news_title: str, *, max_len: int = 20) -> str:
    title = (news_title or "").strip()
    if not title:
        return "每日新闻"
    # Prefer the first segment before long detail separators.
    for sep in ("：", ":", " - ", "—", "（", "("):
        if sep in title:
            head = title.split(sep, 1)[0].strip()
            if head:
                title = head
                break
    prefix = "每日新闻｜"
    if len(prefix) + len(title) <= max_len:
        return f"{prefix}{title}"
    # Trim title to fit.
    room = max(0, max_len - len(prefix))
    return f"{prefix}{title[:room]}".rstrip("｜").rstrip()


def _daily_news_prompt(picked, prompt_norm: str) -> str:
    """
    Prompt for LLM to write publishable body ONLY (no metadata/requirements echoed).
    """
    return (
        "你正在为小红书图文笔记写「每日新闻」栏目。\n"
        "请根据下面的新闻信息写一篇可直接发布的正文（通俗中文）。\n"
        "注意：正文里不要包含“来源/时间/链接/提示词/要求”等元信息，也不要复述下面的提示文本。\n\n"
        f"新闻标题：{picked.title}\n"
        f"用户关注点（可选）：{prompt_norm or '无'}\n\n"
        "写作要求：\n"
        "- 1-2 句概括新闻主题（不要杜撰未提供的具体细节/数字）\n"
        "- 2-3 条你的解读/影响/建议（可结合用户关注点）\n"
        "- 结尾给一个互动问题，引导评论\n"
        "- topics 输出 3-8 个话题词，包含「每日新闻」\n"
    )


def _daily_news_offline_body(picked, prompt_norm: str) -> str:
    """
    Offline fallback body: keep it publishable and avoid echoing prompt/requirements.
    """
    focus = prompt_norm.strip()
    focus_line = f"从「{focus}」角度" if focus else "从大众关心的角度"
    return (
        f"今日要闻：{picked.title}\n\n"
        f"{focus_line}，这条新闻值得关注的原因是：\n"
        "1）它释放了一个重要信号，后续可能还会有更多细节披露；\n"
        "2）对相关人群/行业的影响，需要结合权威信息持续观察；\n"
        "3）如果你也在关注这个话题，建议留意官方/主流媒体的进一步更新。\n\n"
        "你觉得这条新闻接下来会怎么发展？"
    )


def create_post_with_draft(
    *,
    title_hint: str,
    prompt_hint: str,
    asset_paths: list[str],
    copy_assets: bool = True,
    auto_image: bool = True,
) -> Post:
    """
    Generate a draft with LLM and persist post + revision.
    """
    cfg = load_llm_config()
    title_norm = (title_hint or "").strip()
    platform_meta: dict = {}

    if title_norm == "每日新闻":
        try:
            picked, news_meta = fetch_and_pick_daily_news(prompt_hint or "")
            platform_meta["news"] = {
                **news_meta,
                "mode": "daily_news",
                "prompt_hint": (prompt_hint or "").strip(),
            }
            prompt_norm = (prompt_hint or "").strip()
            news_prompt = _daily_news_prompt(picked, prompt_norm)
            seed_title = "每日新闻"
            draft = generate_draft(
                cfg,
                title_hint=seed_title,
                prompt_hint=news_prompt,
                asset_paths=asset_paths,
            )
            if draft.get("_fallback_error"):
                draft["title"] = _shorten_daily_news_title(picked.title)
                draft["body"] = _daily_news_offline_body(picked, prompt_norm)
                draft["topics"] = [t for t in ["每日新闻", prompt_norm] if t]
        except Exception as exc:
            platform_meta["news"] = {
                "mode": "daily_news",
                "prompt_hint": (prompt_hint or "").strip(),
                "error": str(exc),
            }
            draft = generate_draft(
                cfg,
                title_hint=title_hint,
                prompt_hint=f"{prompt_hint}\n(news_fetch_failed: {exc})",
                asset_paths=asset_paths,
            )
    else:
        draft = generate_draft(
            cfg,
            title_hint=title_hint,
            prompt_hint=prompt_hint,
            asset_paths=asset_paths,
        )

    post = Post(
        type="image",
        status=PostStatus.draft,
        title=draft["title"],
        body=draft["body"],
        topics=draft.get("topics", []),
    )
    if platform_meta:
        post.platform = platform_meta

    auto_image_enabled = auto_image and is_auto_image_enabled()
    assets_paths = [Path(p) for p in asset_paths]
    effective_copy_assets = copy_assets

    if not assets_paths and auto_image_enabled:
        dest_dir = post_dir(post.id) / "assets"
        image_path, image_meta = fetch_and_download_related_image(
            title=post.title,
            body=post.body,
            topics=post.topics,
            prompt_hint=prompt_hint,
            dest_dir=dest_dir,
        )
        post.platform.setdefault("image", image_meta)
        assets_paths = [image_path]
        # The downloaded file is already under data/posts/<id>/assets.
        effective_copy_assets = False

    if effective_copy_assets:
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


def create_daily_news_posts(
    *,
    prompt_hint: str = "",
    asset_paths: list[str],
    copy_assets: bool = True,
    count: int = 3,
    auto_image: bool = True,
) -> list[Post]:
    """
    Special workflow for title="每日新闻".

    - If `prompt_hint` is provided: pick the best matching news and create 1 post.
    - If `prompt_hint` is empty: pick up to `count` news and create multiple posts.
    """
    cfg = load_llm_config()
    prompt_norm = (prompt_hint or "").strip()
    auto_image_enabled = auto_image and is_auto_image_enabled()

    try:
        candidates, base_meta = fetch_daily_news_candidates(prompt_norm)
        picks = pick_news_items(candidates, prompt_norm, count=count)
    except Exception as exc:
        # Degrade to normal generation if fetching fails.
        draft = generate_draft(
            cfg,
            title_hint="每日新闻",
            prompt_hint=f"{prompt_norm}\n(news_fetch_failed: {exc})",
            asset_paths=asset_paths,
        )
        post = Post(
            type="image",
            status=PostStatus.draft,
            title=draft["title"],
            body=draft["body"],
            topics=draft.get("topics", []),
            platform={
                "news": {
                    "mode": "daily_news_multi",
                    "prompt_hint": prompt_norm,
                    "error": str(exc),
                }
            },
        )
        assets_paths = [Path(p) for p in asset_paths]
        effective_copy_assets = copy_assets

        if not assets_paths and auto_image_enabled:
            dest_dir = post_dir(post.id) / "assets"
            image_path, image_meta = fetch_and_download_related_image(
                title=post.title,
                body=post.body,
                topics=post.topics,
                prompt_hint=prompt_norm,
                dest_dir=dest_dir,
            )
            post.platform.setdefault("image", image_meta)
            assets_paths = [image_path]
            effective_copy_assets = False

        if effective_copy_assets:
            copied = copy_assets_into_post(post.id, assets_paths)
            post.assets = _build_asset_infos(copied)
        else:
            post.assets = _build_asset_infos(assets_paths)

        rev = Revision(post_id=post.id, source=RevisionSource.llm, content=draft)
        save_post(post)
        save_revision(rev)
        return [post]

    total = len(picks)
    posts: list[Post] = []

    for idx, picked in enumerate(picks, start=1):
        news_prompt = _daily_news_prompt(picked, prompt_norm)
        if total > 1:
            news_prompt = f"（第 {idx}/{total} 条）\n{news_prompt}"

        seed_title = "每日新闻"
        draft = generate_draft(
            cfg,
            title_hint=seed_title,
            prompt_hint=news_prompt,
            asset_paths=asset_paths,
        )
        if draft.get("_fallback_error"):
            draft["title"] = _shorten_daily_news_title(picked.title)
            draft["body"] = _daily_news_offline_body(picked, prompt_norm)
            draft["topics"] = [t for t in ["每日新闻", prompt_norm] if t]

        post = Post(
            type="image",
            status=PostStatus.draft,
            title=draft["title"],
            body=draft["body"],
            topics=draft.get("topics", []),
            platform={
                "news": {
                    **base_meta,
                    "picked": asdict(picked),
                    "mode": "daily_news_multi" if total > 1 else "daily_news",
                    "prompt_hint": prompt_norm,
                    "pick_index": idx,
                    "pick_total": total,
                }
            },
        )

        assets_paths = [Path(p) for p in asset_paths]
        effective_copy_assets = copy_assets

        if not assets_paths and auto_image_enabled:
            dest_dir = post_dir(post.id) / "assets"
            image_path, image_meta = fetch_and_download_related_image(
                title=post.title,
                body=post.body,
                topics=post.topics,
                prompt_hint=prompt_norm,
                dest_dir=dest_dir,
            )
            post.platform.setdefault("image", image_meta)
            assets_paths = [image_path]
            effective_copy_assets = False

        if effective_copy_assets:
            copied = copy_assets_into_post(post.id, assets_paths)
            post.assets = _build_asset_infos(copied)
        else:
            post.assets = _build_asset_infos(assets_paths)

        rev = Revision(post_id=post.id, source=RevisionSource.llm, content=draft)
        save_post(post)
        save_revision(rev)
        posts.append(post)

    return posts
