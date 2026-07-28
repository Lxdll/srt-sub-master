import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  FileText,
  MoreHorizontal,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Task } from "../types";

interface TaskListProps {
  tasks: Task[];
  onChanged: () => void;
}

const statusMap = {
  uploading: ["本地复制中", Clock3],
  queued: ["排队中", Clock3],
  downloading: ["下载视频中", RefreshCw],
  transcribing: ["识别中", RefreshCw],
  ready: ["可校对", CheckCircle2],
  failed: ["失败", AlertCircle],
} as const;

export function TaskList({ tasks, onChanged }: TaskListProps) {
  async function remove(task: Task) {
    if (
      !window.confirm(
        `确定删除“${task.original_name}”吗？网站中的字幕记录会被永久删除。`,
      )
    )
      return;
    await api.deleteTask(task.id);
    onChanged();
  }

  async function retry(task: Task) {
    await api.retryTask(task.id);
    onChanged();
  }

  if (!tasks.length) {
    return (
      <div className="empty-tasks">
        <FileText size={28} />
        <strong>还没有字幕任务</strong>
        <p>导入一份本机生成的 SRT，第一份字幕会出现在这里。</p>
      </div>
    );
  }

  return (
    <div className="task-list">
      {tasks.map((task) => {
        const [label, Icon] = statusMap[task.status];
        return (
          <article className="task-row" key={task.id}>
            <div className="task-file-icon">
              <FileText size={21} />
            </div>
            <div className="task-name">
              <Link to={`/tasks/${task.id}`}>{task.original_name}</Link>
              <span>
                {formatBytes(task.size_bytes)}
                {task.duration_ms ? ` · ${formatDuration(task.duration_ms)}` : ""}
                {" · "}
                {new Date(task.created_at).toLocaleString("zh-CN")}
              </span>
            </div>
            <div className={`task-status ${task.status}`}>
              <Icon size={15} className={task.status === "transcribing" ? "spin" : ""} />
              {label}
              {(task.status === "transcribing" ||
                task.status === "downloading") &&
                ` ${Math.round(task.progress)}%`}
            </div>
            <span className="model-tag">
              {task.model_id === "imported-srt"
                ? "SRT"
                : task.model_id === "whisper-small-q5_1"
                  ? "服务器 Small Q5"
                  : task.model_id}
            </span>
            <div className="task-menu">
              {task.status === "failed" && (
                <button className="icon-button" onClick={() => retry(task)} title="重试">
                  <RefreshCw size={17} />
                </button>
              )}
              <button
                className="icon-button danger"
                onClick={() => remove(task)}
                title="删除"
              >
                <Trash2 size={17} />
              </button>
              <MoreHorizontal size={18} className="muted-icon" />
            </div>
          </article>
        );
      })}
    </div>
  );
}

function formatBytes(bytes: number) {
  if (!bytes) return "大小待下载";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatDuration(milliseconds: number) {
  const total = Math.round(milliseconds / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${minutes.toString().padStart(2, "0")}:${seconds
        .toString()
        .padStart(2, "0")}`
    : `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
