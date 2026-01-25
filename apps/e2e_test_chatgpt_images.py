from __future__ import annotations

import argparse
import base64
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from src.images.chatgpt_images import generate_chatgpt_image


def _looks_like_html(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or head.startswith(b"<script")


def _jpeg_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    # Minimal JPEG SOF parser
    i = 2
    n = len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1

        # Standalone markers
        if marker in (0xD8, 0xD9):
            continue

        if i + 2 > n:
            break
        seg_len = int.from_bytes(data[i : i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            break

        # SOF markers that contain size
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            if i + 7 <= n:
                h = int.from_bytes(data[i + 3 : i + 5], "big")
                w = int.from_bytes(data[i + 5 : i + 7], "big")
                return w, h

        i += seg_len

    return None, None


def _webp_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    # Only handles VP8X (most common for modern webp)
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None, None
    off = 12
    n = len(data)
    while off + 8 <= n:
        tag = data[off : off + 4]
        size = int.from_bytes(data[off + 4 : off + 8], "little")
        start = off + 8
        end = start + size
        if end > n:
            break

        if tag == b"VP8X" and size >= 10:
            w = 1 + int.from_bytes(data[start + 4 : start + 7], "little")
            h = 1 + int.from_bytes(data[start + 7 : start + 10], "little")
            return w, h

        # chunks are padded to even sizes
        off = end + (size % 2)

    return None, None


def sniff_image(path: Path) -> tuple[str, Optional[int], Optional[int]]:
    data = path.read_bytes()
    if _looks_like_html(data):
        return "html", None, None

    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        w = int.from_bytes(data[16:20], "big")
        h = int.from_bytes(data[20:24], "big")
        return "png", w, h

    if data.startswith(b"\xff\xd8"):
        w, h = _jpeg_size(data)
        return "jpg", w, h

    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        w, h = _webp_size(data)
        return "webp", w, h

    return "unknown", None, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E: ChatGPT Images generate + download (via CDP)"
    )
    parser.add_argument(
        "--cdp",
        default="http://127.0.0.1:9222",
        help="CDP URL, e.g. http://127.0.0.1:9222",
    )
    parser.add_argument("--prompt", required=True, help="Prompt text for ChatGPT Images")
    parser.add_argument(
        "--timeout",
        type=float,
        default=240.0,
        help="Overall generation wait timeout (seconds)",
    )
    parser.add_argument(
        "--download-timeout",
        type=float,
        default=180.0,
        help="Wait timeout for downloading the real bytes",
    )
    parser.add_argument(
        "--post-id",
        default=uuid.uuid4().hex,
        help="32-hex id used for evidence folder naming",
    )
    parser.add_argument(
        "--dest-dir",
        default="",
        help="Destination dir for saved image; default data/posts/<post_id>/assets",
    )
    args = parser.parse_args()

    os.environ["CHATGPT_CDP_URL"] = args.cdp
    os.environ["CHATGPT_DOWNLOAD_TIMEOUT_S"] = str(args.download_timeout)

    dest_dir = (
        Path(args.dest_dir)
        if args.dest_dir
        else (Path("data") / "posts" / args.post_id / "assets")
    )
    dest_dir.mkdir(parents=True, exist_ok=True)

    res = generate_chatgpt_image(
        post_id=args.post_id,
        prompt=args.prompt,
        dest_dir=dest_dir,
        timeout_s=args.timeout,
    )

    kind, w, h = sniff_image(res.path)
    size = res.path.stat().st_size

    print(f"saved_path={res.path}")
    print(f"size_bytes={size}")
    print(f"kind={kind} width={w} height={h}")
    print(f"method={res.meta.get('method')}")
    print(f"src_url={res.meta.get('src_url')}")
    print(f"evidence_dir={res.meta.get('evidence_dir')}")

    if kind == "html":
        print(
            "FAIL: downloaded content looks like HTML (likely blocked/redirected).",
            file=sys.stderr,
        )
        return 2

    if res.meta.get("method") in ("screenshot", "screenshot_fallback"):
        print(
            "FAIL: still used screenshot; this may capture blurred/in-progress preview.",
            file=sys.stderr,
        )
        return 3

    if size < 30_000:
        print("WARN: image seems unusually small; may still be placeholder.", file=sys.stderr)

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

