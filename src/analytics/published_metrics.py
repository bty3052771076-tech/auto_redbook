from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.storage.files import DATA_ROOT, published_metrics_paths


@dataclass(frozen=True)
class AnalyzedMetric:
    title: str
    published_at: str = ""
    captured_at: str = ""
    likes: int = 0
    comments: int = 0
    favorites: int = 0
    views: int = 0
    shares: int = 0
    category: str = "其他"

    @property
    def engagement(self) -> int:
        return self.likes + self.comments + self.favorites


@dataclass(frozen=True)
class CategorySummary:
    category: str
    count: int = 0
    views: int = 0
    likes: int = 0
    comments: int = 0
    favorites: int = 0
    shares: int = 0
    nonzero_engagement_count: int = 0
    score: float = 0.0
    top_titles: tuple[str, ...] = ()

    @property
    def engagement(self) -> int:
        return self.likes + self.comments + self.favorites

    @property
    def avg_views(self) -> float:
        return self.views / self.count if self.count else 0.0

    @property
    def avg_engagement(self) -> float:
        return self.engagement / self.count if self.count else 0.0

    @property
    def nonzero_engagement_rate(self) -> float:
        return self.nonzero_engagement_count / self.count if self.count else 0.0


@dataclass(frozen=True)
class DirectionRecommendation:
    category: str
    ratio: int
    reason: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishedMetricsAnalysis:
    total_posts: int
    total_views: int
    total_likes: int
    total_comments: int
    total_favorites: int
    total_shares: int
    nonzero_engagement_count: int
    signal_level: str
    published_range: tuple[str, str] = ("", "")
    captured_range: tuple[str, str] = ("", "")
    category_summaries: tuple[CategorySummary, ...] = ()
    recommendations: tuple[DirectionRecommendation, ...] = ()
    top_by_engagement: tuple[AnalyzedMetric, ...] = ()
    top_by_views: tuple[AnalyzedMetric, ...] = ()
    warnings: tuple[str, ...] = ()


CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "国际冲突/外交安全",
        (
            "特朗普",
            "美国",
            "欧盟",
            "德国",
            "法国",
            "英国",
            "俄",
            "乌",
            "俄乌",
            "伊朗",
            "以色列",
            "加沙",
            "委内瑞拉",
            "格陵兰",
            "外交",
            "制裁",
            "禁令",
            "战争",
            "冲突",
            "军",
            "北约",
            "联合国",
            "总统",
            "政府",
            "安全",
            "政治",
        ),
    ),
    (
        "硬科技/芯片/AI",
        (
            "AI",
            "人工智能",
            "生成式",
            "芯片",
            "半导体",
            "英伟达",
            "H200",
            "OpenAI",
            "算力",
            "数据中心",
            "机器人",
            "量子",
            "卫星",
            "航天",
            "无人机",
            "OLED",
            "电池",
            "锂",
            "谷歌",
            "苹果",
            "微软",
            "三星",
            "小米",
            "华为",
            "自动驾驶",
            "新能源",
            "Sakana",
        ),
    ),
    (
        "社会民生/公共事件",
        (
            "父亲",
            "四胞胎",
            "去世",
            "事故",
            "警方",
            "法院",
            "罪犯",
            "囚犯",
            "救援",
            "灾害",
            "民生",
            "就业",
            "教育",
            "学校",
            "学生",
            "医院",
            "医生",
            "养老",
            "城市",
            "交通",
            "居民",
            "儿童",
            "家庭",
            "社会",
        ),
    ),
    (
        "争议文化/体育/品牌",
        (
            "apex",
            "游戏",
            "封禁",
            "Nike",
            "谷爱凌",
            "宝可梦",
            "电影",
            "动画",
            "音乐",
            "香港",
            "体育",
            "比赛",
            "新秀",
            "艺术",
            "文化",
            "旅游",
            "演出",
            "综艺",
            "动漫",
            "品牌",
        ),
    ),
    (
        "财经产业/公司",
        (
            "财经",
            "经营",
            "现金流",
            "公司",
            "企业",
            "市场",
            "贸易",
            "投资",
            "融资",
            "并购",
            "上市",
            "价格",
            "关税",
            "供应链",
            "物流",
            "货运",
            "产业",
            "经济",
            "出口",
            "进口",
            "订单",
            "制造",
            "银行",
            "债券",
            "基金",
            "保险",
            "营收",
            "利润",
            "股",
        ),
    ),
    (
        "健康科学/环境",
        (
            "健康",
            "医疗",
            "医学",
            "药",
            "疫苗",
            "疾病",
            "癌",
            "感染",
            "护理",
            "心理",
            "HPV",
            "微塑料",
            "穿山甲",
            "生态",
            "环保",
            "气候",
            "碳",
            "彗星",
            "科学家",
        ),
    ),
)


def _to_int(value: Any) -> int:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return 0


def _raw_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metric_csv_path(base: Path = DATA_ROOT) -> Path:
    paths = published_metrics_paths(base)
    if paths["latest_csv"].exists():
        return paths["latest_csv"]
    return paths["csv"]


def _category_for_title(title: str) -> str:
    lower = (title or "").lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in lower for keyword in keywords):
            return category
    return "其他"


def load_analyzed_metrics(base: Path = DATA_ROOT, *, limit: int = 0) -> list[AnalyzedMetric]:
    path = _metric_csv_path(base)
    if not path.exists():
        return []

    out: list[AnalyzedMetric] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = _raw_dict(row.get("raw"))
            title = str(row.get("title") or "").strip() or "(无标题)"
            out.append(
                AnalyzedMetric(
                    title=title,
                    published_at=str(row.get("published_at") or ""),
                    captured_at=str(row.get("captured_at") or ""),
                    likes=_to_int(row.get("likes")),
                    comments=_to_int(row.get("comments")),
                    favorites=_to_int(row.get("favorites")),
                    views=_to_int(raw.get("views")),
                    shares=_to_int(raw.get("shares")),
                    category=_category_for_title(title),
                )
            )
            if limit and len(out) >= limit:
                break
    return out


def _date_range(values: list[str]) -> tuple[str, str]:
    clean = sorted(value for value in values if value)
    return (clean[0], clean[-1]) if clean else ("", "")


def _days_old(published_at: str, today: date) -> int:
    try:
        published = datetime.strptime(published_at, "%Y-%m-%d").date()
    except ValueError:
        return 1
    return max(1, (today - published).days + 1)


def _category_score(summary: CategorySummary, *, total_posts: int) -> float:
    confidence = min(1.0, math.sqrt(summary.count / 10.0))
    base = summary.avg_views + summary.avg_engagement * 45.0 + summary.nonzero_engagement_rate * 25.0
    breadth = math.log1p(summary.count) * 2.0
    return (base + breadth) * (0.45 + 0.55 * confidence)


def _build_category_summaries(metrics: list[AnalyzedMetric]) -> tuple[CategorySummary, ...]:
    grouped: dict[str, list[AnalyzedMetric]] = {}
    for item in metrics:
        grouped.setdefault(item.category, []).append(item)

    summaries: list[CategorySummary] = []
    for category, items in grouped.items():
        top = sorted(items, key=lambda x: (x.views, x.engagement), reverse=True)[:5]
        draft = CategorySummary(
            category=category,
            count=len(items),
            views=sum(item.views for item in items),
            likes=sum(item.likes for item in items),
            comments=sum(item.comments for item in items),
            favorites=sum(item.favorites for item in items),
            shares=sum(item.shares for item in items),
            nonzero_engagement_count=sum(1 for item in items if item.engagement > 0),
            top_titles=tuple(item.title for item in top),
        )
        summaries.append(
            CategorySummary(
                category=draft.category,
                count=draft.count,
                views=draft.views,
                likes=draft.likes,
                comments=draft.comments,
                favorites=draft.favorites,
                shares=draft.shares,
                nonzero_engagement_count=draft.nonzero_engagement_count,
                score=_category_score(draft, total_posts=len(metrics)),
                top_titles=draft.top_titles,
            )
        )
    return tuple(sorted(summaries, key=lambda x: x.score, reverse=True))


def _normalize_ratios(summaries: tuple[CategorySummary, ...], *, top_n: int) -> dict[str, int]:
    selected = [item for item in summaries if item.score > 0][: max(1, top_n)]
    if not selected:
        return {}
    if len(selected) == 1:
        return {selected[0].category: 100}

    total_score = sum(item.score for item in selected) or 1.0
    raw = {item.category: max(5, int(round((item.score / total_score) * 100 / 5) * 5)) for item in selected}

    def _ratio_cap(summary: CategorySummary) -> int:
        if summary.count < 5:
            return 20
        if summary.count < 15:
            return 25
        if summary.count < 30:
            return 30
        return 80 if len(selected) == 2 else 40

    caps = {item.category: _ratio_cap(item) for item in selected}
    capped = {category: min(caps[category], value) for category, value in raw.items()}
    diff = 100 - sum(capped.values())
    while diff != 0 and capped:
        ordered = sorted(capped, key=lambda c: raw[c], reverse=(diff > 0))
        changed = False
        for category in ordered:
            if diff > 0 and capped[category] < caps[category]:
                capped[category] += 5
                diff -= 5
                changed = True
            elif diff < 0 and capped[category] > 5:
                capped[category] -= 5
                diff += 5
                changed = True
            if diff == 0:
                break
        if not changed:
            break
    return capped


def _recommendation_reason(summary: CategorySummary) -> str:
    return (
        f"平均浏览 {summary.avg_views:.1f}，平均互动 {summary.avg_engagement:.2f}，"
        f"有互动占比 {summary.nonzero_engagement_rate:.0%}。"
    )


def _build_recommendations(
    summaries: tuple[CategorySummary, ...],
    *,
    top_n: int,
) -> tuple[DirectionRecommendation, ...]:
    recommendation_candidates = tuple(item for item in summaries if item.category != "其他") or summaries
    ratios = _normalize_ratios(recommendation_candidates, top_n=top_n)
    out: list[DirectionRecommendation] = []
    for summary in recommendation_candidates:
        if summary.category not in ratios:
            continue
        out.append(
            DirectionRecommendation(
                category=summary.category,
                ratio=ratios[summary.category],
                reason=_recommendation_reason(summary),
                examples=summary.top_titles[:3],
            )
        )
    return tuple(sorted(out, key=lambda item: item.ratio, reverse=True))


def _signal_level(metrics: list[AnalyzedMetric]) -> str:
    nonzero = sum(1 for item in metrics if item.engagement > 0)
    if len(metrics) < 30 or nonzero < 10:
        return "弱信号"
    if len(metrics) < 100 or nonzero < 30:
        return "中等信号"
    return "较强信号"


def analyze_published_metrics(
    *,
    base: Path = DATA_ROOT,
    today: date | None = None,
    top_n: int = 6,
) -> PublishedMetricsAnalysis:
    metrics = load_analyzed_metrics(base=base)
    today = today or date.today()
    warnings: list[str] = []
    if not metrics:
        return PublishedMetricsAnalysis(
            total_posts=0,
            total_views=0,
            total_likes=0,
            total_comments=0,
            total_favorites=0,
            total_shares=0,
            nonzero_engagement_count=0,
            signal_level="无数据",
            warnings=("未找到已发布数据，请先运行 update-metrics。",),
        )

    if _signal_level(metrics) == "弱信号":
        warnings.append("当前互动样本较少，建议把结果作为选题测试方向，不要当作稳定结论。")

    summaries = _build_category_summaries(metrics)
    recommendations = _build_recommendations(summaries, top_n=top_n)
    top_by_engagement = sorted(metrics, key=lambda x: (x.engagement, x.views), reverse=True)[:10]
    top_by_views = sorted(metrics, key=lambda x: (x.views / _days_old(x.published_at, today), x.engagement), reverse=True)[
        :10
    ]

    return PublishedMetricsAnalysis(
        total_posts=len(metrics),
        total_views=sum(item.views for item in metrics),
        total_likes=sum(item.likes for item in metrics),
        total_comments=sum(item.comments for item in metrics),
        total_favorites=sum(item.favorites for item in metrics),
        total_shares=sum(item.shares for item in metrics),
        nonzero_engagement_count=sum(1 for item in metrics if item.engagement > 0),
        signal_level=_signal_level(metrics),
        published_range=_date_range([item.published_at for item in metrics]),
        captured_range=_date_range([item.captured_at for item in metrics]),
        category_summaries=summaries,
        recommendations=recommendations,
        top_by_engagement=tuple(top_by_engagement),
        top_by_views=tuple(top_by_views),
        warnings=tuple(warnings),
    )


def render_published_metrics_analysis(report: PublishedMetricsAnalysis) -> str:
    lines = ["# 发布方向分析", ""]
    lines.append(
        f"数据量：{report.total_posts} 条；信号强度：{report.signal_level}；"
        f"总浏览：{report.total_views}；点赞/评论/收藏："
        f"{report.total_likes}/{report.total_comments}/{report.total_favorites}。"
    )
    if report.published_range != ("", ""):
        lines.append(f"发布时间范围：{report.published_range[0]} 至 {report.published_range[1]}。")
    for warning in report.warnings:
        lines.append(f"提示：{warning}")

    lines.extend(["", "## 建议发布比例"])
    if report.recommendations:
        for item in report.recommendations:
            examples = "；".join(item.examples) if item.examples else "暂无代表标题"
            lines.append(f"- {item.category}：{item.ratio}% | {item.reason}代表标题：{examples}")
    else:
        lines.append("- 暂无建议。请先同步更多已发布数据。")

    lines.extend(["", "## 分类表现"])
    for item in report.category_summaries:
        lines.append(
            f"- {item.category}：{item.count} 条，浏览 {item.views}，互动 {item.engagement}，"
            f"平均浏览 {item.avg_views:.1f}，平均互动 {item.avg_engagement:.2f}，"
            f"有互动占比 {item.nonzero_engagement_rate:.0%}。"
        )

    lines.extend(["", "## 高互动标题"])
    for item in report.top_by_engagement[:8]:
        lines.append(
            f"- {item.title} | {item.category} | 浏览 {item.views} | "
            f"互动 {item.engagement}（赞{item.likes}/评{item.comments}/藏{item.favorites}）"
        )

    lines.extend(["", "## 执行建议"])
    lines.append("- 每 10 条每日新闻中，优先按上方比例分配选题，并保留 1 条小样本高潜力方向做测试。")
    lines.append("- 标题建议使用“主体 + 动作 + 影响”，避免“出现进展”“发布报告”这类弱信息标题。")
    lines.append("- 泛 AI、普通公司会议、低公共影响海外本地新闻应减少，除非有明确冲突、数字或中国关联。")
    return "\n".join(lines)
