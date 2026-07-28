from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import uuid4

from .config import settings
from .db import db_session, utc_now

TASK_ID_PATTERN = re.compile(r"^[0-9a-f-]{36}$")
CALLBACK_MAX_AGE_SECONDS = 300
CALLBACK_STATUSES = {"downloading", "transcribing"}


class CloudTranscriptionError(RuntimeError):
    pass


def _credentials() -> tuple[str, str, str | None]:
    access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    security_token = os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN", "").strip() or None
    if not access_key_id or not access_key_secret:
        raise CloudTranscriptionError("阿里云访问凭据尚未配置。")
    return access_key_id, access_key_secret, security_token


class CloudTranscriptionService:
    @property
    def enabled(self) -> bool:
        return settings.transcription_backend == "fc"

    def ensure_configured(self) -> None:
        missing = [
            label
            for label, value in (
                ("SRT_FC_ENDPOINT", settings.fc_endpoint),
                ("SRT_FC_FUNCTION_NAME", settings.fc_function_name),
                ("SRT_FC_CALLBACK_SECRET", settings.fc_callback_secret),
                ("SRT_OSS_REGION", settings.oss_region),
                ("SRT_OSS_ENDPOINT", settings.oss_endpoint),
                ("SRT_OSS_BUCKET", settings.oss_bucket),
            )
            if not value
        ]
        if missing:
            raise CloudTranscriptionError(
                f"FC 转写配置不完整：{', '.join(missing)}"
            )
        _credentials()

    def _fc_client(self):
        from alibabacloud_fc20230330.client import Client
        from alibabacloud_tea_openapi import models as open_api_models

        access_key_id, access_key_secret, security_token = _credentials()
        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            security_token=security_token,
            endpoint=settings.fc_endpoint,
        )
        return Client(config)

    def _oss_bucket(self):
        import oss2

        access_key_id, access_key_secret, security_token = _credentials()
        if security_token:
            auth = oss2.StsAuth(
                access_key_id,
                access_key_secret,
                security_token,
                auth_version="v4",
            )
        else:
            auth = oss2.AuthV4(access_key_id, access_key_secret)
        return oss2.Bucket(
            auth,
            settings.oss_endpoint,
            settings.oss_bucket,
            region=settings.oss_region,
        )

    def submit(
        self,
        *,
        task_id: str,
        attempt: int,
        source_urls: list[str],
        extra_allowed_hosts: list[str],
        expected_bytes: int,
        expected_duration_ms: int | None,
    ) -> str:
        self.ensure_configured()
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise CloudTranscriptionError("无效的转写任务 ID。")
        fc_task_id = f"{task_id}-{attempt}"
        payload = {
            "task_id": task_id,
            "attempt": attempt,
            "source_urls": source_urls,
            "extra_allowed_hosts": extra_allowed_hosts,
            "expected_bytes": expected_bytes,
            "expected_duration_ms": expected_duration_ms,
            "max_source_bytes": settings.transcription_max_source_bytes,
            "max_duration_seconds": settings.transcription_max_duration_seconds,
            "oss_prefix": settings.oss_prefix,
        }

        from alibabacloud_fc20230330 import models as fc_models
        from alibabacloud_tea_util import models as util_models

        request = fc_models.InvokeFunctionRequest(
            body=BytesIO(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            ),
            qualifier=settings.fc_qualifier,
        )
        headers = fc_models.InvokeFunctionHeaders(
            x_fc_invocation_type="Async",
            x_fc_async_task_id=fc_task_id,
        )
        self._fc_client().invoke_function_with_options(
            settings.fc_function_name,
            request,
            headers,
            util_models.RuntimeOptions(),
        )
        return fc_task_id

    def stop(self, fc_task_id: str | None) -> None:
        if not fc_task_id:
            return
        try:
            from alibabacloud_fc20230330 import models as fc_models

            self._fc_client().stop_async_task(
                settings.fc_function_name,
                fc_task_id,
                fc_models.StopAsyncTaskRequest(qualifier=settings.fc_qualifier),
            )
        except Exception:
            # Deleting the database task is the source of truth. A late callback is
            # ignored even when Function Compute cannot stop the invocation.
            return

    def media_url(self, object_key: str) -> str:
        self.ensure_configured()
        self._validate_object_key(object_key)
        return self._oss_bucket().sign_url(
            "GET",
            object_key,
            settings.oss_media_url_ttl_seconds,
            slash_safe=True,
        )

    def read_result(self, object_key: str) -> dict[str, Any]:
        self.ensure_configured()
        self._validate_object_key(object_key)
        raw = self._oss_bucket().get_object(object_key).read()
        if len(raw) > 10 * 1024 * 1024:
            raise CloudTranscriptionError("FC 转写结果文件过大。")
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudTranscriptionError("FC 转写结果不是有效 JSON。") from exc
        if not isinstance(result, dict):
            raise CloudTranscriptionError("FC 转写结果格式无效。")
        return result

    def delete_objects(self, *object_keys: str | None) -> None:
        keys: list[str] = []
        for key in object_keys:
            if not key:
                continue
            keys.append(key)
            if key.endswith("/result.json"):
                keys.append(f"{key.removesuffix('result.json')}transcript.srt")
        if not keys:
            return
        try:
            bucket = self._oss_bucket()
            for key in dict.fromkeys(keys):
                self._validate_object_key(key)
                bucket.delete_object(key)
        except Exception:
            # OSS lifecycle rules are the final cleanup safety net.
            return

    @staticmethod
    def verify_callback(
        body: bytes,
        timestamp: str | None,
        nonce: str | None,
        signature: str | None,
    ) -> None:
        if not settings.fc_callback_secret:
            raise CloudTranscriptionError("FC 回调密钥尚未配置。")
        if not timestamp or not nonce or not signature:
            raise CloudTranscriptionError("FC 回调签名不完整。")
        if len(nonce) > 100:
            raise CloudTranscriptionError("FC 回调 nonce 无效。")
        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise CloudTranscriptionError("FC 回调时间戳无效。") from exc
        now = int(datetime.now(UTC).timestamp())
        if abs(now - sent_at) > CALLBACK_MAX_AGE_SECONDS:
            raise CloudTranscriptionError("FC 回调已经过期。")
        signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
        expected = hmac.new(
            settings.fc_callback_secret.encode(),
            signed,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise CloudTranscriptionError("FC 回调签名无效。")

    @staticmethod
    def _claim_nonce(nonce: str, task_id: str) -> bool:
        cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        with db_session() as db:
            db.execute(
                "DELETE FROM fc_callback_receipts WHERE received_at < ?",
                (cutoff,),
            )
            try:
                db.execute(
                    """
                    INSERT INTO fc_callback_receipts(nonce, task_id, received_at)
                    VALUES (?, ?, ?)
                    """,
                    (nonce, task_id, utc_now()),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    @staticmethod
    def _validate_object_key(object_key: str) -> None:
        prefix = settings.oss_prefix.strip("/")
        if (
            not object_key
            or object_key.startswith("/")
            or ".." in object_key.split("/")
            or not object_key.startswith(f"{prefix}/")
        ):
            raise CloudTranscriptionError("OSS 对象路径无效。")

    def handle_callback(self, payload: dict[str, Any], nonce: str) -> bool:
        task_id = payload.get("task_id")
        attempt = payload.get("attempt")
        event = payload.get("event")
        if (
            not isinstance(task_id, str)
            or not TASK_ID_PATTERN.fullmatch(task_id)
            or not isinstance(attempt, int)
            or attempt < 1
            or event not in {"progress", "completed", "failed"}
        ):
            raise CloudTranscriptionError("FC 回调内容无效。")
        if not self._claim_nonce(nonce, task_id):
            return False
        try:
            with db_session() as db:
                job = db.execute(
                    """
                    SELECT j.*, t.status
                    FROM server_transcription_jobs j
                    JOIN tasks t ON t.id = j.task_id
                    WHERE j.task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                if not job or job["attempts"] != attempt:
                    return False
                if job["status"] == "ready":
                    return False

            if event == "progress":
                self._handle_progress(task_id, payload)
            elif event == "failed":
                self._handle_failure(task_id, payload)
            else:
                self._handle_completed(task_id, attempt, payload)
        except Exception:
            with db_session() as db:
                db.execute(
                    "DELETE FROM fc_callback_receipts WHERE nonce = ?",
                    (nonce,),
                )
            raise
        return True

    @staticmethod
    def _handle_progress(task_id: str, payload: dict[str, Any]) -> None:
        status = payload.get("status")
        progress = payload.get("progress")
        if status not in CALLBACK_STATUSES or not isinstance(progress, (int, float)):
            raise CloudTranscriptionError("FC 进度回调格式无效。")
        progress_value = max(0.0, min(99.0, float(progress)))
        with db_session() as db:
            db.execute(
                """
                UPDATE tasks
                SET status = ?, progress = ?, error = NULL, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'downloading', 'transcribing')
                """,
                (status, progress_value, utc_now(), task_id),
            )

    @staticmethod
    def _handle_failure(task_id: str, payload: dict[str, Any]) -> None:
        error = payload.get("error")
        if not isinstance(error, str) or not error.strip():
            error = "云端转写失败，请重试。"
        with db_session() as db:
            db.execute(
                """
                UPDATE tasks
                SET status = 'failed', progress = 0, error = ?, updated_at = ?
                WHERE id = ? AND status != 'ready'
                """,
                (error.strip()[:500], utc_now(), task_id),
            )
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET claimed_at = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (utc_now(), task_id),
            )

    def _handle_completed(
        self,
        task_id: str,
        attempt: int,
        payload: dict[str, Any],
    ) -> None:
        result_key = payload.get("result_key")
        media_key = payload.get("media_key")
        if not isinstance(result_key, str) or not isinstance(media_key, str):
            raise CloudTranscriptionError("FC 完成回调缺少 OSS 对象。")
        result = self.read_result(result_key)
        segments = result.get("segments")
        if not isinstance(segments, list) or not segments:
            raise CloudTranscriptionError("视频中没有识别到可用的说话内容。")

        normalized: list[tuple[int, int, str]] = []
        for item in segments:
            if not isinstance(item, dict):
                raise CloudTranscriptionError("FC 字幕段格式无效。")
            start_ms = item.get("start_ms")
            end_ms = item.get("end_ms")
            text = item.get("text")
            if (
                not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or end_ms <= start_ms
                or not isinstance(text, str)
                or not text.strip()
            ):
                raise CloudTranscriptionError("FC 字幕段格式无效。")
            normalized.append((start_ms, end_ms, text.strip()))

        media_bytes = result.get("media_bytes")
        duration_ms = result.get("duration_ms")
        sha256 = result.get("sha256")
        if (
            not isinstance(media_bytes, int)
            or media_bytes <= 0
            or not isinstance(duration_ms, int)
            or duration_ms <= 0
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise CloudTranscriptionError("FC 媒体元数据格式无效。")

        now = utc_now()
        expires = (
            datetime.now(UTC)
            + timedelta(hours=settings.transcription_media_retention_hours)
        ).isoformat()
        with db_session() as db:
            current = db.execute(
                """
                SELECT j.attempts, t.status
                FROM server_transcription_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE j.task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if not current or current["attempts"] != attempt:
                return
            if current["status"] == "ready":
                return
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
                        start_ms,
                        end_ms,
                        text,
                        text,
                        now,
                    )
                    for index, (start_ms, end_ms, text) in enumerate(normalized)
                ],
            )
            db.execute(
                """
                UPDATE tasks
                SET status = 'ready', progress = 100, error = NULL,
                    size_bytes = ?, duration_ms = ?, sha256 = ?, updated_at = ?
                WHERE id = ?
                """,
                (media_bytes, duration_ms, sha256, now, task_id),
            )
            db.execute(
                """
                UPDATE server_transcription_jobs
                SET oss_media_key = ?, oss_result_key = ?,
                    media_filename = NULL, media_expires_at = ?,
                    claimed_at = NULL, completed_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (media_key, result_key, expires, now, now, task_id),
            )


cloud_transcription_service = CloudTranscriptionService()
