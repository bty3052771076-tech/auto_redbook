import json
import threading
import urllib.error
import urllib.request

import pytest
from PIL import Image
from typer.testing import CliRunner

from apps.web_gui import Server


def seed(root):
    batch = root / "assets/wool/候选原图/test"
    batch.mkdir(parents=True)
    Image.new("RGB", (96, 128), "coral").save(batch / "sample.png")
    (batch / "manifest.json").write_text(json.dumps({"images": [{"filename": "sample.png", "rating": "s"}]}), encoding="utf-8")


def test_wool_library_http_auth_and_manual_review(tmp_path, workbench_factory):
    seed(tmp_path)
    service = workbench_factory(tmp_path)
    server = Server(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, body=None, token=""):
        return urllib.request.urlopen(urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                      headers={"X-Workbench": "1", "Authorization": "Bearer " + token}))

    try:
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            request("/api/wool-library")
        assert unauthorized.value.code == 403
        token = json.load(request("/api/session", {}))["token"]
        rows = json.load(request("/api/wool-library", token=token))["rows"]
        assert len(rows) == 1
        identity = rows[0]["id"]
        with pytest.raises(urllib.error.HTTPError) as missing_confirmation:
            request("/api/wool-library/review", {"id": identity, "decision": "approve"}, token)
        assert missing_confirmation.value.code == 400
        result = json.load(request("/api/wool-library/review", {"id": identity, "decision": "approve", "adult_confirmed": True,
                                   "rights_confirmed": True, "non_explicit_confirmed": True}, token))
        assert result["status"] == "approved"
        image = request(f"/api/wool-library/images/{identity}", token=token)
        assert image.headers["Content-Type"] == "image/png"
        assert image.read().startswith(b"\x89PNG")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_library_cli_approval_requires_flags_and_is_visible(tmp_path, monkeypatch):
    from apps.cli import app
    seed(tmp_path)
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.delenv("WOOL_ASSET_ROOT", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["wool-library", "list"])
    assert result.exit_code == 0, result.output
    identity = json.loads(result.output)["rows"][0]["id"]
    rejected = runner.invoke(app, ["wool-library", "review", identity, "--decision", "approve"])
    assert rejected.exit_code != 0
    approved = runner.invoke(app, ["wool-library", "review", identity, "--decision", "approve", "--adult-confirmed", "--rights-confirmed", "--non-explicit-confirmed"])
    assert approved.exit_code == 0, approved.output
    assert json.loads(approved.output)["status"] == "approved"
    selected = runner.invoke(app, ["wool-library", "select", identity])
    assert selected.exit_code == 0
