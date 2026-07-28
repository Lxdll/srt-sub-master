from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from douyin_engine import build_download_filename

from .config import settings
from .db import db_session, utc_now
from .douyin import douyin_service
from .security import new_token, token_hash
from .transcription import (
    ACTIVE_STATUSES,
    TranscriptionError,
    choose_transcription_quality,
)

LOCAL_MODEL_IDS = frozenset({"small", "large-v3", "large-v3-turbo"})


def installed_model_ids(device: dict[str, Any]) -> set[str]:
    try:
        models = json.loads(device["models_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return set()
    return {
        str(item.get("id"))
        for item in models
        if isinstance(item, dict) and item.get("installed") is True
    }


def recover_offline_local_jobs() -> int:
    cutoff = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    with db_session() as db:
        return db.execute(
            """
            UPDATE tasks
            SET status = 'failed', progress = 0,
                error = '本机 Agent 已离线，请启动 Agent 后手动重试。',
                updated_at = ?
            WHERE backend = 'local_agent'
              AND status IN ('queued', 'downloading', 'transcribing')
              AND id IN (SELECT task_id FROM local_douyin_jobs)
              AND device_id IN (
                  SELECT id FROM devices
                  WHERE last_seen_at IS NULL OR last_seen_at <= ?
              )
            """,
            (utc_now(), cutoff),
        ).rowcount


def ensure_model_available(device: dict[str, Any], model_id: str) -> None:
    if model_id not in LOCAL_MODEL_IDS:
        raise TranscriptionError("不支持所选本机模型。", status_code=400)
    if model_id not in installed_model_ids(device):
        raise TranscriptionError(
            "本机 Agent 尚未安装所选模型，请先下载模型后再试。",
            status_code=409,
        )


def _queue_start_command(
    db: Any,
    *,
    task_id: str,
    device_id: str,
    claim_token: str,
) -> None:
    db.execute(
        """
        INSERT INTO pending_commands(
            id, device_id, command, payload_json, created_at
        ) VALUES (?, ?, 'start_douyin_transcription', ?, ?)
        """,
        (
            str(uuid4()),
            device_id,
            json.dumps(
                {"task_id": task_id, "claim_token": claim_token},
                ensure_ascii=False,
            ),
            utc_now(),
        ),
    )


async def create_local_douyin_task(
    user: dict[str, Any],
    text: str,
    device: dict[str, Any],
    model_id: str,
) -> str:
    if not settings.transcription_enabled:
        raise TranscriptionError("抖音转文案功能尚未启用。", status_code=404)
    ensure_model_available(device, model_id)
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

    task_id = str(uuid4())
    claim_token = new_token()
    now = utc_now()
    original_name = build_download_filename(
        result.author,
        result.title,
        result.aweme_id,
        "本机转写",
    )
    with db_session() as db:
        active = db.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM local_douyin_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE t.user_id = ?
              AND t.status IN ({",".join("?" * len(ACTIVE_STATUSES))})
            """,
            (user["id"], *ACTIVE_STATUSES),
        ).fetchone()["count"]
        if active >= settings.transcription_user_queue_limit:
            raise TranscriptionError(
                "当前账号已有 3 个本机任务待处理，请完成后再提交。",
                status_code=429,
            )
        db.execute(
            """
            INSERT INTO tasks(
                id, user_id, device_id, backend, original_name, size_bytes,
                duration_ms, model_id, status, progress, created_at, updated_at
            ) VALUES (?, ?, ?, 'local_agent', ?, ?, ?, ?, 'queued', 0, ?, ?)
            """,
            (
                task_id,
                user["id"],
                device["id"],
                original_name,
                quality.estimated_bytes or 0,
                result.duration_ms,
                model_id,
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO local_douyin_jobs(
                task_id, source_url, aweme_id, expected_size_bytes,
                expected_duration_ms, claim_token_hash, attempts,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                task_id,
                result.original_url,
                result.aweme_id,
                quality.estimated_bytes or 0,
                result.duration_ms,
                token_hash(claim_token),
                now,
                now,
            ),
        )
        _queue_start_command(
            db,
            task_id=task_id,
            device_id=device["id"],
            claim_token=claim_token,
        )
    return task_id


def claim_local_douyin_task(
    task_id: str,
    device: dict[str, Any],
    raw_token: str,
) -> dict[str, Any]:
    digest = token_hash(raw_token)
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """
            SELECT j.*, t.user_id, t.device_id, t.backend, t.model_id,
                   t.original_name, t.status
            FROM local_douyin_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE j.task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if (
            not row
            or row["backend"] != "local_agent"
            or row["device_id"] != device["id"]
            or row["user_id"] != device["user_id"]
        ):
            raise TranscriptionError(
                "任务不存在或未分配给这台设备。",
                status_code=404,
            )
        first_claim = row["claim_token_hash"] == digest
        replay = row["claim_receipt_hash"] == digest
        if not first_claim and not replay:
            raise TranscriptionError("本机任务授权无效或已失效。", status_code=401)
        if row["completed_at"] or row["status"] == "ready":
            raise TranscriptionError("任务已经完成，无需再次领取。", status_code=409)
        if first_claim:
            if row["status"] != "queued":
                raise TranscriptionError("任务当前无法领取。", status_code=409)
            now = utc_now()
            db.execute(
                """
                UPDATE local_douyin_jobs
                SET claim_token_hash = NULL, claim_receipt_hash = ?,
                    attempts = attempts + 1, claimed_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (digest, now, now, task_id),
            )
            db.execute(
                """
                UPDATE tasks
                SET status = 'downloading', progress = 1, error = NULL,
                    updated_at = ?
                WHERE id = ? AND backend = 'local_agent' AND status = 'queued'
                """,
                (now, task_id),
            )
        elif row["status"] not in {"downloading", "transcribing"}:
            raise TranscriptionError("该次本机任务授权已经使用。", status_code=409)
        return {
            "task_id": task_id,
            "source_url": row["source_url"],
            "aweme_id": row["aweme_id"],
            "original_name": row["original_name"],
            "model_id": row["model_id"],
            "expected_size_bytes": row["expected_size_bytes"],
            "expected_duration_ms": row["expected_duration_ms"],
            "max_source_bytes": settings.transcription_max_source_bytes,
            "max_duration_ms": settings.transcription_max_duration_seconds * 1000,
            "replayed": replay,
        }


def retry_local_douyin_task(
    task: dict[str, Any],
    device: dict[str, Any],
) -> None:
    ensure_model_available(device, task["model_id"])
    claim_token = new_token()
    now = utc_now()
    with db_session() as db:
        job = db.execute(
            "SELECT 1 FROM local_douyin_jobs WHERE task_id = ?",
            (task["id"],),
        ).fetchone()
        if not job:
            raise TranscriptionError("本机抖音任务记录不存在。", status_code=404)
        db.execute(
            """
            UPDATE local_douyin_jobs
            SET claim_token_hash = ?, claim_receipt_hash = NULL,
                claimed_at = NULL, completed_at = NULL, updated_at = ?
            WHERE task_id = ?
            """,
            (token_hash(claim_token), now, task["id"]),
        )
        db.execute(
            """
            UPDATE tasks
            SET status = 'queued', progress = 0, error = NULL, updated_at = ?
            WHERE id = ? AND backend = 'local_agent'
            """,
            (now, task["id"]),
        )
        _queue_start_command(
            db,
            task_id=task["id"],
            device_id=device["id"],
            claim_token=claim_token,
        )


def validate_local_douyin_result(
    task_id: str,
    *,
    duration_ms: int,
    size_bytes: int,
) -> dict[str, Any] | None:
    with db_session() as db:
        row = db.execute(
            """
            SELECT j.*, t.backend, t.status
            FROM local_douyin_jobs j
            JOIN tasks t ON t.id = j.task_id
            WHERE j.task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        return None
    if row["backend"] != "local_agent" or not row["claimed_at"]:
        raise TranscriptionError("本机任务尚未被合法领取。", status_code=409)
    if duration_ms > settings.transcription_max_duration_seconds * 1000:
        raise TranscriptionError("本机上报的视频时长超过限制。", status_code=422)
    if size_bytes > settings.transcription_max_source_bytes:
        raise TranscriptionError("本机上报的视频大小超过限制。", status_code=422)
    expected_duration = row["expected_duration_ms"]
    if expected_duration:
        tolerance = max(5_000, round(expected_duration * 0.05))
        if abs(duration_ms - expected_duration) > tolerance:
            raise TranscriptionError(
                "本机下载的视频时长与任务来源不一致。",
                status_code=409,
            )
    expected_size = row["expected_size_bytes"]
    if expected_size:
        upper_bound = max(expected_size + 5 * 1024 * 1024, round(expected_size * 1.5))
        if size_bytes > upper_bound:
            raise TranscriptionError(
                "本机下载的视频大小与任务来源不一致。",
                status_code=409,
            )
    return dict(row)
