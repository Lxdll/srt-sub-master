from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from douyin_engine import ParseResult, Quality, build_download_filename
from douyin_engine.core import is_media_url_allowed

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


def _source_allowed(source: str) -> bool:
    return is_media_url_allowed(
        source,
        {douyin_service.bhwa.allowed_host},
    )


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


def _compact_transcription_sources(quality: Quality) -> list[str]:
    sources: list[str] = []
    for source in quality.source_urls:
        parsed = urlparse(source)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if (
            parsed.scheme == "https"
            and parsed.hostname == "aweme.snssdk.com"
            and parsed.path == "/aweme/v1/play/"
            and query.get("video_id")
        ):
            query["ratio"] = "480p"
            sources.append(urlunparse(parsed._replace(query=urlencode(query))))
        sources.append(source)
    return list(dict.fromkeys(sources))


def _authorized_quality(result: ParseResult) -> tuple[Quality, list[str]]:
    if (
        result.duration_ms
        and result.duration_ms > settings.transcription_max_duration_seconds * 1000
    ):
        raise TranscriptionError("视频超过 30 分钟，暂不支持转写。")
    quality = choose_transcription_quality(result)
    source_urls = _compact_transcription_sources(quality)
    if not source_urls or any(
        not _source_allowed(source) for source in source_urls
    ):
        raise TranscriptionError(
            "解析服务没有返回可供本机安全下载的视频来源，请稍后重试。",
            status_code=503,
        )
    if (
        quality.estimated_bytes
        and quality.estimated_bytes > settings.transcription_max_source_bytes
    ):
        raise TranscriptionError("视频文件超过 500MB，暂不支持转写。")
    return quality, source_urls


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
    quality, source_urls = _authorized_quality(result)

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
                task_id, source_url, source_urls_json, aweme_id, expected_size_bytes,
                expected_duration_ms, claim_token_hash, attempts,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                task_id,
                result.original_url,
                json.dumps(source_urls, ensure_ascii=False),
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
        try:
            source_urls = json.loads(row["source_urls_json"])
        except (TypeError, json.JSONDecodeError):
            source_urls = []
        if not isinstance(source_urls, list) or any(
            not isinstance(source, str) or not _source_allowed(source)
            for source in source_urls
        ):
            raise TranscriptionError(
                "本机任务的视频来源授权无效，请重新创建任务。",
                status_code=409,
            )
        return {
            "task_id": task_id,
            "source_url": row["source_url"],
            "source_urls": source_urls,
            "authorized_source_hosts": sorted(
                {
                    urlparse(source).hostname
                    for source in source_urls
                    if urlparse(source).hostname
                    == douyin_service.bhwa.allowed_host
                }
            ),
            "aweme_id": row["aweme_id"],
            "original_name": row["original_name"],
            "model_id": row["model_id"],
            "expected_size_bytes": row["expected_size_bytes"],
            "expected_duration_ms": row["expected_duration_ms"],
            "max_source_bytes": settings.transcription_max_source_bytes,
            "max_duration_ms": settings.transcription_max_duration_seconds * 1000,
            "replayed": replay,
        }


async def retry_local_douyin_task(
    task: dict[str, Any],
    device: dict[str, Any],
    user: dict[str, Any],
) -> None:
    ensure_model_available(device, task["model_id"])
    with db_session() as db:
        job = db.execute(
            """
            SELECT source_url, aweme_id
            FROM local_douyin_jobs WHERE task_id = ?
            """,
            (task["id"],),
        ).fetchone()
        if not job:
            raise TranscriptionError("本机抖音任务记录不存在。", status_code=404)
    douyin_service.engine.invalidate(job["aweme_id"])
    result = await douyin_service.resolve(user, job["source_url"])
    if result.aweme_id != job["aweme_id"]:
        raise TranscriptionError(
            "重新解析到的作品与原任务不一致，请重新创建任务。",
            status_code=409,
        )
    quality, source_urls = _authorized_quality(result)
    claim_token = new_token()
    now = utc_now()
    with db_session() as db:
        db.execute(
            """
            UPDATE local_douyin_jobs
            SET claim_token_hash = ?, claim_receipt_hash = NULL,
                source_urls_json = ?, expected_size_bytes = ?,
                expected_duration_ms = ?, claimed_at = NULL,
                completed_at = NULL, downloaded_bytes = 0,
                download_total_bytes = 0, download_speed_bps = 0,
                download_eta_seconds = NULL, updated_at = ?
            WHERE task_id = ?
            """,
            (
                token_hash(claim_token),
                json.dumps(source_urls, ensure_ascii=False),
                quality.estimated_bytes or 0,
                result.duration_ms,
                now,
                task["id"],
            ),
        )
        db.execute(
            """
            UPDATE tasks
            SET status = 'queued', progress = 0, error = NULL,
                size_bytes = ?, duration_ms = ?, updated_at = ?
            WHERE id = ? AND backend = 'local_agent'
            """,
            (
                quality.estimated_bytes or 0,
                result.duration_ms,
                now,
                task["id"],
            ),
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
