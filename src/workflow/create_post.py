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


def _clip_text(value: str | None, *, limit: int = 400) -> str:
    text = (value or "").strip()
    if not text:
        return "无"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _preferred_image_title(post: Post, fallback: str) -> str:
    news_meta = (post.platform or {}).get("news") or {}
    picked = news_meta.get("picked")
    if isinstance(picked, dict):
        picked_title = (picked.get("title") or "").strip()
        if picked_title:
            return picked_title
    return fallback


def _preferred_image_hint(post: Post, fallback: str) -> str:
    news_meta = (post.platform or {}).get("news") or {}
    picked = news_meta.get("picked")
    if isinstance(picked, dict):
        picked_title = (picked.get("title") or "").strip()
        if picked_title:
            return picked_title
        picked_desc = (picked.get("description") or "").strip()
        if picked_desc:
            return picked_desc
    return fallback


def _daily_news_prompt(picked, prompt_norm: str) -> str:
    """
    Prompt for LLM to write publishable body ONLY (no metadata/requirements echoed).
    """
    return (
        "你正在为小红书图文笔记写《每日新闻》栏目。\n"
        "请依据下面提供的新闻信息写一篇可直接发布的正文（通俗中文）。\n"
        "注意：正文里不要包含“来源/时间/链接/提示词/要求”等元信息，也不要复述下面的提示文本。\n"
        "只允许使用下列已提供的新闻信息，不得新增事实或编造细节；信息不足时保持保守表述。\n\n"
        "可用新闻信息（仅限以下字段，链接仅供参考不要输出）：\n"
        f"- 标题：{picked.title}\n"
        f"- 来源名称：{picked.source or '未知'}\n"
        f"- 来源域名：{picked.domain or '未知'}\n"
        f"- 发布时间：{picked.seendate or '未知'}\n"
        f"- 摘要：{_clip_text(picked.description, limit=300)}\n"
        f"- 正文片段：{_clip_text(picked.content, limit=500)}\n"
        f"- 链接：{picked.url}\n"
        f"- 用户关注点（可选）：{prompt_norm or '无'}\n\n"
        "输出格式（必须逐行保留标题，不得更名或省略）：\n"
        "新闻内容：\n"
        "<不少于200字的完整段落>\n\n"
        "我的点评：\n"
        "<不少于100字的完整段落，末尾附带1个互动问题>\n\n"
        "硬性要求：\n"
        "1) 必须包含且仅包含以上两个段落，段落之间空一行。\n"
        "2) 不得输出列表或额外小标题，不得合并成一段。\n"
        "3) 新闻内容（>=200字）：基于上面的信息，说明发生了什么、为何值得关注。\n"
        "4) 我的点评（>=100字）：给出影响解读/建议/风险提示，可结合用户关注点，但不得新增事实。\n"
        "5) topics 输出 3-8 个话题词，包含“每日新闻”。\n"
    )


def _daily_news_offline_body(picked, prompt_norm: str) -> str:
    """
    Offline fallback body: keep it publishable and avoid echoing prompt/requirements.
    """
    focus = prompt_norm.strip()
    focus_line = f"从「{focus}」角度" if focus else "从读者关注点"
    return (
        "新闻内容：\n"
        f"{picked.title}。这条新闻反映出当前议题的最新进展，仍需关注后续权威信息披露。\n\n"
        "我的点评：\n"
        f"{focus_line}来看，它可能带来连锁影响，值得持续观察与跟进。"
        "你认为接下来会如何发展？"
    )


def _ensure_daily_news_sections(body: str, prompt_norm: str) -> str:
    text = (body or "").strip()
    if not text:
        return text
    if "新闻内容：" in text and "我的点评：" in text:
        return text

    cleaned = text.replace("新闻内容：", "").replace("我的点评：", "").strip()
    paragraphs = [p.strip() for p in cleaned.splitlines() if p.strip()]
    if len(paragraphs) >= 2:
        news = paragraphs[0]
        comment = " ".join(paragraphs[1:])
    else:
        news = paragraphs[0] if paragraphs else cleaned
        focus_line = f"从「{prompt_norm}」角度" if prompt_norm else "从读者关注点"
        comment = f"{focus_line}来看，这条新闻提示我们需要持续关注后续进展与影响。你怎么看？"

    return f"新闻内容：\n{news}\n\n我的点评：\n{comment}"


def _fake_news_prompt(prompt_norm: str) -> str:
    """
    Prompt for humorous, clearly fictional fake news.
    """
    topic = prompt_norm or "日常离谱小事"
    return (
        "你正在为小红书图文笔记写《每日假新闻》栏目。\n"
        "请根据给定主题编写一条**明显虚构、幽默夸张**的新闻，语气轻松有趣。\n"
        "必须让读者一眼看出是娱乐内容，避免与现实新闻混淆。\n"
        "不要引用真实媒体/来源/链接，不要提供可核验的具体事实或真实数据。\n"
        "避免对真实人物/机构做恶意指控或诽谤，内容保持善意搞笑。\n"
        "正文只输出可直接发布的文章，不要复述提示词或规则。\n\n"
        f"主题提示（可自由发挥但要贴合）：{topic}\n\n"
        "正文要求：\n"
        "1) 只输出一段完整正文，不要列点或小标题；\n"
        "2) 字数约 200-400 字；\n"
        "3) 末尾必须加一句：本文纯属虚构，仅供娱乐。\n"
        "4) topics 输出 3-8 个话题词，包含“每日假新闻”。\n"
    )


def _fake_news_offline_body(prompt_norm: str) -> str:
    topic = prompt_norm or "离谱日常"
    return (
        f"【假新闻播报】今日最离谱的主角是「{topic}」。\n"
        "据不可靠但十分认真（的想象）消息称，相关事件在短短几小时内引发了全民围观，"
        "围观群众纷纷表示：这是我今天最开心的笑点。更夸张的是，现场还出现了神秘“反转”，"
        "让事情从“不可思议”直接升级为“笑到肚子疼”。\n\n"
        "专家（其实是路过的瓜友）点评：这类剧情虽然离谱，但快乐是真的。"
        "如果明天还能看到同款离谱升级，请记得第一时间来围观。\n"
        "本文纯属虚构，仅供娱乐。"
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
            draft["body"] = _ensure_daily_news_sections(
                draft.get("body", ""), prompt_norm
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
    elif title_norm == "每日假新闻":
        prompt_norm = (prompt_hint or "").strip()
        fake_prompt = _fake_news_prompt(prompt_norm)
        draft = generate_draft(
            cfg,
            title_hint="每日假新闻",
            prompt_hint=fake_prompt,
            asset_paths=asset_paths,
        )
        if draft.get("_fallback_error"):
            draft["title"] = "每日假新闻"
            draft["body"] = _fake_news_offline_body(prompt_norm)
        body_text = (draft.get("body") or "").strip()
        if "本文纯属虚构" not in body_text:
            joiner = "\n" if body_text else ""
            draft["body"] = f"{body_text}{joiner}本文纯属虚构，仅供娱乐。"
        topics = draft.get("topics", [])
        if "每日假新闻" not in topics:
            topics = ["每日假新闻"] + [t for t in topics if t and t != "每日假新闻"]
        draft["topics"] = topics
        platform_meta["fake_news"] = {
            "mode": "daily_fake_news",
            "prompt_hint": prompt_norm,
            "is_fiction": True,
            "tone": "humor",
        }
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
        image_title = _preferred_image_title(post, post.title)
        image_path, image_meta = fetch_and_download_related_image(
            title=image_title,
            body=post.body,
            topics=post.topics,
            prompt_hint=_preferred_image_hint(post, prompt_hint),
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
    count: int = 1,
    auto_image: bool = True,
) -> list[Post]:
    """
    Special workflow for title="每日新闻".

    - Use `prompt_hint` to rank candidates, then pick up to `count` items.
    - When `count` is 1, behavior is equivalent to a single best match.
    """
    cfg = load_llm_config()
    prompt_norm = (prompt_hint or "").strip()
    if count <= 0:
        count = 1
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
            image_title = draft.get("title") or post.title or "每日新闻"
            image_path, image_meta = fetch_and_download_related_image(
                title=image_title,
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
        draft["body"] = _ensure_daily_news_sections(draft.get("body", ""), prompt_norm)
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
            image_title = _preferred_image_title(post, post.title)
            image_prompt = _preferred_image_hint(post, prompt_norm)
            image_path, image_meta = fetch_and_download_related_image(
                title=image_title,
                body=post.body,
                topics=post.topics,
                prompt_hint=image_prompt,
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
