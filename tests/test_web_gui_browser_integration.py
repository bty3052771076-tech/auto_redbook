"""Real HTTP/React checks using an isolated store and simulated CLI execution."""
import json
import threading
import time
from pathlib import Path

import pytest

from apps.web_gui import Server
from apps.web_service import Workbench, ROOT
from src.storage.files import save_post
from src.storage.models import Post


def test_web_feature_pages_and_confirmation(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    service = Workbench(tmp_path)
    post = Post(title="隔离测试新闻", body="测试正文，不上传真实平台。")
    save_post(post, tmp_path / "data")
    planned = []

    def simulate(job, args, env):
        planned.append(args)
        with service.lock:
            job.update(status="completed", started_at=time.time(), ended_at=time.time(), exit_code=0)
            service.event(job, "隔离测试执行完成；未连接平台")

    monkeypatch.setattr(service, "_run", simulate)
    server = Server(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = ROOT / "output/playwright/web-feature-parity"
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="networkidle")
            playwright.expect(page.get_by_text("本地服务已连接", exact=True)).to_be_visible()
            pages = ["自动发帖", "材料发帖", "任务中心", "本地草稿处理", "平台草稿", "已发布数据", "模型与额度", "账号与设置", "删除平台草稿", "信源健康"]

            def navigate(name):
                if page.viewport_size["width"] <= 600:
                    page.get_by_role("button", name="展开导航", exact=True).click()
                page.locator("nav").get_by_role("button", name=name, exact=True).click()
                playwright.expect(page.get_by_role("heading", name=name, exact=True).first).to_be_visible()

            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 1000 if width > 600 else 844})
                for i, name in enumerate(pages):
                    navigate(name)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (name, width)
                    page.screenshot(path=str(out / f"{i}-{width}.png"), animations="disabled")

            page.set_viewport_size({"width": 1440, "height": 1000})
            navigate("删除平台草稿")
            page.get_by_label("标题包含", exact=True).fill("仅删除测试草稿")
            page.get_by_label("最多删除数量（0 为全部）", exact=True).fill("2")
            button = page.get_by_role("button", name="确认删除平台草稿", exact=True)
            playwright.expect(button).to_be_disabled()
            page.get_by_role("button", name="预览平台草稿", exact=True).click()
            playwright.expect(page.get_by_role("heading", name="任务中心", exact=True)).to_be_visible()
            navigate("删除平台草稿")
            # A completed preview never replaces explicit confirmation.
            playwright.expect(button).to_be_disabled()
            page.get_by_label("标题包含", exact=True).fill("仅删除测试草稿")
            page.get_by_label("最多删除数量（0 为全部）", exact=True).fill("2")
            page.get_by_label("输入“确认删除”", exact=True).fill("确认删除")
            playwright.expect(button).to_be_enabled()
            page.screenshot(path=str(out / "delete-confirmation.png"))
            button.click()
            playwright.expect(page.get_by_role("heading", name="任务中心", exact=True)).to_be_visible()
            assert any("--dry-run" in args for args in planned)
            assert any("--yes" in args and "delete-drafts" in args for args in planned)
            assert all(args[args.index("--title-contains") + 1] == "仅删除测试草稿" for args in planned)

            navigate("账号与设置")
            page.get_by_text("模型与信源密钥", exact=True).click()
            page.get_by_label("MINIMAX_TOKEN_PLAN_API_KEY", exact=True).fill("fixture-key-not-real")
            page.get_by_role("button", name="保存本机配置", exact=True).click()
            playwright.expect(page.get_by_text("已保存到本机 .env.gui", exact=True)).to_be_visible()
            playwright.expect(page.get_by_label("MINIMAX_TOKEN_PLAN_API_KEY", exact=True)).to_have_value("")
            assert "fixture-key-not-real" not in page.locator("body").inner_text()

            navigate("本地草稿处理")
            page.get_by_role("button", name="审查 隔离测试新闻", exact=True).click()
            dialog = page.get_by_role("dialog")
            for label in ("校验本地草稿", "本地审核通过", "重试失败上传", "更新平台草稿"):
                playwright.expect(dialog.get_by_role("button", name=label, exact=True)).to_be_visible()
            dialog.get_by_role("button", name="校验本地草稿", exact=True).click()
            playwright.expect(page.get_by_role("heading", name="任务中心", exact=True)).to_be_visible()
            assert any("validate" in args for args in planned)
            assert not errors, errors
            (out / "report.json").write_text(json.dumps({"passed": True, "pages": 10, "viewports": [1440,390],
                "real_platform_mutations": 0, "javascript_errors": errors}, indent=2), encoding="utf-8")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
