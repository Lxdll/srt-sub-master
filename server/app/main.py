from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db_session, initialize_database, utc_now
from .schemas import (
    AttachAssetRequest,
    CreateTaskRequest,
    CreateUserRequest,
    EditSegmentRequest,
    LoginRequest,
    PairDeviceRequest,
    TaskProgressRequest,
    TaskResultRequest,
    VerifyCommandRequest,
)
from .security import (
    admin_user,
    agent_device,
    create_session,
    current_user,
    hash_password,
    new_token,
    require_csrf,
    sign_local_command,
    token_hash,
    verify_local_command,
    verify_password,
)


def _id() -> str:
    return str(uuid4())


def _bootstrap_admin() -> None:
    with db_session() as db:
        count = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if count == 0:
            db.execute(
                """
                INSERT INTO users(id, username, password_hash, is_admin, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (
                    _id(),
                    settings.admin_username,
                    hash_password(settings.admin_password),
                    utc_now(),
                ),
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    _bootstrap_admin()
    yield


app = FastAPI(
    title="SRT Sub Master API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _task_for_user(task_id: str, user_id: str) -> sqlite3.Row:
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


def _device_for_user(device_id: str, user_id: str) -> sqlite3.Row:
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM devices WHERE id = ? AND user_id = ?",
            (device_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")
    return row


def _device_online(last_seen: str | None) -> bool:
    if not last_seen:
        return False
    return datetime.fromisoformat(last_seen) > datetime.now(UTC) - timedelta(seconds=45)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (payload.username,),
        ).fetchone()
    if not row or not verify_password(row["password_hash"], payload.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    session_token, csrf, expires = create_session(row["id"])
    response.set_cookie(
        "srt_session",
        session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        expires=datetime.fromisoformat(expires),
        path="/",
    )
    return {
        "user": {
            "id": row["id"],
            "username": row["username"],
            "is_admin": bool(row["is_admin"]),
        },
        "csrf_token": csrf,
    }


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "is_admin": bool(user["is_admin"]),
        },
        "csrf_token": user["csrf_token"],
    }


@app.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    raw = request.cookies.get("srt_session")
    if raw:
        with db_session() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(raw),))
    response.delete_cookie("srt_session", path="/")
    return {"ok": True}


@app.post("/api/admin/users")
def create_user(
    payload: CreateUserRequest,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    user_id = _id()
    try:
        with db_session() as db:
            db.execute(
                """
                INSERT INTO users(id, username, password_hash, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    payload.username,
                    hash_password(payload.password),
                    int(payload.is_admin),
                    utc_now(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    return {
        "id": user_id,
        "username": payload.username,
        "is_admin": payload.is_admin,
    }


@app.post("/api/devices/pair-code")
def create_pair_code(
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    code = "-".join(
        [
            "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4)),
            "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4)),
        ]
    )
    expires = datetime.now(UTC) + timedelta(minutes=10)
    with db_session() as db:
        db.execute("DELETE FROM pair_codes WHERE expires_at <= ?", (utc_now(),))
        db.execute(
            """
            INSERT INTO pair_codes(code_hash, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                hashlib.sha256(code.encode()).hexdigest(),
                user["id"],
                expires.isoformat(),
                utc_now(),
            ),
        )
    return {"code": code, "expires_at": expires.isoformat()}


@app.post("/api/agent/pair")
def pair_device(payload: PairDeviceRequest) -> dict[str, Any]:
    code_hash = hashlib.sha256(payload.code.upper().encode()).hexdigest()
    with db_session() as db:
        pair = db.execute(
            "SELECT * FROM pair_codes WHERE code_hash = ?",
            (code_hash,),
        ).fetchone()
        if not pair or datetime.fromisoformat(pair["expires_at"]) <= datetime.now(UTC):
            raise HTTPException(status_code=401, detail="配对码无效或已过期")
        device_id = _id()
        raw_token = new_token()
        db.execute(
            """
            INSERT INTO devices(
                id, user_id, name, platform, token_hash, origin,
                hardware_json, models_json, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                pair["user_id"],
                payload.name,
                payload.platform,
                token_hash(raw_token),
                payload.origin.rstrip("/"),
                json.dumps(payload.hardware, ensure_ascii=False),
                json.dumps(payload.models, ensure_ascii=False),
                utc_now(),
                utc_now(),
            ),
        )
        db.execute("DELETE FROM pair_codes WHERE code_hash = ?", (code_hash,))
    return {
        "device_id": device_id,
        "device_token": raw_token,
        "server_url": settings.public_url,
    }


@app.get("/api/devices")
def list_devices(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            "SELECT * FROM devices WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "platform": row["platform"],
            "online": _device_online(row["last_seen_at"]),
            "last_seen_at": row["last_seen_at"],
            "hardware": json.loads(row["hardware_json"]),
            "models": json.loads(row["models_json"]),
        }
        for row in rows
    ]


@app.post("/api/devices/{device_id}/command-token")
def create_command_token(
    device_id: str,
    request: Request,
    task_id: str | None = None,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    require_csrf(request, user)
    _device_for_user(device_id, user["id"])
    if task_id:
        _task_for_user(task_id, user["id"])
    return {"token": sign_local_command(user["id"], device_id, task_id)}


@app.post("/api/tasks")
def create_task(
    payload: CreateTaskRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    _device_for_user(payload.device_id, user["id"])
    task_id = _id()
    now = utc_now()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO tasks(
                id, user_id, device_id, original_name, size_bytes,
                model_id, status, progress, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'uploading', 0, ?, ?)
            """,
            (
                task_id,
                user["id"],
                payload.device_id,
                payload.original_name,
                payload.size_bytes,
                payload.model_id,
                now,
                now,
            ),
        )
    return {
        "id": task_id,
        "command_token": sign_local_command(user["id"], payload.device_id, task_id),
    }


def _serialize_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "original_name": row["original_name"],
        "size_bytes": row["size_bytes"],
        "duration_ms": row["duration_ms"],
        "sha256": row["sha256"],
        "model_id": row["model_id"],
        "status": row["status"],
        "progress": row["progress"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@app.get("/api/tasks")
def list_tasks(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [_serialize_task(row) for row in rows]


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    task = _task_for_user(task_id, user["id"])
    with db_session() as db:
        segments = db.execute(
            "SELECT * FROM segments WHERE task_id = ? ORDER BY ordinal",
            (task_id,),
        ).fetchall()
        assets = db.execute(
            """
            SELECT da.*, d.name AS device_name
            FROM device_assets da JOIN devices d ON d.id = da.device_id
            WHERE da.task_id = ?
            """,
            (task_id,),
        ).fetchall()
    result = _serialize_task(task)
    result["segments"] = [
        {
            "id": row["id"],
            "ordinal": row["ordinal"],
            "start_ms": row["start_ms"],
            "end_ms": row["end_ms"],
            "original_text": row["original_text"],
            "edited_text": row["edited_text"],
            "updated_at": row["updated_at"],
        }
        for row in segments
    ]
    result["device_assets"] = [
        {
            "id": row["id"],
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "local_asset_id": row["local_asset_id"],
        }
        for row in assets
    ]
    return result


@app.patch("/api/tasks/{task_id}/segments/{segment_id}")
def edit_segment(
    task_id: str,
    segment_id: str,
    payload: EditSegmentRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    _task_for_user(task_id, user["id"])
    with db_session() as db:
        cursor = db.execute(
            """
            UPDATE segments SET edited_text = ?, updated_at = ?
            WHERE id = ? AND task_id = ?
            """,
            (payload.text, utc_now(), segment_id, task_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Segment not found")
    return {"ok": True, "updated_at": utc_now()}


@app.post("/api/tasks/{task_id}/retry")
def retry_task(
    task_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    task = _task_for_user(task_id, user["id"])
    if task["status"] != "failed" or not task["device_id"]:
        raise HTTPException(status_code=409, detail="Only failed tasks can be retried")
    with db_session() as db:
        db.execute(
            """
            UPDATE tasks SET status = 'queued', progress = 0, error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), task_id),
        )
        db.execute(
            """
            INSERT INTO pending_commands(id, device_id, command, payload_json, created_at)
            VALUES (?, ?, 'retry', ?, ?)
            """,
            (_id(), task["device_id"], json.dumps({"task_id": task_id}), utc_now()),
        )
    return {"ok": True}


@app.post("/api/tasks/{task_id}/relink")
def relink_task(
    task_id: str,
    device_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    require_csrf(request, user)
    _task_for_user(task_id, user["id"])
    _device_for_user(device_id, user["id"])
    return {"command_token": sign_local_command(user["id"], device_id, task_id)}


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


@app.get("/api/tasks/{task_id}/export")
def export_task(
    task_id: str,
    format: str,
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    task = _task_for_user(task_id, user["id"])
    if format not in {"txt", "srt"}:
        raise HTTPException(status_code=400, detail="format must be txt or srt")
    with db_session() as db:
        rows = db.execute(
            "SELECT * FROM segments WHERE task_id = ? ORDER BY ordinal",
            (task_id,),
        ).fetchall()
    if format == "txt":
        content = "\n".join(row["edited_text"] for row in rows) + "\n"
    else:
        content = "\n\n".join(
            (
                f"{index}\n"
                f"{_srt_time(row['start_ms'])} --> {_srt_time(row['end_ms'])}\n"
                f"{row['edited_text']}"
            )
            for index, row in enumerate(rows, start=1)
        ) + "\n"
    stem = Path(task["original_name"]).stem[:100]
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(f'{stem}.{format}')}"
            )
        },
    )


@app.delete("/api/tasks/{task_id}")
def delete_task(
    task_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    _task_for_user(task_id, user["id"])
    with db_session() as db:
        assets = db.execute(
            "SELECT * FROM device_assets WHERE task_id = ?", (task_id,)
        ).fetchall()
        for asset in assets:
            db.execute(
                """
                INSERT INTO pending_commands(
                    id, device_id, command, payload_json, created_at
                ) VALUES (?, ?, 'delete_asset', ?, ?)
                """,
                (
                    _id(),
                    asset["device_id"],
                    json.dumps(
                        {
                            "task_id": task_id,
                            "local_asset_id": asset["local_asset_id"],
                        }
                    ),
                    utc_now(),
                ),
            )
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return {"ok": True}


@app.post("/api/agent/verify-command")
def verify_command(
    payload: VerifyCommandRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, Any]:
    data = verify_local_command(payload.token)
    if data["device_id"] != device["id"]:
        raise HTTPException(status_code=403, detail="Wrong device")
    if payload.task_id and data.get("task_id") != payload.task_id:
        raise HTTPException(status_code=403, detail="Wrong task")
    return {"ok": True, "user_id": data["user_id"], "task_id": data.get("task_id")}


def _ensure_agent_task(task_id: str, device: dict[str, Any]) -> sqlite3.Row:
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM tasks WHERE id = ? AND device_id = ? AND user_id = ?",
            (task_id, device["id"], device["user_id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not assigned to device")
    return row


@app.post("/api/agent/heartbeat")
def agent_heartbeat(
    payload: dict[str, Any],
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    with db_session() as db:
        db.execute(
            """
            UPDATE devices
            SET last_seen_at = ?, hardware_json = ?, models_json = ?
            WHERE id = ?
            """,
            (
                utc_now(),
                json.dumps(payload.get("hardware", {}), ensure_ascii=False),
                json.dumps(payload.get("models", []), ensure_ascii=False),
                device["id"],
            ),
        )
    return {"ok": True}


@app.post("/api/agent/tasks/{task_id}/progress")
def agent_task_progress(
    task_id: str,
    payload: TaskProgressRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    _ensure_agent_task(task_id, device)
    with db_session() as db:
        db.execute(
            """
            UPDATE tasks
            SET status = ?, progress = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, payload.progress, payload.error, utc_now(), task_id),
        )
    return {"ok": True}


@app.post("/api/agent/tasks/{task_id}/result")
def agent_task_result(
    task_id: str,
    payload: TaskResultRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    _ensure_agent_task(task_id, device)
    now = utc_now()
    with db_session() as db:
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
                    _id(),
                    task_id,
                    index,
                    segment.start_ms,
                    segment.end_ms,
                    segment.text,
                    segment.text,
                    now,
                )
                for index, segment in enumerate(payload.segments)
            ],
        )
        db.execute(
            """
            UPDATE tasks
            SET status = 'ready', progress = 100, error = NULL,
                sha256 = ?, duration_ms = ?, size_bytes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.sha256,
                payload.duration_ms,
                payload.size_bytes,
                now,
                task_id,
            ),
        )
        db.execute(
            """
            INSERT INTO device_assets(
                id, task_id, device_id, local_asset_id,
                sha256, duration_ms, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, device_id) DO UPDATE SET
                local_asset_id = excluded.local_asset_id,
                sha256 = excluded.sha256,
                duration_ms = excluded.duration_ms,
                size_bytes = excluded.size_bytes
            """,
            (
                _id(),
                task_id,
                device["id"],
                payload.local_asset_id,
                payload.sha256,
                payload.duration_ms,
                payload.size_bytes,
                now,
            ),
        )
    return {"ok": True}


@app.post("/api/agent/tasks/{task_id}/attach")
def agent_attach_asset(
    task_id: str,
    payload: AttachAssetRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    with db_session() as db:
        task = db.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, device["user_id"]),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task["sha256"] and task["sha256"] != payload.sha256:
            raise HTTPException(status_code=409, detail="Video hash mismatch")
        if task["size_bytes"] and task["size_bytes"] != payload.size_bytes:
            raise HTTPException(status_code=409, detail="Video size mismatch")
        if task["duration_ms"] and abs(task["duration_ms"] - payload.duration_ms) > 1000:
            raise HTTPException(status_code=409, detail="Video duration mismatch")
        db.execute(
            """
            INSERT INTO device_assets(
                id, task_id, device_id, local_asset_id,
                sha256, duration_ms, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, device_id) DO UPDATE SET
                local_asset_id = excluded.local_asset_id,
                sha256 = excluded.sha256,
                duration_ms = excluded.duration_ms,
                size_bytes = excluded.size_bytes
            """,
            (
                _id(),
                task_id,
                device["id"],
                payload.local_asset_id,
                payload.sha256,
                payload.duration_ms,
                payload.size_bytes,
                utc_now(),
            ),
        )
    return {"ok": True}


@app.websocket("/ws/agent")
async def agent_socket(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        await websocket.close(code=4401)
        return
    raw_token = authorization.split(" ", 1)[1]
    with db_session() as db:
        device = db.execute(
            "SELECT * FROM devices WHERE token_hash = ?",
            (token_hash(raw_token),),
        ).fetchone()
    if not device:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    sent_command_ids: set[str] = set()
    try:
        while True:
            message = await websocket.receive_json()
            with db_session() as db:
                db.execute(
                    "UPDATE devices SET last_seen_at = ? WHERE id = ?",
                    (utc_now(), device["id"]),
                )
                commands = db.execute(
                    """
                    SELECT * FROM pending_commands
                    WHERE device_id = ? AND delivered_at IS NULL
                    ORDER BY created_at
                    """,
                    (device["id"],),
                ).fetchall()
                for command in commands:
                    if command["id"] in sent_command_ids:
                        continue
                    await websocket.send_json(
                        {
                            "type": "command",
                            "id": command["id"],
                            "command": command["command"],
                            "payload": json.loads(command["payload_json"]),
                        }
                    )
                    sent_command_ids.add(command["id"])
                if message.get("type") == "command_ack" and message.get("id"):
                    db.execute(
                        """
                        UPDATE pending_commands SET delivered_at = ?
                        WHERE id = ? AND device_id = ?
                        """,
                        (utc_now(), message["id"], device["id"]),
                    )
            if message.get("type") == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
    except WebSocketDisconnect:
        return


settings.downloads_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/downloads",
    StaticFiles(directory=settings.downloads_dir),
    name="downloads",
)


@app.get("/{full_path:path}", include_in_schema=False)
def serve_web(full_path: str) -> FileResponse:
    index = settings.web_dist / "index.html"
    requested = (settings.web_dist / full_path).resolve()
    if (
        full_path
        and requested.is_relative_to(settings.web_dist.resolve())
        and requested.is_file()
    ):
        return FileResponse(requested)
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Web application is not built")
