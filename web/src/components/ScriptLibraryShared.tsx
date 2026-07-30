import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Keyboard,
  LoaderCircle,
  Save,
  UploadCloud,
  X,
} from "lucide-react";
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import { DocxError, extractDocxText } from "../lib/docx";
import type { ScriptLibraryDetail } from "../types";

export const MAX_SCRIPT_TITLE_LENGTH = 255;
export const MAX_SCRIPT_BODY_LENGTH = 30_000;
export const MAX_SCRIPT_DOCX_BYTES = 10 * 1024 * 1024;

export function formatScriptDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function HighlightedText({
  text,
  query,
}: {
  text: string;
  query: string;
}) {
  const keyword = query.trim();
  if (!keyword) return <>{text}</>;

  const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matcher = new RegExp(escapedKeyword, "giu");
  const parts: ReactNode[] = [];
  let cursor = 0;
  let match = matcher.exec(text);
  while (match) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index));
    parts.push(
      <mark key={`${match.index}-${parts.length}`}>
        {match[0]}
      </mark>,
    );
    cursor = match.index + match[0].length;
    match = matcher.exec(text);
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>{part}</Fragment>
      ))}
    </>
  );
}

type ScriptEditorDialogProps = {
  initial?: Pick<ScriptLibraryDetail, "title" | "body">;
  onClose: () => void;
  onSave: (title: string, body: string) => Promise<void>;
};

export function ScriptEditorDialog({
  initial,
  onClose,
  onSave,
}: ScriptEditorDialogProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  const [source, setSource] = useState<"text" | "docx">("text");
  const [busy, setBusy] = useState(false);
  const [readingFile, setReadingFile] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [titleTouched, setTitleTouched] = useState(Boolean(initial));
  const dialogRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const closeStateRef = useRef({ dirty: false, busy: false, readingFile: false });
  const initialTitle = initial?.title ?? "";
  const initialBody = initial?.body ?? "";
  const dirty = title !== initialTitle || body !== initialBody;
  closeStateRef.current = { dirty, busy, readingFile };

  function requestClose() {
    const current = closeStateRef.current;
    if (current.busy || current.readingFile) return;
    if (current.dirty && !window.confirm("当前内容尚未保存，确定关闭吗？")) {
      return;
    }
    onClose();
  }

  useEffect(() => {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    const timer = window.setTimeout(() => titleRef.current?.focus(), 0);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        requestClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
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
      window.clearTimeout(timer);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, []);

  async function readDocx(file: File) {
    setError("");
    if (file.size > MAX_SCRIPT_DOCX_BYTES) {
      setError("Word 文件不能超过 10MB，请压缩或拆分后再试。");
      return;
    }
    if (
      body.trim() &&
      !window.confirm("当前已有正文，是否用 Word 文档中的内容替换？")
    ) {
      return;
    }
    setReadingFile(true);
    try {
      const extracted = await extractDocxText(file);
      if (extracted.length > MAX_SCRIPT_BODY_LENGTH) {
        setError(
          `文档正文超过 ${MAX_SCRIPT_BODY_LENGTH.toLocaleString()} 字，请精简后再保存。`,
        );
        return;
      }
      const defaultTitle = file.name.replace(/\.docx$/i, "").trim();
      setBody(extracted);
      setFileName(file.name);
      if (!initial && !titleTouched && defaultTitle) setTitle(defaultTitle);
    } catch (reason) {
      setError(
        reason instanceof DocxError
          ? reason.message
          : "Word 文档读取失败，请检查文件后重试。",
      );
    } finally {
      setReadingFile(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void readDocx(file);
  }

  function dropFile(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void readDocx(file);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const normalizedTitle = title.trim();
    const normalizedBody = body.trim();
    if (!normalizedTitle) {
      setError("请输入脚本标题。");
      titleRef.current?.focus();
      return;
    }
    if (!normalizedBody) {
      setError("请输入脚本正文，或从 Word 文档导入。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSave(normalizedTitle, body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="script-library-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) requestClose();
      }}
    >
      <section
        ref={dialogRef}
        className="script-library-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="script-editor-title"
        aria-describedby="script-editor-description"
      >
        <header className="script-library-dialog-head">
          <div>
            <span className="script-library-dialog-icon">
              <FileText size={20} aria-hidden="true" />
            </span>
            <div>
              <small>{initial ? "EDIT SCRIPT" : "ADD TO LIBRARY"}</small>
              <h2 id="script-editor-title">
                {initial ? "编辑脚本" : "新增脚本"}
              </h2>
              <p id="script-editor-description">
                标题和正文将保存到团队共享脚本库。
              </p>
            </div>
          </div>
          <button
            type="button"
            className="script-library-icon-button"
            onClick={requestClose}
            disabled={busy || readingFile}
            aria-label="关闭脚本编辑窗口"
          >
            <X size={19} />
          </button>
        </header>

        <form className="script-library-form" onSubmit={submit}>
          <label className="script-library-title-field">
            <span>
              标题 <strong>必填</strong>
            </span>
            <input
              ref={titleRef}
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                setTitleTouched(true);
                setError("");
              }}
              maxLength={MAX_SCRIPT_TITLE_LENGTH}
              placeholder="例如：夏日新品短视频脚本"
              disabled={busy}
              required
            />
            <small>
              {title.length}/{MAX_SCRIPT_TITLE_LENGTH}
            </small>
          </label>

          <fieldset className="script-library-source">
            <legend>正文来源</legend>
            <div className="script-library-source-tabs">
              <button
                type="button"
                className={source === "text" ? "active" : ""}
                aria-pressed={source === "text"}
                onClick={() => setSource("text")}
              >
                <Keyboard size={16} /> 直接输入
              </button>
              <button
                type="button"
                className={source === "docx" ? "active" : ""}
                aria-pressed={source === "docx"}
                onClick={() => setSource("docx")}
              >
                <UploadCloud size={16} /> 导入 Word
              </button>
            </div>
          </fieldset>

          {source === "docx" && (
            <div
              className={`script-library-dropzone ${dragging ? "dragging" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                  setDragging(false);
                }
              }}
              onDrop={dropFile}
            >
              <input
                ref={fileRef}
                type="file"
                accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={chooseFile}
                disabled={readingFile || busy}
                aria-label="选择 Word 文档"
              />
              <UploadCloud size={21} aria-hidden="true" />
              <span>
                {readingFile
                  ? "正在读取文档…"
                  : fileName || "拖入 .docx，或点击选择文件"}
              </span>
              <small>最大 10MB，文件仅在当前浏览器中读取</small>
            </div>
          )}

          <label className="script-library-body-field">
            <span>
              正文 <strong>必填</strong>
            </span>
            <textarea
              value={body}
              onChange={(event) => {
                setBody(event.target.value);
                setError("");
              }}
              maxLength={MAX_SCRIPT_BODY_LENGTH}
              placeholder="在这里粘贴或输入完整脚本…"
              disabled={busy || readingFile}
              required
            />
            <small>
              {body.length.toLocaleString()}/
              {MAX_SCRIPT_BODY_LENGTH.toLocaleString()} 字
            </small>
          </label>

          <div className="script-library-form-footer">
            <div className="script-library-form-message" aria-live="polite">
              {error && (
                <span role="alert">
                  <AlertCircle size={15} aria-hidden="true" />
                  {error}
                </span>
              )}
              {!error && fileName && (
                <span className="success">
                  <CheckCircle2 size={15} aria-hidden="true" />
                  已读取 {fileName}
                </span>
              )}
            </div>
            <div>
              <button
                type="button"
                className="script-library-secondary-button"
                onClick={requestClose}
                disabled={busy || readingFile}
              >
                取消
              </button>
              <button
                type="submit"
                className="script-library-primary-button"
                disabled={
                  busy ||
                  readingFile ||
                  !title.trim() ||
                  !body.trim() ||
                  (!dirty && Boolean(initial))
                }
              >
                {busy ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Save size={17} />
                )}
                {busy ? "保存中…" : initial ? "保存修改" : "保存到脚本库"}
              </button>
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}
