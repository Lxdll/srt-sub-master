import {
  ArrowLeft,
  Download,
  FileQuestion,
  FileVideo,
  RotateCcw,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import {
  SegmentEditor,
  type SegmentEditorHandle,
} from "../components/SegmentEditor";
import { api } from "../lib/api";
import { agent, AGENT_URL, relinkVideo } from "../lib/agent";

export function EditorPage() {
  const { taskId = "" } = useParams();
  const queryClient = useQueryClient();
  const videoRef = useRef<HTMLVideoElement>(null);
  const rowRefs = useRef(new Map<string, SegmentEditorHandle>());
  const [currentMs, setCurrentMs] = useState(0);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [relinking, setRelinking] = useState(false);
  const [relinkProgress, setRelinkProgress] = useState(0);
  const [error, setError] = useState("");
  const [videoToken, setVideoToken] = useState("");

  const task = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId),
    refetchInterval: (query) =>
      query.state.data?.status === "ready" ? false : 1500,
  });

  useEffect(() => {
    agent
      .health()
      .then((health) => setDeviceId(health.device_id ?? null))
      .catch(() => setDeviceId(null));
  }, []);

  const segments = task.data?.segments ?? [];

  const active = segments.find(
    (segment) => currentMs >= segment.start_ms && currentMs < segment.end_ms,
  );

  useEffect(() => {
    if (active) rowRefs.current.get(active.id)?.scrollIntoView();
  }, [active?.id]);

  const asset = task.data?.device_assets.find(
    (item) => item.device_id === deviceId,
  );

  useEffect(() => {
    if (!asset || !deviceId) {
      setVideoToken("");
      return;
    }
    api
      .commandToken(deviceId, taskId)
      .then(({ token }) => setVideoToken(token))
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "视频授权失败"),
      );
  }, [asset?.id, deviceId, taskId]);

  function seek(seconds: number) {
    if (!videoRef.current) return;
    videoRef.current.currentTime = seconds;
    void videoRef.current.play();
  }

  async function relink(file: File | undefined) {
    if (!file || !deviceId) return;
    setRelinking(true);
    setError("");
    try {
      const { command_token } = await api.relinkToken(taskId, deviceId);
      await relinkVideo(file, taskId, command_token, setRelinkProgress);
      await queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重新关联失败");
    } finally {
      setRelinking(false);
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
          <Link to="/" className="back-link">
            <ArrowLeft size={17} /> 返回工作台
          </Link>
          <div className="editor-title">
            <strong>{task.data.original_name}</strong>
            <span>
              {task.data.model_id} · {segments.length} 条字幕
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
              {task.data.status === "failed" ? "识别没有完成" : "正在本机识别"}
            </h2>
            <p>
              {task.data.error ||
                "可以暂时离开页面，本机识别器会继续处理并同步进度。"}
            </p>
            <div className="large-progress">
              <span style={{ width: `${task.data.progress}%` }} />
            </div>
            <strong>{Math.round(task.data.progress)}%</strong>
            {task.data.status === "failed" && (
              <button
                className="primary-button"
                onClick={async () => {
                  await api.retryTask(taskId);
                  await task.refetch();
                }}
              >
                <RotateCcw size={17} /> 重试识别
              </button>
            )}
          </section>
        ) : (
          <>
            <section className="video-stage">
              {asset && videoToken ? (
                <video
                  ref={videoRef}
                  controls
                  preload="metadata"
                  src={`${AGENT_URL}/assets/${asset.local_asset_id}?task_id=${encodeURIComponent(taskId)}&token=${encodeURIComponent(videoToken)}`}
                  onTimeUpdate={(event) =>
                    setCurrentMs(event.currentTarget.currentTime * 1000)
                  }
                />
              ) : (
                <div className="missing-video">
                  <FileQuestion size={36} />
                  <h2>这台电脑还没有原视频</h2>
                  <p>
                    字幕已经保存在服务器。重新选择同一个 MP4，校验通过后即可继续播放校对。
                  </p>
                  <label className="primary-button">
                    <FileVideo size={17} />
                    {relinking
                      ? `正在关联 ${relinkProgress}%`
                      : "重新选择原视频"}
                    <input
                      type="file"
                      accept=".mp4,video/mp4"
                      hidden
                      onChange={(event) => relink(event.target.files?.[0])}
                    />
                  </label>
                  {error && <div className="form-error">{error}</div>}
                </div>
              )}
            </section>

            <section className="subtitle-workbench">
              <div className="subtitle-heading">
                <div>
                  <span className="eyebrow">LIVE REVIEW</span>
                  <h2>字幕校对</h2>
                </div>
                <p>播放时自动定位 · 点击时间跳转 · 修改后自动保存</p>
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
                  />
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}
