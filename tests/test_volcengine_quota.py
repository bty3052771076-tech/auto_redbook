from __future__ import annotations

from src.volcengine.quota import (
    _charge_item_model_names,
    _complete_volcengine_visible_only_records,
    _capture_charge_item_request_headers,
    _fetch_all_charge_item_payloads,
    _fetch_target_charge_item_payloads,
    _make_volcengine_not_visible_records,
    format_volcengine_quota_records,
    parse_all_volcengine_console_api_quota,
    parse_volcengine_console_api_quota,
    parse_volcengine_quota_text,
    volcengine_quota_model_candidates,
)


def test_charge_item_model_names_discovers_models_outside_static_candidates():
    payloads = [
        {
            "Result": {
                "Items": [
                    {"FoundationModelName": "doubao-seed-1-6-vision"},
                    {"DisplayName": "new-vision-model"},
                    {"FoundationModelName": "doubao-seed-1-6-vision"},
                ]
            }
        }
    ]

    assert _charge_item_model_names(payloads) == [
        "doubao-seed-1-6-vision",
        "new-vision-model",
    ]


def test_parse_volcengine_quota_text_extracts_llm_and_image_values():
    text = """
    模型名称 免费推理额度 已使用 剩余 到期时间
    doubao-seed-2-1-turbo-260628 token 500000 12000 488000 2026-08-01
    doubao-seedream-5-0-lite-260128 张 100 3 97 2026-08-01
    """

    records = parse_volcengine_quota_text(
        text,
        ["doubao-seed-2-1-turbo-260628", "doubao-seedream-5-0-lite-260128"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["doubao-seed-2-1-turbo-260628"].kind == "llm"
    assert by_model["doubao-seed-2-1-turbo-260628"].total == 500000
    assert by_model["doubao-seed-2-1-turbo-260628"].used == 12000
    assert by_model["doubao-seed-2-1-turbo-260628"].remaining == 488000
    assert by_model["doubao-seed-2-1-turbo-260628"].unit.lower() == "token"
    assert by_model["doubao-seed-2-1-turbo-260628"].expires_at == "2026-08-01"
    assert by_model["doubao-seedream-5-0-lite-260128"].kind == "image"
    assert by_model["doubao-seedream-5-0-lite-260128"].remaining == 97
    assert by_model["doubao-seedream-5-0-lite-260128"].unit == "张"


def test_volcengine_quota_model_candidates_merge_defaults_and_env(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_LLM_MODELS", "custom-llm,doubao-seed-2-1-turbo-260628")
    monkeypatch.setenv("VOLCENGINE_IMAGE_MODELS", "custom-image,doubao-seedream-5-0-lite-260128")

    candidates = volcengine_quota_model_candidates()

    assert candidates[:4] == [
        "custom-llm",
        "doubao-seed-2-1-turbo-260628",
        "custom-image",
        "doubao-seedream-5-0-lite-260128",
    ]


def test_parse_volcengine_quota_text_handles_reordered_columns_units_and_status():
    text = """
    模型名称 剩余额度 已使用 免费推理额度 状态 有效期
    glm-5.2 12.5万 token 1.5万 token 14万 token 生效中 2026年8月31日
    doubao-seedream-5-0-lite-260128 0 张 100 张 100 张 已用完 2026/08/31
    deepseek-v4-pro 无免费额度
    deepseek-v4-flash 已过期 2026-07-01
    """

    records = parse_volcengine_quota_text(
        text,
        [
            "glm-5.2",
            "doubao-seedream-5-0-lite-260128",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
        ],
    )

    by_model = {record.model: record for record in records}
    glm = by_model["glm-5.2"]
    assert glm.remaining == 125000
    assert glm.used == 15000
    assert glm.total == 140000
    assert glm.status == "available"
    assert glm.expires_at == "2026-08-31"
    assert by_model["doubao-seedream-5-0-lite-260128"].status == "exhausted"
    assert by_model["deepseek-v4-pro"].status == "no_free_quota"
    assert by_model["deepseek-v4-flash"].status == "expired"


def test_volcengine_quota_default_llm_candidates_include_current_ark_models(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VOLCENGINE_LLM_MODELS", raising=False)
    monkeypatch.delenv("VOLCENGINE_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("VOLCENGINE_IMAGE_MODELS", raising=False)

    candidates = volcengine_quota_model_candidates()

    assert "glm-5.2" in candidates
    assert "deepseek-v4-pro" in candidates
    assert "deepseek-v4-flash" in candidates


def test_format_volcengine_quota_records_marks_unknown_remaining_values():
    records = parse_volcengine_quota_text(
        "doubao-seed-2-1-turbo-260628 控制台页面未展开",
        ["doubao-seed-2-1-turbo-260628"],
    )

    output = format_volcengine_quota_records(records)

    assert "doubao-seed-2-1-turbo-260628" in output
    assert "unknown" in output
    assert "status" in output
    assert "official Volcengine Ark console" in output


def test_make_volcengine_not_visible_records_marks_visible_only_status():
    records = _make_volcengine_not_visible_records(["glm-5.2", "doubao-seedream-5-0-lite-260128"])

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].kind == "llm"
    assert by_model["doubao-seedream-5-0-lite-260128"].kind == "image"
    assert all(record.status == "not_visible_on_page" for record in records)
    assert all(record.remaining is None for record in records)

    output = format_volcengine_quota_records(records)

    assert "not_visible_on_page" in output
    assert "visible-only" in output


def test_complete_volcengine_visible_only_records_fills_missing_targets():
    parsed = parse_volcengine_quota_text("glm-5.2 token 100 20 80 2026-08-01", ["glm-5.2"])

    records = _complete_volcengine_visible_only_records(
        parsed,
        ["glm-5.2", "doubao-seedream-5-0-lite-260128"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].remaining == 80
    assert by_model["doubao-seedream-5-0-lite-260128"].status == "not_visible_on_page"


def test_fetch_target_charge_item_payloads_uses_default_headers_without_capture():
    class FakePage:
        def __init__(self):
            self.payload = None

        def evaluate(self, _script, payload):
            self.payload = payload
            return [{"Result": {"FoundationModelName": "glm-5-2"}}]

    page = FakePage()

    payloads = _fetch_target_charge_item_payloads(page, ["glm-5.2"], [])

    assert payloads[0]["Result"]["FoundationModelName"] == "glm-5-2"
    assert page.payload["headers"]["content-type"] == "application/json"
    assert "glm-5-2" in page.payload["models"]


def test_fetch_all_charge_item_payloads_pages_without_model_filter():
    class FakePage:
        def __init__(self):
            self.payload = None

        def evaluate(self, _script, payload):
            self.payload = payload
            return [
                {"Result": {"TotalCount": 2, "PageNumber": 1, "Items": [{"FoundationModelName": "glm-5-2"}]}},
                {"Result": {"TotalCount": 2, "PageNumber": 2, "Items": [{"FoundationModelName": "deepseek-v4-pro"}]}},
            ]

    page = FakePage()

    payloads = _fetch_all_charge_item_payloads(page, [{"x-csrf-token": "token"}], page_size=1, max_pages=5)

    assert [payload["Result"]["Items"][0]["FoundationModelName"] for payload in payloads] == [
        "glm-5-2",
        "deepseek-v4-pro",
    ]
    assert page.payload["headers"]["x-csrf-token"] == "token"
    assert page.payload["pageSize"] == 1
    assert page.payload["maxPages"] == 5


def test_capture_charge_item_request_headers_accepts_any_ark_console_api_request():
    class FakeRequest:
        url = "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetAutoSetFreeLimit?"
        headers = {
            "x-csrf-token": "csrf-token",
            "x-web-id": "web-id",
            "cookie": "should-not-be-captured",
        }

    captured: list[dict[str, str]] = []

    _capture_charge_item_request_headers(FakeRequest(), captured)

    assert captured == [{"x-csrf-token": "csrf-token", "x-web-id": "web-id"}]


def test_parse_volcengine_console_api_quota_extracts_free_usage():
    payload = {
        "Result": {
            "Items": [
                {
                    "FoundationModelName": "doubao-pro-32k",
                    "DisplayName": "Doubao-pro-32k",
                    "State": "Available",
                    "InferenceFreeUsage": {"Total": 500000, "Consumed": 12000},
                    "IsOverdue": False,
                }
            ]
        }
    }

    records = parse_volcengine_console_api_quota([payload], ["doubao-pro-32k"])

    assert len(records) == 1
    record = records[0]
    assert record.model == "doubao-pro-32k"
    assert record.total == 500000
    assert record.used == 12000
    assert record.remaining == 488000
    assert record.status == "available"
    assert "InferenceFreeUsage" in record.raw_text


def test_parse_volcengine_console_api_quota_distinguishes_available_without_free_usage():
    payload = {
        "Result": {
            "Items": [
                {
                    "FoundationModelName": "glm-5-2",
                    "DisplayName": "GLM-5.2",
                    "State": "Available",
                    "IsOverdue": False,
                },
                {
                    "FoundationModelName": "doubao-seedream-5-0",
                    "DisplayName": "Doubao-Seedream-5.0-lite",
                    "State": "Available",
                    "IsOverdue": False,
                },
            ]
        }
    }

    records = parse_volcengine_console_api_quota(
        [payload],
        ["glm-5.2", "doubao-seedream-5-0-lite-260128"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].status == "quota_not_returned"
    assert by_model["glm-5.2"].remaining is None
    assert by_model["doubao-seedream-5-0-lite-260128"].status == "quota_not_returned"
    assert "doubao-seedream-5-0" in by_model["doubao-seedream-5-0-lite-260128"].raw_text


def test_parse_volcengine_console_api_quota_extracts_resource_pack_free_inference():
    payload = {
        "Result": {
            "FoundationModelName": "doubao-seedream-5-0",
            "DisplayName": "Doubao-Seedream-5.0-lite",
            "State": "Available",
            "ChargeItems": [
                {"Type": "T2ICompletion", "UnitCode": "张", "Price": 0.22},
                {"Type": "I2ICompletion", "UnitCode": "张", "Price": 0.22},
            ],
            "ResourcePackItems": [
                {
                    "Total": 50,
                    "Consumed": 13,
                    "Type": "FreeInference",
                    "SyncTime": "2026-07-03T11:53:56+08:00",
                    "Reclaimed": 0,
                }
            ],
            "IsOverdue": False,
        }
    }

    records = parse_volcengine_console_api_quota(
        [payload],
        ["doubao-seedream-5-0-lite-260128"],
    )

    record = records[0]
    assert record.status == "available"
    assert record.total == 50
    assert record.used == 13
    assert record.remaining == 37
    assert record.unit == "张"
    assert "SyncTime" in record.raw_text


def test_parse_all_volcengine_console_api_quota_keeps_resource_pack_free_models():
    payload = {
        "Result": {
            "Items": [
                {
                    "FoundationModelName": "glm-5-2",
                    "DisplayName": "GLM-5.2",
                    "State": "Available",
                    "ResourcePackItems": [
                        {"Total": 500000, "Consumed": 0, "Type": "FreeInference", "Reclaimed": 0}
                    ],
                    "IsOverdue": False,
                },
                {
                    "FoundationModelName": "doubao-seed-2-1-turbo",
                    "DisplayName": "Doubao-Seed-2.1-turbo",
                    "State": "Available",
                    "ResourcePackItems": [
                        {"Total": 500000, "Consumed": 100, "Type": "FreeInference", "Reclaimed": 0}
                    ],
                    "IsOverdue": False,
                },
                {
                    "FoundationModelName": "doubao-seedream-5-0",
                    "DisplayName": "Doubao-Seedream-5.0-lite",
                    "State": "Available",
                    "ChargeItems": [{"UnitCode": "image", "Type": "T2ICompletion"}],
                    "ResourcePackItems": [
                        {"Total": 50, "Consumed": 13, "Type": "FreeInference", "Reclaimed": 0}
                    ],
                    "IsOverdue": False,
                },
                {
                    "FoundationModelName": "doubao-seedream-4-5",
                    "DisplayName": "Doubao-Seedream-4.5",
                    "State": "Available",
                    "ChargeItems": [{"UnitCode": "image", "Type": "T2ICompletion"}],
                    "ResourcePackItems": [
                        {"Total": 200, "Consumed": 1, "Type": "FreeInference", "Reclaimed": 0}
                    ],
                    "IsOverdue": False,
                },
                {
                    "FoundationModelName": "no-free-pack",
                    "DisplayName": "No free pack",
                    "State": "Available",
                    "IsOverdue": False,
                },
            ]
        }
    }

    records = parse_all_volcengine_console_api_quota([payload])

    by_model = {record.model: record for record in records}
    assert by_model["glm-5.2"].remaining == 500000
    assert by_model["glm-5.2"].kind == "llm"
    assert by_model["doubao-seed-2-1-turbo-260628"].remaining == 499900
    assert by_model["doubao-seedream-5-0-lite-260128"].remaining == 37
    assert by_model["doubao-seedream-5-0-lite-260128"].kind == "image"
    assert by_model["doubao-seedream-4-5-251128"].remaining == 199
    assert by_model["doubao-seedream-4-5-251128"].kind == "image"
    assert "no-free-pack" not in by_model
