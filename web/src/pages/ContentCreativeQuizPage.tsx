import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  ListChecks,
  Play,
  RefreshCcw,
  RotateCcw,
  Shuffle,
  Sparkles,
  Target,
  Trophy,
  XCircle,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import type {
  ContentCreativeQuestion,
  ContentCreativeQuestionType,
  ContentCreativeQuizMode,
  ContentCreativeQuizOverview,
  ContentCreativeQuizSession,
} from "../types";

const TYPE_LABELS: Record<ContentCreativeQuestionType, string> = {
  single: "单选",
  multiple: "多选",
  judgment: "判断",
};
const MODE_LABELS: Record<ContentCreativeQuizMode, string> = {
  sequential: "顺序练习",
  random: "随机练习",
  mistakes: "错题重练",
  mock: "模拟考试",
};

function formatDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function ModeSetup({
  mode,
  overview,
  onClose,
  onStart,
}: {
  mode: ContentCreativeQuizMode;
  overview: ContentCreativeQuizOverview;
  onClose: () => void;
  onStart: (session: ContentCreativeQuizSession) => void;
}) {
  const [sources, setSources] = useState(overview.sources.map((item) => item.source));
  const [types, setTypes] = useState<ContentCreativeQuestionType[]>(["single", "multiple", "judgment"]);
  const [questionCount, setQuestionCount] = useState(mode === "random" ? "20" : "");
  const [duration, setDuration] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function toggleSource(source: string) {
    setSources((current) => current.includes(source) ? current.filter((item) => item !== source) : [...current, source]);
  }
  function toggleType(type: ContentCreativeQuestionType) {
    setTypes((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type]);
  }
  async function start() {
    if (!sources.length || !types.length) { setError("请至少选择一个题目来源和一种题型。"); return; }
    if (mode === "mock" && (!questionCount || !duration)) { setError("模拟考试必须填写题数和时长。"); return; }
    setBusy(true); setError("");
    try {
      const session = await api.createContentCreativeQuizSession({
        mode,
        sources: sources.length === overview.sources.length ? [] : sources,
        question_types: types.length === 3 ? [] : types,
        question_count: mode === "mock" || (mode === "random" && questionCount !== "all") ? Number(questionCount) : undefined,
        duration_minutes: mode === "mock" ? Number(duration) : undefined,
        all_questions: mode === "random" && questionCount === "all",
      });
      onStart(session);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "练习创建失败。"); }
    finally { setBusy(false); }
  }
  return <div className="quiz-dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="quiz-setup-dialog" role="dialog" aria-modal="true" aria-labelledby="quiz-setup-title">
      <header><div><span><Target size={19} /></span><div><h2 id="quiz-setup-title">{MODE_LABELS[mode]}</h2><p>选择这一次希望覆盖的题目范围。</p></div></div><button type="button" onClick={onClose} aria-label="关闭"><XCircle size={19} /></button></header>
      <div className="quiz-setup-section"><strong>题目来源</strong><div className="quiz-filter-grid">{overview.sources.map((item) => <label key={item.source} className={sources.includes(item.source) ? "selected" : ""}><input type="checkbox" checked={sources.includes(item.source)} onChange={() => toggleSource(item.source)} /><span>{item.source}<small>{item.count} 题</small></span></label>)}</div></div>
      <div className="quiz-setup-section"><strong>题型</strong><div className="quiz-type-picker">{Object.entries(TYPE_LABELS).map(([value, label]) => <label key={value} className={types.includes(value as ContentCreativeQuestionType) ? "selected" : ""}><input type="checkbox" checked={types.includes(value as ContentCreativeQuestionType)} onChange={() => toggleType(value as ContentCreativeQuestionType)} /><span>{label}<small>{overview.by_type[value as ContentCreativeQuestionType]} 题</small></span></label>)}</div></div>
      {mode === "random" && <div className="quiz-setup-section"><strong>题目数量</strong><div className="quiz-count-picker">{[10, 20, 50].map((count) => <button type="button" className={questionCount === String(count) ? "selected" : ""} key={count} onClick={() => setQuestionCount(String(count))}>{count} 题</button>)}<button type="button" className={questionCount === "all" ? "selected" : ""} onClick={() => setQuestionCount("all")}>全部</button></div></div>}
      {mode === "mock" && <div className="quiz-custom-fields"><label>题目数量<input type="number" min="1" max={overview.question_count} value={questionCount} onChange={(event) => setQuestionCount(event.target.value)} placeholder="例如 50" /></label><label>考试时长（分钟）<input type="number" min="1" max="300" value={duration} onChange={(event) => setDuration(event.target.value)} placeholder="例如 45" /></label></div>}
      {error && <div className="quiz-inline-error" role="alert"><AlertTriangle size={16} />{error}</div>}
      <footer><button type="button" onClick={onClose}>取消</button><button type="button" className="primary-button" disabled={busy} onClick={start}><Play size={16} />{busy ? "正在组题…" : "开始"}</button></footer>
    </section>
  </div>;
}

function QuizWorkspace({ session: initialSession, onExit }: { session: ContentCreativeQuizSession; onExit: () => void }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState(initialSession);
  const firstUnanswered = Math.max(0, session.questions.findIndex((item) => !item.answered_at));
  const [index, setIndex] = useState(firstUnanswered >= 0 ? firstUnanswered : 0);
  const question = session.questions[index];
  const [selected, setSelected] = useState<string[]>(question?.selected_options ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const autoSubmitting = useRef(false);
  const completed = session.status === "completed";
  const isMock = session.mode === "mock";
  const remaining = session.deadline_at ? Math.max(0, Math.ceil((new Date(session.deadline_at).getTime() - now) / 1000)) : null;

  useEffect(() => { setSelected(question?.selected_options ?? []); setError(""); }, [question?.id, question?.selected_options]);
  useEffect(() => {
    if (!session.deadline_at || completed) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [completed, session.deadline_at]);
  useEffect(() => {
    if (remaining !== 0 || completed || autoSubmitting.current) return;
    autoSubmitting.current = true;
    void api.submitContentCreativeQuizSession(session.id).then((result) => { setSession(result); void queryClient.invalidateQueries({ queryKey: ["content-creative-quiz-overview"] }); }).catch((reason) => setError(reason instanceof Error ? reason.message : "自动交卷失败，请手动交卷。"));
  }, [completed, queryClient, remaining, session.id]);

  function toggleOption(key: string) {
    if (question.answered_at && !isMock) return;
    setSelected((current) => question.question_type === "multiple" ? current.includes(key) ? current.filter((item) => item !== key) : [...current, key].sort() : [key]);
  }
  async function confirmAnswer() {
    if (!selected.length) { setError("请先选择答案。"); return; }
    setBusy(true); setError("");
    try {
      const result = await api.answerContentCreativeQuestion(session.id, question.id, selected);
      setSession(result);
      if (result.status === "completed") void queryClient.invalidateQueries({ queryKey: ["content-creative-quiz-overview"] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "答案保存失败。"); }
    finally { setBusy(false); }
  }
  async function submitExam() {
    if (!window.confirm(`确认交卷？当前已答 ${session.answered_count} / ${session.question_count} 题。`)) return;
    setBusy(true); setError("");
    try { const result = await api.submitContentCreativeQuizSession(session.id); setSession(result); setIndex(0); void queryClient.invalidateQueries({ queryKey: ["content-creative-quiz-overview"] }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "交卷失败。"); }
    finally { setBusy(false); }
  }
  function handleKeys(event: KeyboardEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).tagName === "BUTTON") return;
    const key = event.key.toUpperCase();
    if (question.options.some((item) => item.key === key)) { event.preventDefault(); toggleOption(key); }
    if (event.key === "Enter" && !busy && !completed) { event.preventDefault(); void confirmAnswer(); }
  }
  const currentAnswered = Boolean(question.answered_at);
  return <div className="quiz-workspace" tabIndex={-1} onKeyDown={handleKeys}>
    <header className="quiz-workspace-header"><button type="button" onClick={onExit}><ArrowLeft size={16} />返回概览</button><div><span>{MODE_LABELS[session.mode]}</span><strong>{session.answered_count} / {session.question_count}</strong></div>{remaining !== null ? <div className={`quiz-timer ${remaining < 300 ? "urgent" : ""}`}><Clock3 size={16} />{formatDuration(remaining)}</div> : <div className="quiz-progress-percent">{Math.round((session.answered_count / session.question_count) * 100)}%</div>}</header>
    <div className="quiz-progress-track"><span style={{ width: `${(session.answered_count / session.question_count) * 100}%` }} /></div>
    {completed && <section className="quiz-result-banner"><div><span><Trophy size={27} /></span><div><small>{MODE_LABELS[session.mode]}完成</small><h2>{session.score_correct} / {session.score_total}</h2><p>正确率 {Math.round(((session.score_correct ?? 0) / Math.max(1, session.score_total ?? 1)) * 100)}% · 用时 {formatDuration(session.elapsed_seconds)}</p></div></div><div className="quiz-result-breakdown">{Object.entries(session.breakdown ?? {}).map(([type, values]) => <span key={type}><b>{TYPE_LABELS[type as ContentCreativeQuestionType]}</b><strong>{values.correct}/{values.total}</strong></span>)}</div></section>}
    <div className="quiz-answer-layout">
      <main className="quiz-question-card">
        <div className="quiz-question-meta"><span>第 {index + 1} 题</span><b>{TYPE_LABELS[question.question_type]}</b><em>{question.source}</em></div>
        <h1>{question.prompt}</h1>
        <div className="quiz-options">{question.options.map((option) => {
          const chosen = selected.includes(option.key);
          const correct = Boolean(question.correct_options?.includes(option.key));
          const wrongChoice = Boolean(question.is_correct === false && question.selected_options.includes(option.key));
          return <button type="button" key={option.key} disabled={currentAnswered && !isMock} onClick={() => toggleOption(option.key)} className={[chosen ? "selected" : "", question.correct_options && correct ? "correct" : "", wrongChoice ? "wrong" : ""].filter(Boolean).join(" ")}><strong>{option.key}</strong><span>{option.text}</span>{question.correct_options && correct && <Check size={18} />}{wrongChoice && <XCircle size={18} />}</button>;
        })}</div>
        {question.correct_options && <div className={`quiz-feedback ${question.is_correct ? "success" : "error"}`}>{question.is_correct ? <CheckCircle2 size={19} /> : <XCircle size={19} />}<div><strong>{question.is_correct ? "回答正确" : `回答错误，正确答案：${question.correct_options.join("")}`}</strong>{question.note && <p>{question.note}</p>}</div></div>}
        {error && <div className="quiz-inline-error"><AlertTriangle size={16} />{error}</div>}
        <footer className="quiz-question-actions">
          <button type="button" disabled={index === 0} onClick={() => setIndex(index - 1)}><ChevronLeft size={16} />上一题</button>
          <div>
            {!completed && (!currentAnswered || isMock) && <button type="button" className="primary-button" disabled={busy || !selected.length} onClick={confirmAnswer}>{busy ? "保存中…" : isMock && currentAnswered ? "更新答案" : "确认答案"}</button>}
            {currentAnswered && !isMock && index < session.question_count - 1 && <button type="button" className="primary-button" onClick={() => setIndex(index + 1)}>下一题<ArrowRight size={16} /></button>}
          </div>
          {(!currentAnswered || isMock) && <button type="button" disabled={index >= session.question_count - 1} onClick={() => setIndex(index + 1)}>下一题<ChevronRight size={16} /></button>}
        </footer>
      </main>
      <aside className="quiz-answer-sheet"><header><ListChecks size={17} /><div><strong>答题卡</strong><span>{session.answered_count} 题已作答</span></div></header><div>{session.questions.map((item, questionIndex) => <button type="button" key={item.id} aria-label={`第 ${questionIndex + 1} 题`} onClick={() => setIndex(questionIndex)} className={[questionIndex === index ? "current" : "", item.answered_at ? "answered" : "", item.is_correct === true ? "correct" : "", item.is_correct === false ? "wrong" : ""].filter(Boolean).join(" ")}>{questionIndex + 1}</button>)}</div>{isMock && !completed && <button type="button" className="quiz-submit-button" disabled={busy} onClick={submitExam}><Trophy size={16} />交卷</button>}{completed && <button type="button" className="quiz-submit-button" onClick={onExit}><RotateCcw size={16} />返回练习首页</button>}</aside>
    </div>
  </div>;
}

export function ContentCreativeQuizPage() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["content-creative-quiz-overview"], queryFn: api.contentCreativeQuizOverview });
  const [setupMode, setSetupMode] = useState<ContentCreativeQuizMode | null>(null);
  const [session, setSession] = useState<ContentCreativeQuizSession | null>(null);
  const [loadingSession, setLoadingSession] = useState(false);
  const [error, setError] = useState("");
  async function openSession(sessionId: string) {
    setLoadingSession(true); setError("");
    try { setSession(await api.contentCreativeQuizSession(sessionId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "场次读取失败。"); }
    finally { setLoadingSession(false); }
  }
  async function exitWorkspace() { setSession(null); await queryClient.invalidateQueries({ queryKey: ["content-creative-quiz-overview"] }); }
  if (session) return <AppShell><QuizWorkspace key={session.id} session={session} onExit={() => void exitWorkspace()} /></AppShell>;
  const data = overview.data;
  return <AppShell><div className="quiz-page">
    <section className="quiz-hero"><div><span className="quiz-hero-icon"><BookOpenCheck size={27} /></span><div><span className="eyebrow">CONTENT CREATIVE CERTIFICATION</span><h1>巨量认证内容创意初级刷题</h1><p>按真题来源练习，及时复盘错题，把每一次作答变成进步。</p></div></div><div className="quiz-hero-total"><span>当前有效题库</span><strong>{data?.question_count ?? "—"}</strong><small>道题</small></div></section>
    {overview.isLoading ? <div className="quiz-loading"><RefreshCcw className="spin" size={22} />正在读取题库和你的进度…</div> : overview.isError ? <div className="quiz-loading error"><AlertTriangle size={22} />题库读取失败，请稍后重试。</div> : data && <>
      {data.active_session && <section className="quiz-resume-card"><div><span><Play size={20} /></span><div><small>上次练习还没有结束</small><h2>{MODE_LABELS[data.active_session.mode]}</h2><p>已完成 {data.active_session.answered_count} / {data.active_session.question_count} 题</p></div></div><button type="button" disabled={loadingSession} onClick={() => openSession(data.active_session!.id)}>{loadingSession ? "正在恢复…" : "继续答题"}<ArrowRight size={16} /></button></section>}
      <section className="quiz-overview-stats"><article><Target size={19} /><span>累计作答</span><strong>{data.progress.attempts}</strong></article><article><CheckCircle2 size={19} /><span>总体正确率</span><strong>{Math.round(data.progress.correct_rate * 100)}%</strong></article><article><RotateCcw size={19} /><span>当前错题</span><strong>{data.progress.mistakes}</strong></article><article><Sparkles size={19} /><span>单 / 多 / 判断</span><strong>{data.by_type.single}<i>/</i>{data.by_type.multiple}<i>/</i>{data.by_type.judgment}</strong></article></section>
      <section className="quiz-mode-section"><div className="quiz-section-heading"><span>01</span><div><h2>选择练习方式</h2><p>练习模式立即判题，模拟考试交卷后统一复盘。</p></div></div><div className="quiz-mode-grid">
        <button type="button" onClick={() => setSetupMode("sequential")}><span><ListChecks size={23} /></span><h3>顺序练习</h3><p>按照题库序号完整学习，适合第一轮系统刷题。</p><b>开始配置<ArrowRight size={15} /></b></button>
        <button type="button" onClick={() => setSetupMode("random")}><span><Shuffle size={23} /></span><h3>随机练习</h3><p>随机抽取 10、20 或 50 题，利用碎片时间巩固。</p><b>开始配置<ArrowRight size={15} /></b></button>
        <button type="button" className={data.progress.mistakes === 0 ? "muted" : ""} disabled={data.progress.mistakes === 0} onClick={() => setSetupMode("mistakes")}><span><RotateCcw size={23} /></span><h3>错题重练</h3><p>{data.progress.mistakes ? `集中练习当前 ${data.progress.mistakes} 道错题。` : "答错的题目会自动收录到这里。"}</p><b>{data.progress.mistakes ? "开始配置" : "暂无错题"}<ArrowRight size={15} /></b></button>
        <button type="button" className="featured" onClick={() => setSetupMode("mock")}><span><Trophy size={23} /></span><h3>模拟考试</h3><p>自定义题数和时长，交卷前不显示答案。</p><b>设置考试<ArrowRight size={15} /></b></button>
      </div></section>
      {data.recent_sessions.length > 0 && <section className="quiz-history-section"><div className="quiz-section-heading"><span>02</span><div><h2>最近记录</h2><p>查看成绩并继续复盘已完成的场次。</p></div></div><div className="quiz-history-list">{data.recent_sessions.map((item) => <button type="button" key={item.id} disabled={item.status !== "completed" || loadingSession} onClick={() => openSession(item.id)}><span className={item.status}><Trophy size={17} /></span><div><strong>{MODE_LABELS[item.mode]}</strong><small>{new Date(item.started_at).toLocaleString("zh-CN")}</small></div><b>{item.status === "completed" ? `${item.score_correct} / ${item.score_total}` : "已放弃"}</b><ArrowRight size={16} /></button>)}</div></section>}
    </>}
    {error && <div className="quiz-inline-error"><AlertTriangle size={16} />{error}</div>}
    {setupMode && data && <ModeSetup mode={setupMode} overview={data} onClose={() => setSetupMode(null)} onStart={(created) => { setSetupMode(null); setSession(created); }} />}
  </div></AppShell>;
}
