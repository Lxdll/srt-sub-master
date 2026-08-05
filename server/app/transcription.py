from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from douyin_engine import DouyinError, ParseResult, Quality, build_download_filename

from .chinese import to_simplified_chinese
from .cloud_transcription import (
    CloudTranscriptionError,
    cloud_transcription_service,
)
from .config import settings
from .db import db_session, initialize_database, utc_now
from .douyin import douyin_service
from .srt import SrtError, parse_srt

ACTIVE_STATUSES = ("queued", "downloading", "transcribing")
MODEL_ID = "whisper-small-q5_1"
WORKER_SERVICE = "douyin-transcription"
PROGRESS_PATTERN = re.compile(r"progress\s*=\s*(\d{1,3})%", re.IGNORECASE)


class TranscriptionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


def _task_root(task_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f-]{36}", task_id):
        raise ValueError("invalid task id")
    return settings.data_dir / "douyin-transcriptions" / task_id


def _relative_media_path(task_id: str) -> str:
    return str(Path("douyin-transcriptions") / task_id / "video.mp4")


def resolve_media_path(relative_name: str | None) -> Path | None:
    if not relative_name:
        return None
    root = settings.data_dir.resolve()
    candidate = (root / relative_name).resolve()
    if candidate == root or root not in candidate.parents:
        return None
    return candidate


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def delete_job_media(task_id: str) -> None:
    with db_session() as db:
        row = db.execute(
            """
            SELECT j.fc_task_id, j.oss_media_key, j.oss_result_key, t.backend
            FROM server_transcription_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE j.task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if row and row["backend"] == "fc":
        try:
            cloud_transcription_service.stop(row["fc_task_id"])
            cloud_transcription_service.delete_objects(
                row["oss_media_key"],
                row["oss_result_key"],
            )
        except Exception:
            pass
    _remove_tree(_task_root(task_id))


def cleanup_expired_media() -> int:
    now_value = datetime.now(UTC)
    removed = 0
    cloud_objects: list[tuple[str | None, str | None]] = []
    with db_session() as db:
        rows = db.execute(
            """
            SELECT task_id, media_filename, oss_media_key, oss_result_key
            FROM server_transcription_jobs
            WHERE (media_filename IS NOT NULL OR oss_media_key IS NOT NULL)
              AND media_expires_at IS NOT NULL
              AND media_expires_at <= ?
            """,
            (now_value.isoformat(),),
        ).fetchall()
        for row in rows:
            path = resolve_media_path(row["media_filename"])
            if path and path.exists():
                path.unlink(missing_ok=True)
                removed += 1
            if row["oss_media_key"]:
                cloud_objects.append(
                    (row["oss_media_key"], row["oss_result_key"])
                )
                removed += 1
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET media_filename = NULL, media_expires_at = NULL,
                    oss_media_key = NULL, oss_result_key = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (utc_now(), row["task_id"]),
            )
    for media_key, result_key in cloud_objects:
        cloud_transcription_service.delete_objects(media_key, result_key)
    return removed


def media_usage_bytes() -> int:
    if cloud_transcription_service.enabled:
        with db_session() as db:
            row = db.execute(
                """
                SELECT COALESCE(SUM(t.size_bytes), 0) AS total
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE j.oss_media_key IS NOT NULL
                  AND j.media_expires_at > ?
                """,
                (utc_now(),),
            ).fetchone()
        return int(row["total"])
    root = settings.data_dir / "douyin-transcriptions"
    if not root.exists():
        return 0
    total = 0
    for path in root.glob("*/video.mp4"):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def recover_stale_cloud_jobs() -> int:
    if not cloud_transcription_service.enabled:
        return 0
    now_value = datetime.now(UTC)
    running_cutoff = (
        now_value - timedelta(seconds=settings.fc_stale_job_seconds)
    ).isoformat()
    queued_cutoff = (
        now_value - timedelta(seconds=settings.fc_queue_max_age_seconds)
    ).isoformat()
    now = now_value.isoformat()
    with db_session() as db:
        running = db.execute(
            """
            UPDATE tasks
            SET status = 'failed', progress = 0,
                error = '云端转写任务超时，请重试。', updated_at = ?
            WHERE id IN (
                SELECT j.task_id
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE t.status IN ('downloading', 'transcribing')
                  AND t.backend = 'fc'
                  AND t.updated_at <= ?
            )
            """,
            (now, running_cutoff),
        ).rowcount
        queued = db.execute(
            """
            UPDATE tasks
            SET status = 'failed', progress = 0,
                error = '云端转写排队超时，请重试。', updated_at = ?
            WHERE id IN (
                SELECT j.task_id
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE t.status = 'queued'
                  AND t.backend = 'fc'
                  AND t.created_at <= ?
            )
            """,
            (now, queued_cutoff),
        ).rowcount
    return running + queued


def choose_transcription_quality(result: ParseResult) -> Quality:
    def score(item: Quality) -> tuple[int, int, int]:
        dimensions = [
            value for value in (item.width, item.height) if value and value > 0
        ]
        short_edge = min(dimensions) if dimensions else 0
        if short_edge:
            below_target = 1 if short_edge < 480 else 0
            distance = abs(short_edge - 540)
        else:
            below_target = 2
            distance = 10_000
        return (
            below_target,
            distance,
            item.estimated_bytes or item.bitrate or 2**63 - 1,
        )

    return min(result.qualities, key=score)


async def create_transcription_task(
    user: dict[str, Any],
    text: str,
) -> str:
    if not settings.transcription_enabled:
        raise TranscriptionError("抖音转文案功能尚未启用。", status_code=404)
    if settings.transcription_backend not in {"local", "fc"}:
        raise TranscriptionError(
            "转写后端配置无效，请使用 local 或 fc。",
            status_code=503,
        )

    cleanup_expired_media()
    result = await douyin_service.resolve(user, text)
    if (
        result.duration_ms
        and result.duration_ms > settings.transcription_max_duration_seconds * 1000
    ):
        raise TranscriptionError("视频超过 30 分钟，暂不支持转写。")
    quality = choose_transcription_quality(result)
    if (
        quality.estimated_bytes
        and quality.estimated_bytes > settings.transcription_max_source_bytes
    ):
        raise TranscriptionError("视频文件超过 500MB，暂不支持转写。")
    expected_bytes = quality.estimated_bytes or 0
    if (
        media_usage_bytes() + expected_bytes
        > settings.transcription_media_quota_bytes
    ):
        raise TranscriptionError(
            "服务器视频临时空间已满，请等待过期文件自动清理。",
            status_code=507,
        )

    task_id = str(uuid4())
    now = utc_now()
    original_name = build_download_filename(
        result.author,
        result.title,
        result.aweme_id,
        "转写",
    )
    cloud_enabled = cloud_transcription_service.enabled
    if cloud_enabled:
        try:
            cloud_transcription_service.ensure_configured()
        except CloudTranscriptionError as exc:
            raise TranscriptionError(str(exc), status_code=503) from exc

    with db_session() as db:
        user_active = db.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM server_transcription_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE t.user_id = ? AND t.status IN ({",".join("?" * len(ACTIVE_STATUSES))})
            """,
            (user["id"], *ACTIVE_STATUSES),
        ).fetchone()["count"]
        global_active = db.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM server_transcription_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE t.status IN ({",".join("?" * len(ACTIVE_STATUSES))})
            """,
            ACTIVE_STATUSES,
        ).fetchone()["count"]
        if user_active >= settings.transcription_user_queue_limit:
            raise TranscriptionError(
                "当前账号已有 3 个待处理任务，请完成后再提交。",
                status_code=429,
            )
        if global_active >= settings.transcription_global_queue_limit:
            raise TranscriptionError(
                "服务器转写队列已满，请稍后再试。",
                status_code=429,
            )
        db.execute(
            """
            INSERT INTO tasks(
                id, user_id, device_id, backend, original_name, size_bytes,
                duration_ms, model_id, status, progress,
                created_at, updated_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
            """,
            (
                task_id,
                user["id"],
                "fc" if cloud_enabled else "server_local",
                original_name,
                expected_bytes,
                result.duration_ms,
                MODEL_ID,
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO server_transcription_jobs(
                task_id, source_url, aweme_id, attempts, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                result.original_url,
                result.aweme_id,
                1 if cloud_enabled else 0,
                now,
                now,
            ),
        )
    if cloud_enabled:
        extra_allowed_hosts: list[str] = []
        if result.provider == "bhwa":
            host = urlparse(settings.bhwa_api_base).hostname
            if host:
                extra_allowed_hosts.append(host.lower())
        try:
            fc_task_id = await asyncio.to_thread(
                cloud_transcription_service.submit,
                task_id=task_id,
                attempt=1,
                source_urls=list(quality.source_urls),
                extra_allowed_hosts=extra_allowed_hosts,
                expected_bytes=expected_bytes,
                expected_duration_ms=result.duration_ms,
            )
        except Exception as exc:
            with db_session() as db:
                db.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed', progress = 0,
                        error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("无法提交云端转写任务，请检查 FC 配置。", utc_now(), task_id),
                )
            raise TranscriptionError(
                "无法提交云端转写任务，请检查 FC 配置。",
                status_code=502,
            ) from exc
        with db_session() as db:
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET fc_task_id = ?, claimed_at = ?, updated_at = ?
                WHERE task_id = ? AND attempts = 1
                """,
                (fc_task_id, utc_now(), utc_now(), task_id),
            )
    return task_id


def task_transcription_metadata(task_id: str) -> dict[str, Any]:
    with db_session() as db:
        job = db.execute(
            """
            SELECT j.*, t.status, t.backend
            FROM server_transcription_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE j.task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if not job:
            local_job = db.execute(
                """
                SELECT j.*, t.status
                FROM local_douyin_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE j.task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if not local_job:
                return {}
            queue_position = None
            if local_job["status"] == "queued":
                queue_position = db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM local_douyin_jobs j
                    JOIN tasks t ON t.id = j.task_id
                    WHERE t.status = 'queued' AND j.created_at <= ?
                    """,
                    (local_job["created_at"],),
                ).fetchone()["count"]
            return {
                "source_type": "douyin",
                "media_available": False,
                "media_expires_at": None,
                "queue_position": queue_position,
                "downloaded_bytes": local_job["downloaded_bytes"],
                "download_total_bytes": local_job["download_total_bytes"],
                "download_speed_bps": local_job["download_speed_bps"],
                "download_eta_seconds": local_job["download_eta_seconds"],
            }
        queue_position = None
        if job["status"] == "queued":
            queue_position = db.execute(
                """
                SELECT COUNT(*) AS count
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE t.status = 'queued' AND t.backend = ?
                  AND j.created_at <= ?
                """,
                (job["backend"], job["created_at"]),
            ).fetchone()["count"]

    expires_at = (
        datetime.fromisoformat(job["media_expires_at"])
        if job["media_expires_at"]
        else None
    )
    if job["oss_media_key"]:
        media_available = bool(expires_at and expires_at > datetime.now(UTC))
    else:
        path = resolve_media_path(job["media_filename"])
        media_available = bool(
            path
            and path.is_file()
            and expires_at
            and expires_at > datetime.now(UTC)
        )
    return {
        "source_type": "douyin",
        "media_available": media_available,
        "media_expires_at": job["media_expires_at"],
        "queue_position": queue_position,
    }


def media_record(task_id: str) -> sqlite3.Row | None:
    with db_session() as db:
        return db.execute(
            """
            SELECT media_filename, media_expires_at, oss_media_key
            FROM server_transcription_jobs
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()


async def retry_server_job(task_id: str, user: dict[str, Any]) -> bool:
    with db_session() as db:
        existing = db.execute(
            """
            SELECT j.*, t.backend
            FROM server_transcription_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE j.task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if not existing:
        return False

    if existing["backend"] == "fc":
        if not cloud_transcription_service.enabled:
            raise TranscriptionError(
                "该任务使用云端转写，但云端后端当前未启用。",
                status_code=409,
            )
        result = await douyin_service.resolve(user, existing["source_url"])
        quality = choose_transcription_quality(result)
        if (
            quality.estimated_bytes
            and quality.estimated_bytes > settings.transcription_max_source_bytes
        ):
            raise TranscriptionError("视频文件超过 500MB，暂不支持转写。")
        attempt = int(existing["attempts"]) + 1
        extra_allowed_hosts: list[str] = []
        if result.provider == "bhwa":
            host = urlparse(settings.bhwa_api_base).hostname
            if host:
                extra_allowed_hosts.append(host.lower())
        cloud_transcription_service.stop(existing["fc_task_id"])
        cloud_transcription_service.delete_objects(
            existing["oss_media_key"],
            existing["oss_result_key"],
        )
        with db_session() as db:
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET attempts = ?, claimed_at = ?, fc_task_id = NULL,
                    media_filename = NULL, media_expires_at = NULL,
                    oss_media_key = NULL, oss_result_key = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (attempt, utc_now(), utc_now(), task_id),
            )
            db.execute(
                """
                UPDATE tasks
                SET status = 'queued', progress = 0, error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), task_id),
            )
        try:
            fc_task_id = await asyncio.to_thread(
                cloud_transcription_service.submit,
                task_id=task_id,
                attempt=attempt,
                source_urls=list(quality.source_urls),
                extra_allowed_hosts=extra_allowed_hosts,
                expected_bytes=quality.estimated_bytes or 0,
                expected_duration_ms=result.duration_ms,
            )
        except Exception as exc:
            with db_session() as db:
                db.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed', progress = 0,
                        error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("无法重新提交云端转写任务。", utc_now(), task_id),
                )
            raise TranscriptionError(
                "无法重新提交云端转写任务。",
                status_code=502,
            ) from exc
        with db_session() as db:
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET fc_task_id = ?, updated_at = ?
                WHERE task_id = ? AND attempts = ?
                """,
                (fc_task_id, utc_now(), task_id, attempt),
            )
        return True

    with db_session() as db:
        db.execute(
            """
            UPDATE server_transcription_jobs
            SET attempts = 0, claimed_at = NULL, media_filename = NULL,
                media_expires_at = NULL, updated_at = ?
            WHERE task_id = ?
            """,
            (utc_now(), task_id),
        )
        db.execute(
            """
            UPDATE tasks
            SET status = 'queued', progress = 0, error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), task_id),
        )
    delete_job_media(task_id)
    return True


def transcription_status() -> dict[str, Any]:
    recover_stale_cloud_jobs()
    with db_session() as db:
        counts = {
            row["status"]: row["count"]
            for row in db.execute(
                """
                SELECT t.status, COUNT(*) AS count
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                GROUP BY t.status
                """
            ).fetchall()
        }
        heartbeat = db.execute(
            "SELECT * FROM service_heartbeats WHERE service = ?",
            (WORKER_SERVICE,),
        ).fetchone()
    return {
        "enabled": settings.transcription_enabled,
        "backend": settings.transcription_backend,
        "model": MODEL_ID,
        "queued": counts.get("queued", 0),
        "running": counts.get("downloading", 0) + counts.get("transcribing", 0),
        "ready": counts.get("ready", 0),
        "failed": counts.get("failed", 0),
        "media_bytes": media_usage_bytes(),
        "media_quota_bytes": settings.transcription_media_quota_bytes,
        "worker": (
            {
                "current_task_id": heartbeat["current_task_id"],
                "updated_at": heartbeat["updated_at"],
                "details": json.loads(heartbeat["details_json"]),
            }
            if heartbeat and not cloud_transcription_service.enabled
            else None
        ),
    }


class TranscriptionWorker:
    def __init__(self) -> None:
        self.stopping = False
        self.lock_file: Any = None

    def acquire_lock(self) -> None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        lock_path = settings.data_dir / "douyin-transcription-worker.lock"
        self.lock_file = lock_path.open("a+")
        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another transcription worker is already running") from exc

    def heartbeat(
        self,
        task_id: str | None = None,
        **details: Any,
    ) -> None:
        with db_session() as db:
            db.execute(
                """
                INSERT INTO service_heartbeats(
                    service, current_task_id, details_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(service) DO UPDATE SET
                    current_task_id = excluded.current_task_id,
                    details_json = excluded.details_json,
                    updated_at = excluded.updated_at
                """,
                (
                    WORKER_SERVICE,
                    task_id,
                    json.dumps(details, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def recover_interrupted(self) -> None:
        with db_session() as db:
            rows = db.execute(
                """
                SELECT j.task_id, j.attempts
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE t.status IN ('downloading', 'transcribing')
                  AND t.backend = 'server_local'
                """
            ).fetchall()
            for row in rows:
                if row["attempts"] < 2:
                    db.execute(
                        """
                        UPDATE tasks
                        SET status = 'queued', progress = 0,
                            error = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (utc_now(), row["task_id"]),
                    )
                else:
                    db.execute(
                        """
                        UPDATE tasks
                        SET status = 'failed', progress = 0,
                            error = '任务连续两次被中断，请手动重试。',
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (utc_now(), row["task_id"]),
                    )
                db.execute(
                    """
                    UPDATE server_transcription_jobs
                    SET claimed_at = NULL, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (utc_now(), row["task_id"]),
                )
                delete_job_media(row["task_id"])

    def claim_next(self) -> dict[str, Any] | None:
        with db_session() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT j.*, t.user_id
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE t.status = 'queued' AND t.backend = 'server_local'
                ORDER BY j.created_at
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            now = utc_now()
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET attempts = attempts + 1, claimed_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (now, now, row["task_id"]),
            )
            db.execute(
                """
                UPDATE tasks
                SET status = 'downloading', progress = 3,
                    error = NULL, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, row["task_id"]),
            )
            return dict(row)

    def update_progress(
        self,
        task_id: str,
        status: str,
        progress: float,
        error: str | None = None,
    ) -> bool:
        with db_session() as db:
            cursor = db.execute(
                """
                UPDATE tasks
                SET status = ?, progress = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, progress, error, utc_now(), task_id),
            )
        return cursor.rowcount > 0

    async def _download(
        self,
        job: dict[str, Any],
        destination: Path,
    ) -> tuple[ParseResult, int]:
        result = await douyin_service.engine.parse(job["source_url"])
        quality = choose_transcription_quality(result)
        if (
            quality.estimated_bytes
            and quality.estimated_bytes > settings.transcription_max_source_bytes
        ):
            raise TranscriptionError("视频文件超过 500MB，暂不支持转写。")
        response = await douyin_service.open_result_source(result, quality)
        total = int(response.headers.get("content-length") or 0)
        if total > settings.transcription_max_source_bytes:
            await response.aclose()
            raise TranscriptionError("视频文件超过 500MB，暂不支持转写。")
        received = 0
        try:
            with destination.open("wb") as output:
                async for chunk in response.aiter_bytes(256 * 1024):
                    received += len(chunk)
                    if received > settings.transcription_max_source_bytes:
                        raise TranscriptionError("视频文件超过 500MB，下载已停止。")
                    output.write(chunk)
                    if total:
                        progress = 3 + min(17, received / total * 17)
                        self.update_progress(job["task_id"], "downloading", progress)
                        self.heartbeat(
                            job["task_id"],
                            stage="downloading",
                            progress=round(progress, 1),
                        )
        finally:
            await response.aclose()
        if received == 0:
            raise TranscriptionError("视频下载结果为空，请稍后重试。")
        return result, received

    async def _run_command(self, *command: str) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        return process.returncode or 0, output.decode("utf-8", errors="replace")

    async def _duration_ms(self, media: Path) -> int:
        code, output = await self._run_command(
            settings.transcription_ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media),
        )
        if code != 0:
            raise TranscriptionError("无法读取视频时长。")
        try:
            return max(1, round(float(output.strip()) * 1000))
        except ValueError as exc:
            raise TranscriptionError("视频时长格式无效。") from exc

    async def _extract_audio(self, media: Path, audio: Path) -> None:
        code, output = await self._run_command(
            settings.transcription_ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(media),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio),
        )
        if code != 0 or not audio.is_file():
            message = output.strip().splitlines()[-1] if output.strip() else ""
            raise TranscriptionError(f"无法提取视频音频。{message[:120]}")

    async def _transcribe(
        self,
        task_id: str,
        audio: Path,
        output_base: Path,
    ) -> Path:
        command = [
            str(settings.transcription_whisper_path),
            "--model",
            str(settings.transcription_model_path),
            "--file",
            str(audio),
            "--threads",
            str(settings.transcription_threads),
            "--language",
            "zh",
            "--no-gpu",
            "--vad",
            "--vad-model",
            str(settings.transcription_vad_model_path),
            "--output-srt",
            "--output-file",
            str(output_base),
            "--print-progress",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        lines: list[str] = []
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace")
            lines.append(line)
            match = PROGRESS_PATTERN.search(line)
            if match:
                whisper_progress = min(100, int(match.group(1)))
                progress = 25 + whisper_progress * 0.7
                self.update_progress(task_id, "transcribing", progress)
                self.heartbeat(
                    task_id,
                    stage="transcribing",
                    progress=round(progress, 1),
                )
        code = await process.wait()
        srt_path = output_base.with_suffix(".srt")
        if code != 0 or not srt_path.is_file():
            tail = "".join(lines[-5:]).strip()
            raise TranscriptionError(f"语音识别失败。{tail[:240]}")
        return srt_path

    def _complete(
        self,
        task_id: str,
        media: Path,
        media_bytes: int,
        duration_ms: int,
        segments: list[dict[str, Any]],
    ) -> None:
        now = utc_now()
        expires = (
            datetime.now(UTC)
            + timedelta(hours=settings.transcription_media_retention_hours)
        ).isoformat()
        digest = _sha256_file(media)
        with db_session() as db:
            exists = db.execute(
                "SELECT 1 FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not exists:
                raise TranscriptionError("任务已被删除。", status_code=404)
            db.execute("DELETE FROM segments WHERE task_id = ?", (task_id,))
            db.executemany(
                """
                INSERT INTO segments(
                    id, task_id, ordinal, start_ms, end_ms,
                    original_text, edited_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid4()),
                        task_id,
                        index,
                        segment["start_ms"],
                        segment["end_ms"],
                        segment["text"],
                        segment["text"],
                        now,
                    )
                    for index, segment in enumerate(segments)
                ],
            )
            db.execute(
                """
                UPDATE tasks
                SET status = 'ready', progress = 100, error = NULL,
                    size_bytes = ?, duration_ms = ?, sha256 = ?, updated_at = ?
                WHERE id = ?
                """,
                (media_bytes, duration_ms, digest, now, task_id),
            )
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET media_filename = ?, media_expires_at = ?,
                    claimed_at = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (_relative_media_path(task_id), expires, now, task_id),
            )

    async def process(self, job: dict[str, Any]) -> None:
        task_id = job["task_id"]
        root = _task_root(task_id)
        _remove_tree(root)
        root.mkdir(parents=True, exist_ok=True)
        media = root / "video.mp4"
        audio = root / "audio.wav"
        output_base = root / "transcript"
        succeeded = False
        try:
            _, media_bytes = await self._download(job, media)
            duration_ms = await self._duration_ms(media)
            if duration_ms > settings.transcription_max_duration_seconds * 1000:
                raise TranscriptionError("视频超过 30 分钟，暂不支持转写。")
            if media_usage_bytes() > settings.transcription_media_quota_bytes:
                raise TranscriptionError("服务器视频临时空间已满，请稍后重试。")
            self.update_progress(task_id, "transcribing", 22)
            self.heartbeat(task_id, stage="extracting_audio", progress=22)
            await self._extract_audio(media, audio)
            self.update_progress(task_id, "transcribing", 25)
            srt_path = await self._transcribe(task_id, audio, output_base)
            try:
                segments = parse_srt(srt_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, SrtError) as exc:
                raise TranscriptionError("识别结果无法转换为字幕。") from exc
            for segment in segments:
                segment["text"] = to_simplified_chinese(segment["text"])
            if not segments:
                raise TranscriptionError("视频中没有识别到可用的说话内容。")
            self._complete(task_id, media, media_bytes, duration_ms, segments)
            succeeded = True
        except (DouyinError, TranscriptionError) as exc:
            self.update_progress(task_id, "failed", 0, str(exc))
        except Exception:
            self.update_progress(task_id, "failed", 0, "转写服务发生异常，请重试。")
        finally:
            audio.unlink(missing_ok=True)
            output_base.with_suffix(".srt").unlink(missing_ok=True)
            if not succeeded:
                _remove_tree(root)
            self.heartbeat(None, stage="idle")

    async def run_forever(self) -> None:
        initialize_database()
        self.acquire_lock()
        cleanup_expired_media()
        self.recover_interrupted()
        self.heartbeat(None, stage="idle", pid=os.getpid())
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, setattr, self, "stopping", True)
        while not self.stopping:
            cleanup_expired_media()
            job = self.claim_next()
            if job:
                await self.process(job)
                continue
            self.heartbeat(None, stage="idle", pid=os.getpid())
            await asyncio.sleep(2)
        await douyin_service.close()


async def run_worker() -> None:
    if cloud_transcription_service.enabled:
        raise RuntimeError(
            "本地转写 Worker 已停用；将 SRT_TRANSCRIPTION_BACKEND 设为 local 后再启动。"
        )
    worker = TranscriptionWorker()
    await worker.run_forever()
