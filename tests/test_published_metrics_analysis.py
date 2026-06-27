from __future__ import annotations

import csv
from pathlib import Path

from typer.testing import CliRunner

import apps.cli as cli
from src.analytics.published_metrics import (
    analyze_published_metrics,
    render_published_metrics_analysis,
)


def _write_latest_metrics(base: Path, rows: list[dict[str, object]]) -> None:
    analytics = base / "data" / "analytics"
    analytics.mkdir(parents=True)
    path = analytics / "published_metrics_latest.csv"
    fieldnames = ["id", "captured_at", "title", "url", "published_at", "likes", "comments", "favorites", "raw"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_analyze_published_metrics_recommends_strong_categories(tmp_path: Path):
    _write_latest_metrics(
        tmp_path,
        [
            {
                "id": "1",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "俄乌冲突最新动态",
                "published_at": "2026-06-25",
                "likes": 2,
                "comments": 5,
                "favorites": 1,
                "raw": '{"views":120,"shares":2}',
            },
            {
                "id": "2",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "英伟达H200芯片受阻",
                "published_at": "2026-06-25",
                "likes": 4,
                "comments": 1,
                "favorites": 0,
                "raw": '{"views":80,"shares":0}',
            },
            {
                "id": "3",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "普通公司会议召开",
                "published_at": "2026-06-25",
                "likes": 0,
                "comments": 0,
                "favorites": 0,
                "raw": '{"views":5,"shares":0}',
            },
        ],
    )

    report = analyze_published_metrics(base=tmp_path / "data")
    text = render_published_metrics_analysis(report)

    assert report.total_posts == 3
    assert report.total_views == 205
    assert report.recommendations[0].category == "国际冲突/外交安全"
    assert any(item.category == "硬科技/芯片/AI" for item in report.recommendations)
    assert "建议发布比例" in text
    assert "俄乌冲突最新动态" in text


def test_analyze_published_metrics_marks_small_samples_as_weak_signal(tmp_path: Path):
    _write_latest_metrics(
        tmp_path,
        [
            {
                "id": "1",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "生成式AI逼资深白领",
                "published_at": "2026-06-27",
                "likes": 0,
                "comments": 0,
                "favorites": 0,
                "raw": '{"views":3,"shares":0}',
            }
        ],
    )

    report = analyze_published_metrics(base=tmp_path / "data")

    assert report.signal_level == "弱信号"
    assert "弱信号" in render_published_metrics_analysis(report)


def test_analyze_published_metrics_single_category_uses_full_ratio(tmp_path: Path):
    _write_latest_metrics(
        tmp_path,
        [
            {
                "id": "1",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "联合国指控以色列在加沙实施种族灭绝",
                "published_at": "2026-06-25",
                "likes": 2,
                "comments": 5,
                "favorites": 1,
                "raw": '{"views":120,"shares":0}',
            }
        ],
    )

    report = analyze_published_metrics(base=tmp_path / "data")

    assert report.recommendations[0].ratio == 100


def test_analyze_published_metrics_caps_small_sample_categories(tmp_path: Path):
    rows = []
    for idx in range(3):
        rows.append(
            {
                "id": f"culture-{idx}",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": f"apex游戏封禁争议{idx}",
                "published_at": "2026-06-25",
                "likes": 20,
                "comments": 5,
                "favorites": 2,
                "raw": '{"views":300,"shares":1}',
            }
        )
    for idx in range(30):
        rows.append(
            {
                "id": f"world-{idx}",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": f"俄乌冲突最新动态{idx}",
                "published_at": "2026-06-25",
                "likes": 1,
                "comments": 1,
                "favorites": 0,
                "raw": '{"views":80,"shares":0}',
            }
        )
    _write_latest_metrics(tmp_path, rows)

    report = analyze_published_metrics(base=tmp_path / "data")
    ratios = {item.category: item.ratio for item in report.recommendations}

    assert ratios["争议文化/体育/品牌"] <= 20
    assert ratios["国际冲突/外交安全"] >= 80


def test_analyze_published_metrics_excludes_other_from_recommendations_when_possible(tmp_path: Path):
    _write_latest_metrics(
        tmp_path,
        [
            {
                "id": "world",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "俄乌冲突最新动态",
                "published_at": "2026-06-25",
                "likes": 1,
                "comments": 1,
                "favorites": 0,
                "raw": '{"views":80,"shares":0}',
            },
            {
                "id": "other",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "普通标题没有明确方向",
                "published_at": "2026-06-25",
                "likes": 20,
                "comments": 5,
                "favorites": 2,
                "raw": '{"views":300,"shares":1}',
            },
        ],
    )

    report = analyze_published_metrics(base=tmp_path / "data")

    assert "其他" not in {item.category for item in report.recommendations}


def test_cli_analyze_metrics_prints_local_recommendations(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    _write_latest_metrics(
        tmp_path,
        [
            {
                "id": "1",
                "captured_at": "2026-06-27T01:00:00Z",
                "title": "联合国指控以色列在加沙实施种族灭绝",
                "published_at": "2026-06-25",
                "likes": 2,
                "comments": 5,
                "favorites": 1,
                "raw": '{"views":120,"shares":0}',
            }
        ],
    )

    result = CliRunner().invoke(cli.app, ["analyze-metrics"])

    assert result.exit_code == 0
    assert "发布方向分析" in result.output
    assert "国际冲突/外交安全" in result.output
