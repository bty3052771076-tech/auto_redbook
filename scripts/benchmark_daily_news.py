"""Time one real ten-post run without exposing local credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

from dotenv import dotenv_values


def main():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update({k: v for k, v in dotenv_values(root / ".env.gui", encoding="utf-8-sig").items() if v is not None})
    env.update({
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
        "LLM_PROVIDER": "minimax", "IMAGE_PROVIDER": "minimax", "IMAGE_SOURCE": "minimax",
        "AUTO_IMAGE": "1", "ALLOW_PAID_LLM_FALLBACK": "0",
        "MINIMAX_BILLING_MODE": "subscription_only", "MINIMAX_ALLOW_PAID_CREDITS": "0",
        "MINIMAX_ALLOW_PAYGO": "0", "MINIMAX_USE_SUBSCRIPTION": "1",
        "WORKFLOW_PERFORMANCE_MODE": "speed",
        "XHS_CHROME_USER_DATA_DIR": str(root / "data/browser/chrome-profile"),
        "XHS_CHROME_PROFILE": "Default",
    })
    secrets = [v for k, v in env.items() if len(v) >= 8 and any(s in k.upper() for s in ("KEY", "TOKEN", "PASSWORD", "SECRET"))]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logdir = root / "data/logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logpath = logdir / f"news_benchmark_{stamp}.log"
    resultpath = logpath.with_suffix(".json")
    args = [sys.executable, "-u", "-m", "apps.cli", "auto",
            "--title", "\u6bcf\u65e5\u65b0\u95fb",
            "--prompt", "\u56fd\u9645\u51b2\u7a81 \u4e89\u8bae\u4e8b\u4ef6 \u5168\u7403\u70ed\u70b9 \u8d22\u7ecf\u4ea7\u4e1a \u516c\u53f8\u653f\u7b56 \u5e02\u573a\u53d8\u5316 \u79d1\u6280\u4ea7\u4e1a \u82af\u7247 AI \u793e\u4f1a\u6c11\u751f \u4f53\u80b2\u6587\u5316 \u54c1\u724c\u5e73\u53f0 \u4e2d\u56fd\u56fd\u5185",
            "--evaluation-viewpoint", "\u65e0\u89c6\u89d2\u8bc4\u4ef7",
            "--assets-glob", "assets/empty/*", "--count", "10", "--platform", "xhs",
            "--lookback-days", "auto", "--headless", "--login-hold", "0", "--wait-timeout", "600",
            "--no-preflight", "--no-refresh-quotas", "--performance-mode", "speed"]
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    events = []
    print(f"benchmark log={logpath}", flush=True)
    with logpath.open("w", encoding="utf-8") as log:
        with subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as child:
            for line in child.stdout:
                for secret in secrets:
                    line = line.replace(secret, "[REDACTED]")
                elapsed = round(time.perf_counter() - started, 3)
                message = line.rstrip()
                events.append({"elapsed_seconds": elapsed, "message": message})
                output = f"[{elapsed:9.3f}s] {message}"
                print(output, flush=True)
                log.write(output + "\n")
                log.flush()
            code = child.wait()
    elapsed = round(time.perf_counter() - started, 3)
    resultpath.write_text(json.dumps({"started_at": started_at, "wall_seconds": elapsed,
        "exit_code": code, "requested_count": 10, "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"benchmark wall_seconds={elapsed} exit={code} result={resultpath}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
