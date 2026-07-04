from __future__ import annotations

from src.aliyun.quota import (
    _complete_aliyun_visible_only_records,
    _make_aliyun_not_visible_records,
    _should_retry_aliyun_quota_after_login_transition,
    AliyunQuotaRecord,
    aliyun_quota_model_candidates,
    detect_aliyun_console_errors,
    format_aliyun_quota_records,
    parse_all_aliyun_console_api_quota,
    parse_aliyun_console_api_quota,
    parse_aliyun_quota_text,
)


def test_parse_aliyun_quota_text_extracts_llm_and_image_remaining_values():
    text = """
    模型名称 免费额度 已用额度 剩余额度 到期时间
    qwen3.7-plus Token 1000000 120000 880000 2026-07-31
    wan2.7-image 张 500 25 475 2026-07-31
    """

    records = parse_aliyun_quota_text(text, ["qwen3.7-plus", "wan2.7-image"])

    by_model = {record.model: record for record in records}
    assert by_model["qwen3.7-plus"].kind == "llm"
    assert by_model["qwen3.7-plus"].total == 1000000
    assert by_model["qwen3.7-plus"].used == 120000
    assert by_model["qwen3.7-plus"].remaining == 880000
    assert by_model["qwen3.7-plus"].unit.lower() == "token"
    assert by_model["qwen3.7-plus"].expires_at == "2026-07-31"
    assert by_model["wan2.7-image"].kind == "image"
    assert by_model["wan2.7-image"].remaining == 475
    assert by_model["wan2.7-image"].unit == "张"


def test_parse_aliyun_quota_text_preserves_raw_row_when_numbers_are_not_parseable():
    text = "qwen3.6-flash 当前页面展示异常，请稍后刷新"

    records = parse_aliyun_quota_text(text, ["qwen3.6-flash"])

    assert len(records) == 1
    assert records[0].model == "qwen3.6-flash"
    assert records[0].remaining is None
    assert "展示异常" in records[0].raw_text


def test_parse_aliyun_quota_text_handles_reordered_columns_units_and_status():
    text = """
    模型名称 剩余额度 已用额度 免费额度 状态 有效期
    qwen-image-2.0-pro-2026-06-22 1.2万 Tokens 800 Tokens 2万 Tokens 生效中 2026年8月31日
    qwen3.7-plus 0 Token 1,000,000 Token 1,000,000 Token 已用完 2026/08/31
    glm-5.2 无免费额度
    """

    records = parse_aliyun_quota_text(
        text,
        ["qwen-image-2.0-pro-2026-06-22", "qwen3.7-plus", "glm-5.2"],
    )

    by_model = {record.model: record for record in records}
    image = by_model["qwen-image-2.0-pro-2026-06-22"]
    assert image.remaining == 12000
    assert image.used == 800
    assert image.total == 20000
    assert image.status == "available"
    assert image.expires_at == "2026-08-31"
    assert by_model["qwen3.7-plus"].status == "exhausted"
    assert by_model["glm-5.2"].remaining == 0
    assert by_model["glm-5.2"].status == "no_free_quota"


def test_parse_aliyun_quota_text_handles_chinese_remaining_ratio_without_date_confusion():
    text = """
    模型Code 免费额度剩余量 过期时间 状态 操作
    qwen3.7-plus 剩118,817/共1,000,000 2026/09/01 已开启 -
    glm-5.1 剩908,470/共1,000,000 2026/07/14 已开启 -
    """

    records = parse_aliyun_quota_text(text, ["qwen3.7-plus", "glm-5.1"])

    by_model = {record.model: record for record in records}
    assert by_model["qwen3.7-plus"].remaining == 118817
    assert by_model["qwen3.7-plus"].total == 1000000
    assert by_model["qwen3.7-plus"].expires_at == "2026-09-01"
    assert by_model["glm-5.1"].remaining == 908470
    assert by_model["glm-5.1"].total == 1000000


def test_parse_aliyun_quota_text_prefers_numeric_remaining_over_top3_warning_label():
    text = """
    免费额度即将用尽TOP3模型
    glm-5.2
    剩205,875/共1,000,000
    9%
    全部模型
    批量操作免费额度用完即停
    """

    records = parse_aliyun_quota_text(text, ["glm-5.2"])

    assert records[0].remaining == 205875
    assert records[0].total == 1000000
    assert records[0].status == "available"


def test_parse_aliyun_console_api_quota_extracts_free_tier_quotas():
    payload = {
        "data": {
            "DataV2": {
                "data": {
                    "data": {
                        "freeTierQuotas": [
                            {
                                "model": "glm-5.2",
                                "quotaInitTotal": 1000000.0,
                                "quotaTotal": 205875.0,
                                "quotaStatus": "VALID",
                                "quotaValidityPeriod": 1789401600000,
                            },
                            {
                                "model": "qwen-image-2.0-pro-2026-06-22",
                                "quotaStatus": "UNKNOWN",
                            },
                        ]
                    }
                }
            }
        }
    }

    records = parse_aliyun_console_api_quota(
        [payload],
        ["glm-5.2", "qwen-image-2.0-pro-2026-06-22"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].remaining == 205875
    assert by_model["glm-5.2"].total == 1000000
    assert by_model["glm-5.2"].status == "available"
    assert by_model["glm-5.2"].unit == "token"
    assert by_model["qwen-image-2.0-pro-2026-06-22"].status == "quota_not_returned"


def test_parse_all_aliyun_console_api_quota_keeps_only_models_with_free_tier_total():
    payload = {
        "data": {
            "DataV2": {
                "data": {
                    "data": {
                        "freeTierQuotas": [
                            {
                                "model": "glm-5.2",
                                "quotaInitTotal": 1000000.0,
                                "quotaTotal": 205875.0,
                                "quotaStatus": "VALID",
                            },
                            {
                                "model": "qwen-image-2.0-pro-2026-06-22",
                                "quotaInitTotal": 100.0,
                                "quotaTotal": 100.0,
                                "quotaStatus": "VALID",
                            },
                            {
                                "model": "qwen3.7-plus",
                                "quotaInitTotal": 1000000.0,
                                "quotaTotal": 0.0,
                                "quotaStatus": "VALID",
                            },
                            {
                                "model": "model-without-free-tier",
                                "quotaInitTotal": 0.0,
                                "quotaTotal": 0.0,
                                "quotaStatus": "VALID",
                            },
                        ]
                    }
                }
            }
        }
    }

    records = parse_all_aliyun_console_api_quota([payload])

    by_model = {record.model: record for record in records}
    assert list(by_model) == [
        "glm-5.2",
        "qwen-image-2.0-pro-2026-06-22",
        "qwen3.7-plus",
    ]
    assert by_model["glm-5.2"].remaining == 205875
    assert by_model["qwen-image-2.0-pro-2026-06-22"].kind == "image"
    assert by_model["qwen3.7-plus"].status == "exhausted"
    assert "model-without-free-tier" not in by_model


def test_aliyun_quota_model_candidates_merge_defaults_and_env(monkeypatch):
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "custom-llm,qwen3.7-plus custom-llm")
    monkeypatch.setenv("ALIYUN_IMAGE_MODELS", "custom-image,wan2.7-image")

    candidates = aliyun_quota_model_candidates()

    assert candidates[:4] == [
        "custom-llm",
        "qwen3.7-plus",
        "custom-image",
        "wan2.7-image",
    ]


def test_aliyun_quota_default_image_candidates_include_current_qwen_image(monkeypatch):
    monkeypatch.delenv("ALIYUN_LLM_MODEL", raising=False)
    monkeypatch.delenv("ALIYUN_LLM_MODELS", raising=False)
    monkeypatch.delenv("ALIYUN_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("ALIYUN_IMAGE_MODELS", raising=False)

    candidates = aliyun_quota_model_candidates()

    assert "qwen-image-2.0-pro-2026-06-22" in candidates
    assert candidates.index("qwen-image-2.0-pro-2026-06-22") < candidates.index(
        "qwen-image-2.0-pro-2026-04-22"
    )


def test_format_aliyun_quota_records_marks_unknown_remaining_values():
    records = parse_aliyun_quota_text("qwen3.7-plus 页面未展开", ["qwen3.7-plus"])

    output = format_aliyun_quota_records(records)

    assert "qwen3.7-plus" in output
    assert "unknown" in output
    assert "status" in output
    assert "open the official Bailian console" in output


def test_make_aliyun_not_visible_records_marks_visible_only_status():
    records = _make_aliyun_not_visible_records(["glm-5.2", "qwen-image-2.0-pro-2026-06-22"])

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].kind == "llm"
    assert by_model["qwen-image-2.0-pro-2026-06-22"].kind == "image"
    assert all(record.status == "not_visible_on_page" for record in records)
    assert all(record.remaining is None for record in records)

    output = format_aliyun_quota_records(records)

    assert "not_visible_on_page" in output
    assert "visible-only" in output


def test_complete_aliyun_visible_only_records_fills_missing_targets():
    parsed = parse_aliyun_quota_text("glm-5.2 Token 100 20 80 2026-08-01", ["glm-5.2"])

    records = _complete_aliyun_visible_only_records(
        parsed,
        ["glm-5.2", "qwen-image-2.0-pro-2026-06-22"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].remaining == 80
    assert by_model["qwen-image-2.0-pro-2026-06-22"].status == "not_visible_on_page"


def test_detect_aliyun_console_errors_marks_internal_not_logged_in():
    payloads = [
        {
            "data": {
                "success": False,
                "errorCode": "BailianGateway.Login.NotLogined",
                "errorMsg": "BailianGateway.Login.NotLogined",
            }
        }
    ]

    errors = detect_aliyun_console_errors(
        "登录以使用\n您当前处于未登录状态",
        payloads,
    )

    assert "bailian_internal_not_logged_in" in errors
    assert "aliyun_console_login_required" in errors


def test_detect_aliyun_console_errors_uses_later_logged_in_status():
    payloads = [
        {"data": {"DataV2": {"data": {"data": {"loginStatus": "NOT_LOGINED"}}}}},
        {"data": {"DataV2": {"data": {"data": {"loginStatus": "ALIYUN_LOGINED", "spaceInited": True}}}}},
    ]

    errors = detect_aliyun_console_errors("WH1TE123\n主账号", payloads)

    assert "bailian_internal_not_logged_in" not in errors


def test_should_retry_aliyun_quota_after_login_transition_only_for_empty_retryable_page():
    payloads = [
        {"data": {"errorCode": "BailianGateway.Login.NotLogined"}},
        {"data": {"DataV2": {"data": {"data": {"loginStatus": "ALIYUN_LOGINED"}}}}},
    ]

    assert _should_retry_aliyun_quota_after_login_transition(
        "免费额度\n暂无符合条件的资源",
        payloads,
        [],
    )
    assert not _should_retry_aliyun_quota_after_login_transition(
        "免费额度\n暂无符合条件的资源",
        payloads,
        [AliyunQuotaRecord(model="glm-5.2", status="available", remaining=1)],
    )
    assert not _should_retry_aliyun_quota_after_login_transition(
        "免费额度\n暂无符合条件的资源",
        payloads,
        [],
        visible_only=True,
    )
