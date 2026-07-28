from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.app.cloud_transcription import cloud_transcription_service
from server.app.config import settings
from server.app.db import db_session, utc_now
from server.app.transcription import recover_stale_cloud_jobs
from server.tests.conftest import login


def _create_cloud_job(client: TestClient) -> tuple[str, str]:
    csrf = login(client, "admin", "admin-password-123")
    task_id = str(uuid4())
    now = utc_now()
    with db_session() as db:
        user_id = db.execute(
            "SELECT id FROM users WHERE username = 'admin'"
        ).fetchone()["id"]
        db.execute(
            """
            INSERT INTO tasks(
                id, user_id, device_id, original_name, size_bytes,
                duration_ms, model_id, status, progress, created_at, updated_at
            ) VALUES (?, ?, NULL, 'cloud.mp4', 100, 4000,
                      'whisper-small-q5_1', 'queued', 0, ?, ?)
            """,
            (task_id, user_id, now, now),
        )
        db.execute(
            """
            INSERT INTO server_transcription_jobs(
                task_id, source_url, aweme_id, attempts,
                fc_task_id, created_at, updated_at
            ) VALUES (?, 'https://www.douyin.com/video/123',
                      '123', 1, ?, ?, ?)
            """,
            (task_id, f"{task_id}-1", now, now),
        )
    return task_id, csrf


def _signed_headers(body: bytes, nonce: str, timestamp: str | None = None):
    timestamp = timestamp or str(int(time.time()))
    signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
    signature = hmac.new(
        settings.fc_callback_secret.encode(),
        signed,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-SRT-Timestamp": timestamp,
        "X-SRT-Nonce": nonce,
        "X-SRT-Signature": signature,
    }


def test_fc_callback_is_authenticated_idempotent_and_completes_task(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id, _ = _create_cloud_job(client)
    result_key = f"douyin-transcriptions/results/{task_id}/1/result.json"
    result = {
        "media_bytes": 1234,
        "duration_ms": 4000,
        "sha256": "a" * 64,
        "segments": [
            {"start_ms": 0, "end_ms": 1900, "text": "第一句"},
            {"start_ms": 2000, "end_ms": 4000, "text": "second"},
        ],
    }
    monkeypatch.setattr(
        cloud_transcription_service,
        "read_result",
        lambda key: result if key == result_key else {},
    )
    body = json.dumps(
        {
            "task_id": task_id,
            "attempt": 1,
            "event": "completed",
            "media_key": f"douyin-transcriptions/media/{task_id}/video.mp4",
            "result_key": result_key,
        },
        separators=(",", ":"),
    ).encode()
    nonce = str(uuid4())
    completed = client.post(
        "/api/internal/fc/transcription-events",
        content=body,
        headers=_signed_headers(body, nonce),
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["processed"] is True

    duplicate = client.post(
        "/api/internal/fc/transcription-events",
        content=body,
        headers=_signed_headers(body, nonce),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["processed"] is False

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "ready"
    assert [segment["edited_text"] for segment in detail["segments"]] == [
        "第一句",
        "second",
    ]
    assert detail["media_available"] is True


def test_fc_callback_rejects_expired_signature(client: TestClient):
    body = b"{}"
    response = client.post(
        "/api/internal/fc/transcription-events",
        content=body,
        headers=_signed_headers(
            body,
            str(uuid4()),
            timestamp=str(int(time.time()) - 600),
        ),
    )
    assert response.status_code == 401


def test_fc_submit_uses_async_attempt_id(monkeypatch: pytest.MonkeyPatch):
    original = {
        name: getattr(settings, name)
        for name in (
            "transcription_backend",
            "fc_endpoint",
            "fc_function_name",
            "fc_qualifier",
            "fc_callback_secret",
            "oss_region",
            "oss_endpoint",
            "oss_bucket",
        )
    }
    configured = {
        "transcription_backend": "fc",
        "fc_endpoint": "123456.cn-hangzhou.fc.aliyuncs.com",
        "fc_function_name": "transcription",
        "fc_qualifier": "LATEST",
        "fc_callback_secret": "a" * 32,
        "oss_region": "cn-hangzhou",
        "oss_endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
        "oss_bucket": "private-test-bucket",
    }
    for name, value in configured.items():
        object.__setattr__(settings, name, value)
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-secret")

    calls = []

    class FakeClient:
        def invoke_function_with_options(
            self,
            function_name,
            request,
            headers,
            _runtime,
        ):
            calls.append(
                (
                    function_name,
                    json.loads(request.body.read()),
                    headers.x_fc_invocation_type,
                    headers.x_fc_async_task_id,
                )
            )

    monkeypatch.setattr(
        cloud_transcription_service,
        "_fc_client",
        lambda: FakeClient(),
    )
    task_id = "b2e16f90-aac5-4372-9a65-c7ba22bbce10"
    try:
        fc_task_id = cloud_transcription_service.submit(
            task_id=task_id,
            attempt=3,
            source_urls=["https://v5-se.douyinvod.com/video/test.mp4"],
            extra_allowed_hosts=[],
            expected_bytes=123,
            expected_duration_ms=4000,
        )
    finally:
        for name, value in original.items():
            object.__setattr__(settings, name, value)

    assert fc_task_id == f"{task_id}-3"
    assert calls == [
        (
            "transcription",
            {
                "task_id": task_id,
                "attempt": 3,
                "source_urls": [
                    "https://v5-se.douyinvod.com/video/test.mp4"
                ],
                "extra_allowed_hosts": [],
                "expected_bytes": 123,
                "expected_duration_ms": 4000,
                "max_source_bytes": settings.transcription_max_source_bytes,
                "max_duration_seconds": settings.transcription_max_duration_seconds,
                "oss_prefix": settings.oss_prefix,
            },
            "Async",
            f"{task_id}-3",
        )
    ]


def test_fc_media_uses_short_lived_oss_redirect(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id, _ = _create_cloud_job(client)
    with db_session() as db:
        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        db.execute(
            """
            UPDATE server_transcription_jobs
            SET oss_media_key = ?, media_expires_at = ?
            WHERE task_id = ?
            """,
            (
                f"douyin-transcriptions/media/{task_id}/video.mp4",
                expires_at,
                task_id,
            ),
        )
        db.execute(
            "UPDATE tasks SET status = 'ready', progress = 100 WHERE id = ?",
            (task_id,),
        )
    monkeypatch.setattr(
        cloud_transcription_service,
        "media_url",
        lambda _key: "https://private-oss.example/video.mp4?signature=test",
    )
    response = client.get(
        f"/api/tasks/{task_id}/media",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://private-oss.example/")


def test_fc_result_cleanup_also_deletes_srt(
    monkeypatch: pytest.MonkeyPatch,
):
    deleted: list[str] = []

    class FakeBucket:
        def delete_object(self, key: str):
            deleted.append(key)

    monkeypatch.setattr(
        cloud_transcription_service,
        "_oss_bucket",
        lambda: FakeBucket(),
    )
    task_id = "b2e16f90-aac5-4372-9a65-c7ba22bbce10"
    media_key = f"douyin-transcriptions/media/{task_id}/video.mp4"
    result_key = (
        f"douyin-transcriptions/results/{task_id}/1/result.json"
    )

    cloud_transcription_service.delete_objects(media_key, result_key)

    assert deleted == [
        media_key,
        result_key,
        f"douyin-transcriptions/results/{task_id}/1/transcript.srt",
    ]


def test_stale_running_fc_job_becomes_retryable(client: TestClient):
    task_id, _ = _create_cloud_job(client)
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with db_session() as db:
        db.execute(
            """
            UPDATE tasks
            SET status = 'transcribing', progress = 50, updated_at = ?
            WHERE id = ?
            """,
            (old, task_id),
        )
    original_backend = settings.transcription_backend
    object.__setattr__(settings, "transcription_backend", "fc")
    try:
        assert recover_stale_cloud_jobs() == 1
    finally:
        object.__setattr__(settings, "transcription_backend", original_backend)
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "failed"
    assert "超时" in detail["error"]
