import React, { useState, useEffect, useRef, useId } from "react";
import { createRoot } from "react-dom/client";
import {
  Newspaper,
  FileText,
  ListChecks,
  Folder,
  Cloud,
  BarChart3,
  Layers,
  Settings,
  RefreshCw,
  Plus,
  X,
  Play,
  Search,
  ChevronRight,
  ChevronLeft,
  Menu,
  CheckCircle2,
  AlertTriangle,
  Download,
  Square,
  Eye,
  Upload,
  Save,
  LogIn,
  ShieldCheck,
  ArrowUpDown,
  Image as ImageIcon,
  ExternalLink,
  Trash2,
  Activity,
} from "lucide-react";
import { DeleteDrafts, SourceHealth, AnalysisReport, LocalConfiguration } from "./WorkbenchTools";
import {
  api,
  connect,
  imageURL,
  providers,
  stateLabel,
  dateLabel,
  numberLabel,
  download,
  type Bootstrap,
  type Model,
  type Models,
  type Job,
  type PostRow,
  type Post,
} from "./api";
import "./styles.css";

const nav = [
  ["auto", "自动发帖", Newspaper],
  ["material", "材料发帖", FileText],
  ["jobs", "任务中心", ListChecks],
  ["local", "本地草稿处理", Folder],
  ["remote", "平台草稿", Cloud],
  ["delete", "删除平台草稿", Trash2],
  ["metrics", "已发布数据", BarChart3],
  ["sources", "信源健康", Activity],
  ["models", "模型与额度", Layers],
  ["settings", "账号与设置", Settings],
] as const;
type Page = (typeof nav)[number][0];
type Request = Record<string, unknown>;
const active = (j: Job) =>
  ["queued", "running", "waiting_user", "stopping"].includes(j.status);
function Status({ value }: { value: string }) {
  return (
    <span className={"status " + value}>
      <span />
      {stateLabel[value] || value}
    </span>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
      <Folder size={26} />
      <span>{text}</span>
    </div>
  );
}
function IconButton({
  label,
  onClick,
  children,
  disabled = false,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="icon-button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {React.Children.map(children, (child) =>
        React.isValidElement(child) &&
        ["input", "select", "textarea"].includes(String(child.type))
          ? React.cloneElement(child as React.ReactElement<{ id: string }>, {
              id,
            })
          : child,
      )}
    </div>
  );
}
function Duration({ job }: { job: Job }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);
  const s = Math.max(
    0,
    Math.floor((job.ended_at || now) - (job.started_at || job.created_at)),
  );
  return (
    <span className="mono">
      {Math.floor(s / 3600)
        .toString()
        .padStart(2, "0")}
      :
      {Math.floor((s / 60) % 60)
        .toString()
        .padStart(2, "0")}
      :{(s % 60).toString().padStart(2, "0")}
    </span>
  );
}
function ModelPicker({
  kind,
  value,
  onChange,
  models,
}: {
  kind: string;
  value: string;
  onChange: (id: string) => void;
  models: Model[];
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState(""),
    [provider, setProvider] = useState("");
  const selected = models.find((m) => m.id === value);
  const filtered = models.filter(
    (m) =>
      m.kind === kind &&
      (!provider || m.provider === provider) &&
      m.model.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="model-picker">
      <span className="field-label">
        {kind === "llm" ? "语言模型" : "生图模型"}
      </span>
      <button
        type="button"
        className={
          "model-trigger " + (selected && !selected.selectable ? "invalid" : "")
        }
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <Layers size={17} />
        <span>
          {selected
            ? `${providers[selected.provider]} · ${selected.model}`
            : "选择模型"}
          {selected && !selected.selectable && (
            <small>{selected.disabled_reason}</small>
          )}
        </span>
        <ChevronRight size={16} />
      </button>
      {open && (
        <div className="model-menu">
          <div className="toolbar">
            <Search size={16} />
            <input
              aria-label="搜索模型"
              placeholder="搜索模型"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <IconButton label="关闭模型列表" onClick={() => setOpen(false)}>
              <X size={16} />
            </IconButton>
          </div>
          <select
            aria-label="模型平台"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="">全部平台</option>
            {Object.entries(providers).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <div className="model-options">
            {!filtered.length && <Empty text="没有匹配的模型" />}
            {filtered.map((m) => (
              <button
                type="button"
                className="model-option"
                key={m.id}
                disabled={!m.selectable}
                onClick={() => {
                  onChange(m.id);
                  setOpen(false);
                }}
              >
                <strong>{m.model}</strong>
                <small>
                  {providers[m.provider]} ·{" "}
                  {m.selectable
                    ? numberLabel(m.remaining) + " " + m.unit
                    : m.disabled_reason}
                </small>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
function QuotaPanel({
  data,
  sync,
  choose,
  wide = false,
}: {
  data: Models;
  sync: () => void;
  choose?: (m: Model) => void;
  wide?: boolean;
}) {
  const [provider, setProvider] = useState(""),
    [q, setQ] = useState(""),
    [sort, setSort] = useState("name"),
    [usable, setUsable] = useState(false);
  const rows = data.rows
    .filter(
      (m) =>
        (!provider || m.provider === provider) &&
        (!usable || m.selectable) &&
        `${providers[m.provider]} ${m.model}`
          .toLowerCase()
          .includes(q.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "name"
        ? a.model.localeCompare(b.model)
        : `${a.cost_class}:${a.unit}`.localeCompare(
            `${b.cost_class}:${b.unit}`,
          ) || (b.remaining ?? -1) - (a.remaining ?? -1),
    );
  return (
    <section className={"quota-panel " + (wide ? "wide" : "")}>
      <div className="section-heading">
        <h2>模型与额度</h2>
        <IconButton label="同步免费额度" onClick={sync}>
          <RefreshCw size={17} />
        </IconButton>
      </div>
      <div className="platform-tabs" role="group" aria-label="额度平台">
        <button
          className={!provider ? "selected" : ""}
          onClick={() => setProvider("")}
        >
          全部
        </button>
        {Object.entries(providers).map(([k, v]) => (
          <button
            key={k}
            className={provider === k ? "selected" : ""}
            onClick={() => setProvider(k)}
          >
            {v}
          </button>
        ))}
      </div>
      <div className="search">
        <Search size={16} />
        <input
          aria-label="搜索额度模型"
          placeholder="搜索模型名称"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div className="quota-controls">
        <select
          aria-label="额度排序"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="name">模型名称</option>
          <option value="remaining">同单位剩余额度优先</option>
        </select>
        <label>
          <input
            type="checkbox"
            checked={usable}
            onChange={(e) => setUsable(e.target.checked)}
          />
          可用
        </label>
      </div>
      <div className="quota-rows">
        {!rows.length && (
          <Empty text={q || usable ? "没有匹配的模型" : "尚未取得额度快照"} />
        )}{" "}
        {rows.map((m) => (
          <article className="quota-row" key={m.id}>
            <div className="quota-name">
              <button
                type="button"
                disabled={!choose || !m.selectable}
                onClick={() => choose?.(m)}
                title={m.disabled_reason || "选择此模型"}
              >
                {m.model}
              </button>
              <span className="subtle">
                {providers[m.provider]} ·{" "}
                {m.kind === "image"
                  ? "生图"
                  : m.kind === "llm"
                    ? "语言"
                    : "其他"}{" "}
                ·{" "}
                {m.cost_class === "subscription_included"
                  ? "订阅"
                  : m.cost_class === "free"
                    ? "免费"
                    : "计费待核对"}
              </span>
            </div>
            <div className="quota-value">
              <strong>
                {numberLabel(m.remaining)}
                {m.total != null ? " / " + numberLabel(m.total) : ""}
              </strong>
              <small>{m.unit || "单位未获取"}</small>
            </div>
            {m.total != null && m.total > 0 && m.remaining != null && (
              <progress
                aria-label={m.model + "剩余额度"}
                max={m.total}
                value={Math.max(0, Math.min(m.total, m.remaining))}
              />
            )}
            <div className="quota-meta">
              <span>
                {m.disabled_reason || "可选择"}
                {m.quota_pool ? " · 共享池 " + m.quota_pool : ""}
              </span>
              <time>{dateLabel(m.snapshot_at)}</time>
            </div>
          </article>
        ))}
      </div>
      <div className="resource-foot">
        <ShieldCheck size={15} />
        <span>免费 / 订阅优先 · 禁止付费回退</span>
      </div>
    </section>
  );
}
function Creation({
  material,
  boot,
  submit,
  sync,
  onError,
}: {
  material: boolean;
  boot: Bootstrap;
  submit: (r: Request) => Promise<void>;
  sync: () => void;
  onError: (s: string) => void;
}) {
  const [title, setTitle] = useState("每日新闻"),
    [prompts, setPrompts] = useState(["国际争议事件", "中国产业与公司政策"]),
    [count, setCount] = useState(10),
    [days, setDays] = useState("auto"),
    [mode, setMode] = useState(boot.settings.performance_mode),
    [platform, setPlatform] = useState(boot.settings.platform),
    [view, setView] = useState("无视角评价"),
    [llm, setLLM] = useState(""),
    [img, setImg] = useState(""),
    [source, setSource] = useState(""),
    [materialTitle, setMaterialTitle] = useState(""),
    [time, setTime] = useState(""),
    [text, setText] = useState(""),
    [fileText, setFileText] = useState(""),
    [inputMode, setInputMode] = useState("text"),
    [fileName, setFileName] = useState(""),
    [materialMode, setMaterialMode] = useState("single"),
    [localImages, setLocalImages] = useState(false),
    [assetsGlob, setAssetsGlob] = useState("assets/*"),
    [sending, setSending] = useState(false);
  const isNews = material || title === "每日新闻" || title === "每日假新闻";
  const choose = (m: Model) => (m.kind === "llm" ? setLLM(m.id) : setImg(m.id));
  async function run(e: React.FormEvent) {
    e.preventDefault();
    setSending(true);
    try {
      await submit({
        kind: material ? "material" : "auto",
        title: material ? "每日新闻" : title,
        prompts,
        count: material && materialMode === "single" ? 1 : count,
        material_mode: materialMode,
        use_local_images: localImages,
        assets_glob: assetsGlob,
        lookback_days: days,
        performance_mode: mode,
        platform,
        evaluation_viewpoint: view,
        llm_id: llm,
        image_id: img,
        material_title: materialMode === "multiple" ? "" : materialTitle,
        material_time: time,
        material_text: inputMode === "file" ? fileText : text,
        material_source: materialMode === "multiple" ? "" : source,
      });
    } catch (e) {
      onError(String(e));
    } finally {
      setSending(false);
    }
  }
  async function loadFile(file?: File) {
    if (!file) return;
    if (file.size > 1024 * 1024) {
      onError("材料文件超过1MiB，请缩小文件");
      return;
    }
    try {
      setFileText(
        new TextDecoder("utf-8", { fatal: true }).decode(
          await file.arrayBuffer(),
        ),
      );
      setFileName(file.name);
    } catch {
      onError("无法读取文件，请使用 UTF-8 文字文件");
    }
  }
  return (
    <div className="creation-grid">
      <form className="creation-form" onSubmit={run}>
        {material && <div className="form-grid">
          <Field label="材料类型"><select value={materialMode} onChange={e=>setMaterialMode(e.target.value)}><option value="single">单条材料</option><option value="multiple">多条材料</option></select></Field>
          {materialMode === "multiple" && <Field label="材料生成数量"><input type="number" min={1} max={20} value={count} onChange={e=>setCount(Number(e.target.value))}/></Field>}
        </div>}
        {!material ? (
          <>
            <div className="segmented" aria-label="内容类型">
              {boot.capabilities.titles.map((t) => (
                <button
                  type="button"
                  key={t}
                  className={title === t ? "selected" : ""}
                  onClick={() => setTitle(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <section>
              <div className="section-heading">
                <h2>选题与范围</h2>
                <span className="subtle">
                  {isNews ? "新闻草稿" : "单篇简报"}
                </span>
              </div>
              <label className="field-label">提示词</label>
              <div className="prompt-list">
                {prompts.map((p, i) => (
                  <div className="prompt-row" key={i}>
                    <input
                      aria-label={"提示词 " + (i + 1)}
                      placeholder="输入一个选题方向"
                      value={p}
                      onChange={(e) =>
                        setPrompts(
                          prompts.map((v, n) => (n === i ? e.target.value : v)),
                        )
                      }
                    />
                    <IconButton
                      label={"删除提示词 " + (i + 1)}
                      onClick={() =>
                        setPrompts(prompts.filter((_, n) => n !== i))
                      }
                    >
                      <X size={16} />
                    </IconButton>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() => setPrompts([...prompts, ""])}
              >
                <Plus size={16} />
                添加提示词
              </button>
              {isNews ? (
                <div className="form-grid">
                  <Field label="稿件数量">
                    <input
                      type="number"
                      min={1}
                      max={boot.capabilities.max_count}
                      value={count}
                      onChange={(e) => setCount(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="新闻回溯">
                    <select
                      value={days}
                      onChange={(e) => setDays(e.target.value)}
                    >
                      <option value="auto">自动 · 1 → 2 → 3 → 5 天</option>
                      {[1, 2, 3, 4, 5].map((d) => (
                        <option value={d} key={d}>
                          {d} 天内
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              ) : (
                <div className="policy-strip">
                  <ShieldCheck size={18} />
                  <span>
                    {title === "每日AI讯息"
                      ? `历史查重 · 同源最多 ${boot.capabilities.source_cap} 条 · 模型发布优先`
                      : "有效期核查 · 官方证据优先"}
                  </span>
                </div>
              )}
            </section>
          </>
        ) : (
          <>
            <div className="segmented">
              <button
                type="button"
                className={inputMode === "text" ? "selected" : ""}
                onClick={() => setInputMode("text")}
              >
                输入文字
              </button>
              <button
                type="button"
                className={inputMode === "file" ? "selected" : ""}
                onClick={() => setInputMode("file")}
              >
                上传文件
              </button>
            </div>
            <section>
              <h2>新闻材料</h2>
              <Field label="材料标题">
                <input
                  disabled={materialMode === "multiple"}
                  value={materialTitle}
                  onChange={(e) => setMaterialTitle(e.target.value)}
                  placeholder="填写材料的事件标题"
                />
              </Field>
              {inputMode === "file" && (
                <Field label="材料文件 (.txt / .md / .json / .jsonl)">
                  <input
                    type="file"
                    accept=".txt,.md,.json,.jsonl"
                    onChange={(e) => loadFile(e.target.files?.[0])}
                  />
                  {fileName && <small>{fileName}</small>}
                </Field>
              )}
              <Field label="材料正文">
                <textarea
                  required
                  rows={12}
                  placeholder="粘贴完整材料"
                  value={inputMode === "file" ? fileText : text}
                  onChange={(e) =>
                    inputMode === "file"
                      ? setFileText(e.target.value)
                      : setText(e.target.value)
                  }
                />
              </Field>
              <div className="form-grid">
                <Field label="材料时间（北京时间）">
                  <input
                    required
                    type="datetime-local"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                  />
                </Field>
                <Field label="来源名称（选填）">
                  <input
                    disabled={materialMode === "multiple"}
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                  />
                </Field>
              </div>
            </section>
          </>
        )}
        <section>
          <h2>模型与生成</h2>
          <ModelPicker
            kind="llm"
            value={llm}
            onChange={setLLM}
            models={boot.models.rows}
          />
          {isNews && <label className="check-label"><input type="checkbox" checked={localImages} onChange={e=>setLocalImages(e.target.checked)}/>使用本地图片</label>}
          {isNews && localImages && <Field label="工作区图片路径"><input value={assetsGlob} onChange={e=>setAssetsGlob(e.target.value)}/></Field>}
          {isNews && !localImages && (
            <ModelPicker
              kind="image"
              value={img}
              onChange={setImg}
              models={boot.models.rows}
            />
          )}
          <div className="form-grid">
            <Field label="评价视角">
              <input value={view} onChange={(e) => setView(e.target.value)} />
            </Field>
            <Field label="运行模式">
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="balanced">速度与稳定平衡</option>
                <option value="speed">速度优先</option>
              </select>
            </Field>
          </div>
        </section>
        <section>
          <div className="section-heading">
            <h2>保存位置</h2>
            <span className="subtle">仅保存草稿</span>
          </div>
          <Field label="目标平台">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="xhs">小红书创作者中心</option>
              <option value="toutiao">今日头条</option>
              <option value="both">小红书 + 今日头条</option>
            </select>
          </Field>
          <div className="submit-row">
            <button
              className="primary"
              disabled={sending || boot.jobs.some(active)}
            >
              <Play size={17} />
              {sending ? "正在提交" : "生成并保存草稿"}
            </button>
            <span className="subtle">专用浏览器 · 无窗口上传</span>
          </div>
        </section>
      </form>
      <aside className="resource-column">
        <QuotaPanel data={boot.models} sync={sync} choose={choose} />
      </aside>
    </div>
  );
}
function Jobs({
  jobs,
  onError,
  openPost,
}: {
  jobs: Job[];
  onError: (s: string) => void;
  openPost: (id: string) => void;
}) {
  const [selected, setSelected] = useState(""),
    [detail, setDetail] = useState<Job | null>(null);
  const id = selected || jobs[0]?.id;
  useEffect(() => {
    let live = true;
    const refresh = () =>
      id &&
      api<Job>("/jobs/" + id)
        .then((j) => {
          if (live) setDetail(j);
        })
        .catch((e) => onError(String(e)));
    refresh();
    const t = setInterval(refresh, 2000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [id]);
  if (!jobs.length) return <Empty text="暂无工作台任务" />;
  return (
    <div className="jobs-layout">
      <div className="job-list">
        {jobs.map((j) => (
          <button
            key={j.id}
            className={"job-select " + (j.id === id ? "selected" : "")}
            onClick={() => setSelected(j.id)}
          >
            <strong>{j.title}</strong>
            <Status value={j.status} />
            <small>{dateLabel(j.created_at)}</small>
          </button>
        ))}
      </div>
      {detail && (
        <section className="job-detail">
          <div className="section-heading">
            <h2>{detail.title}</h2>
            <Status value={detail.status} />
          </div>
          <div className="job-summary">
            <div>
              <span>墙钟耗时</span>
              <Duration job={detail} />
            </div>
            <div>
              <span>当前阶段</span>
              <strong>{detail.stage}</strong>
            </div>
            <div>
              <span>退出码</span>
              <strong>{detail.exit_code ?? "—"}</strong>
            </div>
          </div>
          <div className="current-step" role="status">
            <span className={active(detail) ? "activity-dot" : ""} />
            {detail.message}
          </div>
          {detail.post_ids.length > 0 && (
            <div className="post-links">
              {detail.post_ids.map((p, i) => (
                <button onClick={() => openPost(p)} key={p}>
                  <FileText size={16} />
                  稿件 {i + 1}
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
          )}
          {!!detail.post_rows?.length && (
            <PostProgress rows={detail.post_rows} openPost={openPost} />
          )}
          <div className="toolbar">
            <h3>执行日志</h3>
            <IconButton
              label="下载日志"
              onClick={() =>
                download(
                  detail.id + ".log",
                  detail.events?.map((e) => e.message).join("\n") || "",
                )
              }
            >
              <Download size={17} />
            </IconButton>
            {active(detail) && (
              <button
                className="danger"
                onClick={() => {
                  if (
                    confirm(
                      "停止会中断当前子进程。已上传草稿可能需要核对，确定停止？",
                    )
                  )
                    api("/jobs/" + detail.id + "/stop", "POST", {}).catch((e) =>
                      onError(String(e)),
                    );
                }}
              >
                <Square size={15} />
                停止任务
              </button>
            )}
          </div>
          <pre className="logs" aria-label="执行日志">
            {detail.events
              ?.map((e) => `${dateLabel(e.at)}  ${e.message}`)
              .join("\n") || "等待日志"}
          </pre>
        </section>
      )}
    </div>
  );
}
function PostProgress({
  rows,
  openPost,
}: {
  rows: NonNullable<Job["post_rows"]>;
  openPost: (id: string) => void;
}) {
  return (
    <div className="table-wrap post-progress">
      <table>
        <thead>
          <tr>
            <th>稿件</th>
            <th>正文</th>
            <th>图片</th>
            <th>平台读回</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id}>
              <td>
                <button className="text-button" onClick={() => openPost(p.id)}>
                  {p.title}
                </button>
              </td>
              <td>{p.text}</td>
              <td>{p.images} 张</td>
              <td>
                <Status value={p.readback} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function ImagePreview({ url, name }: { url: string; name: string }) {
  const [src, setSrc] = useState(""),
    [error, setError] = useState(false);
  useEffect(() => {
    let alive = true,
      value = "";
    imageURL(url)
      .then((v) => {
        value = v;
        if (alive) setSrc(v);
        else URL.revokeObjectURL(v);
      })
      .catch(() => setError(true));
    return () => {
      alive = false;
      if (value) URL.revokeObjectURL(value);
    };
  }, [url]);
  return src ? (
    <img src={src} alt={name} />
  ) : (
    <div className="image-empty">
      <ImageIcon />
      {error ? "图片加载失败" : "图片加载中"}
    </div>
  );
}
function DraftDrawer({
  id,
  close,
  submit,
  onError,
}: {
  id: string;
  close: () => void;
  submit: (r: Request) => Promise<void>;
  onError: (s: string) => void;
}) {
  const [post, setPost] = useState<Post | null>(null),
    [tab, setTab] = useState("body"),
    [saved, setSaved] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
    api<Post>("/posts/" + id)
      .then(setPost)
      .catch((e) => onError(String(e)));
  }, [id]);
  return (
    <dialog className="draft-dialog" ref={dialog} onCancel={close}>
      <div className="drawer-header">
        <h2>草稿审查</h2>
        <IconButton label="关闭草稿" onClick={close}>
          <X />
        </IconButton>
      </div>
      {post ? (
        <>
          <div className="drawer-meta">
            <Status value={post.status} />
            <Status value={post.readback} />
            <span>{post.assets.length} 张图片</span>
          </div>
          <div className="segmented">
            {[
              ["body", "正文"],
              ["images", "图片"],
              ["evidence", "来源与执行证据"],
            ].map(([k, l]) => (
              <button
                className={tab === k ? "selected" : ""}
                onClick={() => setTab(k)}
                key={k}
              >
                {l}
              </button>
            ))}
          </div>
          {tab === "body" && (
            <div className="drawer-body">
              <Field label="标题">
                <input
                  value={post.title}
                  onChange={(e) => setPost({ ...post, title: e.target.value })}
                />
              </Field>
              <Field label="正文与评价">
                <textarea
                  rows={18}
                  value={post.body}
                  onChange={(e) => setPost({ ...post, body: e.target.value })}
                />
              </Field>
              <button
                onClick={() =>
                  api<Post>("/posts/" + id, "PUT", {
                    title: post.title,
                    body: post.body,
                    updated_at: post.updated_at,
                  })
                    .then((p) => {
                      setPost(p);
                      setSaved("已保存本地修改，平台内容尚未更新");
                    })
                    .catch((e) => onError(String(e)))
                }
              >
                <Save size={16} />
                保存本地修改
              </button>
              <span role="status">{saved}</span>
            </div>
          )}
          {tab === "images" && (
            <div className="image-grid">
              {post.assets.map((a) => (
                <ImagePreview key={a.url} {...a} />
              ))}
            </div>
          )}
          {tab === "evidence" && (
            <div className="drawer-body">
              <h3>平台执行步骤</h3>
              {post.steps.map((s, i) => (
                <div className="evidence-step" key={i}>
                  <strong>{s.name}</strong>
                  <Status value={s.status} />
                  <p>{s.detail}</p>
                </div>
              ))}
              <h3>来源记录</h3>
              <pre className="evidence-json">
                {JSON.stringify(post.platform, null, 2)}
              </pre>
            </div>
          )}
          <div className="drawer-actions">
            <button onClick={()=>submit({kind:"validate",post_id:id}).then(close).catch(e=>onError(String(e)))}><ListChecks size={16}/>校验本地草稿</button>
            <button disabled={post.status === "published" || post.status === "publishing"} onClick={()=>submit({kind:"approve",post_id:id}).then(close).catch(e=>onError(String(e)))}><CheckCircle2 size={16}/>本地审核通过</button>
            <button onClick={()=>submit({kind:"retry",post_id:id}).then(close).catch(e=>onError(String(e)))}><RefreshCw size={16}/>重试失败上传</button>
            <button
              onClick={() =>
                submit({ kind: "verify-draft", post_id: id })
                  .then(close)
                  .catch((e) => onError(String(e)))
              }
            >
              <Eye size={16} />
              核对远端草稿
            </button>
            <button
              className="primary"
              onClick={() => {
                if (confirm("将使用本地已保存内容更新对应的小红书草稿，继续？"))
                  submit({ kind: "update-draft", post_id: id })
                    .then(close)
                    .catch((e) => onError(String(e)));
              }}
            >
              <Upload size={16} />
              更新平台草稿
            </button>
          </div>
        </>
      ) : (
        <Empty text="正在读取草稿" />
      )}
    </dialog>
  );
}
function Drafts({
  remote,
  submit,
  openPost,
  onError,
}: {
  remote: boolean;
  submit: (r: Request) => Promise<void>;
  openPost: (id: string) => void;
  onError: (s: string) => void;
}) {
  const [rows, setRows] = useState<any[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [destination, setDestination] = useState("xhs"),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [pageIndex, setPageIndex] = useState(0),
    [at, setAt] = useState<number | null>(null);
  const refresh = () =>
    api<any>(remote ? "/remote" : "/posts")
      .then((d) => {
        setRows(remote ? d.rows : d);
        setAt(remote ? d.captured_at : null);
      })
      .catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
  }, [remote]);
  const filtered = rows.filter(
    (r) => r.title.includes(query) && (!status || r.status === status),
  );
  useEffect(() => setPageIndex(0), [query, status, rows]);
  return (
    <>
      <div className="toolbar">
        {!remote && <select aria-label="上传目标平台" value={destination} onChange={e=>setDestination(e.target.value)}><option value="xhs">小红书</option><option value="toutiao">今日头条</option><option value="both">两个平台</option></select>}
        {remote && <button disabled={!selected.length} onClick={()=>{const confirmation=prompt(`将公开发布已选择的 ${selected.length} 条草稿，请输入确认发布`);if(confirmation === "确认发布")submit({kind:"publish-batch",post_ids:selected,confirmation}).catch(e=>onError(String(e)));}}><Upload size={16}/>发布已选（{selected.length}）</button>}
        <div className="search">
          <Search size={16} />
          <input
            aria-label="搜索草稿"
            placeholder="搜索标题"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {!remote && (
          <select
            aria-label="草稿状态"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">全部状态</option>
            <option value="draft">本地草稿</option>
            <option value="saved_as_draft">已保存草稿</option>
            <option value="failed">失败</option>
          </select>
        )}
        <button
          onClick={() =>
            remote
              ? submit({ kind: "scan-drafts" }).catch((e) => onError(String(e)))
              : refresh()
          }
        >
          <RefreshCw size={16} />
          {remote ? "读取平台未发布草稿" : "刷新本地草稿"}
        </button>
        {remote && (
          <IconButton label="刷新扫描结果" onClick={refresh}>
            <Eye size={17} />
          </IconButton>
        )}
      </div>
      {remote && (
        <div className="policy-strip">
          <Cloud size={17} />
          小红书 · 列表快照：{dateLabel(at)} · 列表存在不代表正文已验证
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>标题</th>
              <th>{remote ? "保存时间" : "创建时间"}</th>
              <th>{remote ? "本地关联" : "状态"}</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered
              .slice(pageIndex * 25, (pageIndex + 1) * 25)
              .map((r, i) => (
                <tr key={r.post_id || i}>
                  <td>
                    {remote && r.post_id && <input type="checkbox" aria-label={"选择发布 " + r.title} checked={selected.includes(r.post_id)} onChange={e=>setSelected(e.target.checked ? [...selected,r.post_id] : selected.filter(id=>id!==r.post_id))}/>}
                    <strong>{r.title}</strong>
                    {!remote && <small>{r.asset_count} 张图片</small>}
                  </td>
                  <td>{dateLabel(r.saved_at || r.created_at)}</td>
                  <td>
                    {remote ? (
                      r.post_id ? (
                        "已关联"
                      ) : (
                        "未关联"
                      )
                    ) : (
                      <Status value={r.status} />
                    )}
                  </td>
                  <td>
                    <div className="row-actions">
                      <IconButton
                        label={"审查 " + r.title}
                        disabled={!r.post_id}
                        onClick={() => openPost(r.post_id)}
                      >
                        <Eye size={17} />
                      </IconButton>
                      {remote ? (
                        <IconButton
                          label={"发布 " + r.title}
                          disabled={!r.post_id}
                          onClick={() => {
                            const answer = prompt(
                              "此操作将发布到公众。输入“确认发布”继续：",
                            );
                            if (answer === "确认发布")
                              submit({
                                kind: "publish-drafts",
                                post_id: r.post_id,
                                confirmation: answer,
                              }).catch((e) => onError(String(e)));
                          }}
                        >
                          <Upload size={17} />
                        </IconButton>
                      ) : (
                        <IconButton
                          label={"上传 " + r.title}
                          disabled={r.uploaded || r.status === "published"}
                          onClick={() =>
                            submit({ kind: "run", post_id: r.post_id, platform: destination }).catch(
                              (e) => onError(String(e)),
                            )
                          }
                        >
                          <Upload size={17} />
                        </IconButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
        {!filtered.length && (
          <Empty
            text={
              remote ? "暂无平台快照，请读取未发布草稿" : "没有匹配的本地草稿"
            }
          />
        )}
      </div>
      <Pager total={filtered.length} page={pageIndex} setPage={setPageIndex} />
      {!remote && <p className="subtle">最近 {rows.length} 条本地记录</p>}
      {remote && (
        <div className="footer-actions">
          <button
            onClick={() =>
              submit({ kind: "delete-preview" }).catch((e) =>
                onError(String(e)),
              )
            }
          >
            <Eye size={16} />
            删除草稿安全预览
          </button>
        </div>
      )}
    </>
  );
}
function Metrics({
  submit,
  onError,
}: {
  submit: (r: Request) => Promise<void>;
  onError: (s: string) => void;
}) {
  const [data, setData] = useState<{
      rows: any[];
      captured_at: number | null;
      complete: boolean | null;
    }>({ rows: [], captured_at: null, complete: null }),
    [query, setQuery] = useState(""),
    [sort, setSort] = useState("views"),
    [range, setRange] = useState(0),
    [pageIndex, setPageIndex] = useState(0);
  useEffect(() => setPageIndex(0), [query, sort, range]);
  const refresh = () =>
    api<typeof data>("/metrics")
      .then(setData)
      .catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
  }, []);
  const rows = data.rows
    .filter(
      (r) =>
        r.title.includes(query) &&
        (!range || Date.parse(r.published_at) > Date.now() - range * 86400000),
    )
    .sort((a, b) => (b[sort] ?? -1) - (a[sort] ?? -1));
  const total = (key: string) => rows.reduce((n, r) => n + (r[key] ?? 0), 0);
  return (
    <>
      <div className="toolbar">
        <button
          className="primary"
          onClick={() =>
            submit({ kind: "update-metrics" }).catch((e) => onError(String(e)))
          }
        >
          <RefreshCw size={16} />
          全量同步
        </button>
        <IconButton label="刷新数据" onClick={refresh}>
          <RefreshCw size={17} />
        </IconButton>
        <button
          onClick={() =>
            download(
              "published-metrics.json",
              JSON.stringify(rows, null, 2),
              "application/json",
            )
          }
        >
          <Download size={16} />
          导出
        </button>
        <select
          aria-label="时间范围"
          value={range}
          onChange={(e) => setRange(Number(e.target.value))}
        >
          <option value={0}>全部时间</option>
          <option value={7}>近7天</option>
          <option value={30}>近30天</option>
        </select>
      </div>
      <div className="policy-strip">
        <AlertTriangle size={17} />
        完整性{data.complete === true ? "已确认" : "待核对"} · 最近快照{" "}
        {dateLabel(data.captured_at)}
      </div>
      <div className="metrics-summary">
        {[
          ["帖子", rows.length],
          ["阅读", total("views")],
          ["点赞", total("likes")],
          ["收藏", total("favorites")],
        ].map(([label, val]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{numberLabel(Number(val))}</strong>
          </div>
        ))}
      </div>
      <section className="chart-section">
        <h2>阅读表现</h2>
        {rows.slice(0, 5).map((r, i) => (
          <div className="chart-row" key={i}>
            <span>{r.title}</span>
            <progress
              max={Math.max(1, ...rows.map((r) => r.views || 0))}
              value={r.views || 0}
            />
            <b>{numberLabel(r.views)}</b>
          </div>
        ))}
      </section>
      <div className="toolbar">
        <div className="search">
          <Search size={16} />
          <input
            placeholder="搜索帖子"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <ArrowUpDown size={16} />
        <select
          aria-label="数据排序"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          {[
            ["views", "阅读"],
            ["likes", "点赞"],
            ["favorites", "收藏"],
            ["comments", "评论"],
          ].map(([k, v]) => (
            <option value={k} key={k}>
              {v}从高到低
            </option>
          ))}
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {["标题", "发布时间", "阅读", "点赞", "收藏", "评论"].map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(pageIndex * 25, (pageIndex + 1) * 25).map((r, i) => (
              <tr key={i}>
                <td>{r.title}</td>
                <td>{dateLabel(r.published_at)}</td>
                {["views", "likes", "favorites", "comments"].map((k) => (
                  <td key={k}>{numberLabel(r[k])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <Empty text="暂无已发布数据" />}
      </div>
      <Pager total={rows.length} page={pageIndex} setPage={setPageIndex} />
    </>
  );
}
function Pager({
  total,
  page,
  setPage,
}: {
  total: number;
  page: number;
  setPage: (n: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / 25));
  return (
    <div className="pager">
      <span>共 {total} 条</span>
      <IconButton
        label="上一页"
        disabled={page === 0}
        onClick={() => setPage(page - 1)}
      >
        <ChevronLeft size={17} />
      </IconButton>
      <span>
        {page + 1} / {pages}
      </span>
      <IconButton
        label="下一页"
        disabled={page + 1 >= pages}
        onClick={() => setPage(page + 1)}
      >
        <ChevronRight size={17} />
      </IconButton>
    </div>
  );
}
function SettingsPage({
  boot,
  submit,
  reload,
  onError,
}: {
  boot: Bootstrap;
  submit: (r: Request) => Promise<void>;
  reload: () => void;
  onError: (s: string) => void;
}) {
  const [mode, setMode] = useState(boot.settings.performance_mode),
    [platform, setPlatform] = useState(boot.settings.platform),
    [saved, setSaved] = useState("");
  return (
    <div className="settings-page">
      <section>
        <h2>专用浏览器</h2>
        <div className="setting-row">
          <div>
            <strong>小红书创作者中心</strong>
            <small>
              {boot.profile} · 登录状态：{boot.login_status}
            </small>
          </div>
          <button
            onClick={() =>
              submit({ kind: "login" }).catch((e) => onError(String(e)))
            }
          >
            <LogIn size={16} />
            打开专用登录窗口
          </button>
        </div>
      </section>
      <section>
        <h2>模型平台</h2>
        {boot.accounts.map((a) => (
          <div className="setting-row" key={a.provider}>
            <strong>{a.label}</strong>
            <Status value={a.configured ? "已配置密钥" : "未配置密钥"} />
          </div>
        ))}
      </section>
      <section>
        <h2>运行默认值</h2>
        <div className="form-grid">
          <Field label="运行模式">
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="balanced">速度与稳定平衡</option>
              <option value="speed">速度优先</option>
            </select>
          </Field>
          <Field label="目标平台">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="xhs">小红书</option>
              <option value="toutiao">今日头条</option>
              <option value="both">小红书 + 今日头条</option>
            </select>
          </Field>
        </div>
        <div className="policy-strip">
          <ShieldCheck size={18} />
          禁止付费 PPInfra 回退 · MiniMax 仅订阅
        </div>
        <button
          className="primary"
          onClick={() =>
            api("/settings", "PUT", { performance_mode: mode, platform })
              .then(() => {
                setSaved("设置已保存");
                reload();
              })
              .catch((e) => onError(String(e)))
          }
        >
          <Save size={16} />
          保存设置
        </button>
        <span role="status">{saved}</span>
      </section>
    </div>
  );
}
function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null),
    [page, setPage] = useState<Page>("auto"),
    [error, setError] = useState(""),
    [menu, setMenu] = useState(false),
    [post, setPost] = useState(""),
    [syncOpen, setSyncOpen] = useState(false),
    [visible, setVisible] = useState(false),
    [quotaProvider, setQuotaProvider] = useState("all"),
    [quotaModels, setQuotaModels] = useState(""),
    [visibleOnly, setVisibleOnly] = useState(false),
    [connected, setConnected] = useState(false);
  const busy = useRef(false);
  const previousJobs = useRef<Job[]>([]);
  const reload = () =>
    api<Bootstrap>("/bootstrap")
      .then((b) => {
        previousJobs.current = b.jobs;
        setBoot(b);
        setConnected(true);
      })
      .catch((e) => {
        setConnected(false);
        setError(String(e));
      });
  useEffect(() => {
    connect()
      .then(reload)
      .catch((e) => setError(String(e)));
    const id = setInterval(
      () =>
        api<Job[]>("/jobs")
          .then((jobs) => {
            const finished = previousJobs.current.some(
              (old) =>
                active(old) &&
                jobs.some((job) => job.id === old.id && !active(job)),
            );
            previousJobs.current = jobs;
            setConnected(true);
            setBoot((b) => (b ? { ...b, jobs } : b));
            if (finished) void reload();
          })
          .catch(() => setConnected(false)),
      2500,
    );
    return () => clearInterval(id);
  }, []);
  async function submit(request: Request) {
    if (busy.current) throw Error("任务正在提交");
    busy.current = true;
    try {
      await api<Job>("/jobs", "POST", request, crypto.randomUUID());
      setPage("jobs");
      await reload();
    } finally {
      busy.current = false;
    }
  }
  const current = boot?.jobs.find(active);
  const pageName = nav.find(([k]) => k === page)?.[1];
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (menu ? "open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("auto");
          }}
        >
          <span className="brand-mark">
            <Newspaper size={21} />
          </span>
          <span>
            创作工作台<small>AUTO REDBOOK</small>
          </span>
        </a>
        <div className="nav-caption">创作与执行</div>
        <nav>
          {nav.map(([id, name, Icon], i) => (
            <React.Fragment key={id}>
              {i === 3 && <div className="nav-caption">内容与数据</div>}
              {i === 7 && <div className="nav-caption">资源与设置</div>}
              <button
                aria-current={page === id ? "page" : undefined}
                className={page === id ? "active" : ""}
                title={name}
                onClick={() => {
                  setPage(id);
                  setMenu(false);
                }}
              >
                <Icon size={19} />
                <span>{name}</span>
                {id === "jobs" && current && <span className="nav-dot" />}
              </button>
            </React.Fragment>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className={"connection-dot " + (connected ? "online" : "")} />
          <span>{connected ? "本地服务已连接" : "服务未连接"}</span>
        </div>
      </aside>
      {menu && (
        <button
          className="nav-scrim"
          aria-label="关闭导航"
          onClick={() => setMenu(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <IconButton label="展开导航" onClick={() => setMenu(!menu)}>
            <Menu size={20} />
          </IconButton>
          <span>
            工作台 <ChevronRight size={14} /> {pageName}
          </span>
          <div className="topbar-right">
            <ShieldCheck size={16} />
            <span>本地运行</span>
            <IconButton
              label="刷新资源数据"
              onClick={() => {
                connect()
                  .then(reload)
                  .catch((e) => setError(String(e)));
              }}
            >
              <RefreshCw size={16} />
            </IconButton>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {page === "auto" || page === "material"
                  ? "CONTENT STUDIO"
                  : "WORKSPACE"}
              </span>
              <h1>{pageName}</h1>
            </div>
            <div className="page-heading-actions">
              <span className="profile-label">
                <Cloud size={16} />
                专用浏览器
              </span>
              <button
                type="button"
                className="platform-access"
                title={
                  current
                    ? "任务运行中，浏览器任务不能并发"
                    : "使用项目专用 profile 打开小红书创作者中心"
                }
                disabled={Boolean(current)}
                onClick={() =>
                  submit({
                    kind: "open-xhs",
                    title: "打开小红书创作者中心",
                  }).catch((e) => setError(String(e)))
                }
              >
                <ExternalLink size={15} />
                <span>打开创作者中心</span>
              </button>
            </div>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <AlertTriangle size={20} />
              <span>{error.replace(/^Error: /, "")}</span>
              <IconButton label="关闭错误" onClick={() => setError("")}>
                <X size={18} />
              </IconButton>
            </div>
          )}
          {!boot ? (
            <Empty text="等待本地服务连接" />
          ) : (
            <>
              <div hidden={page !== "auto"}>
                <Creation
                  material={false}
                  boot={boot}
                  submit={submit}
                  sync={() => setSyncOpen(true)}
                  onError={setError}
                />
              </div>
              <div hidden={page !== "material"}>
                <Creation
                  material
                  boot={boot}
                  submit={submit}
                  sync={() => setSyncOpen(true)}
                  onError={setError}
                />
              </div>
              {page === "jobs" && (
                <Jobs jobs={boot.jobs} openPost={setPost} onError={setError} />
              )}{" "}
              {page === "models" && (
                <QuotaPanel
                  wide
                  data={boot.models}
                  sync={() => setSyncOpen(true)}
                />
              )}{" "}
              {page === "local" && (
                <Drafts
                  remote={false}
                  submit={submit}
                  openPost={setPost}
                  onError={setError}
                />
              )}{" "}
              {page === "remote" && (
                <Drafts
                  remote
                  submit={submit}
                  openPost={setPost}
                  onError={setError}
                />
              )}{" "}
              {page === "metrics" && (
                <><Metrics submit={submit} onError={setError} /><AnalysisReport submit={submit} onError={setError}/></>
              )}{" "}
              {page === "settings" && (
                <><SettingsPage
                  boot={boot}
                  submit={submit}
                  reload={reload}
                  onError={setError}
                /><div className="toolbar"><button onClick={()=>submit({kind:"open-toutiao",title:"打开头条号创作者中心"}).catch(e=>setError(String(e)))}><ExternalLink size={16}/>打开头条号创作者中心</button></div><LocalConfiguration onError={setError}/></>
              )}
              <div hidden={page !== "delete"}><DeleteDrafts jobs={boot.jobs} submit={submit} onError={setError}/></div>
              {page === "sources" && <SourceHealth submit={submit} onError={setError}/>}
            </>
          )}
          {current && page !== "jobs" && (
            <button className="active-task" onClick={() => setPage("jobs")}>
              <span className="activity-dot" />
              <strong>{current.title}</strong>
              <span>{current.stage}</span>
              <Duration job={current} />
              <ChevronRight size={18} />
            </button>
          )}
        </main>
      </div>
      {post && (
        <DraftDrawer
          id={post}
          close={() => setPost("")}
          submit={submit}
          onError={setError}
        />
      )}{" "}
      {syncOpen && (
        <div className="modal-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-label="同步额度"
            className="modal"
          >
            <div className="section-heading">
              <h2>同步模型与额度</h2>
              <IconButton label="关闭同步" onClick={() => setSyncOpen(false)}>
                <X size={18} />
              </IconButton>
            </div>
            <label className="check-label">
              <input
                type="checkbox"
                checked={visible}
                onChange={(e) => setVisible(e.target.checked)}
              />
              允许打开平台专用登录窗口
            </label>
            <Field label="同步平台"><select value={quotaProvider} onChange={e=>setQuotaProvider(e.target.value)}><option value="all">全部平台</option>{Object.entries(providers).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></Field>
            {quotaProvider !== "all" && <Field label="指定模型（留空获取全部）"><input value={quotaModels} onChange={e=>setQuotaModels(e.target.value)}/></Field>}
            <label className="check-label"><input type="checkbox" checked={visibleOnly} onChange={e=>setVisibleOnly(e.target.checked)}/>仅解析控制台可见额度</label>
            <div className="modal-actions">
              <button onClick={() => setSyncOpen(false)}>取消</button>
              <button
                className="primary"
                onClick={() =>
                  submit({ kind: "sync-quotas", visible, provider: quotaProvider, models: quotaProvider === "all" ? "" : quotaModels, visible_only: visibleOnly })
                    .then(() => setSyncOpen(false))
                    .catch((e) => setError(String(e)))
                }
              >
                <RefreshCw size={16} />
                开始同步
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
