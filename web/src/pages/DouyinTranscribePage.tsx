import {
  AudioLines,
  CheckCircle2,
  Clipboard,
  Clock3,
  Cpu,
  Link2,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";

interface LocationState {
  text?: string;
}

export function DouyinTranscribePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialText = (location.state as LocationState | null)?.text ?? "";
  const [text, setText] = useState(initialText);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function paste() {
    try {
      setText(await navigator.clipboard.readText());
      setError("");
    } catch {
      setError("浏览器没有允许读取剪贴板，请手动粘贴。");
    }
  }

  async function submit() {
    const value = text.trim();
    if (!value) {
      setError("请先粘贴抖音分享文案或链接。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await api.createDouyinTranscription(value);
      navigate(`/tasks/${result.task_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法创建转写任务。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="transcribe-page">
        <section className="transcribe-hero">
          <div>
            <span className="eyebrow">
              <AudioLines size={14} /> DOUYIN TO COPY
            </span>
            <h1>粘贴一条抖音链接，直接得到可校对的说话文案。</h1>
            <p>
              视频由服务器下载并识别。任务创建后会直接进入字幕校对，完成前可以关掉页面，稍后再回来。
            </p>
          </div>
          <div className="transcribe-orbit" aria-hidden="true">
            <span />
            <AudioLines size={36} />
          </div>
        </section>

        <section className="transcribe-workbench">
          <div className="transcribe-model">
            <span>
              <Cpu size={16} /> 服务器 Whisper Small Q5
            </span>
            <small>原声语言识别 · 单任务排队 · 最长 30 分钟</small>
          </div>
          <label htmlFor="douyin-transcribe-link">分享文案或视频链接</label>
          <div className="douyin-input-row">
            <div className="douyin-input-wrap">
              <Link2 size={20} />
              <textarea
                id="douyin-transcribe-link"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="粘贴“复制链接”得到的整段文案，或 https://v.douyin.com/…"
                rows={4}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                    void submit();
                  }
                }}
              />
              {text && (
                <button
                  type="button"
                  className="clear-link"
                  onClick={() => setText("")}
                  aria-label="清空链接"
                >
                  <X size={16} />
                </button>
              )}
            </div>
            <div className="douyin-input-actions">
              <button type="button" className="paste-button" onClick={paste}>
                <Clipboard size={16} /> 粘贴
              </button>
              <button
                type="button"
                className="parse-button"
                onClick={() => void submit()}
                disabled={submitting || !text.trim()}
              >
                {submitting ? (
                  <>
                    <LoaderCircle className="spin" size={18} /> 正在创建
                  </>
                ) : (
                  <>
                    <Sparkles size={18} /> 转成文案
                  </>
                )}
              </button>
            </div>
          </div>
          <small className="douyin-shortcut">按 ⌘ / Ctrl + Enter 快速提交</small>
        </section>

        {error && (
          <div className="douyin-error" role="alert">
            {error}
          </div>
        )}

        <section className="transcribe-facts">
          <article>
            <Clock3 size={20} />
            <div>
              <strong>准确优先，自动排队</strong>
              <span>低配服务器每次只识别一条，等待时间可能接近视频时长。</span>
            </div>
          </article>
          <article>
            <CheckCircle2 size={20} />
            <div>
              <strong>完成后直接校对</strong>
              <span>逐句时间轴、修改自动保存，并可导出 TXT 或 SRT。</span>
            </div>
          </article>
          <article>
            <ShieldCheck size={20} />
            <div>
              <strong>视频保留 7 天</strong>
              <span>用于同步播放校对；到期后只删除视频，不删除字幕。</span>
            </div>
          </article>
        </section>
      </div>
    </AppShell>
  );
}
