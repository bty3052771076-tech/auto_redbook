import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from apps.web_gui import Server


def test_custom_provider_configuration_verification_and_role_binding(tmp_path, workbench_factory):
    requests = []
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            value = {'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}]}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    service = workbench_factory(tmp_path)
    server = Server(('127.0.0.1', 0), service)
    for host in (upstream, server):
        threading.Thread(target=host.serve_forever, daemon=True).start()
    artifacts = Path('data/tmp/model-platforms-browser')
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('nav').get_by_role('button', name='模型与供应商', exact=True).click()
            page.get_by_role('button', name='添加供应商', exact=True).click()
            page.screenshot(path=str(artifacts / 'add-connection.png'))
            expect(page.get_by_label('连接模板', exact=True)).to_be_visible()
            page.get_by_label('连接模板', exact=True).select_option('ollama')
            page.get_by_label('供应商名称', exact=True).fill('我的本机模型')
            page.get_by_label('API 基址', exact=True).fill(f'http://127.0.0.1:{upstream.server_port}/v1')
            page.get_by_role('button', name='保存连接', exact=True).click()
            expect(page.get_by_role('dialog', name='添加供应商', exact=True)).to_have_count(0)
            assert requests == []
            page.get_by_role('button', name='添加模型', exact=True).click()
            page.get_by_label('原生模型 ID', exact=True).fill('org/model:preview')
            page.get_by_role('button', name='保存模型', exact=True).click()
            page.get_by_role('button', name='授权此连接', exact=True).click()
            page.get_by_label('确认承担此连接的费用风险', exact=True).check()
            page.get_by_role('button', name='保存授权', exact=True).click()
            page.get_by_role('tab', name='模型目录', exact=True).click()
            page.get_by_role('button', name='测试结构化', exact=True).click()
            expect(page.get_by_text('验证通过', exact=True)).to_be_visible(timeout=15000)
            assert len(requests) == 1
            assert requests[0]['model'] == 'org/model:preview'
            page.get_by_role('tab', name='默认角色', exact=True).click()
            page.get_by_role('button', name='智能体主控模型', exact=True).click()
            page.get_by_role('option', name='我的本机模型 · org/model:preview', exact=True).click()
            page.get_by_role('button', name='写稿模型', exact=True).click()
            page.get_by_role('option', name='我的本机模型 · org/model:preview', exact=True).click()
            page.get_by_role('button', name='保存默认模型', exact=True).click()
            expect(page.get_by_text('默认角色已保存', exact=True)).to_be_visible()
            page.reload()
            page.locator('nav').get_by_role('button', name='模型与供应商', exact=True).click()
            page.get_by_role('tab', name='默认角色', exact=True).click()
            expect(page.get_by_role('button', name='智能体主控模型', exact=True)).to_contain_text('org/model:preview')
            page.screenshot(path=str(artifacts / 'desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(artifacts / 'mobile.png'), full_page=True)
            assert errors == []
            browser.close()
    finally:
        for host in (server, upstream):
            host.shutdown()
            host.server_close()
