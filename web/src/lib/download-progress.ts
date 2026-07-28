export interface DownloadProgress {
  downloaded_bytes?: number;
  download_total_bytes?: number;
  download_speed_bps?: number;
  download_eta_seconds?: number | null;
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${Math.max(0, Math.round(bytes))} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatEta(seconds: number) {
  if (seconds < 60) return `${Math.max(1, Math.ceil(seconds))} 秒`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} 分钟`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return minutes ? `${hours} 小时 ${minutes} 分钟` : `${hours} 小时`;
}

export function downloadProgressText(progress: DownloadProgress) {
  const downloaded = progress.downloaded_bytes ?? 0;
  const total = progress.download_total_bytes ?? 0;
  const speed = progress.download_speed_bps ?? 0;
  const eta = progress.download_eta_seconds;
  const pieces = [
    total > 0
      ? `${formatBytes(downloaded)} / ${formatBytes(total)}`
      : downloaded > 0
        ? `已下载 ${formatBytes(downloaded)}`
        : "正在建立下载连接",
  ];
  if (speed > 0) pieces.push(`${formatBytes(speed)}/s`);
  if (eta !== null && eta !== undefined && eta > 0) {
    pieces.push(`预计剩余 ${formatEta(eta)}`);
  }
  return pieces.join(" · ");
}
