import weakref

from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import ai_update_history_key
from src.storage.models import Post
from src.workflow import create_post


def test_history_scan_retains_keys_not_whole_post_payloads(monkeypatch):
    monkeypatch.setenv("AI_DIGEST_HISTORY_SKIP_TODAY", "0")
    refs = []
    peak = 0
    item = AIUpdateItem(
        title="OpenAI新增Responses API语音接口",
        summary="OpenAI为Responses API新增语音输入输出接口，开发者可在单次请求中处理音频。",
        source_name="OpenAI", source_type="official",
        url="https://openai.com/index/realtime/", published_at="2026-10-01",
    )

    def archived_posts():
        nonlocal peak
        for index in range(20):
            post = Post(id=f"history-{index}", title="每日AI讯息", body=item.summary, uploaded=True,
                        platform={"ai_digest": {"items": [item.model_dump()]}})
            refs.append(weakref.ref(post))
            peak = max(peak, sum(ref() is not None for ref in refs))
            yield post

    monkeypatch.setattr(create_post, "iter_posts", archived_posts)
    monkeypatch.setattr(create_post, "list_posts", lambda: list(archived_posts()))
    assert create_post._uploaded_ai_digest_history_keys() == {ai_update_history_key(item)}
    assert peak <= 2
