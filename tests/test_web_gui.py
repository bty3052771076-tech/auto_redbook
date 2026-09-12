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
def service(tmp_path):
    return Workbench(tmp_path)


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


def test_models_share_catalog_and_kind(service):
    snapshot(service)
    rows = service.models()["rows"]
    assert {m["kind"] for m in rows} == {"llm", "image"}
    assert all(m["selectable"] for m in rows)


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
    resumed = Workbench(service.root)
    assert resumed.jobs["a"*32]["status"] == "interrupted"


def test_publication_requires_explicit_confirmation(service):
    p = Post(title="新闻", body="正文")
    save_post(p, service.root / "data")
    with pytest.raises(ValueError, match="确认发布"):
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
    assert service.sources() == {"rows": []}
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
    with pytest.raises(ValueError, match="确认发布"):
        service.plan(req, "a" * 32)
    args, _ = service.plan({**req, "confirmation": "确认发布"}, "a" * 32)
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
