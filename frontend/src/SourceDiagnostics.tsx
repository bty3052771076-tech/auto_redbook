import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, ExternalLink, LoaderCircle, RefreshCw, Search } from "lucide-react";

type SourceRow = {
  collection: string; source_name: string; vendor: string; source_url: string; status: string;
  status_label: string; connection_status: string; action: string; item_count: number;
  dated_count: number; recent_count: number | null; elapsed_seconds: number;
  checked_at: string; latest_published_at: string; error: string;
};
type Check = { id: string; status: string; stage: string; message: string };
type Report = { rows: SourceRow[]; check?: Check | null };
type Props = { read: () => Promise<Report>; check: (request: Record<string, unknown>) => Promise<unknown> };
const active = new Set(["queued", "running", "waiting_user", "stopping"]);
const timeLabel = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}（仅日期）` : value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚未检测";

export function SourceDiagnostics({ read, check }: Props) {
  const [report, setReport] = useState<Report>({ rows: [] });
  const [scope, setScope] = useState("all"), [keywords, setKeywords] = useState("国际冲突 科技产业 社会民生 财经产业");
  const [days, setDays] = useState(2), [query, setQuery] = useState(""), [failedOnly, setFailedOnly] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const mounted = useRef(false), pending = useRef(false), readRef = useRef(read); readRef.current = read;
  const refresh = useCallback(async () => {
    try { const result = await readRef.current(); if (mounted.current) { setReport(result); setError(""); } }
    catch (cause) { if (mounted.current) setError(String(cause)); }
  }, []);
  useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false; }; }, [refresh]);
  const running = Boolean(report.check && active.has(report.check.status));
  useEffect(() => {
    if (!running) return;
    let disposed = false, timer: ReturnType<typeof setTimeout>;
    const tick = async () => { await refresh(); if (!disposed) timer = setTimeout(tick, 1500); };
    timer = setTimeout(tick, 1500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [running, refresh]);
  async function begin() {
    if (pending.current || running) return;
    pending.current = true; setBusy(true); setError("");
    try { await check({ kind: "check-sources", title: "信源检测", collection: scope, keywords, max_age_days: days }); await refresh(); }
    catch (cause) { if (mounted.current) setError(String(cause)); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  const scoped = report.rows.filter(row => scope === "all" || row.collection === scope);
  const rows = scoped.filter(row => (!failedOnly || row.connection_status === "failed") &&
    `${row.source_name} ${row.vendor} ${row.status_label} ${row.error}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="source-diagnostics" aria-label="信源检测">
    <div className="source-controls" data-tour="sources.scope">
      <label>检测范围<select value={scope} onChange={e => setScope(e.target.value)} disabled={busy || running}>
        <option value="all">全部信源</option><option value="daily_news">每日新闻</option><option value="ai_digest">每日AI讯息</option>
      </select></label>
      <label>新闻检索关键词<input value={keywords} maxLength={400} onChange={e => setKeywords(e.target.value)} disabled={busy || running}/></label>
      <label>近期窗口（天）<input type="number" min={1} max={14} value={days} onChange={e => setDays(Math.max(1, Math.min(14, Number(e.target.value) || 2)))} disabled={busy || running}/></label>
    </div>
    <div className="source-toolbar" data-tour="sources.check">
      <button className="source-check-button" onClick={begin} disabled={busy || running}>
        {busy || running ? <LoaderCircle size={16} className="source-spinner"/> : <Activity size={16}/>}{busy || running ? "检测中" : "检查信源"}
      </button>
      <button onClick={refresh} aria-label="刷新信源状态"><RefreshCw size={16}/>刷新</button>
      <label className="source-search"><Search size={16}/><input aria-label="搜索信源" placeholder="搜索信源" value={query} onChange={e => setQuery(e.target.value)}/></label>
      <label className="source-checkbox"><input type="checkbox" checked={failedOnly} onChange={e => setFailedOnly(e.target.checked)}/>仅请求失败</label>
    </div>
    {error && <p role="alert" className="source-alert">{error}</p>}
    {report.check && <p role="status" className="source-check-status">{report.check.message || report.check.stage}{report.check.status === "failed" && " · 检测任务失败，下面保留上次记录"}</p>}
    <div className="source-summary"><span>目录 {scoped.length}</span><span>已检测 {scoped.filter(r => r.checked_at).length}</span>
      <span className="source-good">有近期材料 {scoped.filter(r => r.status === "success").length}</span>
      <span>无近期消息 {scoped.filter(r => r.status === "stale").length}</span>
      <span className="source-alert">请求失败 {scoped.filter(r => r.connection_status === "failed").length}</span></div>
    <div className="source-table-wrap" data-tour="sources.results"><table className="source-table"><thead><tr>
      <th>信源</th><th>检测状态</th><th>材料 / 有日期 / 近期</th><th>最后发布时间</th><th>耗时 / 检测时间</th><th>原因与处理建议</th>
    </tr></thead><tbody>{rows.map(row => <tr key={`${row.collection}:${row.source_name}`}>
      <td><strong>{row.vendor || row.source_name}</strong><small>{row.source_name}</small>
        {/^(https?):\/\//.test(row.source_url) && <a href={row.source_url} target="_blank" rel="noreferrer" aria-label={`打开 ${row.source_name}`}><ExternalLink size={13}/>信源地址</a>}</td>
      <td className={row.connection_status === "failed" ? "source-alert" : row.status === "success" ? "source-good" : ""}>{row.status_label}</td>
      <td>{row.checked_at ? `${row.item_count} / ${row.dated_count} / ${row.recent_count ?? "未知"}` : "尚未检测"}</td>
      <td>{row.latest_published_at ? timeLabel(row.latest_published_at) : "无已核验日期"}</td>
      <td>{row.checked_at ? `${row.elapsed_seconds.toFixed(1)} 秒` : "—"}<small>{timeLabel(row.checked_at)}</small></td>
      <td>{row.error && <div className="source-alert">{row.error}</div>}<div>{row.action}</div></td>
    </tr>)}</tbody></table></div>
    {!rows.length && <p className="source-empty">暂无匹配的信源</p>}
  </section>;
}
