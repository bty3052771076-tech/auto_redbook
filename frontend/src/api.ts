export type Model = {
  id: string;
  provider: string;
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
