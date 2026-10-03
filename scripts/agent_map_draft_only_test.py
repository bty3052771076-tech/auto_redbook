"""Run a single map-only Web agent plan without publishing."""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from agent_draft_only_e2e import call, wait_job


def main() -> int:
    base = "http://127.0.0.1:8765"
    root = Path("data/runs/agent_draft_only_test") / time.strftime("%Y%m%d-%H%M%S-map")
    root.mkdir(parents=True, exist_ok=True)
    token = str(call(base, "/api/session", payload={})["token"])
    conversation = call(base, "/api/agent/conversations", token=token, payload={"title": "Map draft-only test"})
    parsed = call(
        base,
        f"/api/agent/conversations/{conversation['id']}/messages",
        token=token,
        payload={"content": "生成一条今日全球事件关注图，保存到小红书草稿箱。"},
    )
    plan = parsed["plan"]
    jobs = plan.get("jobs") or []
    if plan.get("delivery") != "save_draft" or plan.get("platform") != "xhs" or len(jobs) != 1 or jobs[0].get("kind") != "daily_global_map":
        raise RuntimeError(f"Unexpected plan: delivery={plan.get('delivery')}, jobs={[j.get('kind') for j in jobs]}")
    print(f"map_plan={plan['id']} jobs=1 delivery=save_draft", flush=True)
    run = call(
        base,
        f"/api/agent/plans/{plan['id']}/execute",
        token=token,
        payload={"conversation_id": conversation["id"], "version": plan["version"], "skill_mode": "off", "skill_names": []},
        key=uuid4().hex,
    )
    job = wait_job(base, token, str(run["id"]), timeout_s=15 * 60)
    report = {
        "run_id": run["id"],
        "status": job.get("status"),
        "exit_code": job.get("exit_code"),
        "elapsed_s": round(float(job.get("ended_at") or time.time()) - float(job.get("started_at") or time.time()), 2),
        "post_ids": job.get("post_ids") or [],
    }
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["exit_code"] == 0 and report["post_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
