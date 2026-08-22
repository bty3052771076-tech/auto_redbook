import json

import pytest

from src.news.manual_material_input import prepare_material_text_snapshot
from src.news.daily_news import read_manual_material_source_info


def test_prepare_single_text_material_accepts_plain_article(tmp_path):
    snapshot = prepare_material_text_snapshot(
        "恒大案一审宣判\n法院公开宣判了案件结果，并说明了判决依据。",
        mode="single",
        requested_count=7,
        default_material_time="2026-08-20 10:00",
        output_dir=tmp_path,
    )

    payload = json.loads(snapshot.path.read_text(encoding="utf-8"))

    assert snapshot.item_count == 1
    assert payload["schema_version"] == 1
    assert payload["input_origin"] == "gui_text"
    assert payload["items"][0]["title"] == "恒大案一审宣判"
    assert payload["items"][0]["content"] == "法院公开宣判了案件结果，并说明了判决依据。"
    assert payload["items"][0]["seendate"] == "2026-08-20T10:00:00+08:00"


def test_prepare_single_text_material_applies_nonempty_metadata_overrides(tmp_path):
    snapshot = prepare_material_text_snapshot(
        "正文首行会被标题覆盖\n这是完整的材料正文。",
        mode="single",
        requested_count=1,
        default_material_time="2026-08-20 10:00",
        title_override="恒大集团及许家印案一审宣判",
        source_override="深圳市中级人民法院",
        url_override="https://example.com/court",
        output_dir=tmp_path,
    )

    item = json.loads(snapshot.path.read_text(encoding="utf-8"))["items"][0]

    assert item["title"] == "恒大集团及许家印案一审宣判"
    assert item["source"] == "深圳市中级人民法院"
    assert item["url"] == "https://example.com/court"


def test_prepare_single_text_material_preserves_one_line_body_when_title_is_overridden(tmp_path):
    body = "法院公开宣判了案件结果，并说明了判决依据。"
    snapshot = prepare_material_text_snapshot(
        body + "\n",
        mode="single",
        requested_count=1,
        default_material_time="2026-08-20 10:00",
        title_override="恒大集团及许家印案一审宣判",
        output_dir=tmp_path,
    )

    item = json.loads(snapshot.path.read_text(encoding="utf-8"))["items"][0]

    assert item["title"] == "恒大集团及许家印案一审宣判"
    assert item["content"] == body


def test_prepare_single_text_material_rejects_multiple_blocks(tmp_path):
    with pytest.raises(RuntimeError, match="恰好 1 条"):
        prepare_material_text_snapshot(
            "第一条\n正文一\n---\n第二条\n正文二",
            mode="single",
            requested_count=1,
            default_material_time="2026-08-20",
            output_dir=tmp_path,
        )


def test_prepare_multiple_text_material_requires_requested_count(tmp_path):
    with pytest.raises(RuntimeError, match="需要至少 3 条.*当前只有 2 条"):
        prepare_material_text_snapshot(
            "第一条\n正文一\n---\n第二条\n正文二",
            mode="multiple",
            requested_count=3,
            default_material_time="2026-08-20",
            output_dir=tmp_path,
        )


def test_prepare_text_material_resolves_default_time_without_recency_check(tmp_path):
    snapshot = prepare_material_text_snapshot(
        "很久以前的材料\n这条材料由用户直接提供。",
        mode="single",
        requested_count=1,
        default_material_time="2020-01-02 03:04",
        output_dir=tmp_path,
    )

    item = json.loads(snapshot.path.read_text(encoding="utf-8"))["items"][0]

    assert item["seendate"] == "2020-01-02T03:04:00+08:00"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("   \n\t", "没有可用文字"),
        ("含有\0控制字符\n正文", "NUL"),
    ],
)
def test_prepare_text_material_rejects_blank_and_nul(text, message, tmp_path):
    with pytest.raises(RuntimeError, match=message):
        prepare_material_text_snapshot(
            text,
            mode="single",
            requested_count=1,
            default_material_time="2026-08-20",
            output_dir=tmp_path,
        )


def test_prepare_text_material_rejects_oversized_input(tmp_path):
    with pytest.raises(RuntimeError, match="超过"):
        prepare_material_text_snapshot(
            "x" * (1024 * 1024 + 1),
            mode="single",
            requested_count=1,
            default_material_time="2026-08-20",
            output_dir=tmp_path,
        )


def test_read_manual_material_source_info_recognizes_gui_snapshot(tmp_path):
    snapshot = prepare_material_text_snapshot(
        "标题\n正文",
        mode="single",
        requested_count=1,
        default_material_time="2026-08-20",
        output_dir=tmp_path,
    )

    info = read_manual_material_source_info(snapshot.path)

    assert info["input_origin"] == "gui_text"
    assert info["schema_version"] == 1
    assert info["raw_char_count"] == snapshot.raw_char_count
    assert info["raw_sha256"] == snapshot.raw_sha256
    assert "正文" not in json.dumps(info, ensure_ascii=False)


def test_read_manual_material_source_info_marks_regular_file(tmp_path):
    path = tmp_path / "manual.md"
    path.write_text("标题\n正文", encoding="utf-8")

    assert read_manual_material_source_info(path) == {"input_origin": "file"}
