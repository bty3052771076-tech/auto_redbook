from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Execution, Post, Revision

DATA_ROOT = Path("data")


def ensure_dirs(base: Path = DATA_ROOT) -> None:
    (base / "posts").mkdir(parents=True, exist_ok=True)
    (base / "indexes").mkdir(parents=True, exist_ok=True)
    (base / "events").mkdir(parents=True, exist_ok=True)


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def post_dir(post_id: str, base: Path = DATA_ROOT) -> Path:
    return base / "posts" / post_id


def revision_path(post_id: str, revision_id: str, base: Path = DATA_ROOT) -> Path:
    return post_dir(post_id, base) / "revisions" / f"{revision_id}.json"


def execution_path(post_id: str, execution_id: str, base: Path = DATA_ROOT) -> Path:
    return post_dir(post_id, base) / "executions" / f"{execution_id}.json"


def evidence_dir(post_id: str, execution_id: str, base: Path = DATA_ROOT) -> Path:
    return post_dir(post_id, base) / "evidence" / execution_id


def save_post(post: Post, base: Path = DATA_ROOT) -> Path:
    ensure_dirs(base)
    path = post_dir(post.id, base) / "post.json"
    _write_json_atomic(path, post.model_dump())
    return path


def load_post(post_id: str, base: Path = DATA_ROOT) -> Post:
    path = post_dir(post_id, base) / "post.json"
    data = _read_json(path)
    return Post.model_validate(data)


def list_posts(base: Path = DATA_ROOT) -> Iterable[Post]:
    root = base / "posts"
    if not root.exists():
        return []
    posts: list[Post] = []
    for post_dir_path in root.iterdir():
        post_file = post_dir_path / "post.json"
        if post_file.exists():
            try:
                posts.append(Post.model_validate(_read_json(post_file)))
            except Exception:
                continue
    return posts


def save_revision(revision: Revision, base: Path = DATA_ROOT) -> Path:
    path = revision_path(revision.post_id, revision.id, base)
    _write_json_atomic(path, revision.model_dump())
    return path


def save_execution(execution: Execution, base: Path = DATA_ROOT) -> Path:
    path = execution_path(execution.post_id, execution.id, base)
    _write_json_atomic(path, execution.model_dump())
    return path


def list_executions(post_id: str, base: Path = DATA_ROOT) -> list[Execution]:
    exec_root = post_dir(post_id, base) / "executions"
    if not exec_root.exists():
        return []
    executions: list[Execution] = []
    for exec_file in exec_root.glob("*.json"):
        try:
            executions.append(Execution.model_validate(_read_json(exec_file)))
        except Exception:
            continue
    executions.sort(key=lambda e: (e.attempt, e.started_at))
    return executions


def latest_execution(post_id: str, base: Path = DATA_ROOT) -> Optional[Execution]:
    executions = list_executions(post_id, base=base)
    return executions[-1] if executions else None


def copy_assets_into_post(post_id: str, asset_paths: list[Path], base: Path = DATA_ROOT) -> list[Path]:
    """Copy assets into post directory for isolation (optional)."""
    dest_dir = post_dir(post_id, base) / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for src in asset_paths:
        if not src.exists():
            continue
        target = dest_dir / src.name
        shutil.copy2(src, target)
        copied.append(target)
    return copied
