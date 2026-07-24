from __future__ import annotations

from pathlib import Path

import pytest

from agent.app.config import settings
from agent.app.db import db_session, now
from agent.app.media import MediaError, probe_video


def test_health_and_origin_protection(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    denied = client.get("/system", headers={"Origin": "https://evil.example"})
    assert denied.status_code == 403
    allowed = client.get("/system", headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 200


def test_probe_rejects_non_mp4(tmp_path: Path):
    sample = tmp_path / "audio.wav"
    sample.write_bytes(b"not audio")
    with pytest.raises(MediaError, match="MP4"):
        probe_video(sample)


def test_asset_database_preserves_local_path():
    path = settings.assets_dir / "asset-1" / "source.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"local-video-copy")
    stamp = now()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO assets(
                id, task_id, path, original_name, sha256,
                duration_ms, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "asset-1",
                "task-1",
                str(path),
                "原视频.mp4",
                "b" * 64,
                1000,
                path.stat().st_size,
                stamp,
            ),
        )
    assert path.exists()
