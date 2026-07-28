from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .config import load_state, settings
from .db import db_session, now
from .douyin import local_douyin_service
from .media import MediaError, probe_video
from .models import model_path
from .transcriber import _progress, queue_job


def _choose_quality(result: Any) -> Any:
    def score(item: Any) -> tuple[int, int, int]:
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


def _ensure_disk_space(required_bytes: int) -> None:
    settings.assets_dir.mkdir(parents=True, exist_ok=True)
    reserve = 512 * 1024 * 1024
    if shutil.disk_usage(settings.assets_dir).free < required_bytes + reserve:
        raise RuntimeError("本机磁盘空间不足，请至少预留视频大小外加 512MB。")


def _clear_failed_attempt(task_id: str) -> None:
    with db_session() as db:
        row = db.execute(
            """
            SELECT a.path
            FROM assets a
            WHERE a.task_id = ?
            """,
            (task_id,),
        ).fetchone()
        db.execute("DELETE FROM jobs WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM assets WHERE task_id = ?", (task_id,))
    if row:
        path = Path(row["path"])
        if path.parent.is_relative_to(settings.assets_dir):
            shutil.rmtree(path.parent, ignore_errors=True)


async def _report_failure(task_id: str, message: str) -> None:
    await asyncio.to_thread(_progress, task_id, "failed", 0, message[:500])


async def start_remote_douyin_job(task_id: str, claim_token: str) -> None:
    state = load_state()
    if not state.get("server_url") or not state.get("device_token"):
        return
    directory: Path | None = None
    try:
        async with httpx.AsyncClient(
            base_url=state["server_url"],
            headers={"Authorization": f"Bearer {state['device_token']}"},
            timeout=60,
        ) as client:
            response = await client.post(
                f"/api/agent/tasks/{task_id}/claim-douyin",
                json={"token": claim_token},
            )
        if response.is_error:
            detail = response.json().get("detail", "本机任务领取失败。")
            raise RuntimeError(str(detail))
        claim = response.json()
        model_id = str(claim["model_id"])
        if not model_path(model_id):
            raise RuntimeError("本机缺少所选模型，请先下载模型后再重试。")

        await asyncio.to_thread(_progress, task_id, "downloading", 2)
        result = await local_douyin_service.engine.parse(str(claim["source_url"]))
        if result.aweme_id != claim["aweme_id"]:
            raise RuntimeError("本机解析到的视频与服务器授权任务不一致。")
        quality = _choose_quality(result)
        max_bytes = int(claim["max_source_bytes"])
        if quality.estimated_bytes and quality.estimated_bytes > max_bytes:
            raise RuntimeError("视频文件超过任务大小限制。")
        _ensure_disk_space(quality.estimated_bytes or int(claim["expected_size_bytes"]))

        _clear_failed_attempt(task_id)
        asset_id = str(uuid4())
        directory = settings.assets_dir / asset_id
        directory.mkdir(parents=True, exist_ok=False)
        destination = directory / "source.mp4"
        temporary = directory / "source.downloading"
        digest = hashlib.sha256()
        received = 0
        reported = 2
        upstream = await local_douyin_service.open_result_source(result, quality)
        total = int(upstream.headers.get("content-length") or 0)
        if total > max_bytes:
            await upstream.aclose()
            raise RuntimeError("视频文件超过任务大小限制。")
        try:
            with temporary.open("wb") as output:
                async for chunk in upstream.aiter_bytes(256 * 1024):
                    received += len(chunk)
                    if received > max_bytes:
                        raise RuntimeError("视频文件超过任务大小限制，下载已停止。")
                    digest.update(chunk)
                    output.write(chunk)
                    if total:
                        progress = round(2 + min(18, received / total * 18))
                        if progress >= reported + 2:
                            reported = progress
                            await asyncio.to_thread(
                                _progress,
                                task_id,
                                "downloading",
                                progress,
                            )
        finally:
            await upstream.aclose()
        if received <= 0:
            raise RuntimeError("本机下载的视频为空。")
        temporary.replace(destination)

        try:
            metadata = await asyncio.to_thread(probe_video, destination)
        except MediaError as exc:
            raise RuntimeError(str(exc)) from exc
        duration_ms = int(metadata["duration_ms"])
        if duration_ms > int(claim["max_duration_ms"]):
            raise RuntimeError("视频时长超过任务限制。")
        expected_duration = claim.get("expected_duration_ms")
        if expected_duration:
            tolerance = max(5_000, round(int(expected_duration) * 0.05))
            if abs(duration_ms - int(expected_duration)) > tolerance:
                raise RuntimeError("本机下载的视频时长与授权来源不一致。")

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
                    asset_id,
                    task_id,
                    str(destination),
                    str(claim["original_name"]),
                    digest.hexdigest(),
                    duration_ms,
                    received,
                    stamp,
                ),
            )
            db.execute(
                """
                INSERT INTO jobs(
                    task_id, asset_id, model_id, status, progress,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', 20, ?, ?)
                """,
                (task_id, asset_id, model_id, stamp, stamp),
            )
        await asyncio.to_thread(_progress, task_id, "transcribing", 20)
        queue_job(task_id)
        directory = None
    except Exception as exc:  # noqa: BLE001 - background boundary reports to server
        if directory:
            shutil.rmtree(directory, ignore_errors=True)
        await _report_failure(task_id, str(exc) or "本机抖音转写启动失败。")
