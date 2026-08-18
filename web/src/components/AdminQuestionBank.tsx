import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  History,
  Pencil,
  Plus,
  Power,
  RotateCcw,
  Save,
  Search,
  X,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { api } from "../lib/api";
import type {
  AdminContentCreativeQuestion,
  ContentCreativeOption,
  ContentCreativeQuestionType,
} from "../types";

const PAGE_SIZE = 50;
const TYPE_LABELS: Record<ContentCreativeQuestionType, string> = {
  single: "单选",
  multiple: "多选",
  judgment: "判断",
};
const ACTION_LABELS: Record<string, string> = {
  import: "初始导入",
  create: "新增题目",
  update: "修改题目",
  enable: "启用题目",
  disable: "停用题目",
  restore: "恢复历史版本",
};

type QuestionDraft = Pick<
  AdminContentCreativeQuestion,
  "source" | "question_type" | "prompt" | "options" | "correct_options" | "note"
>;

function emptyDraft(source = ""): QuestionDraft {
  return {
    source,
    question_type: "single",
    prompt: "",
    options: ["A", "B", "C", "D"].map((key) => ({ key, text: "" })),
    correct_options: ["A"],
    note: null,
  };
}

function questionDraft(question: AdminContentCreativeQuestion): QuestionDraft {
  return {
    source: question.source,
    question_type: question.question_type,
    prompt: question.prompt,
    options: question.options.map((item) => ({ ...item })),
    correct_options: [...question.correct_options],
    note: question.note,
  };
}

function sameGrading(left: QuestionDraft, right: QuestionDraft) {
  return (
    left.question_type === right.question_type &&
    JSON.stringify(left.options) === JSON.stringify(right.options) &&
    JSON.stringify(left.correct_options) === JSON.stringify(right.correct_options)
  );
}

function questionValidation(draft: QuestionDraft) {
  if (!draft.source.trim()) return "请输入题目来源。";
  if (!draft.prompt.trim()) return "请输入题目描述。";
  if (draft.options.length < 2 || draft.options.some((item) => !item.text.trim())) {
    return "至少需要两个有内容的选项。";
  }
  if (draft.question_type === "single" && draft.correct_options.length !== 1) {
    return "单选题只能设置一个正确答案。";
  }
  if (draft.question_type === "multiple" && draft.correct_options.length < 2) {
    return "多选题至少需要两个正确答案。";
  }
  if (draft.question_type === "judgment" && draft.correct_options.length !== 1) {
    return "判断题只能设置一个正确答案。";
  }
  return "";
}

function QuestionEditor({
  question,
  defaultSource,
  onClose,
}: {
  question: AdminContentCreativeQuestion | null;
  defaultSource: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<QuestionDraft>(() =>
    question ? questionDraft(question) : emptyDraft(defaultSource),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const validation = questionValidation(draft);

  function changeType(questionType: ContentCreativeQuestionType) {
    setError("");
    setDraft((current) => {
      if (questionType === "judgment") {
        return {
          ...current,
          question_type: questionType,
          options: [
            { key: "A", text: "正确" },
            { key: "B", text: "错误" },
          ],
          correct_options: ["A"],
        };
      }
      const options =
        current.question_type === "judgment"
          ? ["A", "B", "C", "D"].map((key) => ({ key, text: "" }))
          : current.options;
      return {
        ...current,
        question_type: questionType,
        options,
        correct_options:
          questionType === "single" ? [options[0].key] : options.slice(0, 2).map((item) => item.key),
      };
    });
  }

  function updateOption(index: number, text: string) {
    setDraft((current) => ({
      ...current,
      options: current.options.map((item, optionIndex) =>
        optionIndex === index ? { ...item, text } : item,
      ),
    }));
  }

  function addOption() {
    setDraft((current) => ({
      ...current,
      options: [
        ...current.options,
        { key: String.fromCharCode(65 + current.options.length), text: "" },
      ],
    }));
  }

  function removeOption(index: number) {
    setDraft((current) => {
      const removedKey = current.options[index].key;
      const options = current.options
        .filter((_, optionIndex) => optionIndex !== index)
        .map((item, optionIndex) => ({ ...item, key: String.fromCharCode(65 + optionIndex) }));
      const oldCorrectIndexes = current.correct_options
        .filter((key) => key !== removedKey)
        .map((key) => current.options.findIndex((item) => item.key === key))
        .filter((optionIndex) => optionIndex >= 0)
        .map((optionIndex) => (optionIndex > index ? optionIndex - 1 : optionIndex));
      return {
        ...current,
        options,
        correct_options: oldCorrectIndexes.map((optionIndex) => options[optionIndex]?.key).filter(Boolean),
      };
    });
  }

  function toggleCorrect(key: string) {
    setDraft((current) => ({
      ...current,
      correct_options:
        current.question_type === "multiple"
          ? current.correct_options.includes(key)
            ? current.correct_options.filter((item) => item !== key)
            : [...current.correct_options, key].sort()
          : [key],
    }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (validation) {
      setError(validation);
      return;
    }
    const original = question ? questionDraft(question) : null;
    if (
      original &&
      !sameGrading(original, draft) &&
      !window.confirm("题型、选项或正确答案已改变。新场次会启用新的判题版本，确认保存吗？")
    ) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (question) {
        await api.updateAdminContentCreativeQuestion(question.id, {
          ...draft,
          expected_version: question.content_version,
        });
      } else {
        await api.createAdminContentCreativeQuestion(draft);
      }
      await queryClient.invalidateQueries({ queryKey: ["admin-content-creative-questions"] });
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "题目保存失败。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="question-admin-dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="question-admin-dialog" role="dialog" aria-modal="true" aria-labelledby="question-editor-title">
        <header>
          <div>
            <span><Pencil size={18} /></span>
            <div>
              <h2 id="question-editor-title">{question ? `编辑第 ${question.serial} 题` : "新增题目"}</h2>
              <p>保存前请检查学员视角预览和正确答案。</p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭编辑器"><X size={18} /></button>
        </header>
        <form onSubmit={save}>
          <div className="question-editor-grid">
            <div className="question-editor-fields">
              <label>题目来源<input value={draft.source} onChange={(event) => setDraft((current) => ({ ...current, source: event.target.value }))} /></label>
              <label>题型<select value={draft.question_type} onChange={(event) => changeType(event.target.value as ContentCreativeQuestionType)}>
                {Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></label>
              <label>题目描述<textarea rows={5} value={draft.prompt} onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))} /></label>
              <fieldset className="question-option-editor">
                <legend>选项与正确答案</legend>
                {draft.options.map((option, index) => (
                  <div key={option.key}>
                    <label className="question-correct-toggle" title="设为正确答案">
                      <input type={draft.question_type === "multiple" ? "checkbox" : "radio"} name="correct-option" checked={draft.correct_options.includes(option.key)} onChange={() => toggleCorrect(option.key)} />
                      <span>{option.key}</span>
                    </label>
                    <input value={option.text} disabled={draft.question_type === "judgment"} onChange={(event) => updateOption(index, event.target.value)} aria-label={`选项 ${option.key}`} />
                    {draft.question_type !== "judgment" && draft.options.length > 2 && (
                      <button type="button" onClick={() => removeOption(index)} aria-label={`删除选项 ${option.key}`}><X size={15} /></button>
                    )}
                  </div>
                ))}
                {draft.question_type !== "judgment" && draft.options.length < 8 && (
                  <button type="button" className="question-add-option" onClick={addOption}><Plus size={15} /> 添加选项</button>
                )}
              </fieldset>
              <label>备注 / 解析<textarea rows={4} value={draft.note ?? ""} onChange={(event) => setDraft((current) => ({ ...current, note: event.target.value || null }))} placeholder="没有解析可以留空" /></label>
            </div>
            <aside className="question-live-preview">
              <span>学员视角预览</span>
              <div className="question-preview-tags"><b>{TYPE_LABELS[draft.question_type]}</b><em>{draft.source || "未填写来源"}</em></div>
              <h3>{draft.prompt || "题目描述将显示在这里"}</h3>
              <div className="question-preview-options">
                {draft.options.map((option) => <div className={draft.correct_options.includes(option.key) ? "correct" : ""} key={option.key}><strong>{option.key}</strong><span>{option.text || "未填写选项"}</span></div>)}
              </div>
              <small>绿色描边仅供管理员确认正确答案，学员作答前不会看到。</small>
            </aside>
          </div>
          {error && <div className="question-admin-message error" role="alert"><AlertTriangle size={16} />{error}</div>}
          <footer><button type="button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy}><Save size={16} />{busy ? "保存中…" : "保存题目"}</button></footer>
        </form>
      </section>
    </div>
  );
}

function VersionHistory({ question, onClose }: { question: AdminContentCreativeQuestion; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [busyVersion, setBusyVersion] = useState<number | null>(null);
  const [error, setError] = useState("");
  const versions = useQuery({
    queryKey: ["admin-content-creative-question-versions", question.id],
    queryFn: () => api.adminContentCreativeQuestionVersions(question.id),
  });
  const fields = [
    ["source", "来源"], ["question_type", "题型"], ["prompt", "题目"],
    ["options", "选项"], ["correct_options", "答案"], ["note", "备注"], ["is_active", "状态"],
  ] as const;

  async function restore(version: number) {
    if (!window.confirm(`确认将题目恢复到版本 ${version}？当前内容会保留在历史中。`)) return;
    setBusyVersion(version);
    setError("");
    try {
      await api.restoreAdminContentCreativeQuestion(question.id, version, question.content_version);
      await queryClient.invalidateQueries({ queryKey: ["admin-content-creative-questions"] });
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "恢复失败。");
    } finally {
      setBusyVersion(null);
    }
  }

  return (
    <div className="question-admin-dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="question-history-dialog" role="dialog" aria-modal="true" aria-labelledby="question-history-title">
        <header><div><span><History size={18} /></span><div><h2 id="question-history-title">第 {question.serial} 题修改历史</h2><p>恢复旧版本不会删除后续记录。</p></div></div><button type="button" onClick={onClose} aria-label="关闭历史"><X size={18} /></button></header>
        {versions.isLoading ? <div className="question-admin-state">正在读取历史…</div> : versions.isError ? <div className="question-admin-state error">历史记录读取失败。</div> : (
          <div className="question-version-list">
            {versions.data?.map((version, index) => {
              const older = versions.data[index + 1]?.snapshot;
              const changed = older ? fields.filter(([key]) => JSON.stringify(version.snapshot[key]) !== JSON.stringify(older[key])).map(([, label]) => label) : [];
              return <article key={version.version_number}>
                <div className="question-version-marker"><Clock3 size={15} /></div>
                <div><header><strong>版本 {version.version_number} · {ACTION_LABELS[version.action]}</strong><span>{new Date(version.created_at).toLocaleString("zh-CN")}</span></header><p>{version.admin_username ? `操作人：${version.admin_username}` : "由初始 Excel 导入"}</p>{changed.length > 0 && <div className="question-version-changes">变更：{changed.join("、")}</div>}<blockquote>{version.snapshot.prompt}</blockquote></div>
                {version.version_number !== question.content_version && <button type="button" disabled={busyVersion !== null} onClick={() => restore(version.version_number)}><RotateCcw size={14} />{busyVersion === version.version_number ? "恢复中…" : "恢复"}</button>}
              </article>;
            })}
          </div>
        )}
        {error && <div className="question-admin-message error"><AlertTriangle size={16} />{error}</div>}
      </section>
    </div>
  );
}

export function AdminQuestionBank() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [questionType, setQuestionType] = useState<ContentCreativeQuestionType | "">("");
  const [status, setStatus] = useState<"all" | "active" | "inactive">("all");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [sort, setSort] = useState<"serial" | "updated">("serial");
  const [offset, setOffset] = useState(0);
  const [editor, setEditor] = useState<AdminContentCreativeQuestion | "new" | null>(null);
  const [history, setHistory] = useState<AdminContentCreativeQuestion | null>(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const params = useMemo(() => ({ query, source, question_type: questionType || undefined, status, needs_review: reviewOnly ? true : undefined, sort, offset, limit: PAGE_SIZE }), [query, source, questionType, status, reviewOnly, sort, offset]);
  const questions = useQuery({ queryKey: ["admin-content-creative-questions", params], queryFn: () => api.adminContentCreativeQuestions(params) });

  function updateFilter(callback: () => void) { setOffset(0); callback(); }
  async function toggleStatus(question: AdminContentCreativeQuestion) {
    const action = question.is_active ? "停用" : "启用";
    if (!window.confirm(`确认${action}第 ${question.serial} 题？`)) return;
    setBusyId(question.id); setError("");
    try {
      await api.setAdminContentCreativeQuestionStatus(question.id, question.content_version, !question.is_active);
      await queryClient.invalidateQueries({ queryKey: ["admin-content-creative-questions"] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : `${action}失败。`); }
    finally { setBusyId(""); }
  }
  const summary = questions.data?.summary;
  return <div className="question-admin-page">
    <section className="question-admin-hero"><div><span className="eyebrow">QUESTION BANK ADMINISTRATION</span><h1>内容创意题库管理</h1><p>校对题目、选项和答案，每次修改都可以追溯和恢复。</p></div><button type="button" className="primary-button" onClick={() => setEditor("new")}><Plus size={17} />新增题目</button></section>
    <section className="question-admin-stats">
      <article><BookOpenCheck size={18} /><span>启用题目</span><strong>{summary?.active ?? "—"}</strong></article>
      <article><Power size={18} /><span>停用题目</span><strong>{summary?.inactive ?? "—"}</strong></article>
      <article className={summary?.needs_review ? "warning" : ""}><AlertTriangle size={18} /><span>待复核</span><strong>{summary?.needs_review ?? "—"}</strong></article>
      <article><CheckCircle2 size={18} /><span>题型</span><strong>3</strong></article>
    </section>
    <section className="question-admin-panel">
      <div className="question-admin-filters">
        <label className="question-admin-search"><Search size={16} /><input value={query} onChange={(event) => updateFilter(() => setQuery(event.target.value))} placeholder="搜索题目或来源" /></label>
        <select aria-label="题目来源" value={source} onChange={(event) => updateFilter(() => setSource(event.target.value))}><option value="">全部来源</option>{summary?.sources.map((item) => <option key={item} value={item}>{item}</option>)}</select>
        <select aria-label="题型" value={questionType} onChange={(event) => updateFilter(() => setQuestionType(event.target.value as ContentCreativeQuestionType | ""))}><option value="">全部题型</option>{Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <select aria-label="启用状态" value={status} onChange={(event) => updateFilter(() => setStatus(event.target.value as typeof status))}><option value="all">全部状态</option><option value="active">已启用</option><option value="inactive">已停用</option></select>
        <select aria-label="排序" value={sort} onChange={(event) => updateFilter(() => setSort(event.target.value as typeof sort))}><option value="serial">按原序号</option><option value="updated">最近修改</option></select>
        <label className="question-review-filter"><input type="checkbox" checked={reviewOnly} onChange={(event) => updateFilter(() => setReviewOnly(event.target.checked))} />只看待复核</label>
      </div>
      {error && <div className="question-admin-message error"><AlertTriangle size={16} />{error}</div>}
      {questions.isLoading ? <div className="question-admin-state">正在读取题库…</div> : questions.isError ? <div className="question-admin-state error">题库读取失败。</div> : questions.data?.items.length ? <div className="question-admin-list">{questions.data.items.map((question) => <article className={!question.is_active ? "inactive" : ""} key={question.id}>
        <div className="question-admin-number">{question.serial}</div><div className="question-admin-copy"><div className="question-admin-tags"><span>{TYPE_LABELS[question.question_type]}</span><em>{question.source}</em>{!question.is_active && <b>已停用</b>}{question.needs_review && <b className="review">待复核</b>}</div><h3>{question.prompt}</h3><p>{question.options.map((item) => `${item.key}. ${item.text}`).join("　")}</p><small>答案：{question.correct_options.join("")} · 版本 {question.content_version}{question.updated_by_username ? ` · ${question.updated_by_username} 修改` : ""}</small>{question.review_notes.length > 0 && <div className="question-review-note"><AlertTriangle size={14} />{question.review_notes.join("；")}</div>}</div>
        <div className="question-admin-actions"><button type="button" onClick={() => setEditor(question)}><Pencil size={15} />编辑</button><button type="button" onClick={() => setHistory(question)}><History size={15} />历史</button><button type="button" disabled={busyId === question.id} onClick={() => toggleStatus(question)}><Power size={15} />{busyId === question.id ? "处理中…" : question.is_active ? "停用" : "启用"}</button></div>
      </article>)}</div> : <div className="question-admin-state">没有符合筛选条件的题目。</div>}
      <footer className="question-admin-pagination"><span>共 {questions.data?.total ?? 0} 题</span><div><button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}><ChevronLeft size={15} />上一页</button><b>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</b><button type="button" disabled={!questions.data || offset + PAGE_SIZE >= questions.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页<ChevronRight size={15} /></button></div></footer>
    </section>
    {editor && <QuestionEditor key={editor === "new" ? "new" : `${editor.id}-${editor.content_version}`} question={editor === "new" ? null : editor} defaultSource={summary?.sources[0] ?? ""} onClose={() => setEditor(null)} />}
    {history && <VersionHistory question={history} onClose={() => setHistory(null)} />}
  </div>;
}
