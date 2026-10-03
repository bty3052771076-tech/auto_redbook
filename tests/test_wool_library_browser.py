import json
from pathlib import Path
import threading

import pytest
from PIL import Image

from apps.web_gui import Server
from apps.web_service import ROOT


def test_wool_gallery_manual_review_desktop_mobile(tmp_path, workbench_factory):
    playwright = pytest.importorskip("playwright.sync_api")
    batch = tmp_path / "assets/wool/候选原图/test"
    batch.mkdir(parents=True)
    Image.new("RGB", (96, 128), "coral").save(batch / "sample.png")
    (batch / "manifest.json").write_text(json.dumps({"images": [{"filename": "sample.png", "rating": "s", "artist": "fixture_artist"}]}), encoding="utf-8")
    service = workbench_factory(tmp_path)
    server = Server(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = ROOT / "data/research/2026-10-03-wool-library-ui"
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="networkidle")
            page.locator("nav").get_by_role("button", name="自动发帖", exact=True).click()
            page.get_by_role("button", name="每日羊毛", exact=True).click()
            gallery = page.get_by_role("region", name="AI鸡蛋参考图库")
            preview = gallery.get_by_role("button", name="查看 sample.png", exact=True)
            playwright.expect(preview).to_be_visible()
            playwright.expect(preview.locator("img")).to_have_js_property("naturalWidth", 96)
            page.screenshot(path=str(out / "desktop-candidates.png"), full_page=True)
            preview.click()
            dialog = page.get_by_role("dialog", name="图片预览与人工筛选")
            approve = dialog.get_by_role("button", name="入选参考原图", exact=True)
            playwright.expect(approve).to_be_disabled()
            for label in ("确认人物成年，无幼态或年龄疑义", "确认非露骨，无不适合发布的内容", "确认拥有相应参考与描改使用权限"):
                dialog.get_by_label(label, exact=True).check()
            playwright.expect(approve).to_be_enabled()
            page.screenshot(path=str(out / "desktop-review.png"))
            approve.click()
            playwright.expect(dialog).not_to_be_visible()
            gallery.get_by_role("tab", name="参考原图", exact=False).click()
            reference = gallery.get_by_role("button", name="查看 sample.png", exact=True)
            playwright.expect(reference).to_be_visible()
            reference.click()
            dialog.get_by_role("button", name="指定使用此参考图", exact=True).click()
            playwright.expect(gallery.get_by_text("当前参考：sample.png", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            reference.click()
            playwright.expect(dialog).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(out / "mobile-review.png"))
            dialog.get_by_role("button", name="撤销入选", exact=True).click()
            playwright.expect(dialog).not_to_be_visible()
            gallery.get_by_role("tab", name="候选图", exact=False).click()
            gallery.get_by_label("状态", exact=True).select_option("rejected")
            playwright.expect(preview).to_be_visible()
            assert not errors, errors
            assert not (service.root / "data/posts").exists()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
