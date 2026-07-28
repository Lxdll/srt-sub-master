from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import platform
from pathlib import Path
import threading
from typing import Any, Callable

import httpx

from .config import load_state
from .db import db_session, now
from .models import definition, model_path


job_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcription")
job_lock = threading.Lock()


def _server_client() -> tuple[httpx.Client, dict[str, Any]]:
    state = load_state()
    if not state.get("server_url") or not state.get("device_token"):
        raise RuntimeError("本机识别器尚未配对。")
    client = httpx.Client(
        base_url=state["server_url"],
        headers={"Authorization": f"Bearer {state['device_token']}"},
        timeout=60,
    )
    return client, state


def _progress(
    task_id: str,
    status: str,
    progress: float,
    error: str | None = None,
    *,
    downloaded_bytes: int | None = None,
    download_total_bytes: int | None = None,
    download_speed_bps: float | None = None,
    download_eta_seconds: int | None = None,
) -> None:
    with db_session() as db:
        db.execute(
            """
            UPDATE jobs SET status = ?, progress = ?, error = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (status, progress, error, now(), task_id),
        )
    try:
        client, _ = _server_client()
        payload = {
            "status": status,
            "progress": progress,
            "error": error,
        }
        if downloaded_bytes is not None:
            payload["downloaded_bytes"] = downloaded_bytes
        if download_total_bytes is not None:
            payload["download_total_bytes"] = download_total_bytes
        if download_speed_bps is not None:
            payload["download_speed_bps"] = download_speed_bps
        if download_eta_seconds is not None:
            payload["download_eta_seconds"] = download_eta_seconds
        with client:
            client.post(
                f"/api/agent/tasks/{task_id}/progress",
                json=payload,
            ).raise_for_status()
    except Exception:
        pass


def _transcribe_mlx(
    path: Path,
    model_id: str,
    duration_ms: int,
    callback: Callable[[float], None],
) -> list[dict[str, Any]]:
    import mlx_whisper

    model = model_path(model_id)
    if not model:
        raise RuntimeError("所选模型尚未下载。")
    transcribe_module = importlib.import_module("mlx_whisper.transcribe")
    original_tqdm = transcribe_module.tqdm.tqdm

    class CallbackProgress:
        def __init__(self, total: int = 0, **_: Any) -> None:
            self.total = total
            self.n = 0

        def __enter__(self) -> "CallbackProgress":
            return self

        def __exit__(self, *_: Any) -> None:
            callback(90)

        def update(self, amount: int) -> None:
            self.n += amount
            if self.total:
                callback(10 + min(80, self.n / self.total * 80))

    transcribe_module.tqdm.tqdm = CallbackProgress
    try:
        result = mlx_whisper.transcribe(
            str(path),
            path_or_hf_repo=str(model),
            language="zh",
            task="transcribe",
            word_timestamps=True,
            temperature=0.0,
            verbose=False,
        )
    finally:
        transcribe_module.tqdm.tqdm = original_tqdm
    return [
        {
            "start_ms": max(0, round(float(segment["start"]) * 1000)),
            "end_ms": max(1, round(float(segment["end"]) * 1000)),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in result.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]


def _transcribe_windows(
    path: Path,
    model_id: str,
    duration_ms: int,
    callback: Callable[[float], None],
) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel
    from ctranslate2 import get_cuda_device_count

    model = model_path(model_id)
    if not model:
        raise RuntimeError("所选模型尚未下载。")
    use_cuda = get_cuda_device_count() > 0
    whisper = WhisperModel(
        str(model),
        device="cuda" if use_cuda else "cpu",
        compute_type="float16" if use_cuda else "int8",
    )
    segments, _ = whisper.transcribe(
        str(path), language="zh", beam_size=5, vad_filter=True
    )
    output: list[dict[str, Any]] = []
    for segment in segments:
        output.append(
            {
                "start_ms": max(0, round(segment.start * 1000)),
                "end_ms": max(1, round(segment.end * 1000)),
                "text": segment.text.strip(),
            }
        )
        callback(10 + min(80, segment.end * 1000 / duration_ms * 80))
    return output


def run_job(task_id: str) -> None:
    with db_session() as db:
        row = db.execute(
            """
            SELECT j.*, a.path, a.sha256, a.duration_ms, a.size_bytes
            FROM jobs j JOIN assets a ON a.id = j.asset_id
            WHERE j.task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        return
    start_progress = max(5.0, float(row["progress"]))
    _progress(task_id, "transcribing", start_progress)
    try:
        callback = lambda value: _progress(
            task_id,
            "transcribing",
            max(start_progress, round(value, 1)),
        )
        if platform.system() == "Darwin":
            segments = _transcribe_mlx(
                Path(row["path"]), row["model_id"], row["duration_ms"], callback
            )
        else:
            segments = _transcribe_windows(
                Path(row["path"]), row["model_id"], row["duration_ms"], callback
            )
        if not segments:
            raise RuntimeError("识别完成，但没有检测到可用语音。")
        client, _ = _server_client()
        with client:
            response = client.post(
                f"/api/agent/tasks/{task_id}/result",
                json={
                    "local_asset_id": row["asset_id"],
                    "sha256": row["sha256"],
                    "duration_ms": row["duration_ms"],
                    "size_bytes": row["size_bytes"],
                    "segments": segments,
                },
                timeout=120,
            )
            response.raise_for_status()
        _progress(task_id, "ready", 100)
    except Exception as exc:
        _progress(task_id, "failed", 0, str(exc))


def queue_job(task_id: str) -> None:
    with job_lock:
        job_executor.submit(run_job, task_id)
