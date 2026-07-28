from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import websockets

from .config import load_state, save_state, settings
from .db import db_session, initialize_database, now
from .douyin import local_douyin_service
from douyin_engine import DouyinError, content_disposition
from .media import MediaError, probe_video
from .models import catalog, model_path, start_download
from .system_info import hardware_info
from .transcriber import _progress, queue_job


def _id() -> str:
    return str(uuid4())


def _origin_allowed(origin: str | None, path: str) -> bool:
    if not origin:
        return False
    normalized = origin.rstrip("/")
    if normalized in settings.development_origins:
        return True
    state = load_state()
    if path in {"/health", "/pair"} and normalized.startswith("https://"):
        return True
    return normalized == state.get("origin")


def _native_confirm(origin: str) -> bool:
    if os.getenv("SRT_AGENT_AUTO_CONFIRM", "").lower() == "true":
        return True
    message = f"是否允许网站 {origin} 连接本机识别器？"
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    (
                        f'display dialog {json.dumps(message, ensure_ascii=False)} '
                        'buttons {"拒绝", "允许"} default button "允许"'
                    ),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
            return result.returncode == 0
        if platform.system() == "Windows":
            import ctypes

            return ctypes.windll.user32.MessageBoxW(
                0, message, "不二 本机识别器", 1 | 32
            ) == 1
    except (OSError, subprocess.SubprocessError):
        return False
    return False


async def _heartbeat_loop() -> None:
    while True:
        state = load_state()
        if state.get("server_url") and state.get("device_token"):
            try:
                async with httpx.AsyncClient(
                    base_url=state["server_url"],
                    headers={"Authorization": f"Bearer {state['device_token']}"},
                    timeout=15,
                ) as client:
                    await client.post(
                        "/api/agent/heartbeat",
                        json={"hardware": hardware_info(), "models": catalog()},
                    )
            except Exception:
                pass
        await asyncio.sleep(15)


async def _handle_command(command: dict[str, Any]) -> None:
    name = command.get("command")
    payload = command.get("payload") or {}
    if name == "retry" and payload.get("task_id"):
        queue_job(payload["task_id"])
    if name == "delete_asset" and payload.get("local_asset_id"):
        delete_local_asset(payload["local_asset_id"])


async def _agent_socket_loop() -> None:
    while True:
        state = load_state()
        if not state.get("server_url") or not state.get("device_token"):
            await asyncio.sleep(5)
            continue
        websocket_url = state["server_url"].replace("https://", "wss://").replace(
            "http://", "ws://"
        ) + "/ws/agent"
        try:
            async with websockets.connect(
                websocket_url,
                additional_headers={
                    "Authorization": f"Bearer {state['device_token']}"
                },
                ping_interval=20,
            ) as socket:
                while True:
                    await socket.send(json.dumps({"type": "heartbeat"}))
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=20)
                        message = json.loads(raw)
                        if message.get("type") == "command":
                            await _handle_command(message)
                            await socket.send(
                                json.dumps(
                                    {
                                        "type": "command_ack",
                                        "id": message.get("id"),
                                    }
                                )
                            )
                    except asyncio.TimeoutError:
                        continue
                    await asyncio.sleep(10)
        except Exception:
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    settings.assets_dir.mkdir(parents=True, exist_ok=True)
    heartbeat = asyncio.create_task(_heartbeat_loop())
    socket = asyncio.create_task(_agent_socket_loop())
    try:
        yield
    finally:
        heartbeat.cancel()
        socket.cancel()
        await local_douyin_service.close()


app = FastAPI(title="不二 本机组件", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def local_security(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method == "OPTIONS":
        if not _origin_allowed(origin, request.url.path):
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        response = JSONResponse({}, status_code=204)
    else:
        if request.url.path not in {"/health"} and not _origin_allowed(
            origin, request.url.path
        ):
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        response = await call_next(request)
    if origin and _origin_allowed(origin, request.url.path):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization,Content-Type,X-Command-Token,Range"
        )
        response.headers["Access-Control-Expose-Headers"] = (
            "Content-Length,Content-Range,Content-Disposition,Accept-Ranges"
        )
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    state = load_state()
    return {
        "status": "ok",
        "paired": bool(state.get("device_token")),
        "device_id": state.get("device_id"),
        "version": "0.1.0",
        "douyin": True,
    }


@app.get("/system")
def system_status() -> dict[str, Any]:
    state = load_state()
    return {
        "hardware": hardware_info(),
        "models": catalog(),
        "device_id": state.get("device_id"),
        "server_url": state.get("server_url"),
    }


@app.post("/pair")
async def pair(request: Request) -> dict[str, Any]:
    payload = await request.json()
    server_url = str(payload.get("server_url", "")).rstrip("/")
    code = str(payload.get("code", "")).upper()
    origin = str(payload.get("origin") or request.headers.get("origin") or "").rstrip(
        "/"
    )
    if not server_url.startswith("https://") and not server_url.startswith(
        "http://localhost"
    ):
        raise HTTPException(status_code=400, detail="服务器必须使用 HTTPS")
    if origin != server_url and not origin.startswith("http://localhost"):
        raise HTTPException(status_code=400, detail="网站来源与服务器不一致")
    if not _native_confirm(origin):
        raise HTTPException(status_code=403, detail="用户拒绝了本机连接")
    async with httpx.AsyncClient(base_url=server_url, timeout=30) as client:
        response = await client.post(
            "/api/agent/pair",
            json={
                "code": code,
                "name": hardware_info()["hostname"],
                "platform": platform.system(),
                "origin": origin,
                "hardware": hardware_info(),
                "models": catalog(),
            },
        )
        if response.is_error:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json().get("detail", "配对失败"),
            )
        state = response.json()
    state["origin"] = origin
    save_state(state)
    return {"ok": True, "device_id": state["device_id"]}


async def _verify_command(
    token: str, task_id: str | None = None
) -> dict[str, Any]:
    state = load_state()
    if not state.get("server_url") or not state.get("device_token"):
        raise HTTPException(status_code=401, detail="识别器尚未配对")
    async with httpx.AsyncClient(
        base_url=state["server_url"],
        headers={"Authorization": f"Bearer {state['device_token']}"},
        timeout=20,
    ) as client:
        response = await client.post(
            "/api/agent/verify-command",
            json={"token": token, "task_id": task_id},
        )
    if response.is_error:
        raise HTTPException(status_code=401, detail="本机操作授权无效")
    return response.json()


def _douyin_http_error(exc: DouyinError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail=str(exc),
        headers={"X-Douyin-Error": exc.code},
    )


def _douyin_stream_response(stream: Any, *, attachment: bool) -> StreamingResponse:
    upstream = stream.response
    headers = {
        "Accept-Ranges": upstream.headers.get("accept-ranges", "bytes"),
        "Cache-Control": "private, no-store",
    }
    if attachment:
        headers["Content-Disposition"] = content_disposition(stream.filename)
    for source, target in (
        ("content-length", "Content-Length"),
        ("content-range", "Content-Range"),
        ("etag", "ETag"),
        ("last-modified", "Last-Modified"),
    ):
        if upstream.headers.get(source):
            headers[target] = upstream.headers[source]
    return StreamingResponse(
        stream.body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "video/mp4"),
        headers=headers,
    )


@app.post("/douyin/parse")
async def parse_douyin(request: Request) -> dict[str, Any]:
    command = await _verify_command(request.headers.get("x-command-token", ""))
    payload = await request.json()
    try:
        return await local_douyin_service.parse(
            str(command["user_id"]),
            str(payload.get("text") or ""),
        )
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc


@app.get("/douyin/download/{ticket}")
async def download_douyin(
    ticket: str,
    request: Request,
    quality: str | None = None,
) -> StreamingResponse:
    command = await _verify_command(request.headers.get("x-command-token", ""))
    try:
        stream = await local_douyin_service.open_download(
            str(command["user_id"]),
            ticket,
            quality,
            request.headers.get("range"),
        )
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc
    return _douyin_stream_response(stream, attachment=True)


@app.get("/douyin/preview/{ticket}")
async def preview_douyin(
    ticket: str,
    request: Request,
    command_token: str,
    quality: str | None = None,
) -> StreamingResponse:
    command = await _verify_command(command_token)
    try:
        stream = await local_douyin_service.open_download(
            str(command["user_id"]),
            ticket,
            quality,
            request.headers.get("range"),
        )
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc
    return _douyin_stream_response(stream, attachment=False)


@app.post("/models/{model_id}/download")
async def download_model(model_id: str, request: Request) -> dict[str, Any]:
    await _verify_command(request.headers.get("x-command-token", ""))
    try:
        return start_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知模型") from exc
    except OSError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@app.get("/models")
def models() -> list[dict[str, Any]]:
    return catalog()


async def _save_upload(upload: UploadFile, destination: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".uploading")
    try:
        with temporary.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return digest.hexdigest(), size


def _ensure_disk_space(required_bytes: int) -> None:
    settings.assets_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(settings.assets_dir).free
    reserve = 512 * 1024 * 1024
    if free < required_bytes + reserve:
        raise HTTPException(
            status_code=507,
            detail="本机磁盘空间不足，请至少预留视频大小外加 512MB。",
        )


@app.post("/jobs")
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    task_id: str = Form(...),
    model_id: str = Form(...),
) -> dict[str, Any]:
    await _verify_command(request.headers.get("x-command-token", ""), task_id)
    if not file.filename or Path(file.filename).suffix.lower() != ".mp4":
        raise HTTPException(status_code=400, detail="当前只支持 MP4")
    if not model_path(model_id):
        raise HTTPException(status_code=409, detail="请先下载所选模型")
    content_length = int(request.headers.get("content-length") or 0)
    _ensure_disk_space(content_length)
    asset_id = _id()
    directory = settings.assets_dir / asset_id
    destination = directory / "source.mp4"
    try:
        sha256, size = await _save_upload(file, destination)
        metadata = probe_video(destination)
    except MediaError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(
            status_code=507,
            detail="保存本机视频失败，请检查磁盘空间和目录权限。",
        ) from exc
    now_value = now()
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
                file.filename,
                sha256,
                metadata["duration_ms"],
                size,
                now_value,
            ),
        )
        db.execute(
            """
            INSERT INTO jobs(
                task_id, asset_id, model_id, status, progress, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 0, ?, ?)
            """,
            (task_id, asset_id, model_id, now_value, now_value),
        )
    await asyncio.to_thread(_progress, task_id, "queued", 0)
    queue_job(task_id)
    return {
        "ok": True,
        "task_id": task_id,
        "local_asset_id": asset_id,
        "duration_ms": metadata["duration_ms"],
    }


@app.get("/jobs/{task_id}")
async def job_status(task_id: str, token: str) -> dict[str, Any]:
    await _verify_command(token, task_id)
    with db_session() as db:
        row = db.execute("SELECT * FROM jobs WHERE task_id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dict(row)


@app.get("/jobs/{task_id}/events")
async def job_events(task_id: str, token: str) -> StreamingResponse:
    await _verify_command(token, task_id)

    async def event_stream() -> AsyncIterator[bytes]:
        last_payload = ""
        while True:
            with db_session() as db:
                row = db.execute(
                    "SELECT * FROM jobs WHERE task_id = ?", (task_id,)
                ).fetchone()
            payload = (
                json.dumps(dict(row), ensure_ascii=False)
                if row
                else json.dumps({"task_id": task_id, "status": "missing"})
            )
            if payload != last_payload:
                yield f"data: {payload}\n\n".encode("utf-8")
                last_payload = payload
            if not row or row["status"] in {"ready", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _asset_row(asset_id: str):
    with db_session() as db:
        row = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="本机视频不存在")
    return row


@app.get("/assets/{asset_id}")
async def stream_asset(
    asset_id: str,
    request: Request,
    token: str,
    task_id: str,
) -> StreamingResponse:
    await _verify_command(token, task_id)
    row = _asset_row(asset_id)
    if row["task_id"] != task_id:
        raise HTTPException(status_code=403, detail="视频与任务不匹配")
    path = Path(row["path"])
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    status_code = 200
    headers = {"Accept-Ranges": "bytes"}
    if range_header and range_header.startswith("bytes="):
        value = range_header.removeprefix("bytes=").split(",", 1)[0]
        start_text, end_text = value.split("-", 1)
        start = int(start_text) if start_text else 0
        end = int(end_text) if end_text else file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            raise HTTPException(status_code=416, detail="Invalid range")
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    length = end - start + 1
    headers["Content-Length"] = str(length)

    def iterator():
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iterator(),
        status_code=status_code,
        media_type=mimetypes.guess_type(path.name)[0] or "video/mp4",
        headers=headers,
    )


def delete_local_asset(asset_id: str) -> None:
    with db_session() as db:
        row = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            return
        path = Path(row["path"])
        db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    directory = path.parent
    if directory.is_relative_to(settings.assets_dir):
        shutil.rmtree(directory, ignore_errors=True)


@app.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, request: Request) -> dict[str, bool]:
    await _verify_command(request.headers.get("x-command-token", ""))
    delete_local_asset(asset_id)
    return {"ok": True}


@app.post("/assets/relink")
async def relink_asset(
    request: Request,
    file: UploadFile = File(...),
    task_id: str = Form(...),
) -> dict[str, Any]:
    await _verify_command(request.headers.get("x-command-token", ""), task_id)
    content_length = int(request.headers.get("content-length") or 0)
    _ensure_disk_space(content_length)
    asset_id = _id()
    directory = settings.assets_dir / asset_id
    destination = directory / "source.mp4"
    try:
        sha256, size = await _save_upload(file, destination)
        metadata = probe_video(destination)
        state = load_state()
        async with httpx.AsyncClient(
            base_url=state["server_url"],
            headers={"Authorization": f"Bearer {state['device_token']}"},
            timeout=60,
        ) as client:
            response = await client.post(
                f"/api/agent/tasks/{task_id}/attach",
                json={
                    "local_asset_id": asset_id,
                    "sha256": sha256,
                    "duration_ms": metadata["duration_ms"],
                    "size_bytes": size,
                },
            )
        if response.is_error:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json().get("detail", "视频校验失败"),
            )
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
                    file.filename or "source.mp4",
                    sha256,
                    metadata["duration_ms"],
                    size,
                    now(),
                ),
            )
        return {"ok": True, "local_asset_id": asset_id}
    except OSError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(
            status_code=507,
            detail="保存本机视频失败，请检查磁盘空间和目录权限。",
        ) from exc
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def run() -> None:
    import uvicorn

    uvicorn.run(
        "agent.app.main:app",
        host="127.0.0.1",
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
