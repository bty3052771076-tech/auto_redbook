import pytest

from src.agent.task_intent import enrich_local_plan, extract_job_keywords


@pytest.mark.parametrize('text,expected', [
    ('生成10条每日新闻，1条每日AI资讯，至少包含一条女性权益新闻',
     {'daily_news': ['女性权益'], 'daily_ai_digest': []}),
    ('生成3条每日新闻，关键词为女性权益、劳动保障，保存到草稿箱',
     {'daily_news': ['女性权益', '劳动保障'], 'daily_ai_digest': []}),
    ('生成3条每日新闻，关键词是：女性权益，1条每日AI资讯',
     {'daily_news': ['女性权益'], 'daily_ai_digest': []}),
    ('生成3条每日新闻，关键词：女性权益，生成1条每日AI资讯，关键词：DeepSeek',
     {'daily_news': ['女性权益'], 'daily_ai_digest': ['DeepSeek']}),
    ('生成3条每日新闻，优先关注女性权益、劳动保障；每日AI资讯主要关注DeepSeek、MiniMax',
     {'daily_news': ['女性权益', '劳动保障'], 'daily_ai_digest': ['DeepSeek', 'MiniMax']}),
])
def test_natural_topics_are_extracted_without_leaking_between_columns(text, expected):
    assert extract_job_keywords(text, ['daily_news', 'daily_ai_digest']) == expected


def test_partial_topic_requirement_retains_other_news_directions():
    base = {'jobs': [
        {'kind': 'daily_news', 'title': '每日新闻', 'count': 10, 'prompt': '国际冲突 科技产业 社会民生 财经产业'},
        {'kind': 'daily_ai_digest', 'title': '每日AI讯息', 'count': 1, 'prompt': '模型发布'}],
        'assistant_summary': '待确认'}
    plan = enrich_local_plan(base, '生成10条每日新闻，1条每日AI资讯，至少包含一条女性权益新闻')
    news, ai = plan['jobs']
    assert news['keywords'] == ['女性权益']
    assert news['keyword_mode'] == 'preference'
    assert news['topic_brief'] == '至少包含一条女性权益新闻'
    assert news['prompt'] == '国际冲突 科技产业 社会民生 财经产业\n选题要求：至少包含一条女性权益新闻'
    assert ai['keywords'] == [] and ai['topic_brief'] == ''
    assert base['jobs'][0]['prompt'] == '国际冲突 科技产业 社会民生 财经产业'


def test_negated_topic_is_not_treated_as_a_positive_keyword():
    assert extract_job_keywords('生成3条每日新闻，不要包含女性权益新闻', ['daily_news']) == {'daily_news': []}


def test_explicit_keywords_still_replace_default_topics():
    base = {'jobs': [{'kind': 'daily_news', 'title': '每日新闻', 'prompt': '国际冲突 科技产业 社会民生 财经产业'}],
            'assistant_summary': '待确认'}
    job = enrich_local_plan(base, '生成3条每日新闻，关键词为女性权益、芯片')['jobs'][0]
    assert job['prompt'] == '女性权益 芯片'
    assert job['keyword_mode'] == 'filter'
