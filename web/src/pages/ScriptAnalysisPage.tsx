import {
  AlertTriangle,
  Boxes,
  Check,
  ChevronDown,
  Clapperboard,
  Clipboard,
  Copy,
  Eraser,
  FileText,
  Lightbulb,
  ListChecks,
  LoaderCircle,
  PackageOpen,
  Sparkles,
  Target,
  UploadCloud,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from "react";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import { DocxError, extractDocxText } from "../lib/docx";
import type { ScriptAnalysisResult } from "../types";

const MAX_TEXT_LENGTH = 30_000;
const MAX_DOCX_BYTES = 10 * 1024 * 1024;
const PROCESSING_MESSAGES = [
  "正在理解脚本结构…",
  "正在识别内容亮点…",
  "正在定位开场与转折钩子…",
  "正在整理制作所需内容…",
];

function SectionHeading({
  icon,
  eyebrow,
  title,
  description,
  onCopy,
  copied,
}: {
  icon: ReactNode;
  eyebrow: string;
  title: string;
  description: string;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <div className="script-result-heading">
      <div>
        <span>{icon}</span>
        <div>
          <small>{eyebrow}</small>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      <button type="button" className="script-copy-button" onClick={onCopy}>
        {copied ? <Check size={15} /> : <Copy size={15} />}
        {copied ? "已复制" : "复制本节"}
      </button>
    </div>
  );
}

function listLines(items: string[]) {
  return items.length ? items.map((item) => `- ${item}`).join("\n") : "- 暂无";
}

function overviewMarkdown(result: ScriptAnalysisResult) {
  const item = result.overview;
  return [
    "## 内容概览",
    `- 主题：${item.title}`,
    `- 内容概述：${item.synopsis}`,
    `- 核心信息：${item.core_message}`,
    `- 目标受众：${item.target_audience}`,
    `- 整体语气：${item.tone}`,
    `- 预估时长：${item.estimated_duration}`,
  ].join("\n");
}

function breakdownMarkdown(result: ScriptAnalysisResult) {
  return [
    "## 制作拆解",
    ...result.breakdown.map((item) =>
      [
        `### ${item.section}. ${item.label}`,
        `> ${item.excerpt}`,
        `- 段落作用：${item.purpose}`,
        `- 建议画面：\n${listLines(item.visuals)}`,
        `- 人物/场景/素材：\n${listLines(item.assets)}`,
        `- 屏幕文字：\n${listLines(item.on_screen_text)}`,
        `- 声音设计：\n${listLines(item.audio)}`,
        `- 制作提示：${item.production_notes || "暂无"}`,
      ].join("\n"),
    ),
  ].join("\n\n");
}

function requirementsMarkdown(result: ScriptAnalysisResult) {
  return [
    "## 所需内容清单",
    ...result.requirements.map((group) =>
      [
        `### ${group.category}`,
        ...group.items.map(
          (item) => `- [${item.priority}] ${item.name}：${item.purpose}`,
        ),
      ].join("\n"),
    ),
  ].join("\n\n");
}

function highlightsMarkdown(result: ScriptAnalysisResult) {
  return [
    "## 脚本亮点",
    ...result.highlights.map(
      (item, index) =>
        `${index + 1}. 「${item.excerpt}」\n   - 有效原因：${item.reason}\n   - 强化方式：${item.leverage}`,
    ),
  ].join("\n\n");
}

function hooksMarkdown(result: ScriptAnalysisResult) {
  return [
    "## 脚本钩子",
    ...result.hooks.map(
      (item, index) =>
        `${index + 1}. 「${item.excerpt}」\n   - 类型：${item.hook_type} · ${item.position} · 强度${item.strength}\n   - 吸引机制：${item.mechanism}\n   - 优化建议：${item.suggestion}`,
    ),
  ].join("\n\n");
}

function suggestionsMarkdown(result: ScriptAnalysisResult) {
  return [
    "## 整体优化建议",
    ...result.suggestions.map(
      (item, index) =>
        `${index + 1}. ${item.area}\n   - 可提升点：${item.issue}\n   - 建议：${item.recommendation}`,
    ),
  ].join("\n\n");
}

function fullReportMarkdown(result: ScriptAnalysisResult) {
  return [
    `# ${result.overview.title}｜脚本拆解`,
    overviewMarkdown(result),
    breakdownMarkdown(result),
    requirementsMarkdown(result),
    highlightsMarkdown(result),
    hooksMarkdown(result),
    suggestionsMarkdown(result),
  ].join("\n\n");
}

export function ScriptAnalysisPage() {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [platform, setPlatform] = useState("");
  const [audience, setAudience] = useState("");
  const [targetDuration, setTargetDuration] = useState("");
  const [goal, setGoal] = useState("");
  const [result, setResult] = useState<ScriptAnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [readingFile, setReadingFile] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [fileError, setFileError] = useState("");
  const [copiedSection, setCopiedSection] = useState("");
  const [processingMessage, setProcessingMessage] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const copyTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!analyzing) {
      setProcessingMessage(0);
      return;
    }
    const timer = window.setInterval(
      () =>
        setProcessingMessage(
          (current) => (current + 1) % PROCESSING_MESSAGES.length,
        ),
      1_800,
    );
    return () => window.clearInterval(timer);
  }, [analyzing]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    },
    [],
  );

  function invalidateResult() {
    setResult(null);
    setError("");
    setCopiedSection("");
  }

  function updateText(value: string) {
    setText(value);
    setFileName("");
    invalidateResult();
  }

  function updateContext(setter: (value: string) => void, value: string) {
    setter(value);
    invalidateResult();
  }

  async function paste() {
    try {
      const value = await navigator.clipboard.readText();
      updateText(value.slice(0, MAX_TEXT_LENGTH));
      if (value.length > MAX_TEXT_LENGTH) {
        setError(`已保留前 ${MAX_TEXT_LENGTH.toLocaleString()} 字。`);
      }
    } catch {
      setError("浏览器没有允许读取剪贴板，请手动粘贴。");
    }
  }

  async function readDocx(file: File) {
    setFileError("");
    if (file.size > MAX_DOCX_BYTES) {
      setFileError("Word 文件不能超过 10MB，请压缩或拆分后再试。");
      return;
    }
    if (text.trim() && !window.confirm("当前已有脚本，是否用 Word 内容替换？")) {
      return;
    }
    setReadingFile(true);
    try {
      const extracted = await extractDocxText(file);
      if (extracted.length > MAX_TEXT_LENGTH) {
        setFileError(
          `文档正文超过 ${MAX_TEXT_LENGTH.toLocaleString()} 字，请精简后再分析。`,
        );
        return;
      }
      setText(extracted);
      setFileName(file.name);
      invalidateResult();
    } catch (reason) {
      setFileError(
        reason instanceof DocxError
          ? reason.message
          : "Word 文档读取失败，请检查文件后重试。",
      );
    } finally {
      setReadingFile(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
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

  async function analyze() {
    const script = text.trim();
    if (!script) {
      setError("请先输入脚本或选择 Word 文档。");
      return;
    }
    const duration = targetDuration ? Number(targetDuration) : undefined;
    if (
      duration !== undefined &&
      (!Number.isInteger(duration) || duration < 1 || duration > 7_200)
    ) {
      setError("目标时长请输入 1–7200 之间的整数秒数。");
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setAnalyzing(true);
    setResult(null);
    setError("");
    try {
      const response = await api.analyzeScript(
        {
          text: script,
          ...(platform && { platform }),
          ...(audience.trim() && { audience: audience.trim() }),
          ...(duration && { target_duration_seconds: duration }),
          ...(goal.trim() && { goal: goal.trim() }),
        },
        controller.signal,
      );
      setResult(response);
    } catch (reason) {
      if (controller.signal.aborted) {
        setError("已取消本次脚本分析。");
      } else {
        setError(
          reason instanceof Error ? reason.message : "脚本分析失败，请稍后重试。",
        );
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setAnalyzing(false);
    }
  }

  function cancelAnalysis() {
    abortRef.current?.abort();
  }

  async function copySection(key: string, content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedSection(key);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(
        () => setCopiedSection(""),
        1_800,
      );
    } catch {
      setError("复制失败，请检查浏览器剪贴板权限。");
    }
  }

  return (
    <AppShell>
      <div className="script-analysis-page">
        <section className="script-analysis-hero">
          <div className="script-analysis-hero-copy">
            <span className="script-analysis-hero-icon">
              <WandSparkles size={25} />
            </span>
            <div>
              <span className="eyebrow">AI SCRIPT WORKBENCH</span>
              <h1>脚本拆解</h1>
              <p>从一段脚本出发，快速整理制作内容、亮点与吸引观众的关键钩子。</p>
            </div>
          </div>
          <div className="script-analysis-privacy">
            <Sparkles size={16} />
            <span>
              Word 仅在本机读取；分析文字不会保存在本站，但会发送至已配置的模型服务。
            </span>
          </div>
        </section>

        <div className="script-analysis-workspace">
          <section className="script-panel script-input-panel">
            <div className="script-panel-heading">
              <div>
                <span>01</span>
                <div>
                  <h2>输入视频脚本</h2>
                  <p>粘贴文字，或从 Word 文档读取正文</p>
                </div>
              </div>
              <strong className={text.length >= MAX_TEXT_LENGTH ? "limit" : ""}>
                {text.length.toLocaleString()} / {MAX_TEXT_LENGTH.toLocaleString()}
              </strong>
            </div>

            <textarea
              className="script-textarea"
              aria-label="视频脚本"
              value={text}
              maxLength={MAX_TEXT_LENGTH}
              placeholder={"把视频脚本粘贴到这里…\n\nAI 会拆解每段的制作意图、画面素材、亮点和钩子。"}
              onChange={(event) => updateText(event.target.value)}
            />

            <div className="script-input-actions">
              <button type="button" className="ghost-button" onClick={paste}>
                <Clipboard size={15} /> 粘贴
              </button>
              <button
                type="button"
                className="ghost-button"
                disabled={!text || analyzing}
                onClick={() => updateText("")}
              >
                <Eraser size={15} /> 清空
              </button>
            </div>

            <div
              className={`script-docx-dropzone ${dragging ? "dragging" : ""} ${fileError ? "error" : ""}`}
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
                ref={fileInputRef}
                type="file"
                accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                aria-label="选择 Word 文档"
                onChange={chooseFile}
              />
              <button
                type="button"
                disabled={readingFile || analyzing}
                onClick={() => fileInputRef.current?.click()}
              >
                <span>
                  {readingFile ? (
                    <LoaderCircle className="spin" size={20} />
                  ) : (
                    <UploadCloud size={20} />
                  )}
                </span>
                <div>
                  <strong>
                    {readingFile
                      ? "正在读取 Word 正文…"
                      : fileName || "拖入 Word，或点击选择"}
                  </strong>
                  <small>
                    {fileName
                      ? "正文已填入上方，可继续编辑"
                      : "支持 .docx，最大 10MB · 文件不会上传"}
                  </small>
                </div>
                {fileName && !readingFile && <Check size={17} />}
              </button>
            </div>
            {fileError && (
              <div className="script-inline-message error" role="alert">
                <AlertTriangle size={16} />
                {fileError}
              </div>
            )}

            <details className="script-context">
              <summary>
                <span>
                  <Target size={16} />
                  补充分析背景
                  <small>选填，帮助 AI 给出更贴合的建议</small>
                </span>
                <ChevronDown size={16} />
              </summary>
              <div className="script-context-grid">
                <label>
                  发布平台
                  <select
                    value={platform}
                    onChange={(event) =>
                      updateContext(setPlatform, event.target.value)
                    }
                  >
                    <option value="">通用 / 暂不指定</option>
                    <option value="抖音">抖音</option>
                    <option value="快手">快手</option>
                    <option value="小红书">小红书</option>
                    <option value="视频号">视频号</option>
                    <option value="B站">B站</option>
                    <option value="YouTube">YouTube</option>
                  </select>
                </label>
                <label>
                  目标时长（秒）
                  <input
                    type="number"
                    min="1"
                    max="7200"
                    inputMode="numeric"
                    value={targetDuration}
                    placeholder="例如 60"
                    onChange={(event) =>
                      updateContext(setTargetDuration, event.target.value)
                    }
                  />
                </label>
                <label className="wide">
                  目标受众
                  <input
                    value={audience}
                    maxLength={300}
                    placeholder="例如：准备第一次装修的新手业主"
                    onChange={(event) =>
                      updateContext(setAudience, event.target.value)
                    }
                  />
                </label>
                <label className="wide">
                  内容目标
                  <textarea
                    value={goal}
                    maxLength={500}
                    placeholder="例如：建立专业感，并引导观众收藏这条视频"
                    onChange={(event) =>
                      updateContext(setGoal, event.target.value)
                    }
                  />
                </label>
              </div>
            </details>

            {error && (
              <div className="script-inline-message error" role="alert">
                <AlertTriangle size={16} />
                {error}
              </div>
            )}

            <button
              type="button"
              className="primary-button script-analyze-button"
              disabled={analyzing || readingFile || !text.trim()}
              onClick={analyze}
            >
              {analyzing ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <Sparkles size={18} />
              )}
              {analyzing ? "正在拆解脚本…" : "开始 AI 拆解"}
            </button>
          </section>

          <section
            className={`script-output-panel ${result ? "ready" : ""}`}
            aria-live="polite"
          >
            {analyzing ? (
              <div className="script-processing-state">
                <div className="script-processing-orbit">
                  <Clapperboard size={29} />
                  <span />
                </div>
                <div>
                  <span className="eyebrow">AI ANALYZING</span>
                  <h2>{PROCESSING_MESSAGES[processingMessage]}</h2>
                  <p>完整拆解通常需要一点时间，期间可以随时取消。</p>
                </div>
                <div className="script-processing-lines" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={cancelAnalysis}
                >
                  <X size={15} /> 取消分析
                </button>
              </div>
            ) : !result ? (
              <div className="script-empty-state">
                <div>
                  <Clapperboard size={30} />
                  <span />
                </div>
                <span className="eyebrow">YOUR CREATIVE BLUEPRINT</span>
                <h2>制作思路会在这里展开</h2>
                <p>
                  输入脚本并开始分析后，你会得到分段制作清单、亮点、钩子和可执行的优化建议。
                </p>
                <div className="script-empty-preview" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : (
              <div className="script-result">
                <header className="script-result-topbar">
                  <div>
                    <span className="eyebrow">ANALYSIS COMPLETE</span>
                    <h2>{result.overview.title}</h2>
                    <p>{result.overview.synopsis}</p>
                  </div>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() =>
                      copySection("all", fullReportMarkdown(result))
                    }
                  >
                    {copiedSection === "all" ? (
                      <Check size={16} />
                    ) : (
                      <Copy size={16} />
                    )}
                    {copiedSection === "all" ? "已复制完整报告" : "复制完整报告"}
                  </button>
                </header>

                <div className="script-result-stats">
                  <span>
                    <Boxes size={16} />
                    <strong>{result.breakdown.length}</strong> 个内容段
                  </span>
                  <span>
                    <Lightbulb size={16} />
                    <strong>{result.highlights.length}</strong> 个亮点
                  </span>
                  <span>
                    <Zap size={16} />
                    <strong>{result.hooks.length}</strong> 个钩子
                  </span>
                  <span>
                    <Target size={16} />
                    {result.overview.estimated_duration}
                  </span>
                </div>

                <section className="script-result-section script-overview-section">
                  <SectionHeading
                    icon={<FileText size={18} />}
                    eyebrow="OVERVIEW"
                    title="内容概览"
                    description="先抓住脚本想传达的核心"
                    copied={copiedSection === "overview"}
                    onCopy={() =>
                      copySection("overview", overviewMarkdown(result))
                    }
                  />
                  <div className="script-overview-grid">
                    <article>
                      <small>核心信息</small>
                      <p>{result.overview.core_message}</p>
                    </article>
                    <article>
                      <small>目标受众</small>
                      <p>{result.overview.target_audience}</p>
                    </article>
                    <article>
                      <small>整体语气</small>
                      <p>{result.overview.tone}</p>
                    </article>
                  </div>
                </section>

                <section className="script-result-section">
                  <SectionHeading
                    icon={<Clapperboard size={18} />}
                    eyebrow="PRODUCTION BREAKDOWN"
                    title="制作拆解"
                    description="按内容推进顺序整理每段的执行要点"
                    copied={copiedSection === "breakdown"}
                    onCopy={() =>
                      copySection("breakdown", breakdownMarkdown(result))
                    }
                  />
                  {result.breakdown.length ? (
                    <div className="script-breakdown-list">
                      {result.breakdown.map((item) => (
                        <article
                          className="script-breakdown-card"
                          key={`${item.section}-${item.excerpt}`}
                        >
                          <div className="script-breakdown-index">
                            {String(item.section).padStart(2, "0")}
                          </div>
                          <div className="script-breakdown-content">
                            <div>
                              <h3>{item.label}</h3>
                              <span>{item.purpose}</span>
                            </div>
                            <blockquote>{item.excerpt}</blockquote>
                            <div className="script-breakdown-grid">
                              <div>
                                <strong>建议画面</strong>
                                <ul>
                                  {item.visuals.map((value) => (
                                    <li key={value}>{value}</li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <strong>人物 / 场景 / 素材</strong>
                                <ul>
                                  {item.assets.map((value) => (
                                    <li key={value}>{value}</li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <strong>屏幕文字</strong>
                                <ul>
                                  {item.on_screen_text.map((value) => (
                                    <li key={value}>{value}</li>
                                  ))}
                                </ul>
                              </div>
                              <div>
                                <strong>声音设计</strong>
                                <ul>
                                  {item.audio.map((value) => (
                                    <li key={value}>{value}</li>
                                  ))}
                                </ul>
                              </div>
                            </div>
                            {item.production_notes && (
                              <p className="script-production-note">
                                <WandSparkles size={14} />
                                {item.production_notes}
                              </p>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="script-result-empty">未识别到可定位的内容段落。</p>
                  )}
                </section>

                <section className="script-result-section">
                  <SectionHeading
                    icon={<PackageOpen size={18} />}
                    eyebrow="CONTENT CHECKLIST"
                    title="所需内容清单"
                    description="把拍摄和后期需要准备的东西一次列清"
                    copied={copiedSection === "requirements"}
                    onCopy={() =>
                      copySection(
                        "requirements",
                        requirementsMarkdown(result),
                      )
                    }
                  />
                  {result.requirements.length ? (
                    <div className="script-requirement-grid">
                      {result.requirements.map((group) => (
                        <article key={group.category}>
                          <h3>{group.category}</h3>
                          <div>
                            {group.items.map((item) => (
                              <div key={`${item.name}-${item.purpose}`}>
                                <span
                                  className={
                                    item.priority === "必需"
                                      ? "required"
                                      : "recommended"
                                  }
                                >
                                  {item.priority}
                                </span>
                                <p>
                                  <strong>{item.name}</strong>
                                  <small>{item.purpose}</small>
                                </p>
                              </div>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="script-result-empty">暂无额外内容准备项。</p>
                  )}
                </section>

                <section className="script-result-section">
                  <SectionHeading
                    icon={<Lightbulb size={18} />}
                    eyebrow="HIGHLIGHTS"
                    title="脚本亮点"
                    description="值得在画面、节奏和表达上重点放大的内容"
                    copied={copiedSection === "highlights"}
                    onCopy={() =>
                      copySection("highlights", highlightsMarkdown(result))
                    }
                  />
                  {result.highlights.length ? (
                    <div className="script-insight-grid">
                      {result.highlights.map((item, index) => (
                        <article
                          className="script-highlight-card"
                          key={`${item.excerpt}-${index}`}
                        >
                          <span>{String(index + 1).padStart(2, "0")}</span>
                          <blockquote>“{item.excerpt}”</blockquote>
                          <p>{item.reason}</p>
                          <small>
                            <Sparkles size={13} />
                            {item.leverage}
                          </small>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="script-result-empty">未识别到可定位的亮点原文。</p>
                  )}
                </section>

                <section className="script-result-section">
                  <SectionHeading
                    icon={<Zap size={18} />}
                    eyebrow="HOOKS"
                    title="脚本钩子"
                    description="看清观众为什么愿意继续停留"
                    copied={copiedSection === "hooks"}
                    onCopy={() => copySection("hooks", hooksMarkdown(result))}
                  />
                  {result.hooks.length ? (
                    <div className="script-hook-list">
                      {result.hooks.map((item, index) => (
                        <article key={`${item.excerpt}-${index}`}>
                          <div className="script-hook-meta">
                            <span>{item.hook_type}</span>
                            <span>{item.position}</span>
                            <strong className={`strength-${item.strength}`}>
                              {item.strength}钩子
                            </strong>
                          </div>
                          <blockquote>“{item.excerpt}”</blockquote>
                          <p>{item.mechanism}</p>
                          <small>
                            <WandSparkles size={13} />
                            {item.suggestion}
                          </small>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="script-result-empty">未识别到可定位的钩子原文。</p>
                  )}
                </section>

                <section className="script-result-section">
                  <SectionHeading
                    icon={<ListChecks size={18} />}
                    eyebrow="OPTIMIZATION"
                    title="整体优化建议"
                    description="把分析结论转成下一步可执行的修改"
                    copied={copiedSection === "suggestions"}
                    onCopy={() =>
                      copySection("suggestions", suggestionsMarkdown(result))
                    }
                  />
                  {result.suggestions.length ? (
                    <div className="script-suggestion-list">
                      {result.suggestions.map((item, index) => (
                        <article
                          key={`${item.area}-${index}`}
                          className="script-suggestion-card"
                        >
                          <span>{index + 1}</span>
                          <div>
                            <h3>{item.area}</h3>
                            <p>{item.issue}</p>
                            <strong>{item.recommendation}</strong>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="script-result-empty">暂无额外优化建议。</p>
                  )}
                </section>
              </div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
