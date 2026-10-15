import socket

import pytest

from src.workflow import create_post as news
from test_news_concise_length import SHORT, COMMENT, draft, source, run_candidate


@pytest.fixture(autouse=True)
def isolated_evaluation_test(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise AssertionError('evaluation unit tests must not contact external services')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize('comment', [
    '调查尚处早期，最终结论与影响仍待后续信息明确。',
    '需要进一步查看。',
    '后续影响有待持续观察。',
])
def test_waiting_alone_cannot_replace_event_evaluation(comment):
    assert news._daily_news_comment_is_generic(comment)


def test_concrete_judgment_can_preserve_necessary_uncertainty(monkeypatch):
    assert not news._daily_news_comment_is_generic(COMMENT)
    result, calls, _ = run_candidate(monkeypatch, [draft(SHORT)])
    assert result.status == 'success'
    assert len(calls) == 1


def test_waiting_check_does_not_treat_factual_uncertainty_as_empty_evaluation():
    body = draft(SHORT + '实施时间仍待正式确认。', '公交服务的便利不能以牺牲司机休息为代价。')['body']
    assert not news._daily_news_body_is_too_generic(body)
    assert not news._daily_news_comment_is_generic('平台经济竞争仍需依靠可观察的监管和合规行动。')


def test_empty_evaluation_is_not_silently_filled_with_canned_text():
    normalized = news._finalize_daily_news_body(draft(SHORT, '')['body'], source(), '公交', preserve_length=True)
    assert news._daily_news_body_quality_fields(normalized)['评价'] == ''


def test_generic_evaluation_uses_only_existing_one_rewrite(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [
        draft(SHORT, '后续影响有待进一步观察，实际效果仍需后续信息明确。'), draft(SHORT)])
    assert result.status == 'success', result.reason
    assert len(calls) == 2
    assert news._daily_news_body_quality_fields(result.post.body)['评价'] == COMMENT
    assert '中国国家利益' in calls[0]['prompt_hint']
    assert '人民立场' in calls[1]['prompt_hint']


def test_second_empty_evaluation_is_not_published_or_rewritten_again(monkeypatch):
    monkeypatch.setattr(news, '_fetch_daily_news_related_images',
                        lambda *a, **kw: pytest.fail('rejected commentary must not generate images'))
    result, calls, saved = run_candidate(monkeypatch, [draft(SHORT, ''), draft(SHORT, '')],
                                         auto_image_enabled=True)
    assert result.status == 'skipped'
    assert len(calls) == 2
    assert result.post is None or not result.post.assets
    assert all(post.status.value != 'saved_as_draft' for post in saved)


def test_custom_viewpoint_keeps_fact_and_public_interest_boundaries():
    prompt = news._daily_news_prompt(source(), '公交', evaluation_viewpoint='司机的劳动权益')
    assert '司机的劳动权益' in prompt
    assert '人民立场' in prompt
    assert '不得新增事实' in prompt
