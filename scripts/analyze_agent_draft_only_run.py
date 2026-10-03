"""Summarize draft-only agent timing from durable Web and agent event files."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


KINDS = {"daily_news", "daily_ai_digest", "daily_wool", "daily_wow", "daily_global_map"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    job = load_json(root / "data/web_gui/jobs" / f"{args.run_id}.json")
    agent_dir = root / "data/runs/agent" / args.run_id
    events = [json.loads(line) for line in (agent_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    checkpoint = load_json(agent_dir / "checkpoint.json")
    started = float(job.get("started_at") or 0)
    ended = float(job.get("ended_at") or 0)
    first_agent = min((float(item["at"]) for item in events), default=0)
    last_agent = max((float(item["at"]) for item in events), default=0)
    starts: list[tuple[str, float]] = []
    for event in events:
        if event.get("node") == "sync_context" and event.get("status") == "success":
            kind = str(event.get("detail") or "")
            if kind in KINDS and (not starts or starts[-1][0] != kind):
                starts.append((kind, float(event["at"])))
    finish_at = next((float(e["at"]) for e in reversed(events) if e.get("node") == "finish"), last_agent)
    job_runs = []
    for index, (kind, start) in enumerate(starts):
        stop = starts[index + 1][1] if index + 1 < len(starts) else finish_at
        relevant = [e for e in events if start <= float(e["at"]) <= stop]
        stage_marks = defaultdict(list)
        for event in relevant:
            if event.get("node") in {"generate", "review", "upload", "upload_batch", "recover"}:
                stage_marks[str(event["node"])].append(event)
        generate_end = next((float(e["at"]) for e in stage_marks["generate"]), 0)
        review_end = next((float(e["at"]) for e in stage_marks["review"]), 0)
        last_upload = max((float(e["at"]) for e in stage_marks["upload"]), default=0)
        job_runs.append({
            "kind": kind,
            "elapsed_s": round(stop - start, 2),
            "to_first_generation_s": round(generate_end - start, 2) if generate_end else None,
            "first_review_s": round(review_end - generate_end, 2) if generate_end and review_end else None,
            "upload_from_first_review_s": round(last_upload - review_end, 2) if last_upload and review_end else None,
            "generate_events": len(stage_marks["generate"]),
            "review_events": len(stage_marks["review"]),
            "upload_events": len(stage_marks["upload"]),
            "recovery_events": len(stage_marks["recover"]),
        })
    summary = {
        "run_id": args.run_id,
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat() if started else None,
        "web_status": job.get("status"),
        "agent_status": checkpoint.get("status"),
        "wall_s": round(ended - started, 2) if ended and started else None,
        "pre_agent_s": round(first_agent - started, 2) if first_agent and started else None,
        "agent_s": round(last_agent - first_agent, 2) if first_agent else None,
        "requested_jobs": len(checkpoint.get("jobs") or []),
        "completed_jobs": int(checkpoint.get("job_index") or 0),
        "uploaded_post_ids": checkpoint.get("uploaded_post_ids") or [],
        "failed_jobs": checkpoint.get("failed_jobs") or [],
        "recovery_attempts": checkpoint.get("recovery_attempts") or {},
        "events": len(events),
        "jobs": job_runs,
    }
    out = agent_dir / "draft_only_timing.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
