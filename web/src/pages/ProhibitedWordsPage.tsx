import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Eraser,
  LoaderCircle,
  Plus,
  ScanSearch,
  ShieldAlert,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import type { ProhibitedWordsCheckResult } from "../types";

const MAX_TEXT_LENGTH = 20_000;

type Match = ProhibitedWordsCheckResult["matches"][number];

function HighlightedText({
  text,
  matches,
}: {
  text: string;
  matches: Match[];
}) {
  const candidates = matches
    .flatMap((match) =>
      match.occurrences.map((occurrence) => ({
        ...occurrence,
        term: match.term,
      })),
    )
    .sort(
      (left, right) =>
        left.start - right.start ||
        right.end - right.start - (left.end - left.start),
    );
  const selected: typeof candidates = [];
  let occupiedUntil = 0;
  for (const candidate of candidates) {
    if (candidate.start < occupiedUntil) continue;
    selected.push(candidate);
    occupiedUntil = candidate.end;
  }

  const content: ReactNode[] = [];
  let cursor = 0;
  selected.forEach((occurrence, index) => {
    if (occurrence.start > cursor) {
      content.push(text.slice(cursor, occurrence.start));
    }
    content.push(
      <mark
        key={`${occurrence.start}-${occurrence.end}-${index}`}
        title={`命中：${occurrence.term}`}
      >
        {text.slice(occurrence.start, occurrence.end)}
      </mark>,
    );
    cursor = occurrence.end;
  });
  if (cursor < text.length) content.push(text.slice(cursor));
  return <div className="prohibited-highlight-text">{content}</div>;
}

export function ProhibitedWordsPage() {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [term, setTerm] = useState("");
  const [result, setResult] = useState<ProhibitedWordsCheckResult | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [wordBusy, setWordBusy] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const [error, setError] = useState("");
  const [wordError, setWordError] = useState("");

  const words = useQuery({
    queryKey: ["custom-prohibited-words"],
    queryFn: api.customProhibitedWords,
  });

  function invalidateResult() {
    setResult(null);
    setError("");
  }

  async function paste() {
    try {
      const value = await navigator.clipboard.readText();
      setText(value.slice(0, MAX_TEXT_LENGTH));
      invalidateResult();
    } catch {
      setError("浏览器没有允许读取剪贴板，请手动粘贴。");
    }
  }

  async function detect() {
    if (!text.trim()) {
      setError("请先粘贴或输入需要检测的文字。");
      return;
    }
    setDetecting(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.checkProhibitedWords(text));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "检测失败，请稍后重试。");
    } finally {
      setDetecting(false);
    }
  }

  async function addWord(event: FormEvent) {
    event.preventDefault();
    const value = term.trim();
    if (!value) {
      setWordError("请输入要添加的词语或短语。");
      return;
    }
    setWordBusy(true);
    setWordError("");
    try {
      await api.addCustomProhibitedWord(value);
      setTerm("");
      invalidateResult();
      await queryClient.invalidateQueries({
        queryKey: ["custom-prohibited-words"],
      });
    } catch (reason) {
      setWordError(
        reason instanceof Error ? reason.message : "添加失败，请稍后重试。",
      );
    } finally {
      setWordBusy(false);
    }
  }

  async function deleteWord(id: string) {
    setDeletingId(id);
    setWordError("");
    try {
      await api.deleteCustomProhibitedWord(id);
      invalidateResult();
      await queryClient.invalidateQueries({
        queryKey: ["custom-prohibited-words"],
      });
    } catch (reason) {
      setWordError(
        reason instanceof Error ? reason.message : "删除失败，请稍后重试。",
      );
    } finally {
      setDeletingId("");
    }
  }

  return (
    <AppShell>
      <div className="prohibited-page">
        <section className="prohibited-hero">
          <div className="prohibited-hero-icon">
            <ShieldAlert size={27} />
          </div>
          <div>
            <span className="eyebrow">SOCIAL CONTENT GUARD</span>
            <h1>违禁词检测</h1>
            <p>
              结合 AI 与你的个人词库，定位社交媒体文案中的高风险表达。
            </p>
          </div>
          <div className="prohibited-privacy">
            <Sparkles size={16} />
            检测文字不会保存在本站，但会发送至已配置的模型服务。
          </div>
        </section>

        <div className="prohibited-workspace">
          <section className="prohibited-card prohibited-compose-card">
            <div className="prohibited-card-heading">
              <div>
                <span>01</span>
                <div>
                  <h2>待检测文字</h2>
                  <p>支持文案、评论、私信话术等社交内容</p>
                </div>
              </div>
              <strong className={text.length >= MAX_TEXT_LENGTH ? "limit" : ""}>
                {text.length.toLocaleString()} / {MAX_TEXT_LENGTH.toLocaleString()}
              </strong>
            </div>
            <textarea
              className="prohibited-textarea"
              aria-label="待检测文字"
              value={text}
              maxLength={MAX_TEXT_LENGTH}
              placeholder="在这里粘贴需要检测的文字…"
              onChange={(event) => {
                setText(event.target.value);
                invalidateResult();
              }}
            />
            <div className="prohibited-compose-actions">
              <div>
                <button type="button" className="ghost-button" onClick={paste}>
                  <Clipboard size={16} /> 粘贴
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!text || detecting}
                  onClick={() => {
                    setText("");
                    invalidateResult();
                  }}
                >
                  <Eraser size={16} /> 清空
                </button>
              </div>
              <button
                type="button"
                className="primary-button prohibited-detect-button"
                disabled={detecting || !text.trim()}
                onClick={detect}
              >
                {detecting ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <ScanSearch size={17} />
                )}
                {detecting ? "模型检测中…" : "开始检测"}
              </button>
            </div>
            {error && (
              <div className="prohibited-message error" role="alert">
                <AlertTriangle size={17} />
                {error}
              </div>
            )}
          </section>

          <aside className="prohibited-card prohibited-dictionary-card">
            <div className="prohibited-card-heading">
              <div>
                <span>02</span>
                <div>
                  <h2>个人词库</h2>
                  <p>按当前账号保存，检测时自动匹配</p>
                </div>
              </div>
              <strong>{words.data?.length ?? 0} 个</strong>
            </div>
            <form className="prohibited-word-form" onSubmit={addWord}>
              <input
                aria-label="添加自定义违禁词"
                value={term}
                maxLength={100}
                placeholder="输入词语或短语"
                onChange={(event) => {
                  setTerm(event.target.value);
                  setWordError("");
                }}
              />
              <button
                type="submit"
                aria-label="添加违禁词"
                disabled={wordBusy || !term.trim()}
              >
                {wordBusy ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Plus size={17} />
                )}
              </button>
            </form>
            {wordError && (
              <div className="prohibited-inline-error" role="alert">
                {wordError}
              </div>
            )}
            <div className="prohibited-word-list">
              {words.isLoading ? (
                <div className="prohibited-dictionary-empty">
                  <LoaderCircle className="spin" size={18} /> 正在读取词库…
                </div>
              ) : words.isError ? (
                <div className="prohibited-dictionary-empty error">
                  个人词库加载失败
                </div>
              ) : words.data?.length ? (
                words.data.map((word) => (
                  <div className="prohibited-word-chip" key={word.id}>
                    <span>{word.term}</span>
                    <button
                      type="button"
                      aria-label={`删除 ${word.term}`}
                      disabled={deletingId === word.id}
                      onClick={() => deleteWord(word.id)}
                    >
                      {deletingId === word.id ? (
                        <LoaderCircle className="spin" size={14} />
                      ) : (
                        <Trash2 size={14} />
                      )}
                    </button>
                  </div>
                ))
              ) : (
                <div className="prohibited-dictionary-empty">
                  还没有自定义词，添加后会参与每次检测。
                </div>
              )}
            </div>
          </aside>
        </div>

        <section className="prohibited-results">
          <div className="prohibited-results-heading">
            <div>
              <span>03</span>
              <div>
                <h2>检测结果</h2>
                <p>模型结果均经过原文定位验证</p>
              </div>
            </div>
            {result && (
              <div className="prohibited-result-totals">
                <strong>{result.unique_term_count}</strong> 个风险词 ·{" "}
                <strong>{result.match_count}</strong> 处命中
              </div>
            )}
          </div>

          {!result ? (
            <div className={`prohibited-result-empty ${detecting ? "busy" : ""}`}>
              {detecting ? (
                <>
                  <LoaderCircle className="spin" size={28} />
                  <strong>正在分析文字</strong>
                  <span>模型会查找并验证原文中的风险表达</span>
                </>
              ) : (
                <>
                  <ScanSearch size={30} />
                  <strong>等待检测</strong>
                  <span>检测完成后，这里会列出命中词并高亮原文</span>
                </>
              )}
            </div>
          ) : result.matches.length === 0 ? (
            <div className="prohibited-safe-result" role="status">
              <CheckCircle2 size={28} />
              <div>
                <strong>未发现可定位的违禁词</strong>
                <span>结果仅供内容发布前参考，不能替代平台最终审核。</span>
              </div>
            </div>
          ) : (
            <div className="prohibited-result-grid">
              <div className="prohibited-match-list">
                {result.matches.map((match) => (
                  <article
                    className="prohibited-match-item"
                    key={`${match.term}-${match.category}`}
                  >
                    <div className="prohibited-match-term">
                      <strong>{match.term}</strong>
                      <span>{match.occurrences.length} 处</span>
                    </div>
                    <div className="prohibited-match-meta">
                      <span>{match.category}</span>
                      {match.sources.map((source) => (
                        <span className={`source ${source}`} key={source}>
                          {source === "ai" ? "AI 识别" : "个人词库"}
                        </span>
                      ))}
                    </div>
                    <p>{match.reason}</p>
                  </article>
                ))}
              </div>
              <div className="prohibited-highlight-panel">
                <div>
                  <strong>原文高亮</strong>
                  <span>重叠命中优先显示更长的词句</span>
                </div>
                <HighlightedText text={text} matches={result.matches} />
              </div>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
