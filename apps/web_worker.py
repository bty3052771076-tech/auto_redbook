"""Browser-only jobs launched in an isolated process by the local workbench."""
import argparse
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from apps import gui
from src.storage.files import _write_json_atomic, list_posts
from src.publish.draft_inventory import local_record_from_post, match_draft_inventory, platform_records_from_items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["scan-drafts", "login", "open-xhs", "open-toutiao"])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.action in {"login", "open-xhs", "open-toutiao"}:
        url = gui.DEFAULT_LOGIN_URL if args.action == "open-xhs" else None
        command = gui.build_xhs_creator_launch_args(project_root=args.root, env=os.environ, url=url or gui.DEFAULT_LOGIN_URL) if url else gui.build_xhs_login_launch_args(project_root=args.root, env=os.environ)
        if args.action == "open-toutiao":
            command = gui.build_toutiao_creator_launch_args(project_root=args.root, env=os.environ)
        if not command:
            raise RuntimeError("未找到 Chrome，请在 .env.gui 配置 XHS_CHROME_PATH；不会打开默认浏览器")
        if args.action in {"open-xhs", "open-toutiao"}:
            flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
            subprocess.Popen(command, cwd=args.root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, creationflags=flags)
            platform = "头条号" if args.action == "open-toutiao" else "小红书"
            print(f"[web] stage=打开{platform}创作者中心 | success | 已使用项目专用 profile", flush=True)
        else:
            print("[web] stage=专用浏览器登录 | in_progress | 请登录后关闭浏览器，再刷新平台草稿验证", flush=True)
            subprocess.run(command, cwd=args.root, check=True)
        return
    print("[web] stage=读取平台未发布草稿 | in_progress", flush=True)
    scan = gui.run_collect_platform_drafts_sync(headless=True, login_hold=0, wait_timeout_ms=300000)
    if scan.get("errors"):
        raise RuntimeError("平台草稿读取失败：" + "; ".join(map(str, scan["errors"])))
    inventory = match_draft_inventory(
        [local_record_from_post(p) for p in list_posts(args.root / "data") if p.status.value not in {"published", "publishing"}],
        platform_records_from_items(scan.get("items", [])),
    )
    by_index = {m.platform.index: m.local.post_id for m in inventory.matched}
    rows = [{**asdict(p), "post_id": by_index.get(p.index)} for p in platform_records_from_items(scan.get("items", []))]
    import time
    _write_json_atomic(args.root / "data/web_gui/remote.json", {"rows": rows, "captured_at": time.time(), "complete": scan.get("complete"), "errors": []})
    print(f"[web] stage=读取平台未发布草稿 | success | 共 {len(rows)} 条；已关联 {len(by_index)} 条", flush=True)


if __name__ == "__main__":
    main()
