from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


class MediaError(RuntimeError):
    pass


def ffprobe_path() -> str:
    bundled = Path(__file__).resolve().parents[2] / "bin" / (
        "ffprobe.exe" if os.name == "nt" else "ffprobe"
    )
    if bundled.exists():
        return str(bundled)
    found = shutil.which("ffprobe")
    if not found:
        raise MediaError("没有找到 FFprobe，请重新安装本机识别器。")
    return found


def probe_video(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".mp4":
        raise MediaError("当前只支持 MP4 视频。")
    try:
        completed = subprocess.run(
            [
                ffprobe_path(),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        data = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MediaError("无法读取该 MP4，文件可能损坏。") from exc
    if not data.get("streams"):
        raise MediaError("该视频没有音频轨道。")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise MediaError("无法读取视频时长。")
    data["duration_ms"] = round(duration * 1000)
    return data
