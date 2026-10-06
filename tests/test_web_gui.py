import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from apps.web_service import Workbench
from apps.web_gui import Server
from src.storage.files import save_post, save_execution
from src.storage.models import Post, Execution, StepResult


@pytest.fixture
def service(tmp_path, workbench_factory):
    return workbench_factory(tmp_path)


def snapshot(service, records=None, name="aliyun_quota_1.json"):
    path = service.root / "data/quota" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    records = records if records is not None else [
        {"model": "test-llm", "kind": "llm", "status": "available", "cost_class": "free", "remaining": 1000, "total": 2000, "unit": "tokens"},
        {"model": "test-image", "kind": "image", "status": "available", "cost_class": "free", "remaining": 20, "total": 100, "unit": "images"},
    ]
    path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return path


def creation(**kwargs):
    return {"kind": "auto", "title": "每日新闻", "count": 10, "llm_id": "aliyun:test-llm", "image_id": "aliyun:test-image", "prompts": ["国际新闻", "产业"], **kwargs}


def test_agent_conversation_parses_only_requested_jobs(service):
    conversation = service.create_agent_conversation()
    result = service.append_agent_message(
        conversation["id"],
        "用MiniMax生成3条每日新闻和1篇每日AI讯息，保存到小红书草稿",
    )
    plan = result["plan"]
    assert plan["executable"] is True
    assert [job["kind"] for job in plan["jobs"]] == ["daily_news", "daily_ai_digest"]
    assert plan["jobs"][0]["count"] == 3
    assert plan["platform"] == "xhs"
    assert plan["delivery"] == "save_draft"
    assert "每日羊毛" not in json.dumps(plan, ensure_ascii=False)


def test_agent_conversation_can_plan_global_map_without_adding_other_jobs(service):
    conversation = service.create_agent_conversation()
    result = service.append_agent_message(conversation["id"], "生成今日全球事件关注图并保存到本地")

    assert result["plan"]["executable"] is True
    assert [job["kind"] for job in result["plan"]["jobs"]] == ["daily_global_map"]
    assert result["plan"]["delivery"] == "save_draft"


def test_agent_conversation_honors_negated_jobs_and_explicit_draft_save(service):
    conversation = service.create_agent_conversation()
    result = service.append_agent_message(
        conversation["id"],
        "只生成一条今日全球事件关注图并保存到小红书创作者中心草稿箱，"
        "禁止公开发布，不生成每日新闻，不需要每日AI讯息。",
    )

    plan = result["plan"]
    assert plan["executable"] is True
    assert [job["kind"] for job in plan["jobs"]] == ["daily_global_map"]
    assert plan["delivery"] == "save_draft"


def test_agent_conversation_keeps_explicit_local_only_request(service):
    conversation = service.create_agent_conversation()
    plan = service.append_agent_message(
        conversation["id"], "只生成一条每日我去，不上传平台，也不要发布"
    )["plan"]

    assert [job["kind"] for job in plan["jobs"]] == ["daily_wow"]
    assert plan["delivery"] == "generate_only"


def test_agent_conversation_uses_latest_positive_job_mention(service):
    conversation = service.create_agent_conversation()
    plan = service.append_agent_message(
        conversation["id"], "不要每日新闻，改为生成一条每日新闻并保存草稿"
    )["plan"]

    assert [job["kind"] for job in plan["jobs"]] == ["daily_news"]


def test_agent_conversation_can_plan_platform_draft_review_without_generation(service):
    conversation = service.create_agent_conversation()
    result = service.append_agent_message(
        conversation["id"],
        "检查小红书创作者中心现有草稿，筛选最多3条适合今天发布的内容，先审查不要发布",
    )

    plan = result["plan"]
    assert plan["executable"] is True
    assert plan["plan_kind"] == "draft_management"
    assert plan["management"]["mode"] == "review"
    assert plan["management"]["max_items"] == 3
    assert plan["jobs"] == []


def test_agent_conversation_can_plan_explicit_platform_draft_publish(service):
    conversation = service.create_agent_conversation()
    result = service.append_agent_message(
        conversation["id"],
        "从小红书草稿箱已有内容里筛选最多2条并发布",
    )

    plan = result["plan"]
    assert plan["executable"] is True
    assert plan["plan_kind"] == "draft_management"
    assert plan["management"]["mode"] == "publish"
    assert plan["management"]["max_items"] == 2


def test_platform_draft_management_plan_uses_dedicated_cli_command(service):
    args, _ = service.plan(
        {
            "kind": "manage-drafts",
            "mode": "review",
            "draft_type": "image",
            "max_items": 3,
            "headless": True,
        },
        "c" * 32,
    )

    assert "manage-drafts" in args
    assert "--mode" in args and "review" in args
    assert "--max-items" in args and "3" in args


def test_platform_draft_management_plan_executes_without_generation(monkeypatch, service):
    conversation = service.create_agent_conversation()
    planned = service.append_agent_message(conversation["id"], "检查小红书平台草稿并筛选最多2条，先审查")
    fake_job = {"id": "d" * 32, "kind": "manage-drafts", "title": "平台草稿管理", "status": "queued"}
    monkeypatch.setattr(service, "submit", lambda request, key: {**fake_job, "request": request, "key": key})

    result = service.execute_agent_plan(conversation["id"], planned["plan"]["id"], planned["plan"]["version"], "draft-manage-test-0001")

    assert result["id"] == "d" * 32
    assert result["request"]["kind"] == "manage-drafts"
    assert result["request"]["mode"] == "review"


def test_daily_global_map_plan_freezes_scope_and_uses_standalone_cli(service):
    args, _ = service.plan(
        {
            "kind": "daily-global-map",
            "target_date": "2026-09-18",
            "cutoff_at": "2026-09-18T12:00:00+08:00",
            "delivery": "local",
            "map_mode": "coordinate-grid",
            "max_events": 6,
        },
        "b" * 32,
    )

    assert args[args.index("daily-global-map")] == "daily-global-map"
    assert "--date" in args and "2026-09-18" in args
    assert "--max-events" in args and "6" in args
    assert "--delivery" in args and "local" in args


def test_agent_conversation_rejects_invalid_count(service):
    conversation = service.create_agent_conversation()
    with pytest.raises(ValueError, match="1至20"):
        service.append_agent_message(conversation["id"], "生成21条每日新闻")


def test_agent_conversation_requires_a_supported_task(service):
    conversation = service.create_agent_conversation()
    result = service.append_agent_message(conversation["id"], "先告诉我今天适合发什么")
    assert result["plan"]["executable"] is False
    assert "每日新闻" in result["assistant"]["content"]


def test_agent_conversation_http_routes_use_existing_job_service(tmp_path, monkeypatch, workbench_factory):
    service = workbench_factory(tmp_path)
    fake_job = {"id": "a" * 32, "kind": "agent", "title": "智能体任务", "status": "queued"}
    service.jobs[fake_job["id"]] = fake_job
    monkeypatch.setattr(service, "submit", lambda request, key: {**fake_job, "request": request, "key": key})
    server = Server(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path, method="GET", body=None, key=""):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        headers = {"X-Workbench": "1"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        return json.load(urllib.request.urlopen(request))

    try:
        token = call("/api/session", method="POST", body={})["token"]
        headers = {"X-Workbench": "1", "Authorization": "Bearer " + token, "Content-Type": "application/json"}

        def authed(path, method="GET", body=None, key=""):
            data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
            current = dict(headers)
            if key:
                current["Idempotency-Key"] = key
            request = urllib.request.Request(base + path, data=data, headers=current, method=method)
            return json.load(urllib.request.urlopen(request))

        created = authed("/api/agent/conversations", "POST", {})
        conversation_id = created["id"]
        message = authed(
            f"/api/agent/conversations/{conversation_id}/messages",
            "POST",
            {"content": "生成1篇每日AI讯息并保存到小红书草稿"},
        )
        plan = message["plan"]
        assert [job["kind"] for job in plan["jobs"]] == ["daily_ai_digest"]
        executed = authed(
            f"/api/agent/plans/{plan['id']}/execute",
            "POST",
            {"conversation_id": conversation_id, "version": plan["version"]},
            key="agent-api-test-0001",
        )
        assert executed["id"] == "a" * 32
        assert executed["request"]["kind"] == "agent"
        repeated = authed(
            f"/api/agent/plans/{plan['id']}/execute",
            "POST",
            {"conversation_id": conversation_id, "version": plan["version"]},
            key="agent-api-test-0002",
        )
        assert repeated["id"] == executed["id"]
        detail = authed(f"/api/agent/conversations/{conversation_id}")
        assert detail["runs"] == ["a" * 32]
        events = authed(f"/api/agent/conversations/{conversation_id}/events?after=0")
        assert "events" in events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_models_share_catalog_and_kind(service):
    snapshot(service)
    rows = service.models()["rows"]
    assert {m["kind"] for m in rows} == {"llm", "image"}
    assert all(m["selectable"] for m in rows)


def test_minimax_subscription_models_are_visible_without_quota_snapshot(service):
    (service.root / ".env.gui").write_text(
        "MINIMAX_TOKEN_PLAN_API_KEY=test-subscription-key\n"
        "MINIMAX_USE_SUBSCRIPTION=1\n"
        "MINIMAX_BILLING_MODE=subscription_only\n"
        "MINIMAX_LLM_MODEL=MiniMax-M3\n"
        "MINIMAX_IMAGE_MODEL=image-01\n",
        encoding="utf-8",
    )
    rows = service.models()["rows"]
    llm = next(row for row in rows if row["id"] == "minimax:MiniMax-M3")
    image = next(row for row in rows if row["id"] == "minimax:image-01")
    assert llm["selectable"] is True and llm["cost_class"] == "subscription_included"
    assert image["selectable"] is True and image["cost_class"] == "subscription_included"
    assert llm["remaining"] is None and "未同步" in llm["unit"]


def test_agent_plan_accepts_configured_minimax_subscription_without_snapshot(service):
    (service.root / ".env.gui").write_text(
        "MINIMAX_TOKEN_PLAN_API_KEY=test-subscription-key\n"
        "MINIMAX_USE_SUBSCRIPTION=1\n"
        "MINIMAX_BILLING_MODE=subscription_only\n"
        "MINIMAX_LLM_MODEL=MiniMax-M3\n"
        "MINIMAX_IMAGE_MODEL=image-01\n",
        encoding="utf-8",
    )
    _, env = service.plan({
        "kind": "agent",
        "count": 1,
        "agent_id": "minimax:MiniMax-M3",
        "llm_id": "minimax:MiniMax-M3",
        "image_id": "minimax:image-01",
    }, "minimax" * 6)
    assert env["AGENT_LLM_PROVIDER"] == "minimax"
    assert env["AGENT_LLM_MODEL"] == "MiniMax-M3"
    assert env["MINIMAX_LLM_MODEL"] == "MiniMax-M3"
    assert env["MINIMAX_IMAGE_MODEL"] == "image-01"


def test_provider_catalog_exposes_independent_role_bindings(service):
    snapshot(service)
    result = service.providers()
    assert {row["id"] for row in result["connections"]} >= {"aliyun", "volcengine", "siliconflow", "minimax"}
    assert set(result["bindings"]) == {"agent", "writer", "image"}
    result = service.save_model_bindings({"agent": "aliyun:test-llm", "writer": "aliyun:test-llm", "image": "aliyun:test-image"})
    assert result["bindings"] == {"agent": "aliyun:test-llm", "writer": "aliyun:test-llm", "image": "aliyun:test-image"}
    assert service.providers()["bindings"]["agent"] == "aliyun:test-llm"
    assert service.providers()["bindings"]["writer"] == "aliyun:test-llm"
    assert service.providers()["bindings"]["image"] == "aliyun:test-image"


def test_model_bindings_reject_missing_or_unusable_models(service):
    snapshot(service)
    with pytest.raises(ValueError, match="可执行"):
        service.save_model_bindings({"agent": "aliyun:not-in-catalog", "writer": "", "image": ""})


def test_custom_provider_models_are_visible_without_exposing_api_key(service):
    result = service.save_provider({
        "id": "my-lab",
        "name": "我的模型服务",
        "protocol": "openai_chat",
        "base_url": "https://api.example.test/v1",
        "billing": "subscription",
        "api_key": "secret-custom-provider-key",
        "models": [{"id": "writer-v1", "kind": "llm", "name": "Writer V1"}],
    })
    assert result["connection"]["id"] == "my-lab"
    assert result["connection"]["configured"] is True
    assert "secret-custom-provider-key" not in json.dumps(result, ensure_ascii=False)
    rows = service.models()["rows"]
    custom = next(row for row in rows if row["id"] == "my-lab:writer-v1")
    assert custom["model"] == "writer-v1"
    assert custom["kind"] == "llm"
    assert custom["selectable"] is False
    assert "适配器" in custom["disabled_reason"]


def test_custom_provider_rejects_unsafe_url_and_unknown_billing_selection(service):
    with pytest.raises(ValueError, match="API 地址"):
        service.save_provider({"id": "bad", "name": "坏服务", "protocol": "openai_chat", "base_url": "file:///secret"})
    with pytest.raises(ValueError, match="API 地址"):
        service.save_provider({"id": "bad-userinfo", "name": "坏服务", "protocol": "openai_chat", "base_url": "https://secret@example.test/v1"})
    service.save_provider({
        "id": "unknown-lab",
        "name": "费用未知服务",
        "protocol": "openai_chat",
        "base_url": "https://api.example.test/v1",
        "billing": "unknown",
        "models": [{"id": "model-x", "kind": "llm", "name": "Model X"}],
    })
    custom = next(row for row in service.models()["rows"] if row["id"] == "unknown-lab:model-x")
    assert custom["selectable"] is False
    assert "费用" in custom["disabled_reason"]


def test_empty_latest_snapshot_does_not_revive_old(service):
    path = snapshot(service)
    import os
    os.utime(path, (1, 1))
    snapshot(service, [], "aliyun_quota_2.json")
    assert service.models()["rows"] == []


@pytest.mark.parametrize("change", [{"expires_at": "2020-01-01"}, {"cost_class": "paid"}, {"remaining": 0}, {"remaining": None}, {"status": "removed"}])
def test_unsafe_models_cannot_be_selected(service, change):
    row = {"model": "test-llm", "kind": "llm", "status": "available", "cost_class": "free", "remaining": 100, **change}
    snapshot(service, [row])
    assert not service.models()["rows"][0]["selectable"]
    with pytest.raises(ValueError):
        service.plan(creation(), "a" * 32)


def test_auto_does_not_refresh_quotas_or_allow_paid(service):
    snapshot(service)
    args, env = service.plan(creation(), "a" * 32)
    assert "--no-refresh-quotas" in args and "--headless" in args
    assert "--force" not in args
    assert args[args.index("--lookback-days") + 1] == "auto"
    assert env["ALLOW_PAID_LLM_FALLBACK"] == "0"
    assert env["MINIMAX_ALLOW_PAYGO"] == "0"
    assert env["XHS_CHROME_USER_DATA_DIR"].startswith(str(service.root))


def test_agent_plan_uses_shared_runner_and_minimax_subscription(service):
    args, env = service.plan({
        "kind": "agent",
        "count": 10,
        "prompts": ["国际热点", "AI模型发布"],
        "performance_mode": "speed",
        "platform": "xhs",
    }, "agent" * 6)
    assert args[args.index("agent") + 1] == "--prompt"
    assert "--no-refresh-quotas" in args
    assert "--preflight" not in args
    assert args[args.index("--count") + 1] == "10"
    assert env["LLM_PROVIDER"] == "minimax"
    assert env["IMAGE_PROVIDER"] == "minimax"
    assert env["MINIMAX_BILLING_MODE"] == "subscription_only"
    assert env["ALLOW_PAID_LLM_FALLBACK"] == "0"
    assert env["DAILY_NEWS_SELECTION_POLICY"] == "soft"
    assert args[args.index("--budget-minutes") + 1] == "30.0"


def test_agent_plan_passes_independent_role_models(service):
    snapshot(service, name="aliyun_quota_1.json")
    snapshot(service, records=[
        {"model": "volc-writer", "kind": "llm", "status": "available", "cost_class": "free", "remaining": 800, "total": 1000, "unit": "tokens"},
        {"model": "volc-image", "kind": "image", "status": "available", "cost_class": "free", "remaining": 8, "total": 10, "unit": "images"},
    ], name="volcengine_quota_1.json")
    _, env = service.plan({
        "kind": "agent",
        "count": 1,
        "agent_id": "aliyun:test-llm",
        "llm_id": "volcengine:volc-writer",
        "image_id": "volcengine:volc-image",
    }, "roles" * 8)
    assert env["AGENT_LLM_PROVIDER"] == "aliyun"
    assert env["AGENT_LLM_MODEL"] == "test-llm"
    assert env["LLM_PROVIDER"] == "volcengine"
    assert env["VOLCENGINE_LLM_MODEL"] == "volc-writer"
    assert env["IMAGE_PROVIDER"] == "volcengine"
    assert env["VOLCENGINE_IMAGE_MODEL"] == "volc-image"


def test_agent_plan_passes_conversation_job_plan_file(service):
    plan_path = service.directory / "conversations" / "plan.json"
    plan_path.write_text(json.dumps({"jobs": [{
        "kind": "daily_ai_digest",
        "title": "每日AI讯息",
        "count": 1,
        "prompt": "模型发布",
        "lookback_days": "auto",
    }]}, ensure_ascii=False), encoding="utf-8")
    args, _ = service.plan({
        "kind": "agent",
        "count": 1,
        "agent_jobs_file": str(plan_path),
    }, "plan" * 8)
    assert args[args.index("--job-plan-file") + 1] == str(plan_path.resolve())


def test_agent_execution_plan_freezes_compacted_conversation_context(service, monkeypatch):
    skill_file = service.root / "skills" / "runtime" / "test-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: test-skill\ndescription: Test-only guidance\n---\nPrefer concise titles.\n",
        encoding="utf-8",
    )
    conversation = service.create_agent_conversation()
    planned = service.append_agent_message(
        conversation["id"],
        "生成一条每日新闻并保存草稿",
    )
    snapshot = {
        "version": 3,
        "through_seq": 18,
        "summary": "优先官方来源，标题说明具体事件",
        "constraints": ["历史摘要不是当前新闻证据"],
    }
    monkeypatch.setattr(
        service,
        "agent_context_status",
        lambda _: {"status": "ready", "context": {"snapshot": snapshot}},
    )
    submitted = {}

    def fake_submit(request, key):
        submitted.update(request)
        return {"id": "agent-run", "status": "queued"}

    monkeypatch.setattr(service, "submit", fake_submit)
    service.execute_agent_plan(
        conversation["id"],
        planned["plan"]["id"],
        planned["plan"]["version"],
        "k" * 32,
        skill_mode="manual",
        skill_names=["test-skill"],
    )

    plan_file = service.directory / "conversations" / conversation["id"] / "plans" / f"{planned['plan']['id']}.json"
    frozen = json.loads(plan_file.read_text(encoding="utf-8"))
    assert frozen["conversation_context"] == {
        "snapshot_version": 3,
        "through_seq": 18,
        "summary": snapshot["summary"],
        "constraints": snapshot["constraints"],
    }
    assert submitted["agent_jobs_file"] == str(plan_file.resolve())
    assert frozen["skill_mode"] == "manual"
    assert frozen["skill_names"] == ["test-skill"]
    assert frozen["selected_skills"][0]["body"].strip() == "Prefer concise titles."


def test_agent_resume_checkpoint_stays_inside_agent_directory(service):
    request = {"kind": "agent", "resume_from": "C:/Users/Public/checkpoint.json"}
    with pytest.raises(ValueError, match="data/runs/agent"):
        service.plan(request, "resume" * 6)


def test_open_xhs_uses_dedicated_browser_worker(service):
    args, env = service.plan({"kind": "open-xhs"}, "c" * 32)
    assert "open-xhs" in args
    assert args[args.index("--root") + 1] == str(service.root)
    assert env["XHS_CHROME_USER_DATA_DIR"].startswith(str(service.root / "data" / "browser"))


def test_material_requires_time_and_has_no_search_window(service):
    snapshot(service)
    request = creation(kind="material", material_text="材料标题\n公司发布了可验证的新产品，提供具体规格及上市时间。", material_title="材料标题")
    with pytest.raises(ValueError, match="材料时间"):
        service.plan(request, "a" * 32)
    request["material_time"] = "2020-01-01T12:00"
    args, _ = service.plan(request, "b" * 32)
    assert "--single-news-material-file" in args
    assert "--lookback-days" not in args and "--keywords" not in args
    assert args[args.index("--count")+1] == "1"


def test_profile_outside_workspace_rejected(service):
    (service.root / ".env.gui").write_text("XHS_CHROME_USER_DATA_DIR=C:/Users/Public/Chrome\n", encoding="utf-8")
    with pytest.raises(ValueError, match="profile"):
        service.environment()


def test_redact_does_not_expose_keys(service):
    (service.root / ".env.gui").write_text("MINIMAX_API_KEY=super-secret-test-key\n", encoding="utf-8")
    output = service.redact({"message": "key=super-secret-test-key", "api_key": "hidden", "authorization": "hidden"})
    assert "super-secret" not in str(output) and "api_key" not in output


def test_post_paths_and_edit_conflict(service):
    p = Post(title="事件标题", body="原始正文")
    save_post(p, service.root / "data")
    with pytest.raises(ValueError):
        service.post("../.env.gui")
    with pytest.raises(ValueError, match="其他操作"):
        service.edit_post(p.id, {"title": "修改", "body": "修改正文", "updated_at": "old"})
    result = service.edit_post(p.id, {"title": "修改", "body": "修改正文", "updated_at": p.updated_at})
    assert result["body"] == "修改正文"
    assert list((service.directory / "edits" / p.id).glob("*.json"))


def test_saved_draft_is_not_readback_verified(service):
    p = Post(title="新闻", body="正文", uploaded=True)
    save_post(p, service.root / "data")
    assert service.post(p.id)["readback"] == "unverified"
    save_execution(Execution(post_id=p.id, steps=[StepResult(name="readback_saved_draft", status="success", detail="title=True body=True images=3/3")]), service.root / "data")
    assert service.post(p.id)["readback"] == "verified"


def test_idempotency_and_busy_guard(service, monkeypatch):
    snapshot(service)
    monkeypatch.setattr(threading.Thread, "start", lambda _: None)
    req = creation()
    first = service.submit(req, "test-idempotency-001")
    assert service.submit(req, "test-idempotency-001")["id"] == first["id"]
    with pytest.raises(ValueError, match="不同任务"):
        service.submit(creation(count=2), "test-idempotency-001")
    with pytest.raises(ValueError, match="已有任务"):
        service.submit(req, "test-idempotency-002")


def test_interrupted_jobs_not_automatically_retried(service):
    jobs = service.directory / "jobs"
    jobs.mkdir()
    (jobs / ("a"*32+".json")).write_text(json.dumps({"id":"a"*32,"status":"running","created_at":time.time()}))
    resumed = service.__class__(service.root, conversation_store=service.conversation_store)
    assert resumed.jobs["a"*32]["status"] == "interrupted"


def test_publication_requires_explicit_confirmation(service):
    p = Post(title="新闻", body="正文")
    save_post(p, service.root / "data")
    with pytest.raises(ValueError, match="确认仅自己可见"):
        service.plan({"kind":"publish-drafts", "post_id":p.id}, "a"*32)


def test_metrics_missing_is_not_zero(service):
    path = service.root / "data/analytics/published_metrics_latest.csv"
    path.parent.mkdir(parents=True)
    path.write_text('id,title,likes,raw\n1,news,,{}\n', encoding="utf-8")
    assert service.metrics()["rows"][0]["likes"] is None
    assert service.metrics()["complete"] is None


def test_delete_requires_successful_matching_recent_preview(service):
    scope = {"draft_type": "image", "title_contains": "测试", "limit": 2}
    request = {"kind": "delete-drafts", **scope, "preview_id": "a" * 32, "confirmation": "确认删除"}
    with pytest.raises(ValueError, match="预览"):
        service.plan(request, "b" * 32)
    service.jobs["a" * 32] = {"kind": "delete-preview", "status": "completed", "deletion_scope": scope, "ended_at": time.time()}
    args, _ = service.plan(request, "b" * 32)
    assert args[args.index("--title-contains") + 1] == "测试"
    assert "--yes" in args and "--headless" in args
    for change in ({"limit": 0}, {"title_contains": "其他"}, {"confirmation": ""}):
        with pytest.raises(ValueError):
            service.plan({**request, **change}, "b" * 32)
    service.jobs["a" * 32]["ended_at"] = time.time() - 601
    with pytest.raises(ValueError, match="预览"):
        service.plan(request, "b" * 32)


def test_delete_preview_is_bound_to_scope(service, monkeypatch):
    monkeypatch.setattr(threading.Thread, "start", lambda _: None)
    job = service.submit({"kind": "delete-preview", "draft_type": "all", "title_contains": "  测试  ", "limit": 1}, "preview-test-00001")
    assert job["deletion_scope"] == {"draft_type": "all", "title_contains": "测试", "limit": 1}
    args, _ = service.plan({"kind": "delete-preview", **job["deletion_scope"]}, "a" * 32)
    assert "--dry-run" in args and "--yes" not in args and "--all" in args


@pytest.mark.parametrize("provider", ["aliyun", "volcengine", "siliconflow", "minimax"])
def test_provider_quota_uses_existing_cli(service, provider):
    args, _ = service.plan({"kind": "sync-quotas", "provider": provider, "models": "test-model"}, "a" * 32)
    assert f"{provider}-quota" in args
    assert args[args.index("--model") + 1] == "test-model"
    assert "--all-free" not in args


def test_sources_analysis_and_local_approval(service):
    report = service.sources()
    assert report["rows"]
    assert report["check"] is None
    assert all(row["status"] in {"not_checked", "not_configured", "disabled", "not_selected"} for row in report["rows"])
    assert service.analysis()["text"] == ""
    args, _ = service.plan({"kind": "check-sources", "collection": "ai_digest", "max_age_days": 3}, "a" * 32)
    assert "ai_digest" in args
    with pytest.raises(ValueError):
        service.plan({"kind": "check-sources", "collection": "invalid"}, "a" * 32)
    args, _ = service.plan({"kind": "analyze-metrics", "top_n": 6}, "a" * 32)
    assert "--save" in args
    p = Post(title="新闻", body="正文")
    save_post(p, service.root / "data")
    args, _ = service.plan({"kind": "approve", "post_id": p.id}, "a" * 32)
    assert "approve" in args and "--force" not in args
    with pytest.raises(ValueError, match="仅重试"):
        service.plan({"kind": "retry", "post_id": p.id}, "a" * 32)


def test_config_secrets_write_only_and_blank_preserves(service):
    secret = "test-secret-do-not-return"
    result = service.save_configuration({"MINIMAX_TOKEN_PLAN_API_KEY": secret})
    assert result["secrets"]["MINIMAX_TOKEN_PLAN_API_KEY"] is True
    assert secret not in str(result)
    service.save_configuration({"MINIMAX_TOKEN_PLAN_API_KEY": ""})
    assert secret in (service.root / ".env.gui").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        service.save_configuration({"MINIMAX_ALLOW_PAYGO": "1"})
    with pytest.raises(ValueError):
        service.save_configuration({"MINIMAX_TOKEN_PLAN_API_KEY": "abc\nMINIMAX_ALLOW_PAYGO=1"})


def test_configuration_refuses_tracked_env(service, monkeypatch):
    import subprocess
    (service.root / ".git").mkdir()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0))
    with pytest.raises(ValueError, match="Git"):
        service.save_configuration({"MINIMAX_TOKEN_PLAN_API_KEY": "test-secret"})
    assert not (service.root / ".env.gui").exists()


def test_multiple_materials_pass_batch_snapshot(service):
    snapshot(service)
    text = json.dumps({"items": [{"title": "新闻一", "content": "公司一发布具体产品。"}, {"title": "新闻二", "content": "公司二发布具体产品。"}]}, ensure_ascii=False)
    args, _ = service.plan(creation(kind="material", material_mode="multiple", material_text=text,
                                   material_time="2026-01-01T12:00", count=2), "a" * 32)
    assert "--news-materials-file" in args and "--single-news-material-file" not in args
    assert args[args.index("--count") + 1] == "2"


def test_local_images_reject_secret_files_and_skip_image_model(service):
    snapshot(service)
    assets = service.root / "assets"
    assets.mkdir()
    (assets / "cover.png").write_bytes(b"fixture")
    args, _ = service.plan(creation(use_local_images=True, assets_glob="assets/*.png", image_id=""), "a" * 32)
    assert args[args.index("--assets-glob")+1] == str(service.root / "assets/*.png")
    (assets / "key.txt").write_text("secret")
    for pattern in ("../.env.gui", "assets/*", "no-images/*"):
        with pytest.raises(ValueError):
            service.plan(creation(use_local_images=True, assets_glob=pattern), "a" * 32)


def test_publish_batch_requires_confirmation_and_exact_ids(service):
    p = Post(title="新闻", body="正文", uploaded=True)
    save_post(p, service.root / "data")
    req = {"kind": "publish-batch", "post_ids": [p.id]}
    with pytest.raises(ValueError, match="确认仅自己可见"):
        service.plan(req, "a" * 32)
    args, _ = service.plan({**req, "confirmation": "确认仅自己可见"}, "a" * 32)
    assert args[args.index("--post-id") + 1] == p.id
    assert "--all" not in args


def test_run_allows_selected_platform(service):
    p = Post(title="新闻", body="正文")
    save_post(p, service.root / "data")
    args, _ = service.plan({"kind":"run", "post_id":p.id, "platform":"both"}, "a" * 32)
    assert args[args.index("--platform") + 1] == "both"


def test_http_auth_origin_static_secret_protection(service):
    server = Server(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/api/bootstrap")
        assert err.value.code == 403
        req = urllib.request.Request(base + "/api/session", data=b"{}", headers={"X-Workbench":"1", "Origin":"https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req)
        assert err.value.code == 403
        req = urllib.request.Request(base + "/api/session", data=b"{}", headers={"X-Workbench":"1"})
        token = json.load(urllib.request.urlopen(req))["token"]
        req = urllib.request.Request(base + "/api/bootstrap", headers={"Authorization":"Bearer "+token})
        response = json.load(urllib.request.urlopen(req))
        assert response["capabilities"]["source_cap"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
