from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E: apps.cli auto with auto-image provider (e.g. aliyun/pexels)"
    )
    parser.add_argument(
        "--cdp",
        default="",
        help="Optional: attach XHS automation to an existing Chrome via CDP, e.g. http://127.0.0.1:9222",
    )
    parser.add_argument("--title", default="每日新闻")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument(
        "--assets-glob",
        default="empty/pics/*",
        help="Use an empty glob to force auto-image",
    )
    parser.add_argument("--wait-timeout", type=int, default=600)
    parser.add_argument(
        "--image-provider",
        default=os.getenv("IMAGE_PROVIDER") or "aliyun",
        help="auto-image provider, e.g. aliyun or pexels",
    )
    parser.add_argument("--aliyun-timeout", type=int, default=180)
    parser.add_argument("--aliyun-download-timeout", type=int, default=60)
    args = parser.parse_args()

    env = os.environ.copy()
    env["IMAGE_PROVIDER"] = (args.image_provider or "").strip()
    if args.cdp.strip():
        env["XHS_CDP_URL"] = args.cdp.strip()
    env["ALIYUN_IMAGE_TIMEOUT_S"] = str(args.aliyun_timeout)
    env["ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S"] = str(args.aliyun_download_timeout)

    cmd = [
        sys.executable,
        "-m",
        "apps.cli",
        "auto",
        "--title",
        args.title,
        "--count",
        str(args.count),
        "--assets-glob",
        args.assets_glob,
        "--login-hold",
        "0",
        "--wait-timeout",
        str(args.wait_timeout),
    ]
    if args.prompt.strip():
        cmd.extend(["--prompt", args.prompt])

    print("RUN:", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    print(proc.stdout, end="")
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)

    out = proc.stdout + "\n" + proc.stderr
    ids = re.findall(r"post_id=([0-9a-f]{32})", out)
    if not ids:
        print("FAIL: cannot find post_id in output", file=sys.stderr)
        return 2

    seen: set[str] = set()
    post_ids: list[str] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        post_ids.append(pid)

    if len(post_ids) < args.count:
        print(
            f"FAIL: expected >= {args.count} posts, got {len(post_ids)}: {post_ids}",
            file=sys.stderr,
        )
        return 3

    ok = True
    for post_id in post_ids[: args.count]:
        post_path = Path("data") / "posts" / post_id / "post.json"
        if not post_path.exists():
            print(f"FAIL: post.json not found: {post_path}", file=sys.stderr)
            ok = False
            continue

        obj = json.loads(post_path.read_text(encoding="utf-8"))
        status = obj.get("status")
        image_meta = (obj.get("platform") or {}).get("image") or {}
        method = image_meta.get("method")
        evidence_dir = image_meta.get("evidence_dir")

        assets = obj.get("assets") or []
        asset_paths = [
            a.get("path")
            for a in assets
            if isinstance(a, dict) and a.get("path") and a.get("kind") == "image"
        ]
        missing = [p for p in asset_paths if p and not Path(p).exists()]

        print(f"post_id={post_id}")
        print(f"status={status}")
        print(f"platform.image.method={method}")
        print(f"platform.image.src_url={image_meta.get('src_url')}")
        print(f"platform.image.evidence_dir={evidence_dir}")
        print("assets:", asset_paths)
        for p in asset_paths:
            try:
                if p and Path(p).exists():
                    print(f"- {p} size={Path(p).stat().st_size}")
            except Exception:
                pass

        if missing:
            print(f"FAIL: missing asset files: {missing}", file=sys.stderr)
            ok = False

        if method in ("screenshot", "screenshot_fallback"):
            print(
                "FAIL: image captured by screenshot (risk of blurred/in-progress).",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 5

    if proc.returncode != 0:
        print(
            f"WARN: auto returned non-zero ({proc.returncode}), but image meta was recorded.",
            file=sys.stderr,
        )
        return proc.returncode

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
