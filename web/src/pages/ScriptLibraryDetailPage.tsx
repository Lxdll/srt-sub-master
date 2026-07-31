import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarDays,
  Check,
  Copy,
  FileQuestion,
  LoaderCircle,
  Pencil,
  Trash2,
  UserRound,
  WandSparkles,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { AppShell } from "../components/AppShell";
import {
  HighlightedText,
  ScriptEditorDialog,
  formatScriptDate,
} from "../components/ScriptLibraryShared";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { hasPermission } from "../lib/permissions";

function DeleteScriptDialog({
  title,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  title: string;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const stateRef = useRef({ busy, onCancel });
  stateRef.current = { busy, onCancel };

  useEffect(() => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !stateRef.current.busy) {
        stateRef.current.onCancel();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLButtonElement>(
          "button:not(:disabled)",
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, []);

  return (
    <div
      className="script-library-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !busy) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        className="script-library-delete-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-script-title"
        aria-describedby="delete-script-description"
      >
        <button
          className="script-library-icon-button close"
          type="button"
          onClick={onCancel}
          disabled={busy}
          aria-label="关闭删除确认"
        >
          <X size={18} />
        </button>
        <span>
          <AlertTriangle size={24} aria-hidden="true" />
        </span>
        <h2 id="delete-script-title">确定删除这篇脚本？</h2>
        <p id="delete-script-description">
          “{title}”将从共享脚本库中永久删除，此操作无法撤销。
        </p>
        {error && <div role="alert">{error}</div>}
        <footer>
          <button
            ref={cancelRef}
            type="button"
            className="script-library-secondary-button"
            onClick={onCancel}
            disabled={busy}
          >
            取消
          </button>
          <button
            type="button"
            className="script-library-danger-button"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Trash2 size={16} />
            )}
            {busy ? "删除中…" : "确认删除"}
          </button>
        </footer>
      </section>
    </div>
  );
}

export function ScriptLibraryDetailPage() {
  const { user } = useAuth();
  const { scriptId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [copied, setCopied] = useState<"title" | "body" | "">("");
  const [copyError, setCopyError] = useState("");
  const copyTimerRef = useRef<number | null>(null);
  const script = useQuery({
    queryKey: ["script", scriptId],
    queryFn: () => api.script(scriptId),
    enabled: Boolean(scriptId),
  });
  const query = searchParams.get("q")?.trim() ?? "";
  const state = location.state as { from?: string } | null;
  const fallbackSearch = searchParams.toString();
  const backTarget =
    state?.from ??
    `/script-library${fallbackSearch ? `?${fallbackSearch}` : ""}`;

  useEffect(
    () => () => {
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    },
    [],
  );

  async function copyPart(kind: "title" | "body", value: string) {
    setCopyError("");
    try {
      await navigator.clipboard.writeText(value);
      setCopied(kind);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setCopied(""), 1_800);
    } catch {
      setCopyError("复制失败，请检查浏览器剪贴板权限后重试。");
    }
  }

  async function updateScript(title: string, body: string) {
    const updated = await api.updateScript(scriptId, { title, body });
    queryClient.setQueryData(["script", scriptId], updated);
    await queryClient.invalidateQueries({ queryKey: ["scripts"] });
    setEditorOpen(false);
  }

  async function deleteScript() {
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await api.deleteScript(scriptId);
      queryClient.removeQueries({ queryKey: ["script", scriptId] });
      await queryClient.invalidateQueries({ queryKey: ["scripts"] });
      navigate(backTarget, { replace: true });
    } catch (reason) {
      setDeleteError(
        reason instanceof Error ? reason.message : "删除失败，请稍后重试。",
      );
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <AppShell>
      <div className="script-library-detail-page">
        <Link className="script-library-back" to={backTarget}>
          <ArrowLeft size={17} aria-hidden="true" />
          返回脚本库
        </Link>

        {script.isPending ? (
          <section className="script-library-state detail">
            <LoaderCircle className="spin" size={27} />
            <h2>正在打开脚本…</h2>
          </section>
        ) : script.isError || !script.data ? (
          <section className="script-library-state detail error" role="alert">
            <FileQuestion size={31} />
            <h1>没有找到这篇脚本</h1>
            <p>
              {script.error?.message ??
                "它可能已经被其他成员删除，或你没有查看权限。"}
            </p>
            <Link to={backTarget}>返回脚本库</Link>
          </section>
        ) : (
          <article className="script-library-detail">
            <header className="script-library-detail-head">
              <div className="script-library-detail-title">
                {query && <span>当前搜索：{query}</span>}
                <h1 aria-label={script.data.title}>
                  <HighlightedText text={script.data.title} query={query} />
                </h1>
              </div>
              <div className="script-library-detail-actions">
                {hasPermission(user, "script_fission") && (
                  <Link
                    className="script-library-secondary-button"
                    to={`/script-fission?scriptId=${encodeURIComponent(scriptId)}`}
                  >
                    <WandSparkles size={16} /> 基于此脚本裂变
                  </Link>
                )}
                <button
                  type="button"
                  className="script-library-secondary-button"
                  onClick={() => void copyPart("title", script.data.title)}
                >
                  {copied === "title" ? (
                    <Check size={16} />
                  ) : (
                    <Copy size={16} />
                  )}
                  {copied === "title" ? "已复制" : "复制标题"}
                </button>
                <button
                  type="button"
                  className="script-library-secondary-button"
                  onClick={() => void copyPart("body", script.data.body)}
                >
                  {copied === "body" ? (
                    <Check size={16} />
                  ) : (
                    <Copy size={16} />
                  )}
                  {copied === "body" ? "已复制" : "复制正文"}
                </button>
                <button
                  type="button"
                  className="script-library-secondary-button"
                  onClick={() => setEditorOpen(true)}
                >
                  <Pencil size={16} /> 编辑
                </button>
                <button
                  type="button"
                  className="script-library-delete-button"
                  onClick={() => {
                    setDeleteError("");
                    setDeleteOpen(true);
                  }}
                >
                  <Trash2 size={16} /> 删除
                </button>
              </div>
              <div className="script-library-copy-status" aria-live="polite">
                {copyError}
              </div>
            </header>

            <dl className="script-library-detail-meta">
              <div>
                <UserRound size={15} aria-hidden="true" />
                <dt>创建人</dt>
                <dd>{script.data.created_by.username}</dd>
              </div>
              <div>
                <UserRound size={15} aria-hidden="true" />
                <dt>最后修改</dt>
                <dd>{script.data.updated_by.username}</dd>
              </div>
              <div>
                <CalendarDays size={15} aria-hidden="true" />
                <dt>创建时间</dt>
                <dd>
                  <time dateTime={script.data.created_at}>
                    {formatScriptDate(script.data.created_at)}
                  </time>
                </dd>
              </div>
              <div>
                <CalendarDays size={15} aria-hidden="true" />
                <dt>更新时间</dt>
                <dd>
                  <time dateTime={script.data.updated_at}>
                    {formatScriptDate(script.data.updated_at)}
                  </time>
                </dd>
              </div>
              <div>
                <dt>正文长度</dt>
                <dd>{script.data.character_count.toLocaleString()} 字</dd>
              </div>
            </dl>

            <section className="script-library-detail-body">
              <div>
                <span>脚本正文</span>
                <small>{script.data.character_count.toLocaleString()} 字</small>
              </div>
              <p>
                <HighlightedText text={script.data.body} query={query} />
              </p>
            </section>
          </article>
        )}
      </div>

      {editorOpen && script.data && (
        <ScriptEditorDialog
          initial={{ title: script.data.title, body: script.data.body }}
          onClose={() => setEditorOpen(false)}
          onSave={updateScript}
        />
      )}
      {deleteOpen && script.data && (
        <DeleteScriptDialog
          title={script.data.title}
          busy={deleteBusy}
          error={deleteError}
          onCancel={() => {
            if (!deleteBusy) setDeleteOpen(false);
          }}
          onConfirm={() => void deleteScript()}
        />
      )}
    </AppShell>
  );
}
