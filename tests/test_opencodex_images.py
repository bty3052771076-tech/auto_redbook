from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image, ImageDraw
import pytest

from src.images import opencodex_images as relay


def image_bytes():
    image = Image.new("RGB", (128, 192), "white")
    ImageDraw.Draw(image).rectangle((10, 10, 90, 120), fill="teal")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def config():
    return {"port": 10100, "providers": {"openai": {
        "adapter": "openai-responses", "authMode": "forward",
        "baseUrl": "https://chatgpt.com/backend-api/codex", "codexAccountMode": "pool"}}}


@pytest.mark.parametrize("change", [
    {"images": {"provider": "openai-apikey"}},
    {"images": {"bridgeEnabled": True}},
    {"providers": {"openai-apikey": {"apiKey": "dummy"}}},
    {"providers": {"openai": {"adapter": "openai-responses", "authMode": "apikey"}}},
])
def test_paid_or_unverified_routes_are_blocked(change):
    value = config()
    value.update(change)
    with pytest.raises(relay.OpenCodexImageError):
        relay.validate_subscription_config(value)


def test_subscription_mode_allows_main_account():
    value = config()
    value["providers"]["openai"]["codexAccountMode"] = "direct"
    relay.validate_subscription_config(value)


def test_subscription_provider_cannot_contain_api_key():
    value = config()
    value["providers"]["openai"]["apiKey"] = "dummy"
    with pytest.raises(relay.OpenCodexImageError):
        relay.validate_subscription_config(value)


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:10100",
                                  "http://127.0.0.1:10100/v1", "http://127.0.0.1:10100?q=x"])
def test_only_exact_loopback_origin_is_accepted(monkeypatch, url):
    monkeypatch.setenv("OPENCODEX_IMAGE_BASE_URL", url)
    with pytest.raises(relay.OpenCodexImageError):
        relay.connection_settings()


@pytest.fixture
def mocked_relay(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text("{}")
    monkeypatch.setenv("OPENCODEX_IMAGE_HOME", str(home))
    monkeypatch.setenv("OPENCODEX_IMAGE_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("OPENCODEX_IMAGE_STATE_DIR", str(tmp_path / "submission-state"))
    monkeypatch.setenv("OPENCODEX_IMAGE_FALLBACK", "none")
    monkeypatch.setattr(relay, "preflight", lambda _client: {
        "version": "test", "config_hash": sha256(b"{}").hexdigest(),
        "billing": "chatgpt_subscription"})
    original = httpx.Client
    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(relay.httpx, "Client", lambda **kw: original(transport=transport, **kw))
    return install


def test_cached_image_does_not_submit_again(mocked_relay, tmp_path):
    calls = []
    def handler(request):
        import base64
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]})
    mocked_relay(handler)
    kwargs = dict(post_id="test", prompt="news illustration", dest_dir=tmp_path / "assets")
    first = relay.generate_subscription_image(**kwargs)
    second = relay.generate_subscription_image(**kwargs)
    assert len(calls) == 1
    assert second.meta["cache_hit"]
    assert first.path == second.path


def test_timeout_never_falls_back_or_resubmits(mocked_relay, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("OPENCODEX_IMAGE_FALLBACK", "minimax")
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("dummy", request=request)
    mocked_relay(handler)
    kwargs = dict(post_id="test", prompt="scene", dest_dir=tmp_path / "assets")
    for _ in range(2):
        with pytest.raises(relay.OpenCodexImageError):
            relay.generate_subscription_image(**kwargs)
    assert len(calls) == 1


def test_timeout_cannot_be_resubmitted_with_a_new_post_id(mocked_relay, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("dummy", request=request)

    mocked_relay(handler)
    for post_id in ("first", "replacement"):
        with pytest.raises(relay.OpenCodexImageError):
            relay.generate_subscription_image(
                post_id=post_id, prompt="same scene", dest_dir=tmp_path / post_id
            )
    assert len(calls) == 1


def test_two_references_use_json_edit_route(mocked_relay, tmp_path):
    import base64
    refs = []
    for name in ("composition", "persona"):
        path = tmp_path / (name + ".png")
        image = Image.new("RGB", (128, 128), "coral")
        image.save(path)
        refs.append(path)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]})
    mocked_relay(handler)
    relay.generate_subscription_image(post_id="test", prompt="edit", dest_dir=tmp_path / "assets",
                                      reference_paths=refs)
    request = requests[0]
    assert request.url.path == "/v1/images/edits"
    assert len(json.loads(request.content)["images"]) == 2
    assert "authorization" not in request.headers


def test_uncertain_checkpoint_stops_without_network(mocked_relay, tmp_path):
    def handler(request):
        pytest.fail("must not submit")
    mocked_relay(handler)
    dest = tmp_path / "assets"
    dest.mkdir()
    payload = {"model": relay.MODEL, "prompt": "scene", "inputs": [], "quality": "medium", "size": "1024x1536"}
    key = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    (dest / f"opencodex-{key}.json").write_text(json.dumps({"status": "submitted"}))
    with pytest.raises(relay.OpenCodexImageError, match="PREVIOUS_REQUEST_UNCERTAIN"):
        relay.generate_subscription_image(post_id="test", prompt="scene", dest_dir=dest)


def test_bad_or_original_images_fail():
    with pytest.raises(relay.OpenCodexImageError):
        relay.validate_image(b"not an image", [])
    raw = image_bytes()
    with pytest.raises(relay.OpenCodexImageError):
        relay.validate_image(raw, [sha256(raw).hexdigest()])


def test_two_concurrent_requests_share_two_slots(mocked_relay, monkeypatch, tmp_path):
    import base64
    from threading import Lock
    active = peak = 0
    lock = Lock()
    monkeypatch.setenv("OPENCODEX_IMAGE_CONCURRENCY", "2")
    def handler(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.12)
        with lock:
            active -= 1
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]})
    mocked_relay(handler)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda i: relay.generate_subscription_image(
            post_id=str(i), prompt=f"scene {i}", dest_dir=tmp_path / str(i)), range(4)))
    assert len(values) == 4
    assert peak == 2


def test_update_code_must_be_explicitly_verified(monkeypatch, tmp_path):
    home, package = tmp_path / "home", tmp_path / "package"
    home.mkdir()
    package.mkdir()
    (home / "config.json").write_text(json.dumps(config()))
    monkeypatch.setenv("OPENCODEX_IMAGE_HOME", str(home))
    monkeypatch.setenv("OPENCODEX_IMAGE_PACKAGE_DIR", str(package))
    monkeypatch.setattr(relay, "package_code_hash", lambda _path: "unverified-new-code")
    with httpx.Client() as client:
        with pytest.raises(relay.OpenCodexImageError, match="COMPATIBILITY_REVIEW"):
            relay.preflight(client)


def test_wool_provider_not_inferred_from_underlying_model():
    from src.wool.image_edit import pick_persona
    assert pick_persona("ZCode")[0] == "ZCode.png"
    assert pick_persona("WorkBuddy")[0] == "workbuddy.png"
    assert pick_persona("unknown") is None


def test_gui_provider_binding_preserves_opencodex():
    from apps.gui import build_provider_env_overrides
    env = build_provider_env_overrides({}, llm_provider="minimax", llm_model="MiniMax-M3",
                                       image_provider="opencodex", image_model=relay.MODEL)
    assert env["IMAGE_PROVIDER"] == "opencodex"
    assert env["OPENCODEX_IMAGE_ENABLED"] == "1"


@pytest.mark.parametrize("text", ["生成10条今日每日新闻", "生成10条每日新闻", "生成10条今天的每日新闻", "每日新闻生成10条"])
def test_agent_news_quantity_accepts_day_qualifier(text):
    from apps.web_service import Workbench
    assert Workbench._agent_count(text) == 10


def test_catalog_exposes_enabled_subscription_image(tmp_path):
    from apps.web_service import Workbench
    (tmp_path / ".env.gui").write_text("OPENCODEX_IMAGE_ENABLED=1\n", encoding="utf-8")
    workbench = Workbench(root=tmp_path, conversation_store=object())
    model = next(row for row in workbench.models()["rows"] if row["id"] == "opencodex:gpt-image-2")
    assert model["selectable"]
    assert model["remaining"] is None
    assert model["cost_class"] == "subscription_included"


def test_explicit_quota_rejection_can_fall_back_to_minimax_subscription(mocked_relay, monkeypatch, tmp_path):
    from src.images import minimax_images
    monkeypatch.setenv("OPENCODEX_IMAGE_FALLBACK", "minimax")
    mocked_relay(lambda request: httpx.Response(429))
    image = tmp_path / "minimax.png"
    image.write_bytes(image_bytes())
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return minimax_images.MiniMaxImageResult(image, {"provider": "minimax", "model": "image-01"})
    monkeypatch.setattr(minimax_images, "generate_minimax_image", generate)
    result = relay.generate_subscription_image(post_id="test", prompt="scene", dest_dir=tmp_path / "assets")
    assert len(calls) == 1
    assert result.meta["fallback_from"] == "opencodex"
    assert result.meta["provider"] == "minimax"


def test_two_reference_edit_does_not_use_unsupported_minimax_fallback(mocked_relay, monkeypatch, tmp_path):
    from src.images import minimax_images
    monkeypatch.setenv("OPENCODEX_IMAGE_FALLBACK", "minimax")
    mocked_relay(lambda request: httpx.Response(429))
    refs = [tmp_path / "ref.png", tmp_path / "persona.png"]
    for path in refs:
        path.write_bytes(image_bytes())
    monkeypatch.setattr(minimax_images, "generate_minimax_image", lambda **kwargs: pytest.fail("unsupported edit fallback"))
    with pytest.raises(relay.OpenCodexImageError, match="429"):
        relay.generate_subscription_image(post_id="test", prompt="scene", dest_dir=tmp_path / "assets", reference_paths=refs)


def test_preflight_does_not_replace_explicit_opencodex_with_minimax(monkeypatch, tmp_path):
    from apps import cli
    metrics = tmp_path / "metrics.csv"
    metrics.write_text("title,likes\nnews,1\n", encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("IMAGE_PROVIDER", "opencodex")
    monkeypatch.setenv("MINIMAX_USE_SUBSCRIPTION", "1")
    monkeypatch.setenv("MINIMAX_LLM_MODEL", "MiniMax-M3")
    monkeypatch.setattr(cli, "load_quota_records", lambda **kw: ([], []))
    monkeypatch.setattr(cli, "_path_is_fresh", lambda *args, **kw: True)
    monkeypatch.setattr(cli, "_refresh_metrics_for_preflight", lambda **kw: pytest.fail("unit test must not open a browser"))
    monkeypatch.setattr(cli, "_refresh_quotas_for_preflight", lambda **kw: pytest.fail("must not sync quota"))
    report = cli._prepare_auto_pipeline(
        headless=True, login_hold=0, wait_timeout=10, metrics_max_age_hours=24,
        quota_max_age_hours=2, require_image=True, refresh_quotas=False,
        metrics_path=metrics, quota_dir=tmp_path / "quota",
        provider_keys={"minimax": True},
    )
    assert "IMAGE_PROVIDER" not in report.model_plan.environment()
    assert report.model_plan.llm.provider == "minimax"
