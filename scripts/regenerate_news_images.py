"""Regenerate AI cover + secondary image for each daily news post and update
the post.json assets manifest in place. Uses SiliconFlow's free
Kwai-Kolors/Kolors model by default (override with SILICONFLOW_IMAGE_MODEL).
Does not upload anything; run ``apps.cli retry <post_id> --force`` afterwards.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.images.siliconflow_images import generate_siliconflow_image  # noqa: E402

DATA_DIR = ROOT / "data" / "posts"


def _load_post(post_dir: Path) -> dict:
    return json.loads((post_dir / "post.json").read_text(encoding="utf-8"))


def _is_daily_news(post: dict) -> bool:
    title = post.get("title") or ""
    if "每日AI" in title:
        return False
    platform = post.get("platform") or {}
    if "ai_digest" in platform:
        return False
    body = post.get("body") or ""
    if "每日AI讯息" in body:
        return False
    return True


def _safe_title(title: str) -> str:
    bad_pairs = [
        ("火箭", "航天器"),
        ("导弹", "飞行器"),
        ("核", "工业"),
        ("袭击", "事件"),
        ("爆炸", "工业事故"),
        ("冲突", "事件"),
        ("战争", "局势"),
        ("抗议", "集会"),
        ("枪击", "事件"),
        ("炸弹", "装置"),
    ]
    out = title
    for bad, good in bad_pairs:
        out = out.replace(bad, good)
    return out


def _prompt_for(post: dict) -> tuple[str, str]:
    title = _safe_title((post.get("title") or "").strip())
    body = (post.get("body") or "").strip()
    summary = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            summary = stripped
            break
    if not summary:
        summary = title
    base = (
        "中文小红书新闻封面海报；3:4 竖版构图；高清写实摄影风格；"
        "画面聚焦主题；不使用任何文字、字母或水印；主体居中。"
    )
    cover_prompt = f"{base}主题：{title}。视觉重点：{summary[:80]}。"
    body_prompt = (
        "中文小红书新闻配图；3:4 竖版；柔和浅色背景；"
        "新闻事件相关的人物剪影或场景道具；不出现任何文字或水印。"
        f"主题：{title}。"
    )
    return cover_prompt, body_prompt


def regenerate(post_id: str) -> bool:
    post_dir = DATA_DIR / post_id
    post = _load_post(post_dir)
    if not _is_daily_news(post):
        print(f"[skip] {post_id}: not a daily news post")
        return False
    assets_dir = post_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    cover_prompt, body_prompt = _prompt_for(post)
    model = os.getenv("SILICONFLOW_IMAGE_MODEL", "Kwai-Kolors/Kolors")
    size = os.getenv("SILICONFLOW_IMAGE_SIZE", "1140x1472")
    try:
        cover = generate_siliconflow_image(
            post_id=post_id,
            prompt=cover_prompt,
            dest_dir=assets_dir,
            model=model,
            size=size,
        )
        body = generate_siliconflow_image(
            post_id=post_id,
            prompt=body_prompt,
            dest_dir=assets_dir,
            model=model,
            size=size,
        )
    except Exception as exc:
        print(f"[fail] {post_id}: {exc}")
        return False
    cover_path = Path(cover.path).relative_to(ROOT)
    body_path = Path(body.path).relative_to(ROOT)
    post["assets"] = [
        {
            "path": str(cover_path).replace("\\", "/"),
            "kind": "image",
            "size_bytes": cover.path.stat().st_size,
            "validated": True,
        },
        {
            "path": str(body_path).replace("\\", "/"),
            "kind": "image",
            "size_bytes": body.path.stat().st_size,
            "validated": True,
        },
    ]
    post["settings"] = post.get("settings") or {}
    post["settings"]["image_provider"] = "siliconflow"
    post["settings"]["image_model"] = model
    (post_dir / "post.json").write_text(
        json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[ok] {post_id}: cover={cover_path.name} body={body_path.name}")
    return True


def main() -> int:
    targets = sys.argv[1:]
    if not targets:
        targets = [
            d.name
            for d in sorted(DATA_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
            if d.is_dir() and (d / "post.json").exists()
        ]
    ok = 0
    for pid in targets:
        if regenerate(pid):
            ok += 1
    print(f"regenerated {ok}/{len(targets)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
