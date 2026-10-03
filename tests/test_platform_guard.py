from pathlib import Path

import pytest

from src.publish.platform_guard import (
    PlatformRiskError,
    classify_platform_surface,
    detect_platform_risk,
)


def test_platform_surface_risk_is_detected_only_from_system_surface():
    assert classify_platform_surface(
        "https://creator.xiaohongshu.com/publish/publish?target=image",
        "",
        "编辑器",
        surface_text="浏览行为与真人操作习惯不一致",
    ) == "risk_blocked"


def test_platform_review_detail_is_a_risk_surface():
    assert classify_platform_surface(
        "https://creator.xiaohongshu.com/manager",
        "笔记审核详情",
        "普通页面正文",
        surface_text="该篇笔记已不可被他人查看\n笔记存在利用AI托管进行发文/互动的内容",
    ) == "risk_blocked"


def test_news_body_text_does_not_trigger_platform_risk():
    assert classify_platform_surface(
        "https://creator.xiaohongshu.com/publish/publish?target=image",
        "",
        "正文：平台提示‘疑似使用第三方工具’，这是新闻原文引用。",
        surface_text="",
    ) == "ready"


def test_detect_platform_risk_raises_for_visible_risk_dialog(tmp_path: Path):
    class FakePage:
        def evaluate(self, script):
            assert "role=\"alert\"" in script
            return {
                "url": "https://creator.xiaohongshu.com/publish/publish?target=image",
                "title": "",
                "body": "编辑器",
                "surface": "疑似使用第三方工具",
            }

    with pytest.raises(PlatformRiskError) as exc:
        from src.publish.platform_state import PlatformStateStore

        detect_platform_risk(
            FakePage(),
            profile_key=Path("data/browser/chrome-profile"),
            store=PlatformStateStore(tmp_path / "state.json"),
        )
    assert exc.value.code == "XHS_RISK_BLOCKED"
