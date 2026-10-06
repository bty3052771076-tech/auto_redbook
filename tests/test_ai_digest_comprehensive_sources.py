from datetime import datetime, timezone
from src.ai_digest.collect import collect_ai_digest_updates
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.sources import AIDigestSource, resolve_ai_digest_sources


def test_research_pool_checks_aggregator_and_social_even_after_official_target_is_met(monkeypatch):
    monkeypatch.setenv('AI_DIGEST_SEARCH_BACKFILL', '0')
    sources = [AIDigestSource('official', 'official', 'https://example.com/feed', 'OpenAI'),
               AIDigestSource('discovery', 'aggregator', 'https://example.com/research', 'News'),
               AIDigestSource('social', 'social', 'https://example.com/social', 'Qwen', 'social_html')]
    calls = []
    def fetch(source):
        calls.append(source.name)
        if source.name != 'official':
            return []
        return [AIUpdateItem(title='OpenAI发布GPT-5.6并开放API',
                             summary='OpenAI发布GPT-5.6，开放模型API和百万token上下文，支持工具调用。',
                             url='https://openai.com/index/new-model-test', published_at='2026-10-06T01:00:00Z',
                             source_name='OpenAI', vendor='OpenAI', source_type='official')]
    items, meta = collect_ai_digest_updates(sources=sources, fetch_source=fetch, target_count=1,
        min_official_count=1, include_pool_items=True, max_age_days=2,
        now=datetime(2026, 10, 6, 3, tzinfo=timezone.utc))
    assert set(calls) == {'official', 'discovery', 'social'}
    assert len(items) == 1
    assert meta['aggregator_backfill_used'] is True
    assert meta['social_backfill_used'] is True


def test_verified_streams_are_default_but_do_not_override_user_source_whitelist():
    names = {s.name for s in resolve_ai_digest_sources({})}
    assert {'google-ai-blog', 'aws-ai-blog', 'microsoft-research', 'openai-codex', 'minimax-releases'} <= names
    selected = resolve_ai_digest_sources({'AI_DIGEST_PRIMARY_SOURCES': 'deepseek'})
    assert [s.name for s in selected if s.kind in {'official', 'github'}] == ['deepseek']
