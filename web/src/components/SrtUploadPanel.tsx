import { FileText, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

interface SrtUploadPanelProps {
  onUploaded: () => void;
}

export function SrtUploadPanel({ onUploaded }: SrtUploadPanelProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  function select(next: File | undefined) {
    if (!next) return;
    if (!next.name.toLowerCase().endsWith(".srt")) {
      setError("请选择 SRT 字幕文件");
      return;
    }
    if (next.size > 5 * 1024 * 1024) {
      setError("SRT 文件不能超过 5MB");
      return;
    }
    setError("");
    setFile(next);
  }

  async function start() {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const task = await api.importSrt(file);
      onUploaded();
      navigate(`/tasks/${task.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入 SRT 失败");
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="upload-card">
      <div
        className={`drop-zone ${file ? "has-file" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="选择 SRT 字幕文件"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          select(event.dataTransfer.files[0]);
        }}
        onClick={() => !file && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (!file && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".srt,application/x-subrip"
          hidden
          onChange={(event) => select(event.target.files?.[0])}
        />
        {file ? (
          <div className="selected-file">
            <div className="file-icon">
              <FileText size={26} />
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
              aria-label="移除字幕"
            >
              <X size={18} />
            </button>
          </div>
        ) : (
          <>
            <div className="upload-icon">
              <UploadCloud size={28} />
            </div>
            <h3>把 SRT 拖到这里</h3>
            <p>或点击选择字幕文件 · 网站只接收字幕，不接收视频</p>
          </>
        )}
      </div>
      <div className="srt-upload-action">
        <div>
          <strong>本机转写，网站校对</strong>
          <span>可由任意 AI 调用通用本地工具生成 SRT</span>
        </div>
        <button
          className="primary-button start-button"
          disabled={!file || uploading}
          onClick={start}
        >
          {uploading ? "正在导入…" : "导入并开始校对"}
        </button>
      </div>
      {error && <div className="form-error">{error}</div>}
    </section>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
