"""Read-only source diagnostics, separate from editorial selection and history."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from src.ai_digest.collect import fetch_ai_digest_source
from src.ai_digest.rank import ai_update_effective_published_datetime
from src.ai_digest.sources import default_ai_digest_sources, resolve_ai_digest_sources
from src.news import daily_news
from src.news.topics import DEFAULT_DAILY_NEWS_PROMPT
from .registry import SourceRegistry
from .service import UnifiedNewsSourceService


LABELS = {
    'success': '有近期材料', 'stale': '可达但无近期消息', 'empty': '可达但未解析到条目',
    'missing_date': '可达但缺少日期', 'future_dates': '日期晚于当前时间',
    'rate_limited': '接口限流', 'unauthorized': '权限或认证失败', 'not_found': '地址不存在',
    'timeout': '请求超时', 'http_error': 'HTTP 错误', 'api_error': '接口请求失败',
    'local_service_unavailable': '本地服务未连接',
    'parse_error': '响应解析失败', 'not_configured': '未配置密钥',
    'disabled': '未启用', 'not_selected': '未纳入采集配置', 'not_checked': '尚未检测',
}
ACTIONS = {
    'success': '仍需经过热度、正文核验及历史查重才能入稿。',
    'stale': '连接正常；保留此来源等待新公告，不要扩大 AI 发布日期窗口。',
    'empty': '检查网页是否为动态页面、订阅流是否为空或解析器是否变化。',
    'missing_date': '核查文章原始发布时间；不能使用抓取时间代替。',
    'future_dates': '检查原文日期及时区；未来日期不能用于当天发布。',
    'rate_limited': '等待接口限流恢复，降低访问频率或使用同厂商的官方订阅流。',
    'unauthorized': '检查接口申请权限、API Key 或登录状态。',
    'not_found': '核对官方新地址，更新对应来源配置。',
    'timeout': '检查代理、DNS 和目标站连接；不要通过扩大日期窗口掩盖超时。',
    'http_error': '检查目标站状态、代理和接口响应。',
    'api_error': '检查接口返回的权限、参数和请求次数；本次错误不等于永久失效。',
    'local_service_unavailable': '按需启动对应本地服务，确认地址与端口后重新检测；检测不会自动启动服务。',
    'parse_error': '连接或返回格式可能变化，检查解析器与响应体大小限制。',
    'not_configured': '在本地配置新闻接口密钥后再检测。',
    'disabled': '此来源当前未启用；没有发起网络请求。',
    'not_selected': '检查 AI_DIGEST_PRIMARY/SOCIAL/AGGREGATOR_SOURCES 的来源名单。',
    'not_checked': '点击检查信源获取当前结果。',
}
API_KEYS = {
    'newsapi': ('NEWS_API_KEY', 'NEWSAPI_API_KEY'), 'gnews': ('GNEWS_API_KEY', 'GNEWS_TOKEN'),
    'juhe': ('JUHE_NEWS_APPKEY', 'JUHE_NEWS_KEY', 'JUHE_TOUTIAO_APPKEY', 'JUHE_APPKEY', 'JUHE_FINANCE_NEWS_APPKEY', 'JUHE_FINANCE_APPKEY'),
    'newsdata': ('NEWSDATA_API_KEY',), 'thenewsapi': ('THENEWSAPI_TOKEN',),
    'alphavantage': ('ALPHAVANTAGE_API_KEY',), 'finnhub': ('FINNHUB_API_KEY',),
    'tianapi': ('TIANAPI_KEY', 'TIANAPI_API_KEY'),
}


def safe_url(value):
    parts = urlsplit(str(value or ''))
    host = parts.hostname or ''
    if ':' in host:
        host = f'[{host}]'
    try:
        port = f':{parts.port}' if parts.port else ''
    except ValueError:
        port = ''
    return urlunsplit((parts.scheme, host + port, parts.path, '', ''))


def safe_error(value, env):
    text = str(value)
    for key, secret in env.items():
        if re.search(r'KEY|TOKEN|SECRET|PASSWORD', key, re.I) and secret and len(str(secret)) >= 6:
            text = text.replace(str(secret), '[redacted]')
    text = re.sub(r'https?://[^\s<>\"\']+', lambda match: safe_url(match[0]), text)
    text = re.sub(r'(?i)(?:key|token|secret|password|authorization)\s*[=:]\s*[^\s,;]+', '[redacted]', text)
    text = re.sub(r'\b[a-fA-F0-9]{32,}\b', '[redacted]', text)
    return text[:400]


def _row(collection, name, url, tier, *, enabled=True, selected=True, configured=True, vendor=''):
    status = 'not_configured' if not configured else 'disabled' if not enabled else 'not_selected' if not selected else 'not_checked'
    return dict(collection=collection, source_name=name, source_url=safe_url(url), tier=tier, vendor=vendor,
                enabled=enabled, selected=selected, configured=configured, status=status,
                status_label=LABELS[status], action=ACTIONS[status], connection_status='unknown',
                item_count=0, dated_count=0, recent_count=None, elapsed_seconds=0.0,
                checked_at='', latest_published_at='', error='', diagnostic=False)


def _catalog(env, root):
    selected = {s.name: s for s in resolve_ai_digest_sources(env)}
    all_env = {k: v for k, v in env.items() if k not in {
        'AI_DIGEST_PRIMARY_SOURCES', 'AI_DIGEST_SOCIAL_SOURCES', 'AI_DIGEST_AGGREGATOR_SOURCES'}}
    available = {s.name: s for s in default_ai_digest_sources()}
    available.update({s.name: s for s in resolve_ai_digest_sources(all_env)})
    rows, specs = [], {}
    for name, source in available.items():
        source = selected.get(name, source)
        row = _row('ai_digest', name, source.url, source.tier, enabled=source.enabled,
                   selected=name in selected, vendor=source.vendor)
        rows.append(row)
        specs[('ai_digest', name)] = ('ai', source)
    public = {'google_rss': daily_news._google_news_rss_base_url(),
              'google_rss_cn': daily_news._google_news_rss_base_url(),
              'bbc_rss': 'https://feeds.bbci.co.uk/news/rss.xml',
              'hotnews': env.get('HOTNEWS_BASE_URL') or daily_news.HOTNEWS_BASE_URL}
    for name in (*API_KEYS, *public):
        path = root / ('docs/news_api-key.md' if name == 'newsapi' else
                       f'docs/{name}_api-key.md' if name in {'juhe', 'gnews'} else 'docs/news_sources_api-key.md')
        if name not in {'newsapi', 'gnews', 'juhe'} and env.get('NEWS_SOURCES_CONFIG_FILE'):
            path = Path(env['NEWS_SOURCES_CONFIG_FILE'])
            if not path.is_absolute():
                path = root / path
        cfg = daily_news._parse_kv_file(path)
        configured = name in public or any(env.get(k) for k in API_KEYS.get(name, ()))
        if not configured:
            aliases = ('api_key', 'apikey', 'appkey', 'news_appkey', 'finance_appkey') if name in {'newsapi', 'gnews', 'juhe'} else (f'{name}_api_key', f'{name}_key', f'{name}_token')
            configured = any(cfg.get(k) for k in aliases)
        row = _row('daily_news', name, public.get(name, ''), 'public_feed' if name in public else 'news_api', configured=configured)
        rows.append(row)
        specs[('daily_news', name)] = ('news', name)
    registry_path = Path(env.get('NEWS_SOURCE_REGISTRY') or root / 'config/news_sources.json')
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    if registry_path.exists():
        registry = SourceRegistry.load(registry_path)
        for spec in registry.specs:
            if spec.adapter != 'rss':
                continue
            name = f'rss:{spec.source_id}'
            rows.append(_row('daily_news', name, spec.source_url, 'native_rss', enabled=spec.enabled, vendor=spec.source_name))
            specs[('daily_news', name)] = ('rss', spec)
    return rows, specs


def source_catalog(*, env=None, root=Path('.')):
    return _catalog(dict(os.environ if env is None else env), Path(root))[0]


def _error_status(exc, source_url=''):
    code = getattr(exc, 'code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
    match = re.search(r'HTTP(?: Error)?\s*[:=]?\s*(\d{3})', str(exc), re.I)
    code = code or (int(match[1]) if match else None)
    if code == 429:
        return 'rate_limited'
    if code in {401, 403}:
        return 'unauthorized'
    if code == 404:
        return 'not_found'
    if code:
        return 'http_error'
    if urlsplit(source_url).hostname in {'127.0.0.1', 'localhost', '::1'} and re.search(
        r'failed to connect|could not connect|connection refused|actively refused|winerror 10061', str(exc), re.I
    ):
        return 'local_service_unavailable'
    if 'timed out' in str(exc).lower() or 'timeout' in str(exc).lower() or isinstance(exc, TimeoutError):
        return 'timeout'
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return 'parse_error'
    return 'api_error'


def _item_dates(items, kind):
    dates = []
    for item in items:
        if kind == 'ai':
            stamp = ai_update_effective_published_datetime(item)
        else:
            stamp = daily_news._parse_seendate_utc(str(getattr(item, 'seendate', None) or getattr(item, 'published_at', '') or ''))
        if stamp is not None:
            raw = str(getattr(item, 'published_at', None) or getattr(item, 'seendate', '') or '')
            dates.append((stamp.astimezone(timezone.utc), raw))
    return dates


def run_source_diagnostics(collection='all', *, root=Path('.'), env=None,
                           keywords=DEFAULT_DAILY_NEWS_PROMPT, max_age_days=2,
                           now=None, progress=None, timeout_s=6.0):
    if collection not in {'all', 'daily_news', 'ai_digest'}:
        raise ValueError('collection must be all, daily_news, or ai_digest')
    if not 1 <= int(max_age_days) <= 14:
        raise ValueError('max_age_days must be between 1 and 14')
    root = Path(root).resolve()
    env = dict(os.environ if env is None else env)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = now.astimezone(timezone(timedelta(hours=8)))
    start = (local - timedelta(days=max_age_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    rows, specs = _catalog(env, root)
    rows = [r for r in rows if collection == 'all' or r['collection'] == collection]
    active = [r for r in rows if r['status'] == 'not_checked']
    rss_service = UnifiedNewsSourceService(SourceRegistry(()), snapshot_dir=root / 'data/source_snapshots')

    def probe(row):
        began = time.monotonic()
        result = dict(row, diagnostic=True, checked_at=datetime.now(timezone.utc).isoformat())
        kind, spec = specs[(row['collection'], row['source_name'])]
        try:
            if kind == 'ai':
                items = fetch_ai_digest_source(spec, timeout_s=timeout_s, max_age_days=max_age_days)
            elif kind == 'rss':
                items, _ = rss_service._fetch_rss(spec, timeout_s)
            else:
                fetched = daily_news._fetch_news_provider(spec, queries=[keywords or '科技'], default_queries=[keywords or '科技'],
                    hint_query='', aggregate_empty_prompt=False, max_records=5,
                    from_iso=start.isoformat(), to_iso=now.isoformat(), start_dt=start, end_dt=now,
                    timeout_s=timeout_s, exhaustive_sources=True, auto_provider_selection=True,
                    manual_materials_file='', deadline=time.monotonic() + 45, retain_raw_dates=True)
                if fetched.error is not None:
                    raise fetched.error
                items = fetched.candidates
            dates = _item_dates(items, kind)
            recent = sum(start <= stamp <= now for stamp, _ in dates)
            status = 'empty' if not items else 'missing_date' if not dates else 'success' if recent else 'future_dates' if all(d > now for d, _ in dates) else 'stale'
            latest = max(dates, key=lambda pair: pair[0]) if dates else None
            latest_label = (latest[1] if re.fullmatch(r'\d{4}-\d{2}-\d{2}', latest[1]) else latest[0].isoformat()) if latest else ''
            result.update(connection_status='reachable', status=status, item_count=len(items),
                          dated_count=len(dates), recent_count=recent,
                          latest_published_at=latest_label)
        except Exception as exc:
            result.update(status=_error_status(exc, row['source_url']), connection_status='failed', error=safe_error(exc, env))
        result.update(elapsed_seconds=round(time.monotonic() - began, 3),
                      status_label=LABELS[result['status']], action=ACTIONS[result['status']])
        return result

    started = time.monotonic()
    by_key = {(r['collection'], r['source_name']): r for r in rows}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='source-diagnostics') as pool:
        tasks = {pool.submit(probe, row): row for row in active}
        for done_count, future in enumerate(as_completed(tasks), 1):
            row = future.result()
            by_key[(row['collection'], row['source_name'])] = row
            if progress:
                progress(f"{done_count}/{len(active)} {row['source_name']}：{row['status_label']}")
    report = dict(version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                  max_age_days=max_age_days, elapsed_seconds=round(time.monotonic() - started, 3),
                  rows=list(by_key.values()))
    directory = root / 'data/source_health'
    directory.mkdir(parents=True, exist_ok=True)
    for group in ('daily_news', 'ai_digest'):
        if collection not in {'all', group}:
            continue
        target = directory / f'diagnostics_{group}.json'
        temporary = directory / f'.{target.name}.{uuid4().hex}.tmp'
        try:
            temporary.write_text(json.dumps({**report, 'rows': [r for r in report['rows'] if r['collection'] == group]}, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return report


def diagnostic_dashboard(*, root=Path('.'), env=None):
    rows = source_catalog(root=root, env=env)
    checked = {}
    for group in ('daily_news', 'ai_digest'):
        path = Path(root) / 'data/source_health' / f'diagnostics_{group}.json'
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            for row in payload.get('rows', []):
                checked[(group, row['source_name'])] = row
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for index, row in enumerate(rows):
        old = checked.get((row['collection'], row['source_name']))
        if row['status'] == 'not_checked' and old and old.get('source_url') == row['source_url']:
            rows[index] = {**row, **old}
    return {'rows': rows}
