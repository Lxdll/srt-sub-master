import {
  AudioLines,
  CheckCircle2,
  Clipboard,
  Clock3,
  Cloud,
  Cpu,
  Laptop,
  Link2,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import { douyinAgent } from "../lib/douyin-agent";
import type { Device } from "../types";

interface LocationState {
  text?: string;
}

type TranscriptionBackend = "local_agent" | "server";

export function DouyinTranscribePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialText = (location.state as LocationState | null)?.text ?? "";
  const [text, setText] = useState(initialText);
  const [backend, setBackend] =
    useState<TranscriptionBackend>("local_agent");
  const [agentHealth, setAgentHealth] = useState<
    Awaited<ReturnType<typeof douyinAgent.health>> | null
  >(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [checkingAgent, setCheckingAgent] = useState(true);
  const [pairing, setPairing] = useState(false);
  const [downloadingModel, setDownloadingModel] = useState("");
  const [modelMessage, setModelMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function refreshAgent() {
    setCheckingAgent(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 1600);
    try {
      const [health, knownDevices] = await Promise.all([
        douyinAgent.health(controller.signal).catch(() => null),
        api.devices(),
      ]);
      setAgentHealth(health);
      setDevices(knownDevices);
    } finally {
      window.clearTimeout(timeout);
      setCheckingAgent(false);
    }
  }

  useEffect(() => {
    void refreshAgent().catch(() => setCheckingAgent(false));
  }, []);

  const device = useMemo(
    () => devices.find((item) => item.id === agentHealth?.device_id) ?? null,
    [agentHealth?.device_id, devices],
  );
  const installedModels = useMemo(
    () => device?.models.filter((model) => model.installed) ?? [],
    [device],
  );
  const localReady = Boolean(
    agentHealth?.paired && device?.online && agentHealth?.douyin !== false,
  );

  useEffect(() => {
    if (installedModels.some((model) => model.id === selectedModel)) return;
    setSelectedModel(
      installedModels.find((model) => model.recommended)?.id ??
        installedModels[0]?.id ??
        "",
    );
  }, [installedModels, selectedModel]);

  async function pairAgent() {
    setPairing(true);
    setError("");
    try {
      const pair = await api.pairCode();
      await douyinAgent.pair(pair.code);
      await refreshAgent();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "本机 Agent 配对失败，请确认它正在运行。",
      );
    } finally {
      setPairing(false);
    }
  }

  async function downloadModel(modelId: string) {
    if (!device) return;
    setDownloadingModel(modelId);
    setModelMessage("");
    setError("");
    try {
      const { token } = await api.commandToken(device.id);
      const state = await douyinAgent.downloadModel(modelId, token);
      if (state.status === "failed") {
        throw new Error(state.error || "模型下载失败。");
      }
      setModelMessage(
        state.status === "ready"
          ? "模型已经安装，请重新检测。"
          : "模型已开始在 Agent 中下载；完成后请重新检测，状态同步最多需要 15 秒。",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法开始下载模型。");
    } finally {
      setDownloadingModel("");
    }
  }

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
      if (backend === "local_agent" && !localReady) {
        throw new Error("本机 Agent 离线或未与当前账号配对，请先启动并连接。");
      }
      const modelId =
        selectedModel ||
        installedModels.find((model) => model.recommended)?.id ||
        installedModels[0]?.id ||
        "";
      if (backend === "local_agent" && !modelId) {
        throw new Error("本机没有已安装的模型，请先在 Agent 中下载模型。");
      }
      const result = await api.createDouyinTranscription(
        value,
        backend === "local_agent"
          ? {
              backend,
              device_id: device?.id,
              model_id: modelId,
            }
          : { backend: "server" },
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
              默认由你自己的电脑直接下载视频并运行模型，网站只接收进度和字幕。
              任务创建后可以关掉页面，Agent 会继续处理。
            </p>
          </div>
          <div className="transcribe-orbit" aria-hidden="true">
            <span />
            <AudioLines size={36} />
          </div>
        </section>

        <section className="transcribe-workbench">
          <div className="transcribe-route-picker" aria-label="转写方式">
            <button
              type="button"
              className={backend === "local_agent" ? "selected" : ""}
              onClick={() => setBackend("local_agent")}
            >
              <Laptop size={18} />
              <span>
                <strong>本机转写 · 免费</strong>
                <small>视频和模型留在你的电脑</small>
              </span>
            </button>
            <button
              type="button"
              className={backend === "server" ? "selected" : ""}
              onClick={() => setBackend("server")}
            >
              <Cloud size={18} />
              <span>
                <strong>服务器转写</strong>
                <small>明确选择后才会使用，可能产生云端费用</small>
              </span>
            </button>
          </div>
          {backend === "local_agent" ? (
            <div className={`local-agent-status ${localReady ? "ready" : "offline"}`}>
              <div>
                {checkingAgent ? (
                  <LoaderCircle className="spin" size={17} />
                ) : localReady ? (
                  <CheckCircle2 size={17} />
                ) : (
                  <WifiOff size={17} />
                )}
                <span>
                  <strong>
                    {checkingAgent
                      ? "正在检测本机 Agent"
                      : localReady
                        ? `${device?.name ?? "本机 Agent"}已连接`
                        : "未检测到当前账号的在线 Agent"}
                  </strong>
                  <small>
                    {localReady
                      ? "Agent 会自行下载素材，浏览器不会搬运完整视频。"
                      : "请启动 127.0.0.1:43921 上的 Agent，然后配对或重新检测。"}
                  </small>
                </span>
              </div>
              <div className="local-agent-actions">
                {!localReady && agentHealth && (
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => void pairAgent()}
                    disabled={pairing}
                  >
                    {pairing ? "正在配对…" : "配对本机 Agent"}
                  </button>
                )}
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => void refreshAgent()}
                  disabled={checkingAgent}
                >
                  重新检测
                </button>
              </div>
            </div>
          ) : (
            <div className="server-cost-warning">
              <Cloud size={16} />
              服务器会按现有配置使用 Linux Worker 或阿里云 FC；不会自动从本机失败回退到服务器。
            </div>
          )}
          <div className="transcribe-model">
            <span>
              <Cpu size={16} />
              {backend === "local_agent" ? "本机 Whisper 模型" : "服务器既有模型"}
            </span>
            {backend === "local_agent" ? (
              <select
                aria-label="本机模型"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={!installedModels.length}
              >
                {!installedModels.length && <option value="">没有已安装模型</option>}
                {installedModels.map((model) => (
                  <option value={model.id} key={model.id}>
                    {model.label}
                    {model.recommended ? "（推荐）" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <small>原声语言识别 · 现有队列 · 最长 30 分钟</small>
            )}
          </div>
          {backend === "local_agent" &&
            localReady &&
            !installedModels.length && (
              <div className="transcribe-model-downloads">
                <span>选择一个模型下载到本机：</span>
                <div>
                  {(device?.models ?? []).map((model) => (
                    <button
                      type="button"
                      className="secondary-button"
                      key={model.id}
                      disabled={Boolean(downloadingModel)}
                      onClick={() => void downloadModel(model.id)}
                    >
                      {downloadingModel === model.id
                        ? "正在启动…"
                        : `下载 ${model.label}`}
                    </button>
                  ))}
                </div>
                {modelMessage && <small>{modelMessage}</small>}
              </div>
            )}
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
                    {backend === "local_agent" ? "在本机转成文案" : "用服务器转成文案"}
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
              <span>本机任务由 Agent 排队，速度取决于所选模型与电脑配置。</span>
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
              <span>本机视频不会上传服务器，可继续用于同步播放校对。</span>
            </div>
          </article>
        </section>
      </div>
    </AppShell>
  );
}
