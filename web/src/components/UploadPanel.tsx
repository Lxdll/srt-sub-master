import { FileVideo, UploadCloud, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { uploadJob } from "../lib/agent";
import type { LocalHealth, LocalSystem } from "../types";

interface UploadPanelProps {
  health: LocalHealth | null;
  system: LocalSystem | null;
  onUploaded: () => void;
}

export function UploadPanel({ health, system, onUploaded }: UploadPanelProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [modelId, setModelId] = useState(
    () => system?.models.find((model) => model.recommended)?.id ?? "large-v3",
  );
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  const installedModels =
    system?.models.filter(
      (model) => model.installed || model.download?.status === "ready",
    ) ?? [];

  useEffect(() => {
    if (!installedModels.some((model) => model.id === modelId)) {
      const next =
        installedModels.find((model) => model.recommended) ?? installedModels[0];
      if (next) setModelId(next.id);
    }
  }, [installedModels, modelId]);

  function select(next: File | undefined) {
    if (!next) return;
    if (next.type !== "video/mp4" && !next.name.toLowerCase().endsWith(".mp4")) {
      setError("当前只支持 MP4 视频");
      return;
    }
    setError("");
    setFile(next);
  }

  async function start() {
    if (!file || !health?.device_id) return;
    setUploading(true);
    setError("");
    try {
      const task = await api.createTask({
        device_id: health.device_id,
        original_name: file.name,
        size_bytes: file.size,
        model_id: modelId,
      });
      await uploadJob(
        file,
        task.id,
        modelId,
        task.command_token,
        setProgress,
      );
      onUploaded();
      navigate(`/tasks/${task.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建任务失败");
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="upload-card">
      <div
        className={`drop-zone ${file ? "has-file" : ""}`}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          select(event.dataTransfer.files[0]);
        }}
        onClick={() => !file && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".mp4,video/mp4"
          hidden
          onChange={(event) => select(event.target.files?.[0])}
        />
        {file ? (
          <div className="selected-file">
            <div className="file-icon">
              <FileVideo size={26} />
            </div>
            <div>
              <strong>{file.name}</strong>
              <span>{formatBytes(file.size)}</span>
            </div>
            <button
              className="icon-button"
              onClick={(event) => {
                event.stopPropagation();
                setFile(null);
              }}
              aria-label="移除视频"
            >
              <X size={18} />
            </button>
          </div>
        ) : (
          <>
            <div className="upload-icon">
              <UploadCloud size={28} />
            </div>
            <h3>把 MP4 拖到这里</h3>
            <p>或点击选择电脑中的视频 · 文件不会上传服务器</p>
          </>
        )}
      </div>
      <div className="upload-controls">
        <label>
          识别模型
          <select
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            disabled={!installedModels.length}
          >
            {installedModels.length ? (
              installedModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))
            ) : (
              <option>请先安装一个模型</option>
            )}
          </select>
        </label>
        <button
          className="primary-button start-button"
          disabled={
            !file || !health?.paired || !installedModels.length || uploading
          }
          onClick={start}
        >
          {uploading ? `正在复制到本机 ${progress}%` : "开始识别"}
        </button>
      </div>
      {uploading && (
        <div className="upload-progress">
          <span style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && <div className="form-error">{error}</div>}
    </section>
  );
}

export function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
