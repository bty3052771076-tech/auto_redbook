from __future__ import annotations

from pathlib import Path
import json
import time

from src.agent.editorial_agent import (
    AgentJob,
    EditorialAgentConfig,
    EditorialAgentTools,
    load_agent_checkpoint,
    run_editorial_agent,
)


class FakePost:
    def __init__(self, post_id: str):
        self.id = post_id


def test_agent_accepts_global_map_job_kind():
    job = AgentJob("daily_global_map", "今日全球事件关注图").normalized()

    assert job.kind == "daily_global_map"
    assert job.count == 1


def test_agent_runs_jobs_and_uploads_serially(tmp_path: Path):
    uploaded: list[str] = []
    events: list[tuple[str, str, str]] = []

    def sync_context(job):
        return {"job": job.kind}

    def generate(job, context):
        return [FakePost(f"{job.kind}-1")]

    def review(job, posts, context):
        return []

    def upload(job, post, context):
        uploaded.append(post.id)
        return True, "saved"

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻", count=1), AgentJob("daily_ai_digest", "每日AI讯息")],
        tools=EditorialAgentTools(sync_context, generate, review, upload),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        progress=lambda node, status, detail: events.append((node, status, detail)),
        run_id="test-run",
    )

    assert result.status == "completed"
    assert result.completed_jobs == 2
    assert uploaded == ["daily_news-1", "daily_ai_digest-1"]
    assert [event[0] for event in events].count("upload") == 2
    checkpoint = load_agent_checkpoint(tmp_path / "test-run" / "checkpoint.json")
    assert checkpoint["status"] == "completed"
    assert checkpoint["uploaded_post_ids"] == uploaded
    assert checkpoint["next_event_id"] == len(checkpoint["events"])
    assert (tmp_path / "test-run" / "events.jsonl").is_file()
    assert (tmp_path / "test-run" / "tmp").is_dir()


def test_compressed_conversation_context_reaches_job_tools(tmp_path: Path):
    seen: list[dict] = []
    memory = {
        "snapshot_version": 2,
        "through_seq": 12,
        "summary": "用户偏好官方来源与清晰标题",
        "constraints": ["不得把历史新闻当作本轮事实"],
        "skills": [],
    }
    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻", count=1)],
        tools=EditorialAgentTools(
            lambda job: {"reader_preferences": ["国内科技"]},
            lambda job, context: (seen.append(context.copy()) or [FakePost("memory-post")]),
            lambda *args: [],
            lambda *args: (True, "saved"),
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, conversation_context=memory),
        run_id="compressed-context",
    )

    assert result.status == "completed"
    assert seen[0]["conversation_memory"] == memory
    assert seen[0]["reader_preferences"] == ["国内科技"]


def test_agent_uses_one_batch_upload_call_for_one_job(tmp_path: Path):
    batch_calls: list[list[str]] = []
    single_calls: list[str] = []

    def upload(job, post, context):
        single_calls.append(post.id)
        return True, "single"

    def upload_batch(job, posts, context):
        batch_calls.append([post.id for post in posts])
        return {post.id: (True, "batch") for post in posts}

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻", count=2)],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost("first"), FakePost("second")],
            lambda *args: [],
            upload,
            upload_batch=upload_batch,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="batch-upload-run",
    )

    assert result.status == "completed"
    assert batch_calls == [["first", "second"]]
    assert single_calls == []
    assert [post.id for post in result.uploaded_posts] == ["first", "second"]


def test_agent_batch_upload_stops_after_terminal_platform_failure(tmp_path: Path):
    batch_calls: list[list[str]] = []
    single_calls: list[str] = []

    def upload(job, post, context):
        single_calls.append(post.id)
        return True, "single"

    def upload_batch(job, posts, context):
        batch_calls.append([post.id for post in posts])
        return {
            "first": (False, "XHS_RISK_BLOCKED: platform review required"),
            "second": (True, "batch"),
        }

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻", count=2)],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost("first"), FakePost("second")],
            lambda *args: [],
            upload,
            upload_batch=upload_batch,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="batch-platform-stop-run",
    )

    assert result.status == "partial"
    assert batch_calls == [["first", "second"]]
    assert single_calls == []
    assert result.uploaded_posts == []
    assert any("XHS_RISK_BLOCKED" in error for error in result.errors)


def test_agent_accepts_bounded_controller_ordering_hint(tmp_path: Path):
    planned = []

    def controller(jobs, context):
        planned.extend(job.kind for job in jobs)
        return {"job_order": [1, 0], "summary": "先完成简报"}

    uploaded: list[str] = []
    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻"), AgentJob("daily_ai_digest", "每日AI讯息")],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost(job.kind)],
            lambda *args: [],
            lambda job, post, context: (uploaded.append(post.id) or True, "saved"),
            plan=controller,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="controller-order",
    )

    assert result.status == "completed"
    assert planned == ["daily_news", "daily_ai_digest"]
    assert uploaded == ["daily_ai_digest", "daily_news"]


def test_agent_retries_review_failure_once(tmp_path: Path):
    review_calls = 0
    generate_calls = 0

    def sync_context(job):
        return {}

    def generate(job, context):
        nonlocal generate_calls
        generate_calls += 1
        return [FakePost(f"post-{generate_calls}")]

    def review(job, posts, context):
        nonlocal review_calls
        review_calls += 1
        return ["内容不完整"] if review_calls == 1 else []

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=EditorialAgentTools(sync_context, generate, review, lambda *args: (True, "saved")),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, max_attempts_per_job=2),
        run_id="retry-run",
    )

    assert result.status == "completed"
    assert generate_calls == 2
    assert review_calls == 2
    assert any("内容不完整" in error for error in result.errors)


def test_agent_stops_on_non_retryable_provider_rate_limit(tmp_path: Path):
    review_calls = 0
    generate_calls = 0
    events: list[tuple[str, str, str]] = []

    def generate(job, context):
        nonlocal generate_calls
        generate_calls += 1
        return [FakePost("rate-limited-post")]

    def review(job, posts, context):
        nonlocal review_calls
        review_calls += 1
        return ["Error code: 429 rate_limit_error: Token Plan 用量上限"]

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=EditorialAgentTools(
            lambda job: {},
            generate,
            review,
            lambda *args: (True, "saved"),
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        progress=lambda node, status, detail: events.append((node, status, detail)),
        run_id="provider-rate-limit-run",
    )

    assert result.status == "blocked"
    assert generate_calls == 1
    assert review_calls == 1
    assert result.uploaded_posts == []
    assert any(event[0] == "provider_pause" for event in events)
    assert not any(event[0] == "recover" and event[1] == "retry" for event in events)


def test_agent_regenerates_after_review_failure_instead_of_reusing_rejected_batch(tmp_path):
    review_calls = 0
    generate_calls = 0
    posts = {}

    def generate(job, context):
        nonlocal generate_calls
        generate_calls += 1
        post = FakePost(f"post-{generate_calls}")
        posts[post.id] = post
        return [post]

    def load_posts(ids):
        return [posts[post_id] for post_id in ids]

    def review(job, current, context):
        nonlocal review_calls
        review_calls += 1
        return ["历史重复"] if review_calls == 1 else []

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=EditorialAgentTools(
            lambda job: {},
            generate,
            review,
            lambda job, post, context: (True, "saved"),
            load_posts=load_posts,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, max_attempts_per_job=2),
        run_id="review-regenerate-run",
    )

    assert result.status == "completed"
    assert generate_calls == 2
    assert review_calls == 2
    assert [post.id for post in result.uploaded_posts] == ["post-2"]


def test_agent_retries_upload_without_regenerating_post(tmp_path: Path):
    generate_calls = 0
    upload_calls = 0
    post = FakePost("stable-post")

    def generate(job, context):
        nonlocal generate_calls
        generate_calls += 1
        return [post]

    def upload(job, current, context):
        nonlocal upload_calls
        upload_calls += 1
        return (upload_calls > 1, "temporary platform error" if upload_calls == 1 else "saved")

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=EditorialAgentTools(lambda job: {}, generate, lambda *args: [], upload),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, max_attempts_per_job=2),
        run_id="upload-retry-run",
    )

    assert result.status == "completed"
    assert generate_calls == 1
    assert upload_calls == 2


def test_agent_does_not_retry_uncertain_platform_write(tmp_path: Path):
    upload_calls = 0

    def upload(job, current, context):
        nonlocal upload_calls
        upload_calls += 1
        return False, "XHS_WRITE_UNCERTAIN: submit result unknown"

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost("uncertain-post")],
            lambda *args: [],
            upload,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, max_attempts_per_job=2),
        run_id="uncertain-upload-run",
    )

    assert result.status == "partial"
    assert upload_calls == 1
    assert any("XHS_WRITE_UNCERTAIN" in error for error in result.errors)


def test_agent_stops_serial_batch_after_uncertain_platform_write(tmp_path: Path):
    upload_calls: list[str] = []

    def upload(job, post, context):
        upload_calls.append(post.id)
        if post.id == "first-post":
            return False, "XHS_WRITE_UNCERTAIN: submit result unknown"
        return True, "saved"

    result = run_editorial_agent(
        [AgentJob("daily_news", "姣忔棩鏂伴椈", count=2)],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost("first-post"), FakePost("second-post")],
            lambda *args: [],
            upload,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, max_attempts_per_job=2),
        run_id="uncertain-batch-stop-run",
    )

    assert result.status == "partial"
    assert upload_calls == ["first-post"]
    assert result.uploaded_posts == []
    assert any("XHS_WRITE_UNCERTAIN" in error for error in result.errors)


def test_agent_keeps_generating_independent_jobs_after_platform_uncertain(tmp_path: Path):
    upload_calls: list[str] = []
    generated: list[str] = []

    def generate(job, context):
        generated.append(job.kind)
        return [FakePost(f"{job.kind}-post")]

    def upload(job, post, context):
        upload_calls.append(post.id)
        return False, "XHS_WRITE_UNCERTAIN: submit result unknown"

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻"), AgentJob("daily_ai_digest", "每日AI讯息")],
        tools=EditorialAgentTools(lambda job: {}, generate, lambda *args: [], upload),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="uncertain-continue-local-run",
    )

    assert generated == ["daily_news", "daily_ai_digest"]
    assert upload_calls == ["daily_news-post"]
    assert result.status == "partial"


def test_agent_resume_from_completed_checkpoint_does_not_reprocess(tmp_path: Path):
    calls = 0

    def generate(job, context):
        nonlocal calls
        calls += 1
        return [FakePost("resume-post")]

    tools = EditorialAgentTools(lambda job: {}, generate, lambda *args: [], lambda *args: (True, "saved"))
    first = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=tools,
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="resume-complete",
    )
    second = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=tools,
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, resume_from=first.checkpoint_path),
        run_id="ignored-on-resume",
    )

    assert first.status == second.status == "completed"
    assert calls == 1


def test_agent_resume_skips_saved_item_and_reuses_pending_posts(tmp_path: Path):
    uploaded: list[str] = []
    generated = 0
    posts = {post_id: FakePost(post_id) for post_id in ("saved-post", "pending-post")}
    checkpoint_dir = tmp_path / "interrupted"
    checkpoint_dir.mkdir(parents=True)
    checkpoint = {
        "run_id": "interrupted-run",
        "jobs": [AgentJob("daily_news", "每日新闻").__dict__],
        "job_index": 0,
        "attempts": {"0": 1},
        "context": {},
        "controller_decision": {},
        "post_ids": ["saved-post", "pending-post"],
        "reviewed_post_ids": ["saved-post", "pending-post"],
        "uploaded_post_ids": ["saved-post"],
        "item_status": {"0:saved-post": "saved"},
        "errors": [],
        "failed_jobs": [],
        "recovery_attempts": {"0": 1},
        "event_log_path": str(checkpoint_dir / "events.jsonl"),
        "next_event_id": 0,
        "started_at": 0.0,
        "root_started_at": 0.0,
        "budget_exceeded": False,
        "events": [],
        "status": "running",
        "last_failure": "upload_error: browser disconnected",
        "last_node": "upload",
        "steps": 4,
    }
    (checkpoint_dir / "checkpoint.json").write_text(
        json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
    )

    def generate(job, context):
        nonlocal generated
        generated += 1
        raise AssertionError("resuming an item batch must not generate it again")

    def upload(job, post, context):
        uploaded.append(post.id)
        return True, "saved"

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")],
        tools=EditorialAgentTools(
            lambda job: {},
            generate,
            lambda *args: [],
            upload,
            load_posts=lambda ids: [posts[post_id] for post_id in ids],
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, resume_from=checkpoint_dir),
        run_id="ignored",
    )

    assert result.status == "completed"
    assert generated == 0
    assert uploaded == ["pending-post"]


def test_agent_resume_after_budget_exhaustion_uses_fresh_attempt_budget(tmp_path: Path):
    checkpoint_dir = tmp_path / "budget-run"
    checkpoint_dir.mkdir()
    post = FakePost("pending-post")
    checkpoint = {
        "run_id": "budget-run",
        "jobs": [AgentJob("daily_news", "每日新闻").__dict__],
        "job_index": 0,
        "post_ids": [post.id],
        "uploaded_post_ids": [],
        "item_status": {},
        "event_log_path": str(checkpoint_dir / "events.jsonl"),
        "started_at": 0.0,
        "budget_exceeded": True,
        "steps": 62,
        "status": "partial",
        "last_failure": "agent budget exhausted at review",
    }
    (checkpoint_dir / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    uploaded: list[str] = []
    tools = EditorialAgentTools(
        lambda _job: {},
        lambda *_args: (_ for _ in ()).throw(AssertionError("must reuse pending draft")),
        lambda *_args: [],
        lambda _job, item, _context: (uploaded.append(item.id) or True, "saved"),
        load_posts=lambda ids: [post for _id in ids],
    )

    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻")], tools=tools,
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, resume_from=checkpoint_dir),
    )

    assert result.status == "completed"
    assert uploaded == [post.id]


def test_agent_completed_jobs_excludes_jobs_that_failed_review(tmp_path: Path):
    def generate(job, _context):
        return [FakePost(job.kind + "-post")]

    def review(job, _posts, _context):
        return ["invalid source"] if job.kind == "daily_ai_digest" else []

    result = run_editorial_agent(
        [AgentJob("daily_ai_digest", "AI"), AgentJob("daily_news", "News")],
        tools=EditorialAgentTools(lambda _job: {}, generate, review, lambda *_args: (True, "saved")),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path, max_attempts_per_job=1),
    )

    assert result.status == "partial"
    assert result.completed_jobs == 1
    assert result.requested_jobs == 2


def test_agent_generate_only_does_not_call_platform_upload(tmp_path: Path):
    upload_calls = 0

    def upload(job, post, context):
        nonlocal upload_calls
        upload_calls += 1
        return True, "should not be called"

    result = run_editorial_agent(
        [AgentJob("daily_ai_digest", "每日AI讯息")],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost("local-only")],
            lambda *args: [],
            upload,
            upload_enabled=False,
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="local-only-run",
    )

    assert result.status == "completed"
    assert upload_calls == 0
    assert result.uploaded_posts == []
    assert any(event["status"] == "skipped" for event in result.events if event["node"] == "upload")


def test_agent_rejects_unknown_provider(tmp_path: Path):
    config = EditorialAgentConfig(provider="ppinfra", checkpoint_dir=tmp_path)

    try:
        config.validate()
    except ValueError as exc:
        assert "已接入的内置供应商" in str(exc)
    else:
        raise AssertionError("non-MiniMax provider must be rejected")


def test_agent_checkpoint_redacts_environment_secret(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "super-secret-agent-key")
    result = run_editorial_agent(
        [AgentJob("daily_news", "每日新闻", prompt="key=super-secret-agent-key")],
        tools=EditorialAgentTools(
            lambda job: {},
            lambda job, context: [FakePost("safe-post")],
            lambda *args: [],
            lambda *args: (True, "saved"),
        ),
        config=EditorialAgentConfig(checkpoint_dir=tmp_path),
        run_id="redaction-run",
    )
    checkpoint_text = result.checkpoint_path.read_text(encoding="utf-8")
    assert "super-secret-agent-key" not in checkpoint_text
    assert "[已隐藏]" in checkpoint_text
