import { useEffect, useRef, useState } from "react";
import { Check, CheckCircle2, Image, RefreshCw, X } from "lucide-react";
import "./WoolGallery.css";

type Row = {
  id: string;
  filename: string;
  image_url: string;
  status: string;
  kind: string;
  artist?: string;
  post_url?: string;
  source?: string;
  rating?: string;
  reference_style?: string;
  note?: string;
  rights_confirmed?: boolean;
};
type Library = {
  rows: Row[];
  selected_id: string;
  root: string;
  warnings: string[];
};
type Request = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
const statusNames: Record<string, string> = {
  pending: "待筛选",
  approved: "已入选",
  rejected: "已排除",
  legacy: "原有参考",
  persona: "人设",
};

function sourceLink(url?: string) {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol)
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function WoolGallery({ request }: { request: Request }) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [tab, setTab] = useState("candidate");
  const [status, setStatus] = useState("pending");
  const [view, setView] = useState<Row | null>(null);
  const [adult, setAdult] = useState(false);
  const [nonExplicit, setNonExplicit] = useState(false);
  const [rights, setRights] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [count, setCount] = useState(10);
  const [style, setStyle] = useState("mixed");
  const dialogRef = useRef<HTMLElement>(null);

  async function reload() {
    setLibrary(await request<Library>("/wool-library"));
  }
  useEffect(() => {
    reload().catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!view) return;
    const old = document.body.style.overflow;
    const previous = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    const focusable = () =>
      Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), a[href], input, textarea",
        ) || [],
      );
    focusable()[0]?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) setView(null);
      if (event.key !== "Tab") return;
      const nodes = focusable();
      if (!nodes.length) {
        event.preventDefault();
        return;
      }
      if (event.shiftKey && document.activeElement === nodes[0]) {
        event.preventDefault();
        nodes[nodes.length - 1].focus();
      } else if (
        !event.shiftKey &&
        document.activeElement === nodes[nodes.length - 1]
      ) {
        event.preventDefault();
        nodes[0].focus();
      }
    };
    window.addEventListener("keydown", close);
    return () => {
      document.body.style.overflow = old;
      window.removeEventListener("keydown", close);
      if (previous?.isConnected) previous.focus();
    };
  }, [view, busy]);

  async function action(name: string, body: unknown) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<{ downloaded?: number; errors?: string[] }>(
        `/wool-library/${name}`,
        "POST",
        body,
      );
      await reload();
      if (name === "fetch")
        setNotice(
          `新增候选 ${result.downloaded ?? 0} 张${result.errors?.length ? " · " + result.errors.join("；") : ""}`,
        );
      else {
        setView(null);
        setNotice(name === "review" ? "人工筛选已保存" : "参考图选择已保存");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const rows = (library?.rows || []).filter((row) =>
    tab === "reference"
      ? ["approved", "legacy"].includes(row.status)
      : tab === "persona"
        ? row.kind === "persona"
        : row.kind === "candidate" && row.status === status,
  );
  const open = (row: Row) => {
    setView(row);
    setAdult(false);
    setNonExplicit(false);
    setRights(false);
    setNote(row.note || "");
    setError("");
  };
  const selected = library?.rows.find((row) => row.id === library.selected_id);
  const reviewable = view && view.kind !== "persona";

  return (
    <section className="wool-gallery" aria-label="AI鸡蛋参考图库">
      <header className="wool-heading">
        <h2>
          <Image size={20} />
          AI鸡蛋参考图库
        </h2>
        <button
          type="button"
          title="刷新图库"
          aria-label="刷新图库"
          disabled={busy}
          onClick={() => reload().catch((e) => setError(String(e)))}
        >
          <RefreshCw size={16} />
        </button>
      </header>
      <div className="wool-tabs" role="tablist" aria-label="图片类型">
        {[
          ["candidate", "候选图"],
          ["reference", "参考原图"],
          ["persona", "人设图"],
        ].map(([value, label]) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === value}
            className={tab === value ? "selected" : ""}
            key={value}
            onClick={() => setTab(value)}
          >
            {label}{" "}
            <small>
              {
                (library?.rows || []).filter((row) =>
                  value === "reference"
                    ? ["approved", "legacy"].includes(row.status)
                    : row.kind === value,
                ).length
              }
            </small>
          </button>
        ))}
      </div>
      {tab === "candidate" && (
        <div className="wool-toolbar">
          <label>
            状态
            <select
              aria-label="状态"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="pending">待筛选</option>
              <option value="rejected">已排除</option>
            </select>
          </label>
          <label>
            风格
            <select
              aria-label="风格"
              value={style}
              onChange={(e) => setStyle(e.target.value)}
            >
              <option value="mixed">综合</option>
              <option value="office">职场</option>
              <option value="dress">礼服</option>
              <option value="casual">清新居家</option>
              <option value="summer">夏日外景</option>
            </select>
          </label>
          <label>
            数量
            <input
              aria-label="数量"
              type="number"
              min={1}
              max={30}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            disabled={busy || count < 1 || count > 30}
            onClick={() => action("fetch", { count, style })}
          >
            <RefreshCw size={16} />
            {busy ? "处理中" : "获取候选"}
          </button>
        </div>
      )}
      {tab === "reference" && (
        <div className="wool-selection">
          <span>当前参考：{selected?.filename || "按日期与厂商自动选择"}</span>
          <button
            type="button"
            disabled={busy || !library?.selected_id}
            onClick={() => action("select", { id: "" })}
          >
            恢复自动选择
          </button>
        </div>
      )}
      {error && (
        <p className="wool-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="wool-notice" role="status">
          {notice}
        </p>
      )}
      {library?.warnings.map((warning, i) => (
        <p className="wool-error" key={i}>
          {warning}
        </p>
      ))}
      {!library ? (
        <p>正在读取图库…</p>
      ) : !rows.length ? (
        <p className="wool-empty">
          {tab === "candidate" ? "暂无此状态的候选图" : "暂无图片"}
        </p>
      ) : (
        <div className="wool-grid">
          {rows.map((row) => (
            <article className="wool-item" key={row.id}>
              <button
                type="button"
                className="wool-preview"
                onClick={() => open(row)}
                aria-label={`查看 ${row.filename}`}
              >
                <img loading="lazy" src={row.image_url} alt={row.filename} />
                {library.selected_id === row.id && (
                  <span className="wool-selected">
                    <CheckCircle2 size={14} />
                    当前使用
                  </span>
                )}
              </button>
              <div className="wool-item-info">
                <strong title={row.filename}>{row.filename}</strong>
                <span>
                  {statusNames[row.status]} ·{" "}
                  {row.reference_style || row.artist || "本地素材"}
                </span>
                <span>
                  权限：{row.rights_confirmed ? "用户已确认" : "未核验"}
                </span>
              </div>
            </article>
          ))}
        </div>
      )}
      {view && (
        <div
          className="wool-backdrop"
          onClick={() => {
            if (!busy) setView(null);
          }}
        >
          <section
            ref={dialogRef}
            className="wool-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="图片预览与人工筛选"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <h3>{view.filename}</h3>
              <button
                type="button"
                title="关闭预览"
                aria-label="关闭预览"
                disabled={busy}
                onClick={() => setView(null)}
              >
                <X size={18} />
              </button>
            </header>
            <div className="wool-dialog-body">
              <div className="wool-full-image">
                <img src={view.image_url} alt={view.filename} />
              </div>
              <div className="wool-review">
                <p>
                  {statusNames[view.status]} · 作者：{view.artist || "未记录"} ·
                  分级：{view.rating || "未记录"}
                </p>
                {sourceLink(view.post_url) && (
                  <a
                    href={sourceLink(view.post_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    原帖与作者信息
                  </a>
                )}
                {sourceLink(view.source) && (
                  <a
                    href={sourceLink(view.source)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    原始来源
                  </a>
                )}
                {reviewable && (
                  <>
                    <label>
                      <input
                        type="checkbox"
                        checked={adult}
                        onChange={(e) => setAdult(e.target.checked)}
                      />
                      确认人物成年，无幼态或年龄疑义
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={nonExplicit}
                        onChange={(e) => setNonExplicit(e.target.checked)}
                      />
                      确认非露骨，无不适合发布的内容
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={rights}
                        onChange={(e) => setRights(e.target.checked)}
                      />
                      确认拥有相应参考与描改使用权限
                    </label>
                    <label>
                      筛选备注
                      <textarea
                        rows={3}
                        maxLength={1000}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </label>
                    <div className="wool-review-actions">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          action("review", {
                            id: view.id,
                            decision: "reject",
                            note,
                          })
                        }
                      >
                        <X size={16} />
                        {view.status === "approved" ? "撤销入选" : "排除"}
                      </button>
                      <button
                        type="button"
                        className="wool-primary"
                        disabled={busy || !adult || !nonExplicit || !rights}
                        onClick={() =>
                          action("review", {
                            id: view.id,
                            decision: "approve",
                            adult_confirmed: adult,
                            non_explicit_confirmed: nonExplicit,
                            rights_confirmed: rights,
                            note,
                          })
                        }
                      >
                        <Check size={16} />
                        入选参考原图
                      </button>
                    </div>
                    {view.status === "approved" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => action("select", { id: view.id })}
                      >
                        指定使用此参考图
                      </button>
                    )}
                  </>
                )}
                {error && (
                  <p className="wool-error" role="alert">
                    {error}
                  </p>
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
