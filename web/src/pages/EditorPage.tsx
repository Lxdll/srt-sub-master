import {
  ArrowLeft,
  Clock3,
  Download,
  FileQuestion,
  FileVideo,
  RefreshCw,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import {
  SegmentEditor,
  type SegmentEditorHandle,
} from "../components/SegmentEditor";
import { api } from "../lib/api";
import { douyinAgent } from "../lib/douyin-agent";

export function EditorPage() {
  const { taskId = "" } = useParams();
  const videoRef = useRef<HTMLVideoElement>(null);
  const rowRefs = useRef(new Map<string, SegmentEditorHandle>());
  const pausedForEditingRef = useRef(false);
  const resumeAfterEditingRef = useRef(false);
  const manuallyPausedRef = useRef(true);
  const resumeTimerRef = useRef<number | null>(null);
  const [currentMs, setCurrentMs] = useState(0);
  const [videoUrl, setVideoUrl] = useState("");
  const [videoName, setVideoName] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");
  const [localAssetUrl, setLocalAssetUrl] = useState("");

  const task = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && status !== "ready" && status !== "failed" ? 2000 : false;
    },
  });

  useEffect(() => {
    return () => {
      if (videoUrl) URL.revokeObjectURL(videoUrl);
      if (resumeTimerRef.current !== null) {
        window.clearTimeout(resumeTimerRef.current);
      }
    };
  }, [videoUrl]);

  const segments = task.data?.segments ?? [];
  const effectiveVideoUrl =
    videoUrl ||
    localAssetUrl ||
    (task.data?.media_available ? api.taskMediaUrl(taskId) : "");

  useEffect(() => {
    const data = task.data;
    if (
      !data ||
      data.backend !== "local_agent" ||
      !data.device_id ||
      !data.device_assets.length
    ) {
      setLocalAssetUrl("");
      return;
    }
    const controller = new AbortController();
    void douyinAgent
      .health(controller.signal)
      .then(async (health) => {
        if (health.device_id !== data.device_id) return;
        const asset = data.device_assets.find(
          (item) => item.device_id === data.device_id,
        );
        if (!asset) return;
        const { token } = await api.commandToken(data.device_id!, taskId);
        setLocalAssetUrl(
          douyinAgent.assetUrl(asset.local_asset_id, taskId, token),
        );
      })
      .catch(() => setLocalAssetUrl(""));
    return () => controller.abort();
  }, [task.data, taskId]);

  const active = segments.find(
    (segment) => currentMs >= segment.start_ms && currentMs < segment.end_ms,
  );

  useEffect(() => {
    if (active) rowRefs.current.get(active.id)?.scrollIntoView();
  }, [active?.id]);

  function seek(seconds: number) {
    if (!videoRef.current) return;
    videoRef.current.currentTime = seconds;
    void videoRef.current.play();
  }

  function startEditing() {
    if (resumeTimerRef.current !== null) {
      window.clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = null;
      return;
    }
    const video = videoRef.current;
    if (!video) return;
    resumeAfterEditingRef.current = !video.paused && !video.ended;
    if (resumeAfterEditingRef.current) {
      pausedForEditingRef.current = true;
      video.pause();
    }
  }

  function finishEditing() {
    if (!videoRef.current || !resumeAfterEditingRef.current) return;
    resumeTimerRef.current = window.setTimeout(() => {
      resumeTimerRef.current = null;
      if (!manuallyPausedRef.current && videoRef.current?.paused) {
        void videoRef.current.play();
      }
      resumeAfterEditingRef.current = false;
    }, 0);
  }

  function selectVideo(file: File | undefined) {
    if (!file) return;
    setVideoUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(file);
    });
    setVideoName(file.name);
  }

  async function retry() {
    setRetrying(true);
    setRetryError("");
    try {
      await api.retryTask(taskId);
      await task.refetch();
    } catch (reason) {
      setRetryError(
        reason instanceof Error ? reason.message : "重新识别失败，请稍后再试。",
      );
    } finally {
      setRetrying(false);
    }
  }

  if (task.isLoading) {
    return <div className="page-loader">正在打开字幕任务…</div>;
  }
  if (!task.data) {
    return <div className="page-loader">任务不存在或无权访问。</div>;
  }

  return (
    <AppShell>
      <div className="editor-page">
        <div className="editor-topbar">
          <Link to="/subtitle" className="back-link">
            <ArrowLeft size={17} /> 返回工作台
          </Link>
          <div className="editor-title">
            <strong>{task.data.original_name}</strong>
            <span>
              {task.data.model_id === "imported-srt"
                ? "SRT 导入"
                : task.data.backend === "local_agent"
                  ? `本机 ${task.data.model_id}`
                  : task.data.model_id}{" "}
              · {segments.length} 条字幕
            </span>
          </div>
          <div className="export-actions">
            <a
              className="secondary-button"
              href={`/api/tasks/${taskId}/export?format=txt`}
            >
              <Download size={16} /> TXT
            </a>
            <a
              className="primary-button"
              href={`/api/tasks/${taskId}/export?format=srt`}
            >
              <Download size={16} /> SRT
            </a>
          </div>
        </div>

        {task.data.status !== "ready" ? (
          <section className="processing-panel">
            <div className="processing-orbit">
              <span />
              <FileVideo size={30} />
            </div>
            <h2>
              {task.data.status === "failed"
                ? "这次没有识别成功"
                : task.data.status === "queued"
                  ? "任务正在排队"
                  : task.data.status === "downloading"
                    ? "正在下载视频"
                    : "正在识别说话内容"}
            </h2>
            <p>
              {task.data.error ||
                (task.data.status === "queued" && task.data.queue_position
                  ? `当前排在第 ${task.data.queue_position} 位，可以关闭页面稍后再回来。`
                  : task.data.backend === "local_agent"
                    ? "请保持本机 Agent 运行；可以关闭网页，Agent 会继续处理。"
                    : "服务器会自动完成处理，可以关闭页面稍后再回来。")}
            </p>
            <div className="large-progress">
              <span style={{ width: `${task.data.progress}%` }} />
            </div>
            <strong>{Math.round(task.data.progress)}%</strong>
            {task.data.status === "failed" && (
              <button
                className="primary-button"
                type="button"
                onClick={() => void retry()}
                disabled={retrying}
              >
                <RefreshCw size={16} className={retrying ? "spin" : ""} />
                {retrying ? "正在重新排队…" : "重新识别"}
              </button>
            )}
            {retryError && <div className="form-error">{retryError}</div>}
          </section>
        ) : (
          <div className="editor-workspace">
            <section className="video-stage">
              {effectiveVideoUrl ? (
                <video
                  ref={videoRef}
                  controls
                  preload="metadata"
                  src={effectiveVideoUrl}
                  onTimeUpdate={(event) =>
                    setCurrentMs(event.currentTarget.currentTime * 1000)
                  }
                  onPlay={() => {
                    manuallyPausedRef.current = false;
                  }}
                  onPause={() => {
                    if (pausedForEditingRef.current) {
                      pausedForEditingRef.current = false;
                      return;
                    }
                    manuallyPausedRef.current = true;
                  }}
                />
              ) : (
                <div className="missing-video">
                  <FileQuestion size={36} />
                  <h2>
                    {task.data.source_type === "douyin"
                      ? task.data.backend === "local_agent"
                        ? "未连接到保存视频的本机 Agent"
                        : "校对视频已过期"
                      : "可选：选择本机原视频"}
                  </h2>
                  <p>
                    {task.data.source_type === "douyin"
                      ? task.data.backend === "local_agent"
                        ? "启动完成转写的 Agent 后可直接播放；也可以手动选择本机视频。"
                        : "服务器只保留视频 7 天，字幕仍可继续修改和导出。"
                      : "视频只在当前浏览器页面中播放，不会上传或保存到网站。"}
                  </p>
                  <label className="primary-button">
                    <FileVideo size={17} />
                    选择本机视频
                    <input
                      type="file"
                      accept="video/*,.mp4"
                      hidden
                      onChange={(event) =>
                        selectVideo(event.target.files?.[0])
                      }
                    />
                  </label>
                </div>
              )}
            </section>

            <section
              className="subtitle-workbench"
              tabIndex={-1}
              onMouseDown={(event) => {
                const target = event.target as HTMLElement;
                if (!target.closest("textarea, button, a, input")) {
                  event.currentTarget.focus();
                }
              }}
            >
              <div className="subtitle-heading">
                <div>
                  <span className="eyebrow">LIVE REVIEW</span>
                  <h2>字幕校对</h2>
                </div>
                <p>
                  {videoName
                    ? `${videoName} · 播放时自动定位 · 修改后自动保存`
                    : task.data.media_available
                      ? "抖音视频 7 天内可播放 · 修改后自动保存"
                    : "选择视频后可同步定位 · 修改后自动保存"}
                </p>
              </div>
              <div className="subtitle-list">
                {segments.map((segment) => (
                  <SegmentEditor
                    key={segment.id}
                    ref={(handle) => {
                      if (handle) rowRefs.current.set(segment.id, handle);
                      else rowRefs.current.delete(segment.id);
                    }}
                    taskId={taskId}
                    segment={segment}
                    active={active?.id === segment.id}
                    onSeek={seek}
                    onEditStart={startEditing}
                    onEditEnd={finishEditing}
                  />
                ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </AppShell>
  );
}
