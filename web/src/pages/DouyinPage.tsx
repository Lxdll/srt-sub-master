import {
  CheckCircle2,
  AudioLines,
  Clipboard,
  Cloud,
  Download,
  FolderDown,
  Gauge,
  Laptop,
  Link2,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { AGENT_URL, douyinAgent } from "../lib/douyin-agent";
import { hasPermission } from "../lib/permissions";
import type { DouyinParseResult } from "../types";

type ResultRoute = "local" | "cloud";
type DownloadTarget = "folder" | "browser";
type DownloadStatus = {
  kind: "success" | "error" | "cancelled";
  message: string;
};

interface ParsedState {
  data: DouyinParseResult;
  route: ResultRoute;
  commandToken?: string;
}

interface SaveFilePickerOptions {
  suggestedName?: string;
  types?: Array<{
    description?: string;
    accept: Record<string, string[]>;
  }>;
}

interface FileSystemWritableFileStream {
  write(data: Uint8Array): Promise<void>;
  close(): Promise<void>;
  abort(reason?: unknown): Promise<void>;
}

interface FileSystemFileHandle {
  createWritable(): Promise<FileSystemWritableFileStream>;
}

interface FileSystemDirectoryHandle {
  getFileHandle(
    name: string,
    options?: { create?: boolean },
  ): Promise<FileSystemFileHandle>;
}

declare global {
  interface Window {
    showSaveFilePicker?: (
      options?: SaveFilePickerOptions,
    ) => Promise<FileSystemFileHandle>;
    showDirectoryPicker?: () => Promise<FileSystemDirectoryHandle>;
  }
}

function formatDuration(durationMs?: number | null) {
  if (!durationMs) return "时长未知";
  const total = Math.round(durationMs / 1000);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

function formatBytes(bytes?: number | null) {
  if (!bytes) return "大小以下载时为准";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function safeFilename(
  author: string,
  title: string,
  awemeId: string,
  quality: string,
) {
  return `${author}_${title}_${awemeId}_${quality}`
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/\s+/g, " ")
    .slice(0, 180)
    .replace(/[ ._]+$/g, "")
    .concat(".mp4");
}

export function DouyinPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedState | null>(null);
  const [agentHealth, setAgentHealth] = useState<
    Awaited<ReturnType<typeof douyinAgent.health>> | null
  >(null);
  const [checkingAgent, setCheckingAgent] = useState(true);
  const [parsing, setParsing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [speed, setSpeed] = useState("");
  const [downloadTarget, setDownloadTarget] = useState<DownloadTarget | null>(
    null,
  );
  const [downloadStatus, setDownloadStatus] =
    useState<DownloadStatus | null>(null);
  const [videoError, setVideoError] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 1400);
    douyinAgent
      .health(controller.signal)
      .then(setAgentHealth)
      .catch(() => setAgentHealth(null))
      .finally(() => {
        window.clearTimeout(timeout);
        setCheckingAgent(false);
      });
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  const localReady = Boolean(
    agentHealth?.paired && agentHealth.device_id && agentHealth.douyin !== false,
  );
  const selectedQuality = useMemo(
    () =>
      parsed?.data.qualities.find(
        (item) => item.id === parsed.data.recommended_quality,
      ) ?? parsed?.data.qualities[0],
    [parsed],
  );
  const previewUrl = useMemo(
    () =>
      parsed
        ? parsed.route === "local" && parsed.commandToken
          ? douyinAgent.previewUrl(
              parsed.data.ticket,
              parsed.data.recommended_quality,
              parsed.commandToken,
            )
          : api.douyinPreviewUrl(
              parsed.data.ticket,
              parsed.data.recommended_quality,
            )
        : "",
    [parsed],
  );

  async function cloudParse(value: string): Promise<ParsedState> {
    return { data: await api.parseDouyin(value), route: "cloud" };
  }

  async function localParse(value: string): Promise<ParsedState> {
    if (!agentHealth?.device_id || !agentHealth.paired) {
      throw new Error("本机组件尚未安装或未与当前账号配对。");
    }
    const { token } = await api.commandToken(agentHealth.device_id);
    return {
      data: await douyinAgent.parse(value, token),
      route: "local",
      commandToken: token,
    };
  }

  async function parse() {
    const value = text.trim();
    if (!value) {
      setError("请先粘贴抖音分享文案或链接。");
      return;
    }
    setParsing(true);
    setError("");
    setParsed(null);
    setDownloadStatus(null);
    setVideoError(false);
    try {
      let result: ParsedState;
      if (localReady) {
        try {
          result = await localParse(value);
        } catch {
          result = await cloudParse(value);
        }
      } else {
        result = await cloudParse(value);
      }
      setParsed(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "暂时无法解析该视频。");
    } finally {
      setParsing(false);
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

  function filenameFor(result: ParsedState) {
    const item =
      result.data.qualities.find(
        (candidate) => candidate.id === result.data.recommended_quality,
      ) ?? result.data.qualities[0];
    return safeFilename(
      result.data.author,
      result.data.title,
      result.data.aweme_id,
      item?.label ?? "推荐画质",
    );
  }

  async function openDownload(
    result: ParsedState,
    controller: AbortController,
  ): Promise<Response & { body: ReadableStream<Uint8Array> }> {
    const quality = result.data.recommended_quality;
    const url =
      result.route === "local"
        ? douyinAgent.downloadUrl(result.data.ticket, quality)
        : api.douyinDownloadUrl(result.data.ticket, quality);
    const response = await fetch(url, {
      credentials: result.route === "cloud" ? "include" : "omit",
      headers:
        result.route === "local" && result.commandToken
          ? { "X-Command-Token": result.commandToken }
          : undefined,
      signal: controller.signal,
      ...(result.route === "local"
        ? ({ targetAddressSpace: "loopback" } as RequestInit)
        : {}),
    });
    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `下载失败（${response.status}）`);
    }
    return response as Response & { body: ReadableStream<Uint8Array> };
  }

  async function saveToFolder(result: ParsedState) {
    const filename = filenameFor(result);
    let handle: FileSystemFileHandle;
    if (window.showSaveFilePicker) {
      handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [
          {
            description: "MP4 视频",
            accept: { "video/mp4": [".mp4"] },
          },
        ],
      });
    } else if (window.showDirectoryPicker) {
      const directory = await window.showDirectoryPicker();
      handle = await directory.getFileHandle(filename, { create: true });
    } else {
      throw new Error(
        "当前浏览器不支持选择保存目录，请使用“浏览器下载”。",
      );
    }

    const writable = await handle.createWritable();
    const controller = new AbortController();
    abortRef.current = controller;
    const started = performance.now();
    let received = 0;
    try {
      const response = await openDownload(result, controller);
      const total = Number(response.headers.get("content-length") || 0);
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        await writable.write(value);
        received += value.byteLength;
        if (total) setProgress(Math.min(100, Math.round((received / total) * 100)));
        const seconds = Math.max((performance.now() - started) / 1000, 0.2);
        setSpeed(`${formatBytes(received / seconds)}/s`);
      }
      await writable.close();
      setProgress(100);
    } catch (reason) {
      await writable.abort(reason).catch(() => undefined);
      throw reason;
    } finally {
      abortRef.current = null;
    }
  }

  async function downloadInBrowser(result: ParsedState) {
    const controller = new AbortController();
    abortRef.current = controller;
    const started = performance.now();
    let received = 0;
    try {
      const response = await openDownload(result, controller);
      const total = Number(response.headers.get("content-length") || 0);
      const contentType = response.headers.get("content-type") || "video/mp4";
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = new Uint8Array(value.byteLength);
        chunk.set(value);
        chunks.push(chunk);
        received += value.byteLength;
        if (total) setProgress(Math.min(100, Math.round((received / total) * 100)));
        const seconds = Math.max((performance.now() - started) / 1000, 0.2);
        setSpeed(`${formatBytes(received / seconds)}/s`);
      }
      const objectUrl = URL.createObjectURL(new Blob(chunks, { type: contentType }));
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filenameFor(result);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
      setProgress(100);
    } finally {
      abortRef.current = null;
    }
  }

  async function download(target: DownloadTarget) {
    if (!parsed) return;
    setDownloading(true);
    setDownloadTarget(target);
    setProgress(0);
    setSpeed("");
    setError("");
    setDownloadStatus(null);
    try {
      if (target === "folder") {
        await saveToFolder(parsed);
      } else {
        await downloadInBrowser(parsed);
      }
      setDownloadStatus({
        kind: "success",
        message:
          target === "folder"
            ? "视频下载成功，已保存到你指定的目录。"
            : "视频下载成功，已交给浏览器保存。",
      });
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setDownloadStatus({ kind: "cancelled", message: "下载已取消。" });
      } else {
        setDownloadStatus({
          kind: "error",
          message:
            reason instanceof Error
              ? `视频下载失败：${reason.message}`
              : "视频下载失败，请稍后重试。",
        });
      }
    } finally {
      setDownloading(false);
      setDownloadTarget(null);
    }
  }

  return (
    <AppShell>
      <div className="douyin-page">
        <section className="douyin-hero">
          <div className="douyin-hero-copy">
            <span className="eyebrow">
              <Sparkles size={14} /> VIDEO FETCHER
            </span>
            <h1>把抖音链接，变成可以保存的视频。</h1>
            <p>
              自动选择更稳定的解析线路，视频直接保存到你的电脑，不进入字幕任务。
            </p>
          </div>
          <div className="douyin-orbit" aria-hidden="true">
            <span />
            <span />
            <Download size={34} />
          </div>
        </section>

        <section className="douyin-workbench">
          <div className="auto-route">
            <span>
              <Sparkles size={15} /> 自动选择解析线路
            </span>
            <div className="route-status">
              {checkingAgent ? (
                <>
                  <LoaderCircle className="spin" size={15} /> 正在检查可用线路
                </>
              ) : localReady ? (
                <>
                  <CheckCircle2 size={15} /> 本机可用，失败时自动转云端
                </>
              ) : (
                <>
                  <Cloud size={15} /> 自动使用云端解析
                </>
              )}
            </div>
          </div>

          <label className="douyin-input-label" htmlFor="douyin-link">
            分享文案或视频链接
          </label>
          <div className="douyin-input-row">
            <div className="douyin-input-wrap">
              <Link2 size={20} />
              <textarea
                id="douyin-link"
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder="粘贴“复制链接”得到的整段文案，或 https://v.douyin.com/…"
                rows={3}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                    void parse();
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
                onClick={parse}
                disabled={parsing || !text.trim()}
              >
                {parsing ? (
                  <>
                    <LoaderCircle className="spin" size={18} /> 正在解析
                  </>
                ) : (
                  <>
                    <Sparkles size={18} /> 解析视频
                  </>
                )}
              </button>
            </div>
          </div>
          <small className="douyin-shortcut">按 ⌘ / Ctrl + Enter 快速解析</small>
        </section>

        {error && <div className="douyin-error">{error}</div>}

        {parsed && (
          <section className="video-result">
            <div className="video-cover">
              <video
                key={previewUrl}
                src={previewUrl}
                poster={parsed.data.cover_url ?? undefined}
                controls
                playsInline
                preload="metadata"
                crossOrigin={parsed.route === "local" ? "anonymous" : undefined}
                onError={() => setVideoError(true)}
                onLoadedData={() => setVideoError(false)}
              />
              <span>{formatDuration(parsed.data.duration_ms)}</span>
            </div>
            <div className="video-details">
              <div className="result-route">
                {parsed.route === "local" ? <Laptop size={14} /> : <Cloud size={14} />}
                {parsed.route === "local" ? "本机解析" : "云端解析"}
              </div>
              <h2>{parsed.data.title}</h2>
              <p className="video-author">@{parsed.data.author}</p>
              <div className="video-facts">
                <span>
                  <Gauge size={15} />
                  {selectedQuality?.width && selectedQuality.height
                    ? `${selectedQuality.width} × ${selectedQuality.height}`
                    : selectedQuality?.label}
                </span>
                <span>{formatBytes(selectedQuality?.estimated_bytes)}</span>
                <span>作品 {parsed.data.aweme_id}</span>
              </div>

              {videoError && (
                <p className="video-playback-error">
                  视频预览加载失败，不影响重新解析或下载。
                </p>
              )}

              <div className="quality-recommended">
                <CheckCircle2 size={16} />
                <span>
                  已自动选择
                  <strong>{selectedQuality?.label ?? "推荐画质"}</strong>
                </span>
                <small>始终优先最高/推荐画质</small>
              </div>

              {downloading && (
                <div className="download-progress">
                  <div>
                    <span>
                      {downloadTarget === "folder"
                        ? "正在保存到指定目录"
                        : "正在准备浏览器下载"}
                    </span>
                    <strong>{progress ? `${progress}%` : "连接中"}</strong>
                  </div>
                  <div className="download-progress-track">
                    <span style={{ width: `${Math.max(progress, 3)}%` }} />
                  </div>
                  <small>{speed || "正在建立安全下载连接…"}</small>
                </div>
              )}

              {downloadStatus && (
                <div
                  className={`download-status ${downloadStatus.kind}`}
                  role={downloadStatus.kind === "error" ? "alert" : "status"}
                >
                  {downloadStatus.kind === "success" ? (
                    <CheckCircle2 size={17} />
                  ) : (
                    <X size={17} />
                  )}
                  {downloadStatus.message}
                </div>
              )}

              <div className="download-actions">
                {hasPermission(user, "subtitle_workspace") && (
                  <button
                    type="button"
                    className="transcribe-video-button"
                    onClick={() =>
                      navigate("/douyin-transcribe", { state: { text } })
                    }
                    disabled={downloading}
                  >
                    <AudioLines size={19} />
                    转成说话文案
                  </button>
                )}
                <button
                  type="button"
                  className="download-button"
                  onClick={() => void download("folder")}
                  disabled={downloading}
                >
                  <FolderDown size={19} />
                  {downloading && downloadTarget === "folder"
                    ? "正在下载"
                    : "保存到指定目录"}
                </button>
                <button
                  type="button"
                  className="browser-download-button"
                  onClick={() => void download("browser")}
                  disabled={downloading}
                >
                  <Download size={18} />
                  {downloading && downloadTarget === "browser"
                    ? "正在下载"
                    : "浏览器下载"}
                </button>
                {downloading && (
                  <button
                    type="button"
                    className="cancel-download"
                    onClick={() => abortRef.current?.abort()}
                  >
                    取消
                  </button>
                )}
              </div>
            </div>
          </section>
        )}

        <section className="douyin-trust">
          <ShieldCheck size={20} />
          <div>
            <strong>请只下载本人拥有或已经获得授权的内容</strong>
            <span>
              服务会温和限速并在解析线路受限时停止重试，不会尝试破解验证码。
            </span>
          </div>
          <code>{AGENT_URL.replace("http://", "")}</code>
        </section>
      </div>
    </AppShell>
  );
}
