"""Local GUI browser checks. Mutating API routes are blocked or mocked."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/playwright/react-gui"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    temp = ROOT / "data/web_gui/browser-temp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(temp)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("pageerror", lambda e: errors.append(str(e)))

        def protect(route):
            if route.request.method in {"POST", "PUT", "DELETE"} and not route.request.url.endswith("/api/session"):
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"error": "浏览器测试已阻止真实修改"}))
            else:
                route.continue_()

        page.route("**/api/**", protect)
        page.goto("http://127.0.0.1:8765", wait_until="networkidle")
        page.get_by_text("本地服务已连接", exact=True).wait_for()
        page.screenshot(path=str(OUT / "auto-desktop.png"), full_page=True)
        pages = ["自动发帖", "材料发帖", "任务中心", "本地草稿处理", "平台草稿", "已发布数据", "模型与额度", "账号与设置"]

        def navigate(name):
            if page.viewport_size["width"] <= 600:
                page.get_by_role("button", name="展开导航", exact=True).click()
            page.locator("nav").get_by_role("button", name=name, exact=True).click()
            expect(page.get_by_role("heading", name=name, exact=True).first).to_be_visible()
            if page.viewport_size["width"] <= 600:
                expect(page.locator('.sidebar')).not_to_have_class('sidebar open')

        for width in [1440, 1024, 768, 390]:
            page.set_viewport_size({"width": width, "height": 1000 if width > 600 else 844})
            for i, name in enumerate(pages):
                navigate(name)
                if name == "本地草稿处理":
                    page.locator("tbody tr").first.wait_for()
                if name == "已发布数据":
                    page.locator(".metrics-summary").wait_for()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1"), f"page overflow {name} {width}"
                page.screenshot(path=str(OUT / f"page-{i}-{width}.png"), full_page=False, animations="disabled")

        page.set_viewport_size({"width": 1440, "height": 1000})
        navigate("材料发帖")
        page.get_by_label("材料正文", exact=True).fill("保留的文字材料\n这是一段用于验证表单保存的测试文本。")
        navigate("自动发帖")
        navigate("材料发帖")
        page.screenshot(path=str(OUT / "material-switch.png"), full_page=True)
        expect(page.get_by_label("材料正文", exact=True)).to_have_value("保留的文字材料\n这是一段用于验证表单保存的测试文本。")
        page.get_by_role("button", name="生成并保存草稿", exact=True).click()
        assert page.get_by_label("材料时间（北京时间）").evaluate("el => !el.validity.valid")
        page.get_by_role("button", name="上传文件", exact=True).click()
        page.locator("input[type=file]:visible").set_input_files({"name":"material.txt","mimeType":"text/plain","buffer":"文件材料\n文件中的独立正文。".encode()})
        expect(page.get_by_label("材料正文", exact=True)).to_have_value("文件材料\n文件中的独立正文。")
        page.get_by_role("button", name="输入文字", exact=True).click()
        expect(page.get_by_label("材料正文", exact=True)).to_have_value("保留的文字材料\n这是一段用于验证表单保存的测试文本。")

        navigate("模型与额度")
        quota = page.locator(".quota-panel:visible")
        quota.get_by_label("搜索额度模型").fill("this-model-does-not-exist")
        expect(page.get_by_text("没有匹配的模型", exact=True)).to_be_visible()
        quota.get_by_label("搜索额度模型").fill("seedream")
        quota.get_by_label("额度排序").select_option("remaining")
        page.screenshot(path=str(OUT / "long-models-desktop.png"), full_page=True)

        navigate("本地草稿处理")
        page.get_by_role("button", name="审查 ").first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_label("正文与评价")).to_be_visible()
        dialog.get_by_role("button", name="图片", exact=True).click()
        if dialog.locator("img").count():
            expect(dialog.locator("img").first).to_be_visible()
            assert dialog.locator("img").first.evaluate("el => el.complete && el.naturalWidth > 0")
        page.screenshot(path=str(OUT / "draft-review.png"), full_page=True)
        dialog.get_by_role("button", name="关闭草稿").click()

        # Safe fixtures exercise paid-operation controls without reaching the worker.
        context = page.context
        page.unroute("**/api/**", protect)
        fake_job = {"id": "a"*32, "kind":"material", "title":"测试任务", "status":"completed", "stage":"平台读回", "message":"测试任务结束", "created_at":time.time(), "started_at":time.time(), "ended_at":time.time()+2, "exit_code":0, "post_ids":[], "events":[{"id":1,"at":time.time(),"message":"测试日志，不代表实际上传"}]}
        submitted = []
        def fixtures(route):
            url = route.request.url
            if url.endswith("/api/bootstrap"):
                response = route.fetch()
                data = response.json()
                data["models"]["rows"] = [{"id":"minimax:test-"+kind, "provider":"minimax", "model":"测试模型-"+kind, "kind":kind, "remaining":99, "total":100, "used":1, "unit":"percent", "cost_class":"subscription_included", "quota_pool":"test-shared-pool", "status":"available", "selectable":True, "disabled_reason":"", "snapshot_at":time.time(), "expires_at":""} for kind in ["llm","image"]]
                route.fulfill(json=data)
            elif url.endswith("/api/jobs"):
                if route.request.method == "POST":
                    submitted.append(route.request.post_data_json)
                    route.fulfill(json=fake_job)
                else:
                    route.fulfill(json=[fake_job] if submitted else [])
            elif "/api/jobs/" in url:
                route.fulfill(json=fake_job)
            else:
                protect(route)
        page.route("**/api/**", fixtures)
        page.reload(wait_until="networkidle")
        navigate("自动发帖")
        page.get_by_role("button", name="打开创作者中心", exact=True).click()
        expect(page.get_by_role("heading", name="任务中心", exact=True)).to_be_visible()
        assert submitted and submitted[0]["kind"] == "open-xhs"
        navigate("材料发帖")
        page.get_by_label("材料标题", exact=True).fill("表单测试事件")
        page.get_by_label("材料正文", exact=True).fill("正文测试：公司发布了具体产品并给出上市安排。")
        page.get_by_label("材料时间（北京时间）").fill("2020-01-01T12:00")
        for kind in ["llm","image"]:
            page.locator(".model-trigger:visible").nth(0 if kind=="llm" else 1).click()
            page.locator(".model-menu:visible").get_by_role("button", name="测试模型-"+kind).click()
        page.get_by_role("button", name="生成并保存草稿", exact=True).click()
        expect(page.get_by_role("heading", name="任务中心", exact=True)).to_be_visible()
        expect(page.get_by_label("执行日志")).to_contain_text("测试日志")
        assert len(submitted) == 2 and submitted[1]["kind"] == "material"
        assert submitted[1]["material_time"] == "2020-01-01T12:00"
        assert submitted[1]["llm_id"] == "minimax:test-llm"
        assert submitted[1]["image_id"] == "minimax:test-image"
        page.screenshot(path=str(OUT / "jobs-fixture.png"), full_page=True)
        assert not errors, errors
        report = {"pages":len(pages), "viewports":[1440,1024,768,390], "javascript_errors":errors, "mock_submissions":len(submitted), "real_mutations":0, "passed":True}
        (OUT / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
