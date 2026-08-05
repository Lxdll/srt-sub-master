import {
  AudioLines,
  CheckCircle2,
  Clipboard,
  Clock3,
  Cloud,
  Link2,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import { douyinAgent } from "../lib/douyin-agent";

interface LocationState {
  text?: string;
}

export function DouyinTranscribePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialText = (location.state as LocationState | null)?.text ?? "";
  const [text, setText] = useState(initialText);
  const [agentHealth, setAgentHealth] = useState<
    Awaited<ReturnType<typeof douyinAgent.health>> | null
  >(null);
  const [checkingAgent, setCheckingAgent] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function refreshAgent() {
    setCheckingAgent(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 1600);
    try {
      const health = await douyinAgent.health(controller.signal).catch(() => null);
      setAgentHealth(health);
    } finally {
      window.clearTimeout(timeout);
      setCheckingAgent(false);
    }
  }

  useEffect(() => {
    void refreshAgent();
  }, []);

  const localConnected = Boolean(
    agentHealth?.paired && agentHealth.device_id && agentHealth.douyin !== false,
  );

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
      const result = await api.createDouyinTranscription(
        value,
        { backend: "server" },
      );
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
              视频将提交到服务器排队转写。任务创建后可以关掉页面，
              服务器会继续处理。
            </p>
          </div>
          <div className="transcribe-orbit" aria-hidden="true">
            <span />
            <AudioLines size={36} />
          </div>
        </section>

        <section className="transcribe-workbench">
          <div className="server-cost-warning">
            <Cloud size={16} />
            当前统一使用服务器转写，任务将按顺序排队处理。
          </div>
          <div
            className={`local-agent-status ${localConnected ? "ready" : "offline"}`}
            role="status"
          >
            <div>
              {checkingAgent ? (
                <LoaderCircle className="spin" size={17} />
              ) : localConnected ? (
                <CheckCircle2 size={17} />
              ) : (
                <WifiOff size={17} />
              )}
              <span>
                <strong>
                  {checkingAgent
                    ? "当前状态：正在检测本机组件"
                    : localConnected
                      ? "当前状态：本机组件已连接"
                      : "当前状态：本机组件未连接"}
                </strong>
                <small>
                  {localConnected
                    ? "抖音下载可优先使用本机线路；转文案当前仍由服务器处理。"
                    : "转文案当前使用服务器线路，本机组件状态不会阻止提交。"}
                </small>
              </span>
            </div>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void refreshAgent()}
              disabled={checkingAgent}
            >
              重新检测
            </button>
          </div>
          <div className="transcribe-model">
            <span>
              <Cloud size={16} />
              服务器转写
            </span>
            <small>原声语言识别 · 现有队列 · 最长 30 分钟</small>
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
                    <Sparkles size={18} />
                    用服务器转成文案
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
              <span>服务器任务会自动排队，完成时间取决于当前队列。</span>
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
              <span>转写视频会保留 7 天，可继续用于同步播放校对。</span>
            </div>
          </article>
        </section>
      </div>
    </AppShell>
  );
}
