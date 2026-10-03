"""Run one draft-only Web agent conversation and record its job IDs/timing."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


EXPECTED_KINDS = {
    "daily_news",
    "daily_ai_digest",
    "daily_wool",
    "daily_wow",
    "daily_global_map",
}
FINISHED = {"completed", "partial_success", "failed", "cancelled", "interrupted"}


def call(base: str, path: str, *, token: str = "", payload: dict | None = None, key: str = "") -> dict:
    headers = {"Content-Type": "application/json", "X-Workbench": "1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"{path}: HTTP {exc.code}: {detail}") from exc


def wait_job(base: str, token: str, job_id: str, *, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last_event_id = 0
    last_status = ""
    while time.monotonic() < deadline:
        job = call(base, f"/api/jobs/{job_id}", token=token)
        if job.get("status") != last_status:
            last_status = str(job.get("status") or "")
            print(f"job={job_id} status={last_status}", flush=True)
        for event in job.get("events") or []:
            event_id = int(event.get("id") or 0)
            if event_id <= last_event_id:
                continue
            last_event_id = event_id
            message = str(event.get("message") or "").replace("\n", " ")[:220]
            print(f"event={event_id} {message}", flush=True)
        if last_status in FINISHED:
            return job
        time.sleep(5)
    raise TimeoutError(f"job {job_id} exceeded the test harness timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--max-minutes", type=float, default=45)
    parser.add_argument("--baseline-max-items", type=int, default=5)
    parser.add_argument("--skill", default="ai-tech-hot")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    report_dir = Path("data/runs/agent_draft_only_test") / time.strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"started_at": time.time(), "message": args.message, "baseline": {}, "agent": {}}

    session = call(base, "/api/session", payload={})
    token = str(session["token"])
    capabilities = call(base, "/api/agent/capabilities", token=token)
    report["capabilities"] = {
        "database_status": capabilities.get("database", {}).get("status"),
        "mcp_status": capabilities.get("mcp", {}).get("status"),
        "skills_status": capabilities.get("skills", {}).get("status"),
    }
    if report["capabilities"]["database_status"] != "ready":
        raise RuntimeError("PostgreSQL knowledge base is not ready")

    if args.baseline_max_items:
        baseline = call(
            base,
            "/api/jobs",
            token=token,
            payload={
                "kind": "manage-drafts",
                "title": "Draft-only test: read existing drafts",
                "mode": "review",
                "draft_type": "image",
                "max_items": args.baseline_max_items,
            },
            key=uuid4().hex,
        )
        baseline_job = wait_job(base, token, baseline["id"], timeout_s=600)
        report["baseline"] = {
            "job_id": baseline["id"],
            "status": baseline_job.get("status"),
            "elapsed_s": round((baseline_job.get("ended_at") or time.time()) - (baseline_job.get("started_at") or time.time()), 2),
            "exit_code": baseline_job.get("exit_code"),
        }
        if baseline_job.get("exit_code") != 0:
            report["ended_at"] = time.time()
            (report_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError("Read-only platform draft baseline failed; the agent was not started")

    conversation = call(base, "/api/agent/conversations", token=token, payload={"title": "Draft-only full-chain test"})
    conversation_id = str(conversation["id"])
    parsed = call(
        base,
        f"/api/agent/conversations/{conversation_id}/messages",
        token=token,
        payload={"content": args.message},
    )
    plan = parsed["plan"]
    actual_kinds = {str(job.get("kind") or "") for job in plan.get("jobs") or []}
    if (
        plan.get("delivery") != "save_draft"
        or plan.get("platform") != "xhs"
        or actual_kinds != EXPECTED_KINDS
        or len(plan.get("jobs") or []) != len(EXPECTED_KINDS)
        or any(int(job.get("count") or 0) != 1 for job in plan["jobs"])
    ):
        raise RuntimeError("The parsed plan is not the expected five-job XHS draft-only plan")
    roles = plan.get("model_roles") or {}
    if any(not str(roles.get(role) or "").startswith("minimax:") for role in ("agent", "writer", "image")):
        raise RuntimeError("Agent, writer and image roles are not all MiniMax")
    report["agent"].update({"conversation_id": conversation_id, "plan_id": plan["id"], "jobs": sorted(actual_kinds)})
    print(f"plan={plan['id']} delivery=save_draft jobs={len(actual_kinds)}", flush=True)

    selected_skill = args.skill.strip()
    skills = capabilities.get("skills", {}).get("items") or []
    available = {str(item.get("name") or "") for item in skills if isinstance(item, dict)}
    if selected_skill and selected_skill not in available:
        raise RuntimeError(f"Requested Skill is not imported: {selected_skill}")
    execute = call(
        base,
        f"/api/agent/plans/{plan['id']}/execute",
        token=token,
        payload={
            "conversation_id": conversation_id,
            "version": plan["version"],
            "skill_mode": "manual" if selected_skill else "off",
            "skill_names": [selected_skill] if selected_skill else [],
        },
        key=uuid4().hex,
    )
    job_id = str(execute["id"])
    report["agent"]["run_id"] = job_id
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    job = wait_job(base, token, job_id, timeout_s=args.max_minutes * 60)
    report["agent"].update({
        "status": job.get("status"),
        "exit_code": job.get("exit_code"),
        "elapsed_s": round((job.get("ended_at") or time.time()) - (job.get("started_at") or time.time()), 2),
        "post_ids": job.get("post_ids") or [],
        "event_count": len(job.get("events") or []),
    })
    report["ended_at"] = time.time()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={report_path} agent_status={job.get('status')} exit={job.get('exit_code')}", flush=True)
    return 0 if job.get("exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
