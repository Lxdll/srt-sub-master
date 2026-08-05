from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from server.app.db import db_session
from server.app.douyin import douyin_service
from server.app.local_agent_transcription import _compact_transcription_sources
from server.app.transcription import TranscriptionWorker
from server.tests.conftest import login
from server.tests.test_transcription import CDN_URL, VIDEO_URL, result


def _pair_device(
    client: TestClient,
    csrf: str,
    *,
    name: str = "测试 Mac",
    models: list[dict] | None = None,
) -> dict:
    code = client.post(
        "/api/devices/pair-code",
        headers={"X-CSRF-Token": csrf},
    ).json()["code"]
    response = client.post(
        "/api/agent/pair",
        json={
            "code": code,
            "name": name,
            "platform": "Darwin",
            "origin": "https://subtitles.test",
            "hardware": {"memory_gb": 16},
            "models": models
            if models is not None
            else [
                {
                    "id": "large-v3-turbo",
                    "label": "Large V3 Turbo",
                    "installed": True,
                    "recommended": True,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_local_task(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    csrf: str,
    device_id: str,
) -> str:
    async def resolve(_user, _text):
        return result()

    monkeypatch.setattr(douyin_service, "resolve", resolve)
    response = client.post(
        "/api/douyin/transcriptions",
        headers={"X-CSRF-Token": csrf},
        json={
            "text": VIDEO_URL,
            "backend": "local_agent",
            "device_id": device_id,
            "model_id": "large-v3-turbo",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def _claim_token(task_id: str) -> str:
    with db_session() as db:
        command = db.execute(
            """
            SELECT payload_json
            FROM pending_commands
            WHERE command = 'start_douyin_transcription'
              AND json_extract(payload_json, '$.task_id') = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    assert command
    return json.loads(command["payload_json"])["claim_token"]


def test_local_transcription_prefers_compact_douyin_playback_source():
    original = (
        "https://aweme.snssdk.com/aweme/v1/play/"
        "?video_id=video-1&ratio=720p&line=0"
    )
    quality = result().qualities[0].__class__(
        id="original",
        label="推荐画质",
        width=None,
        height=None,
        bitrate=None,
        estimated_bytes=None,
        source_urls=(original,),
    )
    sources = _compact_transcription_sources(quality)
    assert len(sources) == 2
    assert parse_qs(urlparse(sources[0]).query)["ratio"] == ["480p"]
    assert sources[1] == original


@pytest.mark.asyncio
async def test_local_claim_is_scoped_and_completion_is_idempotent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    csrf = login(client, "admin", "admin-password-123")
    device = _pair_device(client, csrf)
    other_device = _pair_device(client, csrf, name="另一台电脑")
    task_id = await _create_local_task(
        client,
        monkeypatch,
        csrf,
        device["device_id"],
    )
    other_task_id = await _create_local_task(
        client,
        monkeypatch,
        csrf,
        device["device_id"],
    )
    token = _claim_token(task_id)
    headers = {"Authorization": f"Bearer {device['device_token']}"}
    wrong_headers = {"Authorization": f"Bearer {other_device['device_token']}"}

    denied = client.post(
        f"/api/agent/tasks/{task_id}/claim-douyin",
        headers=wrong_headers,
        json={"token": token},
    )
    assert denied.status_code == 404
    wrong_task = client.post(
        f"/api/agent/tasks/{other_task_id}/claim-douyin",
        headers=headers,
        json={"token": token},
    )
    assert wrong_task.status_code == 401

    claimed = client.post(
        f"/api/agent/tasks/{task_id}/claim-douyin",
        headers=headers,
        json={"token": token},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["source_url"] == VIDEO_URL
    assert claimed.json()["source_urls"] == [CDN_URL]
    assert claimed.json()["authorized_source_hosts"] == []
    assert claimed.json()["model_id"] == "large-v3-turbo"
    assert claimed.json()["replayed"] is False

    progress = client.post(
        f"/api/agent/tasks/{task_id}/progress",
        headers=headers,
        json={
            "status": "downloading",
            "progress": 8,
            "downloaded_bytes": 500_000,
            "download_total_bytes": 2_000_000,
            "download_speed_bps": 250_000,
            "download_eta_seconds": 6,
        },
    )
    assert progress.status_code == 200
    progress_detail = client.get(f"/api/tasks/{task_id}").json()
    assert progress_detail["downloaded_bytes"] == 500_000
    assert progress_detail["download_total_bytes"] == 2_000_000
    assert progress_detail["download_speed_bps"] == 250_000
    assert progress_detail["download_eta_seconds"] == 6

    invalid_progress = client.post(
        f"/api/agent/tasks/{task_id}/progress",
        headers=headers,
        json={
            "status": "downloading",
            "progress": 8,
            "downloaded_bytes": 2_000_001,
            "download_total_bytes": 2_000_000,
        },
    )
    assert invalid_progress.status_code == 422

    replay = client.post(
        f"/api/agent/tasks/{task_id}/claim-douyin",
        headers=headers,
        json={"token": token},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    client.post(
        f"/api/agent/tasks/{task_id}/progress",
        headers=headers,
        json={"status": "transcribing", "progress": 50},
    )
    payload = {
        "local_asset_id": "agent-asset-1",
        "sha256": "a" * 64,
        "duration_ms": 12_000,
        "size_bytes": 123_456,
        "segments": [
            {"start_ms": 0, "end_ms": 2_000, "text": "寶寶問軟件"},
            {"start_ms": 2_100, "end_ms": 4_000, "text": "第二句"},
        ],
    }
    completed = client.post(
        f"/api/agent/tasks/{task_id}/result",
        headers=headers,
        json=payload,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["processed"] is True

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["backend"] == "local_agent"
    assert detail["status"] == "ready"
    assert detail["segments"][0]["original_text"] == "宝宝问软件"
    segment_id = detail["segments"][0]["id"]
    client.patch(
        f"/api/tasks/{task_id}/segments/{segment_id}",
        headers={"X-CSRF-Token": csrf},
        json={"text": "人工校对后的第一句"},
    )

    duplicate = client.post(
        f"/api/agent/tasks/{task_id}/result",
        headers=headers,
        json=payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["processed"] is False
    after = client.get(f"/api/tasks/{task_id}").json()
    assert after["segments"][0]["edited_text"] == "人工校对后的第一句"


@pytest.mark.asyncio
async def test_local_offline_missing_model_failure_retry_and_delete(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    csrf = login(client, "admin", "admin-password-123")
    device = _pair_device(client, csrf)
    task_id = await _create_local_task(
        client,
        monkeypatch,
        csrf,
        device["device_id"],
    )
    headers = {"Authorization": f"Bearer {device['device_token']}"}
    token = _claim_token(task_id)
    assert client.post(
        f"/api/agent/tasks/{task_id}/claim-douyin",
        headers=headers,
        json={"token": token},
    ).status_code == 200
    failed = client.post(
        f"/api/agent/tasks/{task_id}/progress",
        headers=headers,
        json={
            "status": "failed",
            "progress": 0,
            "error": "本机缺少所选模型，请先下载模型后再重试。",
        },
    )
    assert failed.status_code == 200
    queued_task_id = await _create_local_task(
        client,
        monkeypatch,
        csrf,
        device["device_id"],
    )

    with db_session() as db:
        db.execute(
            "UPDATE devices SET last_seen_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                device["device_id"],
            ),
        )
    offline_detail = client.get(f"/api/tasks/{queued_task_id}").json()
    assert offline_detail["status"] == "failed"
    assert "已离线" in offline_detail["error"]
    create_while_offline = client.post(
        "/api/douyin/transcriptions",
        headers={"X-CSRF-Token": csrf},
        json={
            "text": VIDEO_URL,
            "backend": "local_agent",
            "device_id": device["device_id"],
            "model_id": "large-v3-turbo",
        },
    )
    assert create_while_offline.status_code == 409
    assert "离线" in create_while_offline.json()["detail"]
    offline = client.post(
        f"/api/tasks/{task_id}/retry",
        headers={"X-CSRF-Token": csrf},
    )
    assert offline.status_code == 409
    assert "离线" in offline.json()["detail"]

    client.post(
        "/api/agent/heartbeat",
        headers=headers,
        json={
            "hardware": {},
            "models": [
                {
                    "id": "large-v3-turbo",
                    "installed": False,
                    "recommended": True,
                }
            ],
        },
    )
    missing = client.post(
        f"/api/tasks/{task_id}/retry",
        headers={"X-CSRF-Token": csrf},
    )
    assert missing.status_code == 409
    assert "尚未安装" in missing.json()["detail"]

    client.post(
        "/api/agent/heartbeat",
        headers=headers,
        json={
            "hardware": {},
            "models": [
                {
                    "id": "large-v3-turbo",
                    "installed": True,
                    "recommended": True,
                }
            ],
        },
    )
    with db_session() as db:
        db.execute(
            """
            UPDATE local_douyin_jobs SET source_urls_json = '[]'
            WHERE task_id = ?
            """,
            (task_id,),
        )
    retried = client.post(
        f"/api/tasks/{task_id}/retry",
        headers={"X-CSRF-Token": csrf},
    )
    assert retried.status_code == 200
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "queued"
    new_token = _claim_token(task_id)
    assert new_token != token
    refreshed = client.post(
        f"/api/agent/tasks/{task_id}/claim-douyin",
        headers=headers,
        json={"token": new_token},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["source_urls"] == [CDN_URL]

    deleted = client.delete(
        f"/api/tasks/{task_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 200
    after_delete = client.post(
        f"/api/agent/tasks/{task_id}/claim-douyin",
        headers=headers,
        json={"token": new_token},
    )
    assert after_delete.status_code == 404


@pytest.mark.asyncio
async def test_server_worker_cannot_claim_local_agent_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    csrf = login(client, "admin", "admin-password-123")
    device = _pair_device(client, csrf)
    task_id = await _create_local_task(
        client,
        monkeypatch,
        csrf,
        device["device_id"],
    )
    with db_session() as db:
        db.execute(
            """
            INSERT INTO server_transcription_jobs(
                task_id, source_url, aweme_id, attempts, created_at, updated_at
            )
            SELECT id, ?, '7372484719365098803', 0, created_at, updated_at
            FROM tasks WHERE id = ?
            """,
            (VIDEO_URL, task_id),
        )
        prior = {
            row["id"]: row["status"]
            for row in db.execute(
                """
                SELECT id, status FROM tasks
                WHERE status = 'queued' AND id != ?
                """,
                (task_id,),
            ).fetchall()
        }
        db.execute(
            "UPDATE tasks SET status = 'ready' WHERE status = 'queued' AND id != ?",
            (task_id,),
        )
    try:
        assert TranscriptionWorker().claim_next() is None
    finally:
        with db_session() as db:
            for other_id, status in prior.items():
                db.execute(
                    "UPDATE tasks SET status = ? WHERE id = ?",
                    (status, other_id),
                )
