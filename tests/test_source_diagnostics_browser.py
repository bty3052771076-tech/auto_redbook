import json
import threading
import time
from playwright.sync_api import expect, sync_playwright
from apps.web_gui import Server


def test_workflow_source_check_stays_on_page_and_refreshes_without_platform_writes(tmp_path, monkeypatch, workbench_factory):
    monkeypatch.setenv('TEMP', str(tmp_path))
    monkeypatch.setenv('TMP', str(tmp_path))
    current = workbench_factory(tmp_path)
    finish = threading.Event()
    commands = []
    def simulate(job, args, env):
        commands.append(args)
        job.update(status='running')
        current.event(job, '[check-sources] stage=检查信源 | in_progress | 1/2 OpenAI')
        finish.wait(15)
        path = tmp_path / 'data/source_health/diagnostics_ai_digest.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'rows': [dict(source_name='openai', source_url='https://openai.com/news/rss.xml',
            status='rate_limited', status_label='接口限流', connection_status='failed', action='等待限流恢复。',
            checked_at='2026-10-06T03:00:00Z', error='HTTP 429', elapsed_seconds=1.0,
            item_count=0, dated_count=0, recent_count=0)]}), encoding='utf-8')
        job.update(status='completed', ended_at=time.time(), message='检测完成')
    monkeypatch.setattr(current, '_run', simulate)
    server = Server(('127.0.0.1', 0), current)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
            page.locator('nav').get_by_role('button', name='信源健康', exact=True).click()
            page.get_by_role('button', name='检查信源', exact=True).click()
            expect(page.get_by_role('button', name='检测中', exact=True)).to_be_disabled()
            expect(page.get_by_role('heading', name='信源健康', exact=True)).to_be_visible()
            finish.set()
            expect(page.get_by_text('HTTP 429', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='检查信源', exact=True)).to_be_enabled()
            page.get_by_label('仅请求失败', exact=True).check()
            expect(page.locator('.source-table tbody tr')).to_have_count(1)
            page.screenshot(path=str(tmp_path / 'workflow-sources-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_timeout(300)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(tmp_path / 'workflow-sources-mobile.png'), full_page=True)
            assert len(commands) == 1 and 'check-sources' in commands[0]
            assert '--no-refresh-quotas' not in commands[0]
            assert not errors
            browser.close()
    finally:
        finish.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
