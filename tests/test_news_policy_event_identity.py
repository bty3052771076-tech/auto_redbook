"""Policy release identity must win over clause wording and fuzzy title overlap."""

from dataclasses import replace

import pytest

from src.news.daily_news import NewsItem, _dedupe_by_story


def _item(key, title, description, **kwargs):
    return NewsItem(
        title=title,
        url=f"https://example.com/{key}",
        description=description,
        source=kwargs.pop("source", "澎湃新闻"),
        domain=kwargs.pop("domain", "www.thepaper.cn"),
        seendate=kwargs.pop("seendate", "2026-10-21 18:21:03"),
        **kwargs,
    )


@pytest.fixture
def policy_clauses():
    # Hand-checked excerpts from discovery 7fdb0b0df5a54c0ab01dbb784eaacefe.
    rows = [
        (
            "34301258",
            "中办国办：强化国家科技计划项目的产业应用导向，常态化征集企业需求",
            "中办国办：强化国家科技计划项目的产业应用导向。《意见》提出，"
            "强化国家科技计划项目的产业应用导向，常态化征集企业需求。",
            "2026-10-21 18:21:03",
        ),
        (
            "34301407",
            "中办国办：引导高校、科研院所按照先使用后付费方式把科技成果许可给中小微企业使用",
            "中办国办。《意见》提出，畅通科技成果转化途径。健全研用一体的成果转化应用机制，"
            "产业应用目标明确的国家科技计划项目，原则上由企业牵头实施并主导成果转化。",
            "2026-10-21 18:20:25",
        ),
        (
            "34301415",
            "中办国办：推动国家自然科学基金试点向民营企业开放",
            "中办国办。《意见》提出，全面增强企业创新能力。完善企业常态化参与国家科技和"
            "产业发展战略、规划、政策制定机制。推动国家自然科学基金试点向民营企业开放。",
            "2026-10-21 18:24:26",
        ),
        (
            "34301421",
            "中办国办：高质量建设债券市场“科技板”，建立科技保险政策体系",
            "中办国办：高质量建设债券市场“科技板”。《意见》提出，促进科技、产业、金融良性循环。"
            "构建与科技企业全生命周期融资需求相适应的科技金融体系。",
            "2026-10-21 18:26:13",
        ),
        (
            "34301430",
            "中办国办：健全科技成果转化、创业投资等方面尽职免责机制",
            "中办国办。《意见》提出，完善创新激励和评价政策。健全创新活动全链条政策体系，"
            "落实科技创新税收优惠等政策。健全科技成果转化、创业投资等方面尽职免责机制。",
            "2026-10-21 18:34:04",
        ),
        (
            "34301412",
            "中办国办：开展颠覆性技术挖掘甄别，加快新能源、新材料、航空航天等战略性新兴产业发展",
            "中办国办：开展颠覆性技术挖掘甄别。《意见》提出，以原创性颠覆性科技创新培育壮大"
            "新兴产业和未来产业。加强基础理论研究和底层技术研发。",
            "2026-10-21 18:21:49",
        ),
    ]
    return [
        replace(
            _item(key, title, description, seendate=seen),
            url=f"https://www.thepaper.cn/newsDetail_forward_{key}",
        )
        for key, title, description, seen in rows
    ]


def test_real_anonymous_policy_clauses_are_one_event(policy_clauses):
    picked = _dedupe_by_story(policy_clauses, max_count=10)
    assert [item.url for item in picked] == [
        "https://www.thepaper.cn/newsDetail_forward_34301258"
    ]


def test_policy_dedupe_fills_limit_with_independent_event(policy_clauses):
    other = _item("earthquake", "南太平洋发生强震，多地发布海啸预警", "震中附近居民撤离。")
    picked = _dedupe_by_story([*policy_clauses, other], max_count=2)
    assert [item.url for item in picked] == [
        "https://www.thepaper.cn/newsDetail_forward_34301258",
        "https://example.com/earthquake",
    ]


@pytest.mark.parametrize("suffix", ["意见", "通知", "管理办法", "实施方案"])
def test_full_policy_name_matches_different_clause_reports(suffix):
    name = f"关于促进科技成果转化的{suffix}"
    items = [
        _item("funding", "中办国办：设立研发专项资金", f"中办国办印发《{name}》，支持基础研究。"),
        _item(
            "licensing",
            "科研成果许可机制迎来调整",
            "高校科研院所可先使用后付费。",
            content=f"中共中央办公厅、国务院办公厅印发《{name}》。",
            domain="news.cn",
            source="新华社",
        ),
    ]
    assert [item.url for item in _dedupe_by_story(items, max_count=10)] == [
        "https://example.com/funding"
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("关于促进科技成果转化的意见", "关于加强科研诚信建设的意见"),
        ("关于支持AI科研平台的意见", "关于支持AI科研平台的通知"),
    ],
)
def test_distinct_names_survive_identical_vague_titles(first, second):
    items = [
        _item("first", "中办国办：科技创新政策正式发布", f"中办国办印发《{first}》。"),
        _item("second", "中办国办：科技创新政策正式发布", f"中办国办印发《{second}》。"),
    ]
    assert [item.url for item in _dedupe_by_story(items, max_count=10)] == [
        "https://example.com/first", "https://example.com/second"
    ]


def test_distinct_names_survive_shared_english_entities():
    items = [
        _item("research", "科研合作机制调整", "科技部印发《关于科研合作的意见》。涉及OpenAI Microsoft NVIDIA。"),
        _item("insurance", "科技保险政策出台", "科技部印发《关于科技保险的意见》。涉及OpenAI Microsoft NVIDIA。"),
    ]
    assert [item.url for item in _dedupe_by_story(items, max_count=10)] == [
        "https://example.com/research", "https://example.com/insurance"
    ]


def test_same_document_label_from_different_issuers_is_not_one_release():
    items = [
        _item("ministry", "科技创新扶持政策发布", "科技部印发《关于支持科技创新的意见》。"),
        _item("province", "科技创新扶持政策发布", "广东省人民政府印发《关于支持科技创新的意见》。"),
    ]
    assert [item.url for item in _dedupe_by_story(items, max_count=10)] == [
        "https://example.com/ministry", "https://example.com/province"
    ]


@pytest.mark.parametrize("reverse", [False, True])
def test_concrete_execution_is_not_the_policy_release(reverse):
    items = [
        _item(
            "release", "中办国办：加强科研项目资金支持",
            "中办国办印发《关于促进科技成果转化的意见》，要求加强科研项目资金支持。",
        ),
        _item(
            "execution", "北京首批科研项目资金已拨付，科技成果转化项目落地",
            "北京落实中办国办《关于促进科技成果转化的意见》，首批资金已拨付。"
            "要求加强科研项目资金支持。",
        ),
    ]
    if reverse:
        items.reverse()
    assert {item.url for item in _dedupe_by_story(items, max_count=10)} == {
        "https://example.com/release", "https://example.com/execution"
    }


@pytest.mark.parametrize(
    "change",
    [
        {"seendate": None},
        {"seendate": "not-a-date"},
        {"seendate": "2026-10-21"},
        {"seendate": "2026-10-22 18:20:25"},
        {"seendate": "2026-10-21 22:20:25"},
        {"source": "其他媒体", "domain": "other.example"},
        {"title": "科技部：推动国家自然科学基金试点向民营企业开放"},
        {"title": "推动国家自然科学基金试点向民营企业开放", "description": "《意见》提出，支持科研创新。"},
        {"description": "有关部门交换意见，支持科技成果转化。"},
    ],
)
def test_anonymous_policy_requires_corroborating_evidence(policy_clauses, change):
    other = replace(policy_clauses[2], **change)
    picked = _dedupe_by_story([policy_clauses[0], other], max_count=10)
    assert [item.url for item in picked] == [
        "https://www.thepaper.cn/newsDetail_forward_34301258",
        "https://www.thepaper.cn/newsDetail_forward_34301415",
    ]


def test_anonymous_non_technology_opinions_are_not_grouped_by_issuer():
    items = [
        _item("housing", "中办国办：健全住房保障体系", "《意见》提出，完善住房保障政策。"),
        _item("health", "中办国办：提高基层医疗服务水平", "《意见》提出，完善基层医疗体系。"),
    ]
    assert [item.url for item in _dedupe_by_story(items, max_count=10)] == [
        "https://example.com/housing", "https://example.com/health"
    ]


@pytest.mark.parametrize("reverse", [False, True])
def test_unambiguous_named_release_can_anchor_anonymous_clauses(policy_clauses, reverse):
    named = _item(
        "named", "中办国办：研发激励机制调整",
        "中共中央办公厅、国务院办公厅印发《关于促进科技创新和产业创新深度融合的意见》。",
    )
    items = [named, *policy_clauses]
    if reverse:
        items.reverse()
    assert len(_dedupe_by_story(items, max_count=10)) == 1


def test_anonymous_clause_does_not_bridge_two_named_documents(policy_clauses):
    items = [
        policy_clauses[0],
        _item("research", "中办国办：科研协作政策发布", "中办国办印发《关于科研协作的意见》。"),
        _item("insurance", "中办国办：科技保险政策发布", "中办国办印发《关于科技保险的意见》。"),
    ]
    assert [item.url for item in _dedupe_by_story(items, max_count=10)] == [
        "https://www.thepaper.cn/newsDetail_forward_34301258",
        "https://example.com/research",
        "https://example.com/insurance",
    ]


def test_equivalent_china_publication_dates_accept_offset_timestamps(policy_clauses):
    items = [
        replace(policy_clauses[0], seendate="2026-10-21T00:10:00+08:00"),
        replace(policy_clauses[2], seendate="2026-10-20T16:20:00Z"),
    ]
    assert len(_dedupe_by_story(items, max_count=10)) == 1
