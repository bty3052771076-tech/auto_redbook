from datetime import datetime, timezone
from pathlib import Path

from src.ai_digest.models import AIUpdateItem
from src.ai_digest.sources import AIDigestSource
from src.sources.health import SourceAttempt, is_source_in_cooldown, should_replace_source


def test_no_recent_update_is_not_a_network_failure():
    at = datetime.now(timezone.utc)
    row = SourceAttempt('ai_digest', 'official', 'https://example.com', 'official_stream',
                        'stale', at.isoformat(), recent_statuses=('stale',) * 6)
    assert not is_source_in_cooldown(row, now=at)
    assert not should_replace_source(row)


def test_diagnostic_checks_every_source_and_keeps_generation_history(tmp_path, monkeypatch):
    from src.sources import diagnostics as diag
    sources = [AIDigestSource(name, 'official', f'https://example.com/{name}', name)
               for name in ('fresh', 'old', 'broken')]
    monkeypatch.setattr(diag, 'resolve_ai_digest_sources', lambda env=None: sources)
    monkeypatch.setattr(diag, 'default_ai_digest_sources', lambda: sources)
    calls = []
    def fetch(source, **kwargs):
        calls.append(source.name)
        if source.name == 'broken':
            raise RuntimeError('HTTP 429 https://example.com?key=very-secret-token')
        day = '2026-10-06T02:00:00Z' if source.name == 'fresh' else '2026-09-01T02:00:00Z'
        return [AIUpdateItem(title='A concrete model launch', summary='New model weights are available',
                             url=source.url, source_name=source.vendor, source_type='official', published_at=day)]
    monkeypatch.setattr(diag, 'fetch_ai_digest_source', fetch)
    old_path = tmp_path / 'data/source_health/ai_digest.json'
    old_path.parent.mkdir(parents=True)
    old_path.write_text('original-generation-history', encoding='utf-8')
    report = diag.run_source_diagnostics('ai_digest', root=tmp_path, env={'OTHER_API_KEY': 'very-secret-token'},
                                         now=datetime(2026, 10, 6, 3, tzinfo=timezone.utc), max_age_days=2)
    rows = {row['source_name']: row for row in report['rows']}
    assert set(calls) == {'fresh', 'old', 'broken'}
    assert rows['fresh']['recent_count'] == 1
    assert rows['old']['connection_status'] == 'reachable'
    assert rows['old']['status'] == 'stale'
    assert rows['broken']['status'] == 'rate_limited'
    assert rows['broken']['action']
    assert 'very-secret-token' not in str(report)
    assert old_path.read_text(encoding='utf-8') == 'original-generation-history'
    assert not list((tmp_path / 'data').glob('posts/*'))


def test_missing_credentials_and_disabled_sources_are_not_probed(tmp_path, monkeypatch):
    from src.sources import diagnostics as diag
    disabled = AIDigestSource('disabled', 'official', 'https://example.com', 'Disabled', enabled=False)
    monkeypatch.setattr(diag, 'default_ai_digest_sources', lambda: [disabled])
    monkeypatch.setattr(diag, 'resolve_ai_digest_sources', lambda env=None: [])
    monkeypatch.setattr(diag, 'fetch_ai_digest_source', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')))
    rows = diag.source_catalog(env={}, root=tmp_path)
    assert next(row for row in rows if row['source_name'] == 'disabled')['status'] == 'disabled'
    assert next(row for row in rows if row['source_name'] == 'newsapi')['status'] == 'not_configured'


def test_unknown_collection_is_rejected_without_network(tmp_path):
    from src.sources import diagnostics as diag
    import pytest
    with pytest.raises(ValueError):
        diag.run_source_diagnostics('arbitrary-url', root=tmp_path)


def test_default_topics_do_not_override_custom_news_keywords(tmp_path, monkeypatch, workbench_factory):
    current = workbench_factory(tmp_path)
    plan = current._parse_agent_message('生成5条每日新闻')
    assert plan['jobs'][0]['prompt'] == '国际冲突 科技产业 社会民生 财经产业'
    custom = current._parse_agent_message('生成5条每日新闻，关键词：女性权益、芯片；仅生成本地稿')
    assert custom['jobs'][0]['prompt'] == '女性权益 芯片'
    assert custom['jobs'][0]['keywords'] == ['女性权益', '芯片']


def test_future_items_are_rejected_and_date_only_items_do_not_invent_a_clock(tmp_path, monkeypatch):
    from src.sources import diagnostics as diag
    sources = [AIDigestSource(name, 'official', f'https://example.com/{name}', name) for name in ('date-only', 'future')]
    monkeypatch.setattr(diag, 'default_ai_digest_sources', lambda: sources)
    monkeypatch.setattr(diag, 'resolve_ai_digest_sources', lambda env=None: sources)
    def fetch(source, **kwargs):
        return [AIUpdateItem(title='发布模型并开放权重', summary='模型新增图像理解能力并开放模型权重。',
            url=source.url, source_name=source.name, source_type='official',
            published_at='2026-10-06' if source.name == 'date-only' else '2026-10-08')]
    monkeypatch.setattr(diag, 'fetch_ai_digest_source', fetch)
    report = diag.run_source_diagnostics('ai_digest', root=tmp_path, env={}, now=datetime(2026, 10, 6, 3, tzinfo=timezone.utc))
    rows = {r['source_name']: r for r in report['rows']}
    assert rows['date-only']['latest_published_at'] == '2026-10-06'
    assert rows['date-only']['recent_count'] == 1
    assert rows['future']['status'] == 'future_dates'
    assert rows['future']['recent_count'] == 0


def test_legacy_gui_reads_diagnostic_results_instead_of_old_generation_snapshot(tmp_path):
    import json
    from apps.gui import load_latest_source_health_snapshots, source_health_status_label
    path = tmp_path / 'diagnostics_ai_digest.json'
    path.write_text(json.dumps({'generated_at': '2026-10-06T03:00:00Z', 'rows': [
        {'source_name': 'official', 'status': 'rate_limited', 'checked_at': '2026-10-06T03:00:00Z', 'error': 'HTTP 429'}]}), encoding='utf-8')
    snapshot = load_latest_source_health_snapshots(source_dir=tmp_path)
    assert snapshot['ai_digest'].attempts[0].status == 'rate_limited'
    assert source_health_status_label('rate_limited') == '接口限流'


def test_local_service_connection_failure_has_specific_recovery_action(tmp_path, monkeypatch):
    from src.sources import diagnostics as diag
    source = AIDigestSource('aihot-local', 'aggregator', 'http://127.0.0.1:8767/api/v1/items', 'AIHOT')
    monkeypatch.setattr(diag, 'default_ai_digest_sources', lambda: [source])
    monkeypatch.setattr(diag, 'resolve_ai_digest_sources', lambda env=None: [source])
    def fetch(*args, **kwargs):
        raise ConnectionError('curl: (7) Failed to connect to 127.0.0.1 port 8767: Could not connect to server')
    monkeypatch.setattr(diag, 'fetch_ai_digest_source', fetch)
    row = diag.run_source_diagnostics('ai_digest', root=tmp_path, env={})['rows'][0]
    assert row['status'] == 'local_service_unavailable'
    assert row['connection_status'] == 'failed'
    assert '启动' in row['action']
    assert diag._error_status(ConnectionError('Could not connect to server'), 'https://example.com') == 'api_error'
