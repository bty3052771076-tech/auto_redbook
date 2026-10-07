export type Model = {
  id: string;
  provider: string;
  provider_name?: string;
  model: string;
  kind: string;
  remaining: number | null;
  total: number | null;
  used: number | null;
  unit: string;
  cost_class: string;
  quota_pool: string;
  status: string;
  selectable: boolean;
  disabled_reason: string;
  snapshot_at: number;
  expires_at: string;
};
export type Models = {
  rows: Model[];
  snapshots: { provider: string; at: number; name: string; errors: string[] }[];
  provider_labels?: Record<string, string>;
};
export type ProviderConnection = {
  id: string;
  name: string;
  label: string;
  builtin: boolean;
  protocol: string;
  base_url?: string;
  billing: string;
  configured: boolean;
  verification_status: string;
  models: { id: string; name: string; kind: string }[];
};
export type ProviderCatalog = {
  connections: ProviderConnection[];
  bindings: { agent: string; writer: string; image: string };
  roles: Record<string, string>;
};
export type Job = {
  id: string;
  kind: string;
  title: string;
  status: string;
  stage: string;
  message: string;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  exit_code: number | null;
  post_ids: string[];
  post_rows?: {
    id: string;
    title: string;
    text: string;
    images: number;
    status: string;
    readback: string;
  }[];
  events?: { id: number; at: number; message: string }[];
};
export type PostRow = {
  post_id: string;
  title: string;
  status: string;
  created_at: string;
  body_preview: string;
  asset_count: number;
  uploaded: boolean;
};
export type Post = {
  id: string;
  title: string;
  body: string;
  status: string;
  updated_at: string;
  topics: string[];
  readback: string;
  assets: { url: string; name: string }[];
  steps: { name: string; status: string; detail: string }[];
  platform: Record<string, unknown>;
};
export type AgentMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: number;
  plan_id?: string;
};
export type AgentJobPlan = {
  id: string;
  version: number;
  status: string;
  executable: boolean;
  jobs: { kind: string; title: string; count: number; prompt: string; keywords?: string[]; keyword_mode?: "default" | "filter" | "preference"; topic_brief?: string }[];
  plan_kind?: "editorial" | "draft_management";
  management?: { mode: string; draft_type: string; max_items: number; title_contains?: string; max_age_days?: number };
  platform: string;
  delivery: string;
  model_roles: { agent: string; writer: string; image: string };
  performance_mode: string;
  budget_minutes: number;
  assistant_summary: string;
};
export type AgentConversation = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  status: string;
  messages: AgentMessage[];
  plans: AgentJobPlan[];
  runs: string[];
};
export type AgentContextStatus = {
  status: string;
  snapshot_version?: number;
  through_seq?: number;
  raw_message_count?: number;
  active_context_tokens_estimate?: number;
  context?: { snapshot?: { summary?: string; constraints?: string[]; evidence_refs?: string[] } | null; recent_messages?: AgentMessage[] };
  reason?: string;
};
export type AgentCapabilities = {
  database: { status: string; documents?: number; index_ready?: boolean; error?: string };
  mcp: { status: string; tools: { name: string; description: string }[]; error?: string };
  skills: { status: string; items: { name: string; description: string; version_hash: string }[]; error?: string };
  compaction: { available: boolean; default_provider: string };
};
export type AgentEvent = {
  id: number;
  kind: "message" | "job";
  job_id?: string;
  message: AgentMessage | { id: number; at: number; message: string };
};
export type Bootstrap = {
  capabilities: {
    titles: string[];
    news_windows: number[];
    max_count: number;
    source_cap: number;
    platforms: string[];
  };
  settings: { performance_mode: string; platform: string };
  models: Models;
  providers: ProviderCatalog;
  jobs: Job[];
  profile: string;
  login_status: string;
  accounts: { provider: string; label: string; configured: boolean }[];
};
export const API = location.port === "5173" ? "http://127.0.0.1:8765" : "";
let token = "";
export async function connect() {
  const r = await fetch(API + "/api/session", {
    method: "POST",
    headers: { "X-Workbench": "1" },
  });
  if (!r.ok) throw new Error("本地服务连接失败，请检查启动终端");
  token = (await r.json()).token;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
): Promise<T> {
  const r = await fetch(API + "/api" + path, {
    method,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
      "X-Workbench": "1",
      ...(key ? { "Idempotency-Key": key } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "请求失败");
  return data;
}
export async function imageURL(url: string) {
  const response = await fetch(API + url, {
    headers: { Authorization: "Bearer " + token },
  });
  if (!response.ok) throw new Error("图片加载失败");
  return URL.createObjectURL(await response.blob());
}
export const providers: Record<string, string> = {
  aliyun: "阿里云",
  volcengine: "火山引擎",
  siliconflow: "硅基流动",
  minimax: "MiniMax",
};
export const stateLabel: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  stopping: "停止中",
  completed: "执行结束",
  partial_success: "有警告",
  failed: "失败",
  cancelled: "已停止",
  interrupted: "已中断",
  saved_as_draft: "已保存草稿",
  draft: "本地草稿",
  published: "已发布",
  approved: "已批准",
  unverified: "待读回",
  verified: "已读回",
  success: "通过",
  pending: "等待",
};
export const dateLabel = (v: string | number | null | undefined) =>
  !v
    ? "未记录"
    : new Date(typeof v === "number" ? v * 1000 : v).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      });
export const numberLabel = (v: number | null | undefined) =>
  v == null ? "未获取" : new Intl.NumberFormat("zh-CN").format(v);
export function download(name: string, text: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
