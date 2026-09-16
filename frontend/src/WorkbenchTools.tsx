import { useEffect, useState } from "react";
import { Eye, Trash2, RefreshCw, Search, Save, ExternalLink, Download, BarChart3 } from "lucide-react";
import { api, dateLabel, download, type Job } from "./api";

type Actions = { submit: (r: Record<string, unknown>) => Promise<void>; onError: (s: string) => void };
type Scope = { draft_type: string; title_contains: string; limit: number };
type PreviewJob = Job & { deletion_scope?: Scope };

export function DeleteDrafts({ jobs, submit, onError }: Actions & { jobs: Job[] }) {
  const [scope, setScope] = useState<Scope>({ draft_type: "image", title_contains: "", limit: 10 });
  const [confirmation, setConfirmation] = useState("");
  const [previewLog, setPreviewLog] = useState("");
  const preview = (jobs as PreviewJob[]).find(j => j.kind === "delete-preview" && j.status === "completed"
    && Date.now() / 1000 - (j.ended_at || 0) <= 600
    && j.deletion_scope?.draft_type === scope.draft_type
    && j.deletion_scope?.title_contains === scope.title_contains.trim()
    && j.deletion_scope?.limit === scope.limit);
  useEffect(() => {
    let active = true;
    setPreviewLog("");
    if (preview) void api<Job>(`/jobs/${preview.id}`).then(job => {
      if (active) setPreviewLog(job.events?.map(e => e.message).join("\n") || "");
    }).catch(e => onError(String(e)));
    return () => { active = false; };
  }, [preview?.id]);
  const change = (value: Partial<Scope>) => { setScope({ ...scope, ...value }); setConfirmation(""); };
  const execute = async () => {
    try { await submit({ kind: "delete-drafts", ...scope, preview_id: preview?.id, confirmation }); setConfirmation(""); }
    catch (e) { onError(String(e)); }
  };
  return <section className="tool-surface" data-tour-page="delete">
    <div className="form-grid" data-tour="delete.filters">
      <label className="field">草稿类型<select value={scope.draft_type} onChange={e => change({ draft_type: e.target.value })}>
        <option value="image">图文</option><option value="video">视频</option><option value="article">长文</option><option value="all">所有类型</option>
      </select></label>
      <label className="field">标题包含<input value={scope.title_contains} maxLength={200} onChange={e => change({ title_contains: e.target.value })} /></label>
      <label className="field">最多删除数量（0 为全部）<input type="number" min={0} max={10000} value={scope.limit} onChange={e => change({ limit: Number(e.target.value) })} /></label>
    </div>
    <div className="toolbar" data-tour="delete.preview"><button onClick={() => submit({ kind: "delete-preview", ...scope }).catch(e => onError(String(e)))}><Eye size={16}/>预览平台草稿</button>
      <span role="status">{preview ? `预览完成 ${dateLabel(preview.ended_at)}` : "待预览"}</span></div>
    {previewLog && <pre className="analysis-report" aria-label="删除预览结果">{previewLog}</pre>}
    <div className="delete-confirmation" data-tour="delete.confirm">
      <h2>删除小红书平台草稿</h2><p>此操作删除平台中符合筛选条件的草稿，本地记录保留。删除前会重新读取平台列表。</p>
      <label className="field">输入“确认删除”<input autoComplete="off" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label>
      <button className="danger" disabled={!preview || confirmation !== "确认删除"} onClick={execute}><Trash2 size={16}/>确认删除平台草稿</button>
    </div>
  </section>;
}

type Source = { collection: string; source_name: string; source_url: string; status: string; item_count: number;
  dated_count: number; elapsed_seconds: number; error: string; checked_at: string };
export function SourceHealth({ submit, onError }: Actions) {
  const [rows, setRows] = useState<Source[]>([]), [query, setQuery] = useState(""), [collection, setCollection] = useState("all"),
    [keywords, setKeywords] = useState("科技"), [days, setDays] = useState(3), [sort, setSort] = useState("status");
  const refresh = () => api<{ rows: Source[] }>("/sources").then(r => setRows(r.rows)).catch(e => onError(String(e)));
  useEffect(() => { void refresh(); }, []);
  const filtered = rows.filter(r => (collection === "all" || r.collection === collection)
    && `${r.source_name} ${r.error} ${r.status}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a,b) => sort === "elapsed" ? b.elapsed_seconds-a.elapsed_seconds : sort === "items" ? b.item_count-a.item_count : a.status.localeCompare(b.status));
  return <section className="tool-surface" data-tour-page="sources">
    <div className="form-grid" data-tour="sources.scope">
      <label className="field">检查范围<select value={collection} onChange={e=>setCollection(e.target.value)}><option value="all">全部信源</option><option value="daily_news">每日新闻</option><option value="ai_digest">每日AI讯息</option></select></label>
      <label className="field">检索关键词<input value={keywords} onChange={e=>setKeywords(e.target.value)}/></label>
      <label className="field">回溯天数<input type="number" min={1} max={14} value={days} onChange={e=>setDays(Number(e.target.value))}/></label>
    </div>
    <div className="toolbar" data-tour="sources.check"><button className="primary" onClick={()=>submit({kind:"check-sources",collection,keywords,max_age_days:days}).catch(e=>onError(String(e)))}><RefreshCw size={16}/>检查信源</button>
      <button onClick={refresh}><RefreshCw size={16}/>刷新状态</button>
      <label className="search-input"><Search size={16}/><input aria-label="搜索信源" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <select aria-label="信源排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="status">按状态</option><option value="elapsed">耗时从高到低</option><option value="items">条数从高到低</option></select>
    </div>
    <div className="table-wrap" data-tour="sources.results"><table><thead><tr><th>信源</th><th>状态</th><th>材料 / 有日期</th><th>耗时</th><th>检查时间</th><th>错误</th></tr></thead><tbody>
      {filtered.map((r,i)=><tr key={i}><td>{/^https?:\/\//.test(r.source_url) ? <a href={r.source_url} target="_blank" rel="noreferrer">{r.source_name}<ExternalLink size={13}/></a> : r.source_name}</td>
        <td>{r.status}</td><td>{r.item_count} / {r.dated_count}</td><td>{r.elapsed_seconds.toFixed(1)} 秒</td><td>{dateLabel(r.checked_at)}</td><td className="source-error">{r.error || "—"}</td></tr>)}
    </tbody></table></div>{!filtered.length && <p>暂无匹配的信源检查结果</p>}
  </section>;
}

export function AnalysisReport({ submit, onError }: Actions) {
  const [report, setReport] = useState({text:"",captured_at:null as number|null});
  const refresh=()=>api<typeof report>("/analysis").then(setReport).catch(e=>onError(String(e)));
  useEffect(()=>{void refresh();},[]);
  return <section className="tool-surface" data-tour="metrics.analysis"><div className="section-heading"><h2>选题分析</h2><span>{dateLabel(report.captured_at)}</span></div>
    <div className="toolbar"><button onClick={()=>submit({kind:"analyze-metrics",top_n:6}).catch(e=>onError(String(e)))}><BarChart3 size={16}/>生成选题分析</button>
      <button onClick={refresh}><RefreshCw size={16}/>刷新报告</button><button disabled={!report.text} onClick={()=>download("选题分析.md",report.text)}><Download size={16}/>下载报告</button></div>
    <pre className="analysis-report">{report.text || "暂无分析报告"}</pre></section>;
}

type Configuration = {secrets:Record<string,boolean>;values:Record<string,string>};
export function LocalConfiguration({onError}: Pick<Actions,"onError">) {
  const [data,setData]=useState<Configuration>({secrets:{},values:{}}),[changes,setChanges]=useState<Record<string,string>>({}),[message,setMessage]=useState("");
  const refresh=()=>api<Configuration>("/configuration").then(d=>{setData(d);setChanges({});}).catch(e=>onError(String(e)));
  useEffect(()=>{void refresh();},[]);
  async function save(){try{setData(await api<Configuration>("/configuration","PUT",changes));setChanges({});setMessage("已保存到本机 .env.gui");}catch(e){onError(String(e));}}
  return <section className="tool-surface" data-tour-page="settings"><div className="section-heading"><h2>本机配置</h2><button onClick={refresh}><RefreshCw size={16}/>重新加载</button></div>
    <details data-tour="settings.credentials"><summary>模型与信源密钥</summary><div className="config-fields">{Object.entries(data.secrets).map(([key,configured])=><label className="field" key={key}>
      <span>{key}<small>{configured ? "已配置" : "未配置"}</small></span><input type="password" autoComplete="new-password" aria-label={key} placeholder="留空保留已有密钥" value={changes[key]||""} onChange={e=>setChanges({...changes,[key]:e.target.value})}/></label>)}</div></details>
    <details><summary>服务地址与生成参数</summary><div className="config-fields">{Object.entries(data.values).map(([key,value])=><label className="field" key={key}>{key}<input value={changes[key]??value} onChange={e=>setChanges({...changes,[key]:e.target.value})}/></label>)}</div></details>
    <div className="toolbar"><button onClick={save} disabled={!Object.keys(changes).length}><Save size={16}/>保存本机配置</button><span role="status">{message}</span></div>
  </section>;
}
