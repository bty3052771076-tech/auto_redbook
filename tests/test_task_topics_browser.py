"""Real workflow API and UI keyword display, with platform writes forbidden."""

import threading

import pytest
from playwright.sync_api import expect, sync_playwright

from apps.web_gui import Server


def test_workflow_keywords_reach_sidebar_and_survive_reload(tmp_path, monkeypatch, workbench_factory):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    current = workbench_factory(tmp_path)
    monkeypatch.setattr(current, "_run", lambda *args: pytest.fail("UI recognition started a worker"))
    monkeypatch.setattr(current, "agent_capabilities", lambda: {
        "database": {"status": "ready"}, "mcp": {"status": "off", "tools": []},
        "skills": {"status": "off", "items": []}})
    server = Server(("127.0.0.1", 0), current)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="networkidle")
            page.locator("nav").get_by_role("button", name="智能体", exact=True).click()
            page.get_by_label("告诉智能体你要完成什么", exact=True).fill(
                "生成10条每日新闻，1条每日AI资讯，至少包含一条女性权益新闻")
            page.get_by_role("button", name="发送", exact=True).click()
            expect(page.locator(".agent-plan-keywords")).to_have_text("选题偏向：女性权益")
            expect(page.locator(".agent-plan-topic")).to_have_text("至少包含一条女性权益新闻")
            page.screenshot(path=str(tmp_path / "workflow-topic-desktop.png"), full_page=True)
            page.reload()
            page.locator("nav").get_by_role("button", name="智能体", exact=True).click()
            expect(page.locator(".agent-plan-keywords")).to_have_text("选题偏向：女性权益")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(300)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(tmp_path / "workflow-topic-mobile.png"), full_page=True)
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
