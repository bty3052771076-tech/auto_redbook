import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, KeyRound, LoaderCircle, Play, Plus, RefreshCw, Save, Search, Settings2, ShieldCheck, Star, X } from "lucide-react";
import "./model-platforms.css";

type Call = (path: string, method?: string, data?: unknown, key?: string) => Promise<any>;
type Role = "agent" | "writer" | "image";
type Connection = { connection_id: string; name: string; adapter: string; base_url: string; network: string; auth_mode: string;
  credential_ref: string; billing: string; enabled: boolean; authorization: { expires_at: number; max_requests: number } | null };
type Entry = { model_ref: string; connection_id: string; connection_name: string; upstream_model_id: string; name: string; parameters: Record<string, string | number>;
  enabled: boolean; favorite: boolean; origin: string; catalog_missing: boolean; billing: string;
  capabilities: Record<string, { tested_at: number }>; eligible: Record<string, string> };
type Catalog = { revision: number; connections: Connection[]; models: Entry[]; roles: Record<string, string> };
type Preset = { id: string; name: string; adapter: string; base_url: string; network: string; auth_mode: string };
export type ModelChoice = { id: string; label: string; model: string; disabledReason?: string; group?: string };
const roleLabels = { agent: "智能体主控模型", writer: "写稿模型", image: "生图模型" };
const billingLabels: Record<string, string> = { free: "免费（声明）", subscription: "订阅（声明）", payg: "按量", unknown: "费用未验证" };

export function RolePicker({ label, value, choices, onChange, disabled = false }: {
  label: string; value: string; choices: ModelChoice[]; onChange: (value: string) => void; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false), [search, setSearch] = useState("");
  const root = useRef<HTMLDivElement>(null), button = useRef<HTMLButtonElement>(null), input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  const current = choices.find(item => item.id === value);
  return <div className="mp-picker" ref={root} onKeyDown={event => {
    if (event.key === "Escape") { setOpen(false); button.current?.focus(); }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const options = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role="option"]:not(:disabled)') || []);
      const i = options.indexOf(document.activeElement as HTMLButtonElement);
      options[(i + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length]?.focus();
    }
  }}>
    <button type="button" ref={button} className="mp-select" aria-label={label} aria-haspopup="listbox" aria-expanded={open}
      disabled={disabled} onClick={() => setOpen(!open)}><span>{current?.label || (value ? "已选模型暂不可用" : "继承原有配置")}</span><ChevronDown size={16} /></button>
    {open && <div className="mp-menu"><label className="mp-search"><Search size={16} /><input ref={input} aria-label={`搜索${label}`} value={search} onChange={e => setSearch(e.target.value)} /></label>
      <div role="listbox" aria-label={label}>
        <button role="option" aria-selected={!value} onClick={() => { onChange(""); setOpen(false); button.current?.focus(); }}>继承原有配置</button>
        {choices.filter(item => `${item.label} ${item.model}`.toLowerCase().includes(search.toLowerCase())).map(item => <button key={item.id} role="option"
          aria-label={item.label} aria-selected={value === item.id} disabled={!!item.disabledReason} title={item.disabledReason || item.model}
          onClick={() => { onChange(item.id); setOpen(false); button.current?.focus(); }}>
          <span><strong>{item.label}</strong><small>{item.model}</small>{item.disabledReason && <small className="mp-error">{item.disabledReason}</small>}</span>
          {value === item.id && <Check size={16} />}</button>)}
      </div>
    </div>}
  </div>;
}

export function ModelPlatforms({ call, legacyModels, onChanged }: {
  call: Call; legacyModels: { id: string; model: string; provider: string; provider_name?: string; kind: string;
    selectable: boolean; disabled_reason?: string; role_reasons?: Record<string, string> }[];
  onChanged: () => Promise<void> | void;
}) {
  const [catalog, setCatalog] = useState<Catalog>({ revision: 0, connections: [], models: [], roles: {} });
  const [presets, setPresets] = useState<Preset[]>([]);
  const [tab, setTab] = useState("connections"), [selected, setSelected] = useState("");
  const [dialog, setDialog] = useState<"connection" | "model" | "authorization" | "credential" | null>(null);
  const [editingModel, setEditingModel] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState<any>(null), [search, setSearch] = useState("");
  const modal = useRef<HTMLElement>(null), opener = useRef<HTMLElement | null>(null);
  const sequence = useRef(0);
  async function refresh() {
    const [state, bindings] = await Promise.all([call("/api/model-platforms/models"), call("/api/model-platforms/roles")]);
    setCatalog(state); setRoles(bindings.roles);
    setSelected(previous => state.connections.some((c: Connection) => c.connection_id === previous) ? previous : state.connections[0]?.connection_id || "");
  }
  useEffect(() => { Promise.all([refresh(), call("/api/model-platforms/presets").then(value => setPresets(value.presets))]).catch(e => setError(String(e))); }, []);
  useEffect(() => {
    if (!dialog) return;
    modal.current?.querySelector<HTMLElement>("input,select,button")?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) close();
      if (event.key === "Tab") {
        const fields = Array.from(modal.current?.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),select:not(:disabled)") || []);
        const first = fields[0], last = fields.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => document.removeEventListener("keydown", keyboard);
  }, [dialog, busy]);
  useEffect(() => {
    if (!operation || operation.status !== "running") return;
    let stopped = false, timer: number;
    const version = ++sequence.current;
    async function poll() {
      try {
        const result = await call(`/api/model-platforms/operations/${operation.operation_id}`);
        if (stopped || version !== sequence.current) return;
        setOperation(result);
        if (result.status !== "running") {
          if (result.status === "completed") setNotice(result.action === "check" ? "验证通过" : result.result?.complete ? "目录更新完成" : "目录未完整，原模型保留");
          else setError(result.error || "检查中断，原配置保留");
          await refresh(); await onChanged(); return;
        }
      } catch (e) { if (!stopped) setError(String(e)); }
      if (!stopped) timer = window.setTimeout(poll, 750);
    }
    timer = window.setTimeout(poll, 250);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [operation?.operation_id, operation?.status]);
  const connection = catalog.connections.find(c => c.connection_id === selected);
  const checking = operation?.status === "running";
  function open(type: typeof dialog) { opener.current = document.activeElement as HTMLElement; setEditingModel(""); setForm({}); setError(""); setNotice(""); setDialog(type); }
  function close() { setDialog(null); setForm({}); opener.current?.focus(); }
  function field(name: string, label: string, type = "text", fallback = "") {
    return <label className="mp-field"><span>{label}</span><input type={type} value={form[name] ?? fallback} autoComplete={type === "password" ? "new-password" : "off"}
      onChange={e => setForm(previous => ({ ...previous, [name]: e.target.value }))} /></label>;
  }
  async function mutate(path: string, method: string, data: unknown, done = "已保存") {
    setBusy(true); setError(""); setNotice("");
    try { const result = await call(path, method, { ...(data as object), expected_revision: catalog.revision }, crypto.randomUUID());
      if (result.connection_id) setSelected(result.connection_id);
      close(); await refresh(); await onChanged(); setNotice(done);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function start(path: string, data = {}) {
    setBusy(true); setError(""); setNotice("");
    try { setOperation(await call(path, "POST", data, crypto.randomUUID())); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  function choosePreset(id: string) {
    const preset = presets.find(p => p.id === id);
    if (preset) setForm({ ...preset, name: preset.id === "custom" ? "" : preset.name, vendor_preset: preset.id });
  }
  function modelChoices(role: Role): ModelChoice[] {
    const legacy = legacyModels.filter(m => !m.id.startsWith("m_") && m.kind === (role === "image" ? "image" : "llm"))
      .map(m => ({ id: m.id, model: m.model, label: `${m.provider_name || m.provider} · ${m.model}`, disabledReason: m.selectable ? "" : m.disabled_reason || "模型不可用" }));
    const custom = role === "image" ? [] : catalog.models.map(m => ({ id: m.model_ref, model: m.upstream_model_id,
      label: `${m.connection_name} · ${m.name}`, disabledReason: m.eligible[role] }));
    return [...custom, ...legacy];
  }
  return <section className="mp-root" aria-label="模型平台管理">
    <header className="mp-heading"><h2>模型与供应商</h2><button type="button" onClick={() => open("connection")}><Plus size={16} />添加供应商</button></header>
    <div className="mp-tabs" role="tablist" aria-label="模型管理">{[["connections", "供应商"], ["models", "模型目录"], ["roles", "默认角色"]].map(([id, title]) =>
      <button type="button" key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{title}</button>)}</div>
    <div aria-live="polite">{error && <p className="mp-error" role="alert">{error}</p>}{notice && <p className="mp-notice">{notice}</p>}
      {checking && <p className="mp-notice"><LoaderCircle size={16} className="spin" />检查进行中</p>}</div>
    {tab === "connections" && <div className="mp-layout"><aside className="mp-connections">{catalog.connections.map(c => <button key={c.connection_id} onClick={() => setSelected(c.connection_id)} className={selected === c.connection_id ? "selected" : ""}>
      <strong>{c.name}</strong><small>{c.adapter} · {c.enabled ? "启用" : "停用"}</small></button>)}{!catalog.connections.length && <p>暂无自定义连接</p>}</aside>
      <section className="mp-detail">{connection ? <><h3>{connection.name}</h3><dl><dt>API 基址</dt><dd>{connection.base_url}</dd><dt>协议</dt><dd>{connection.adapter}</dd>
        <dt>凭据</dt><dd>{connection.auth_mode === "none" ? "本机无认证" : connection.credential_ref ? "已配置（不显示密钥）" : "未配置"}</dd>
        <dt>计费声明</dt><dd>{billingLabels[connection.billing]}</dd><dt>本地授权</dt><dd>{connection.authorization ? `${connection.authorization.max_requests} 次请求 · ${new Date(connection.authorization.expires_at * 1000).toLocaleString("zh-CN")}` : "未授权"}</dd></dl>
        <div className="mp-actions"><button disabled={busy || checking} onClick={() => start("/api/model-platforms/checks", { connection_id: selected, purpose: "connection" })}><ShieldCheck size={16} />检查连接</button>
          <button disabled={busy || checking} onClick={() => start(`/api/model-platforms/connections/${selected}/discover`)}><RefreshCw size={16} />更新模型列表</button>
          <button disabled={busy} onClick={() => open("model")}><Plus size={16} />添加模型</button><button disabled={busy} onClick={() => open("authorization")}><ShieldCheck size={16} />授权此连接</button>
          {connection.auth_mode !== "none" && <button disabled={busy} onClick={() => open("credential")}><KeyRound size={16} />替换凭据</button>}
          <button disabled={busy} onClick={() => mutate(`/api/model-platforms/connections/${selected}`, "PATCH", { enabled: !connection.enabled })}>{connection.enabled ? "停用连接" : "启用连接"}</button></div>
        <div className="mp-inline-models">{catalog.models.filter(m => m.connection_id === selected).map(m => <div key={m.model_ref}><strong>{m.name}</strong><code>{m.upstream_model_id}</code></div>)}</div>
      </> : <p>选择或添加供应商</p>}</section></div>}
    {tab === "models" && <section><label className="mp-search"><Search size={16} /><input aria-label="搜索模型目录" value={search} onChange={e => setSearch(e.target.value)} /></label>
      {catalog.models.filter(m => `${m.connection_name} ${m.name} ${m.upstream_model_id}`.toLowerCase().includes(search.toLowerCase())).map(m => <article className="mp-model" key={m.model_ref}>
        <div className="mp-heading"><div><h3>{m.name}</h3><p>{m.connection_name} · {m.origin === "manual" ? "手动录入" : "接口发现"}</p><code>{m.upstream_model_id}</code></div>
          <div className="mp-icon-actions"><button aria-label={`复制 ${m.upstream_model_id}`} title="复制模型 ID" onClick={() => navigator.clipboard.writeText(m.upstream_model_id).catch(e => setError(String(e)))}><Copy size={16} /></button>
            <button aria-label={`编辑 ${m.name} 参数`} title="编辑模型参数后需重新验证" onClick={() => {
              open("model"); setEditingModel(m.model_ref); setForm({ name: m.name, ...Object.fromEntries(Object.entries(m.parameters).map(([k, v]) => [k, String(v)])) });
            }}><Settings2 size={16} /></button>
            <button aria-label={`收藏 ${m.name}`} title="收藏" aria-pressed={m.favorite} disabled={busy} onClick={() => mutate(`/api/model-platforms/models/${m.model_ref}`, "PATCH", { favorite: !m.favorite })}><Star size={16} fill={m.favorite ? "currentColor" : "none"} /></button></div></div>
        <label className="mp-checkbox"><input type="checkbox" checked={m.enabled} disabled={busy} onChange={e => mutate(`/api/model-platforms/models/${m.model_ref}`, "PATCH", { enabled: e.target.checked })} />启用模型</label>
        <p className={m.eligible.agent ? "mp-muted" : "mp-notice"}>主控：{m.eligible.agent || "结构化能力已验证"}</p><p className={m.eligible.writer ? "mp-muted" : "mp-notice"}>写稿：{m.eligible.writer || "文本能力已验证"}</p>
        <div className="mp-actions">{[["text", "测试文本"], ["structured", "测试结构化"], ["tools", "测试工具回环"]].map(([purpose, label]) => <button key={purpose} disabled={busy || checking || !m.enabled}
          onClick={() => start("/api/model-platforms/checks", { model_ref: m.model_ref, purpose })}><PlayIcon />{label}</button>)}</div></article>)}
      {!catalog.models.length && <p>暂无自定义模型</p>}</section>}
    {tab === "roles" && <section className="mp-roles">{(["agent", "writer", "image"] as Role[]).map(role => <div className="mp-field" key={role}><span>{roleLabels[role]}</span>
      <RolePicker label={roleLabels[role]} value={roles[role] || ""} choices={modelChoices(role)} onChange={ref => setRoles(previous => ({ ...previous, [role]: ref }))} /></div>)}
      <button disabled={busy} onClick={() => mutate("/api/model-platforms/roles", "PUT", roles, "默认角色已保存")}><Save size={16} />保存默认模型</button></section>}
    {dialog && <div className="mp-backdrop"><section ref={modal} className="mp-dialog" role="dialog" aria-modal="true" aria-label={dialog === "connection" ? "添加供应商" : dialog === "model" ? "添加模型" : dialog === "credential" ? "替换凭据" : "费用授权"}>
      <header className="mp-heading"><h2>{dialog === "connection" ? "添加供应商" : dialog === "model" ? "添加模型" : dialog === "credential" ? "替换凭据" : "费用授权"}</h2><button title="关闭" aria-label="关闭" disabled={busy} onClick={close}><X size={18} /></button></header>
      {error && <p className="mp-error" role="alert">{error}</p>}
      {dialog === "connection" && <><label className="mp-field"><span>连接模板</span><select aria-label="连接模板" value={form.vendor_preset || "custom"} onChange={e => choosePreset(e.target.value)}>{presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        {field("name", "供应商名称")}{field("base_url", "API 基址", "url")}
        <label className="mp-field"><span>接口协议</span><select aria-label="接口协议" value={form.adapter || "openai_chat"} onChange={e => setForm({ ...form, adapter: e.target.value })}><option value="openai_chat">OpenAI Chat / Gemini 兼容</option><option value="openai_responses">OpenAI Responses</option><option value="anthropic_messages">Claude Messages</option></select></label>
        <label className="mp-field"><span>网络模式</span><select aria-label="网络模式" value={form.network || "public"} onChange={e => setForm({ ...form, network: e.target.value })}><option value="public">公网 HTTPS</option><option value="local">本机 loopback</option></select></label>
        <label className="mp-field"><span>认证方式</span><select aria-label="认证方式" value={form.auth_mode || "bearer"} onChange={e => setForm({ ...form, auth_mode: e.target.value })}><option value="bearer">Bearer API Key</option><option value="x-api-key">x-api-key</option>{form.network === "local" && <option value="none">本机无认证</option>}</select></label>
        {form.auth_mode !== "none" && <>{field("api_key", "API Key（仅本地加密保存）", "password")}{field("credential_env", "或使用环境变量名称")}</>}
        <label className="mp-field"><span>计费声明</span><select aria-label="计费声明" value={form.billing || "unknown"} onChange={e => setForm({ ...form, billing: e.target.value })}>{Object.entries(billingLabels).map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select></label>
        <details><summary>高级连接参数</summary>{field("generate_path", "生成相对路径")}{field("models_path", "目录相对路径")}
          <dl><dt>生成端点</dt><dd><code>{form.base_url ? `${form.base_url.replace(/\/$/, "")}/${form.generate_path || (form.adapter === "anthropic_messages" ? "messages" : form.adapter === "openai_responses" ? "responses" : "chat/completions")}` : "未填写基址"}</code></dd>
            <dt>目录端点</dt><dd><code>{form.base_url ? `${form.base_url.replace(/\/$/, "")}/${form.models_path || "models"}` : "未填写基址"}</code></dd></dl>
          <label className="mp-field"><span>代理策略</span><select aria-label="代理策略" value={form.proxy_mode || "inherit"} onChange={e => setForm({ ...form, proxy_mode: e.target.value })}><option value="inherit">继承系统代理</option><option value="direct">直连</option></select></label>
          {field("concurrency", "连接并发上限", "number", "2")}{field("rate_limit_group", "共享限流组（可选）")}</details>
        <footer className="mp-actions"><button disabled={busy} onClick={close}>取消</button><button disabled={busy} onClick={() => mutate("/api/model-platforms/connections", "POST", {
          name: form.name || "", base_url: form.base_url || "", adapter: form.adapter || "openai_chat", network: form.network || "public", auth_mode: form.auth_mode || "bearer",
          api_key: form.api_key || "", credential_env: form.credential_env || "", billing: form.billing || "unknown", vendor_preset: form.vendor_preset || "custom",
          proxy_mode: form.proxy_mode || "inherit", concurrency: Number(form.concurrency || 2), rate_limit_group: form.rate_limit_group || "",
          paths: { ...(form.generate_path ? { generate: form.generate_path } : {}), ...(form.models_path ? { models: form.models_path } : {}) },
        })}><Save size={16} />保存连接</button></footer></>}
      {dialog === "model" && <>{editingModel ? <code>{catalog.models.find(m => m.model_ref === editingModel)?.upstream_model_id}</code> : field("upstream_model_id", "原生模型 ID")}{field("name", "模型展示名（可选）")}
        <details><summary>生成参数</summary>{field("max_output_tokens", "输出 token 上限", "number")}{field("temperature", "temperature（可选）", "number")}{field("top_p", "top_p（可选）", "number")}
          <label className="mp-field"><span>token 参数</span><select aria-label="token 参数" value={form.token_parameter || "max_tokens"} onChange={e => setForm({ ...form, token_parameter: e.target.value })}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>
          <label className="mp-field"><span>推理强度</span><select aria-label="推理强度" value={form.reasoning_effort || ""} onChange={e => setForm({ ...form, reasoning_effort: e.target.value })}><option value="">不发送</option>{["none", "minimal", "low", "medium", "high", "xhigh"].map(v => <option value={v} key={v}>{v}</option>)}</select></label>
        </details>
        <footer className="mp-actions"><button onClick={close} disabled={busy}>取消</button><button disabled={busy} onClick={() => {
          const parameters = { token_parameter: form.token_parameter || "max_tokens",
            ...Object.fromEntries(["max_output_tokens", "temperature", "top_p"].filter(k => form[k] !== undefined && form[k] !== "").map(k => [k, Number(form[k])])),
            ...(form.reasoning_effort ? { reasoning_effort: form.reasoning_effort } : {}),
          };
          mutate(editingModel ? `/api/model-platforms/models/${editingModel}` : "/api/model-platforms/models", editingModel ? "PATCH" : "POST", editingModel ? {
            name: form.name || catalog.models.find(m => m.model_ref === editingModel)?.name, parameters,
          } : { connection_id: selected, upstream_model_id: form.upstream_model_id || "", name: form.name || "", enabled: true, parameters });
        }}><Save size={16} />保存模型</button></footer></>}
      {dialog === "credential" && <>{field("api_key", "替换 API Key", "password")}{field("credential_env", "或使用环境变量名称")}
        <footer className="mp-actions"><button disabled={busy} onClick={() => { if (window.confirm("清除凭据会使模型停止执行，确认清除？")) mutate(`/api/model-platforms/connections/${selected}/credential`, "DELETE", {}); }}>清除凭据</button>
          <button disabled={busy} onClick={() => mutate(`/api/model-platforms/connections/${selected}/credential`, "PUT", { api_key: form.api_key || "", credential_env: form.credential_env || "" })}><KeyRound size={16} />替换凭据</button></footer></>}
      {dialog === "authorization" && <><p className="mp-muted">{billingLabels[connection?.billing || "unknown"]} · 金额上限未验证 · 仅限制本地请求次数</p>
        {(["agent", "writer"] as Role[]).map(role => <label className="mp-checkbox" key={role}><input type="checkbox" checked={form[role] !== "no"} onChange={e => setForm({ ...form, [role]: e.target.checked ? "yes" : "no" })} />{roleLabels[role]}</label>)}
        {field("max_requests", "最多请求次数", "number", "100")}{field("hours", "授权有效小时", "number", "24")}
        <label className="mp-checkbox"><input type="checkbox" checked={form.risk === "yes"} onChange={e => setForm({ ...form, risk: e.target.checked ? "yes" : "no" })} />确认承担此连接的费用风险</label>
        <footer className="mp-actions"><button disabled={busy} onClick={close}>取消</button><button disabled={busy || form.risk !== "yes"} onClick={() => mutate(`/api/model-platforms/connections/${selected}/authorization`, "PUT", {
          roles: ["agent", "writer"].filter(role => form[role] !== "no"), risk_accepted: true, max_requests: Number(form.max_requests || 100), expires_at: Date.now() / 1000 + Number(form.hours || 24) * 3600,
        })}><ShieldCheck size={16} />保存授权</button></footer></>}
    </section></div>}
  </section>;
}

function PlayIcon() { return <Play size={15} />; }
