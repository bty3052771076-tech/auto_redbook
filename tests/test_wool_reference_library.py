import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image


def candidate(root, filename="sample.png", **metadata):
    batch = root / "候选原图/test"
    batch.mkdir(parents=True, exist_ok=True)
    path = batch / filename
    Image.new("RGB", (96, 128), "coral").save(path)
    record = {"filename": filename, "post_url": "https://danbooru.donmai.us/posts/123",
              "artist": "artist", "rating": "s", "approval_status": "visually_reviewed_reference_candidate_only",
              "license_status": "unverified", **metadata}
    (batch / "manifest.json").write_text(json.dumps({"images": [record]}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def library(root):
    from src.wool.reference_library import WoolReferenceLibrary
    return WoolReferenceLibrary(root)


def test_visual_review_is_not_manual_approval(tmp_path):
    _, identity = candidate(tmp_path)
    lib = library(tmp_path)
    row = lib.snapshot()["rows"][0]
    assert row["id"] == identity
    assert row["status"] == "pending"
    with pytest.raises(RuntimeError, match="WOOL_IMAGE_RESOURCE_MISSING"):
        lib.select_reference(issue_date="2026-10-03", provider="ZCode")


def test_manual_approval_copies_reference_and_preserves_provenance(tmp_path):
    source, identity = candidate(tmp_path)
    lib = library(tmp_path)
    with pytest.raises(ValueError, match="确认"):
        lib.review(identity, decision="approve")
    row = lib.review(identity, decision="approve", adult_confirmed=True, rights_confirmed=True,
                     non_explicit_confirmed=True, note="用户已获授权")
    reference, meta = lib.select_reference(issue_date="2026-10-03", provider="ZCode")
    assert reference.parent == tmp_path / "参考原图"
    assert reference.read_bytes() == source.read_bytes()
    assert row["status"] == "approved"
    assert meta["artist"] == "artist"
    assert meta["reference_id"] == identity
    assert meta["rights_confirmed"] is True
    assert source.is_file()
    assert lib.review(identity, decision="approve", adult_confirmed=True, rights_confirmed=True,
                      non_explicit_confirmed=True)["id"] == identity
    assert len(list((tmp_path / "参考原图").iterdir())) == 1


def test_revocation_prevents_selection_without_deleting_files(tmp_path):
    path, identity = candidate(tmp_path)
    lib = library(tmp_path)
    lib.review(identity, decision="approve", adult_confirmed=True, rights_confirmed=True, non_explicit_confirmed=True)
    lib.set_selection(identity)
    lib.review(identity, decision="reject", note="不使用")
    assert lib.snapshot()["selected_id"] == ""
    assert path.is_file()
    with pytest.raises(RuntimeError):
        lib.select_reference(issue_date="2026-10-03", provider="ZCode")


def test_candidate_path_override_is_rejected(tmp_path):
    path, _ = candidate(tmp_path)
    with pytest.raises(ValueError, match="参考原图"):
        library(tmp_path).select_reference(issue_date="2026-10-03", provider="ZCode", override=path)


def test_invalid_manifest_path_never_exposes_external_file(tmp_path):
    candidate(tmp_path, filename="sample.png")
    manifest = tmp_path / "候选原图/test/manifest.json"
    manifest.write_text(json.dumps({"images": [{"filename": "../../secret.png"}]}), encoding="utf-8")
    assert library(tmp_path).snapshot()["rows"] == []


def test_changed_candidate_does_not_inherit_approval(tmp_path):
    path, identity = candidate(tmp_path)
    lib = library(tmp_path)
    lib.review(identity, decision="approve", adult_confirmed=True, rights_confirmed=True, non_explicit_confirmed=True)
    Image.new("RGB", (96, 128), "teal").save(path)
    rows = lib.snapshot()["rows"]
    assert next(row for row in rows if row["id"] != identity)["status"] == "pending"


def test_corrupted_selected_reference_fails_closed(tmp_path):
    _, identity = candidate(tmp_path)
    lib = library(tmp_path)
    lib.review(identity, decision="approve", adult_confirmed=True, rights_confirmed=True, non_explicit_confirmed=True)
    lib.set_selection(identity)
    reference, _ = lib.select_reference(issue_date="2026-10-03", provider="ZCode")
    reference.write_bytes(b"broken")
    with pytest.raises(RuntimeError, match="WOOL_APPROVED_REFERENCE_CHANGED"):
        lib.select_reference(issue_date="2026-10-03", provider="ZCode")


def test_persona_identity_and_reference_composition_use_actual_images(monkeypatch, tmp_path):
    from src.wool import image_edit
    from src.images.opencodex_images import SubscriptionImageResult
    root = tmp_path / "assets/wool"
    _, identity = candidate(root)
    lib = library(root)
    lib.review(identity, decision="approve", adult_confirmed=True, rights_confirmed=True, non_explicit_confirmed=True)
    persona = root / "人设图/ZCode.png"
    persona.parent.mkdir()
    Image.new("RGB", (96, 128), "teal").save(persona)
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.delenv("WOOL_ASSET_ROOT", raising=False)
    monkeypatch.delenv("WOOL_REFERENCE_IMAGE", raising=False)
    requests = []

    def generate(**kwargs):
        requests.append(kwargs)
        return SubscriptionImageResult(Path("output.png"), {"provider": "opencodex"})

    monkeypatch.setattr(image_edit, "generate_subscription_image", generate)
    _, meta = image_edit.create_wool_image(post_id="test", offers=[SimpleNamespace(provider="ZCode")], issue_date="2026-10-03")
    assert requests[0]["reference_paths"][1] == persona
    assert requests[0]["reference_paths"][0].parent == root / "参考原图"
    assert "forward-reaching hand" not in requests[0]["prompt"]
    assert "IMAGE 2" in requests[0]["prompt"]
    assert requests[0]["allow_minimax_fallback"] is False
    assert meta["reference_id"] == identity


def test_danbooru_filter_requires_adult_and_non_explicit_tags():
    from src.wool.danbooru import eligible_post
    post = {"rating": "s", "tag_string_general": "mature_female curvy solo dress", "tag_string_character": ""}
    assert eligible_post(post)
    assert not eligible_post({**post, "rating": "e"})
    assert not eligible_post({**post, "tag_string_general": "large_breasts solo dress"})
    assert not eligible_post({**post, "tag_string_general": "mature_female loli solo dress"})
    assert not eligible_post({**post, "tag_string_character": "kagami_tsurugi"})


def test_fetcher_saves_verified_candidates_not_approved_references(tmp_path):
    import httpx
    from src.wool.danbooru import fetch_candidates
    from io import BytesIO
    content = BytesIO()
    Image.new("RGB", (96, 128), "coral").save(content, format="PNG")
    payload = content.getvalue()
    md5 = hashlib.md5(payload).hexdigest()
    post = {"id": 123, "rating": "s", "tag_string_general": "mature_female curvy solo dress",
            "tag_string_artist": "artist", "tag_string_character": "", "md5": md5,
            "file_url": f"https://cdn.donmai.us/original/{md5}.png", "source": "https://artist.example/123"}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[post]) if request.url.path == "/posts.json" else httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_candidates(tmp_path, count=1, style="dress", client=client, pause=lambda: None)
    assert result["downloaded"] == 1
    assert library(tmp_path).snapshot()["rows"][0]["status"] == "pending"
    assert not (tmp_path / "参考原图").exists()
    assert requests[0].url.host == "danbooru.donmai.us"


def test_fetcher_rejects_untrusted_download_host_and_preserves_failure(tmp_path):
    import httpx
    from src.wool.danbooru import fetch_candidates
    post = {"id": 123, "rating": "s", "tag_string_general": "mature_female curvy dress",
            "file_url": "http://127.0.0.1/secret.png", "md5": "a" * 32}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[post]))) as client:
        result = fetch_candidates(tmp_path, count=1, style="dress", client=client, pause=lambda: None)
    assert result["downloaded"] == 0
    assert result["errors"]


def test_manual_review_cannot_override_explicit_source_rating(tmp_path):
    _, identity = candidate(tmp_path, rating="e")
    with pytest.raises(ValueError, match="露骨"):
        library(tmp_path).review(identity, decision="approve", adult_confirmed=True,
                                 non_explicit_confirmed=True, rights_confirmed=True)


def test_approved_library_automatically_enables_reference_edit(monkeypatch, tmp_path):
    from datetime import date
    from src.wool import workflow, image_edit
    root = tmp_path / "assets/wool"
    source, identity = candidate(root)
    library(root).review(identity, decision="approve", adult_confirmed=True,
                         non_explicit_confirmed=True, rights_confirmed=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.delenv("WOOL_ASSET_ROOT", raising=False)
    monkeypatch.delenv("WOOL_IMAGE_MODE", raising=False)
    monkeypatch.setenv("IMAGE_PROVIDER", "minimax")
    monkeypatch.setattr(workflow, "collect_daily_wool_offers", lambda **kwargs: ([], {}))
    monkeypatch.setattr(image_edit, "create_wool_image", lambda **kwargs: (source, {"asset_mode": "reference_persona_edit", "provider": "opencodex", "elapsed_s": 1}))
    posts = workflow.create_daily_wool_posts(now=date(2026, 10, 3))
    assert posts[0].platform["images"][0]["provider"] == "opencodex"


def test_invalid_review_ledger_does_not_silently_fall_back_to_legacy(tmp_path):
    tmp_path.joinpath("reference-library.json").write_text(json.dumps({"version": 1, "records": {"a" * 64: None}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="WOOL_LIBRARY_INVALID"):
        library(tmp_path).has_approved_references()


def test_failed_candidates_have_actionable_size_reason(tmp_path):
    path, _ = candidate(tmp_path)
    path.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    snapshot = library(tmp_path).snapshot()
    assert not snapshot["rows"]
    assert "10 MiB" in snapshot["warnings"][0]


def test_danbooru_malformed_records_are_reported_as_source_failure(tmp_path):
    import httpx
    from src.wool.danbooru import fetch_candidates
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[None]))) as client:
        result = fetch_candidates(tmp_path, count=1, style="dress", client=client, pause=lambda: None)
    assert result["downloaded"] == 0
    assert result["errors"]


def test_mixed_fetch_spreads_candidates_across_styles(tmp_path):
    import httpx
    from io import BytesIO
    from src.wool.danbooru import fetch_candidates
    records = []
    contents = {}
    for index in range(4):
        stream = BytesIO()
        Image.new("RGB", (96, 128), (50 + index * 40, 100, 150)).save(stream, format="PNG")
        content = stream.getvalue()
        digest = hashlib.md5(content).hexdigest()
        url = f"https://cdn.donmai.us/original/{digest}.png"
        contents[url] = content
        records.append({"id": index + 1, "rating": "s", "tag_string_general": "mature_female curvy dress", "tag_string_artist": f"artist_{index}", "md5": digest, "file_url": url})
    def handler(request):
        return httpx.Response(200, json=records) if request.url.path == "/posts.json" else httpx.Response(200, content=contents[str(request.url)])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_candidates(tmp_path, count=4, style="mixed", client=client, pause=lambda: None)
    assert {row["reference_style"] for row in result["images"]} == {"office", "dress", "casual", "summer"}


def test_reference_provenance_does_not_replace_image_job_identity(tmp_path):
    _, identity = candidate(tmp_path, post_id=123)
    lib = library(tmp_path)
    lib.review(identity, decision="approve", adult_confirmed=True, non_explicit_confirmed=True, rights_confirmed=True)
    _, meta = lib.select_reference(issue_date="2026-10-03", provider="ZCode")
    assert "post_id" not in meta
    assert "status" not in meta
    assert meta["reference_source"]["post_id"] == 123
