from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from douyin_engine import ParseResult, Quality
from server.app.config import settings
from server.app.db import db_session, utc_now
from server.app.douyin import douyin_service
from server.app.transcription import TranscriptionWorker
from server.tests.conftest import login


VIDEO_URL = "https://www.douyin.com/video/7372484719365098803"
CDN_URL = "https://v5-se.douyinvod.com/video/test.mp4"


def result(duration_ms: int = 12_000) -> ParseResult:
    return ParseResult(
        original_url=VIDEO_URL,
        aweme_id="7372484719365098803",
        title="测试口播",
        author="测试作者",
        cover_url=None,
        duration_ms=duration_ms,
        qualities=(
            Quality(
                id="540p",
                label="540P",
                width=540,
                height=960,
                bitrate=800_000,
                estimated_bytes=2_000_000,
                source_urls=(CDN_URL,),
            ),
        ),
        provider="self_hosted",
    )


async def create_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str]:
    csrf = login(client, "admin", "admin-password-123")

    async def resolve(_user, _text):
        return result()

    monkeypatch.setattr(douyin_service, "resolve", resolve)
    response = client.post(
        "/api/douyin/transcriptions",
        headers={"X-CSRF-Token": csrf},
        json={"text": VIDEO_URL},
    )
    assert response.status_code == 202, response.text
    return response.json()["task_id"], csrf


@pytest.mark.asyncio
async def test_create_transcription_requires_both_permissions_and_validates_duration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    admin_csrf = login(client, "admin", "admin-password-123")
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "username": "transcription-limited",
            "password": "transcription-password-123",
            "permissions": ["douyin_download"],
        },
    )
    assert created.status_code == 200
    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
    limited_csrf = login(
        client, "transcription-limited", "transcription-password-123"
    )
    denied = client.post(
        "/api/douyin/transcriptions",
        headers={"X-CSRF-Token": limited_csrf},
        json={"text": VIDEO_URL},
    )
    assert denied.status_code == 403

    client.post("/api/auth/logout", headers={"X-CSRF-Token": limited_csrf})
    admin_csrf = login(client, "admin", "admin-password-123")

    async def too_long(_user, _text):
        return result(30 * 60 * 1000 + 1)

    monkeypatch.setattr(douyin_service, "resolve", too_long)
    rejected = client.post(
        "/api/douyin/transcriptions",
        headers={"X-CSRF-Token": admin_csrf},
        json={"text": VIDEO_URL},
    )
    assert rejected.status_code == 422
    assert "30 分钟" in rejected.json()["detail"]


@pytest.mark.asyncio
async def test_task_metadata_retry_media_range_and_expiry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id, csrf = await create_job(client, monkeypatch)
    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "queued"
    assert detail.json()["source_type"] == "douyin"
    assert detail.json()["queue_position"] >= 1

    media = settings.data_dir / "douyin-transcriptions" / task_id / "video.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"0123456789")
    with db_session() as db:
        db.execute(
            """
            UPDATE server_transcription_jobs
            SET media_filename = ?, media_expires_at = ?
            WHERE task_id = ?
            """,
            (
                f"douyin-transcriptions/{task_id}/video.mp4",
                (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                task_id,
            ),
        )
        db.execute(
            "UPDATE tasks SET status = 'ready', progress = 100 WHERE id = ?",
            (task_id,),
        )

    ranged = client.get(
        f"/api/tasks/{task_id}/media",
        headers={"Range": "bytes=2-5"},
    )
    assert ranged.status_code == 206
    assert ranged.content == b"2345"

    with db_session() as db:
        db.execute(
            """
            UPDATE server_transcription_jobs
            SET media_expires_at = ?
            WHERE task_id = ?
            """,
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task_id),
        )
    expired = client.get(f"/api/tasks/{task_id}/media")
    assert expired.status_code == 410
    assert not media.exists()

    with db_session() as db:
        db.execute(
            """
            UPDATE tasks
            SET status = 'failed', error = '测试失败', updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), task_id),
        )
    retried = client.post(
        f"/api/tasks/{task_id}/retry",
        headers={"X-CSRF-Token": csrf},
    )
    assert retried.status_code == 200
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "queued"

    deleted = client.delete(
        f"/api/tasks/{task_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_worker_completes_job_and_cleans_intermediate_files(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    task_id, _ = await create_job(client, monkeypatch)
    worker = TranscriptionWorker()
    job = worker.claim_next()
    assert job and job["task_id"] == task_id

    async def download(_job, destination: Path):
        destination.write_bytes(b"fake-video")
        return result(), destination.stat().st_size

    async def duration(_media: Path):
        return 12_000

    async def extract(_media: Path, audio: Path):
        audio.write_bytes(b"fake-audio")

    async def transcribe(_task_id: str, _audio: Path, output_base: Path):
        srt = output_base.with_suffix(".srt")
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\n寶寶問軟件\n\n"
            "2\n00:00:02,100 --> 00:00:04,000\n第二句\n",
            encoding="utf-8",
        )
        return srt

    monkeypatch.setattr(worker, "_download", download)
    monkeypatch.setattr(worker, "_duration_ms", duration)
    monkeypatch.setattr(worker, "_extract_audio", extract)
    monkeypatch.setattr(worker, "_transcribe", transcribe)
    await worker.process(job)

    payload = client.get(f"/api/tasks/{task_id}").json()
    assert payload["status"] == "ready"
    assert payload["media_available"] is True
    assert [item["edited_text"] for item in payload["segments"]] == [
        "宝宝问软件",
        "第二句",
    ]
    root = settings.data_dir / "douyin-transcriptions" / task_id
    assert (root / "video.mp4").is_file()
    assert not (root / "audio.wav").exists()
    assert not (root / "transcript.srt").exists()
