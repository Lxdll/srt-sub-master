from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from .chinese import to_simplified_chinese
from .cloud_transcription import (
    CloudTranscriptionError,
    cloud_transcription_service,
)
from .analytics import (
    action_spec_for_request,
    analytics_service,
    set_action_metadata,
)
from .config import settings
from .db import db_session, initialize_database, utc_now
from .douyin import douyin_service
from douyin_engine import DouyinError, content_disposition
from .hot_ranks import hot_rank_service
from .prohibited_words import ProhibitedWordsError, prohibited_word_service
from .schemas import (
    ActionEventListResponse,
    ActionOverviewResponse,
    AdminResetPasswordRequest,
    AnalyticsOverviewResponse,
    AttachAssetRequest,
    ChangePasswordRequest,
    ClaimLocalDouyinTaskRequest,
    CreateTaskRequest,
    CreateUserRequest,
    CustomProhibitedWordRequest,
    CustomProhibitedWordResponse,
    DouyinParseRequest,
    DouyinParseResponse,
    DouyinTranscriptionRequest,
    DouyinTranscriptionResponse,
    EditSegmentRequest,
    HotRanksResponse,
    IpUserListResponse,
    LoginRequest,
    PageViewRequest,
    PairDeviceRequest,
    ProhibitedWordsCheckRequest,
    ProhibitedWordsCheckResponse,
    ScriptAnalysisRequest,
    ScriptAnalysisResponse,
    ScriptFissionGenerateRequest,
    ScriptFissionGenerateResponse,
    ScriptFissionPlanRequest,
    ScriptFissionPlanResponse,
    TaskProgressRequest,
    TaskResultRequest,
    UpdateUserPermissionsRequest,
    VisitListResponse,
    VerifyCommandRequest,
)
from .local_agent_transcription import (
    claim_local_douyin_task,
    create_local_douyin_task,
    recover_offline_local_jobs,
    retry_local_douyin_task,
    validate_local_douyin_result,
)
from .script_analysis import ScriptAnalysisError, script_analysis_service
from .script_fission import ScriptFissionError, script_fission_service
from .script_library import router as script_library_router, script_source_or_404
from .security import (
    FEATURE_PERMISSIONS,
    admin_user,
    agent_device,
    create_session,
    current_user,
    ensure_any_feature,
    ensure_permission,
    ensure_user_id_permission,
    hash_password,
    new_token,
    require_csrf,
    sign_local_command,
    token_hash,
    verify_local_command,
    verify_password,
)
from .srt import SrtError, parse_srt
from .transcription import (
    TranscriptionError,
    cleanup_expired_media,
    create_transcription_task,
    delete_job_media,
    media_record,
    recover_stale_cloud_jobs,
    resolve_media_path,
    retry_server_job,
    task_transcription_metadata,
    transcription_status,
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
    analytics_service.start()
    hot_rank_service.start()
    try:
        yield
    finally:
        await analytics_service.close()
        await hot_rank_service.close()
        await douyin_service.close()


app = FastAPI(
    title="不二 API",
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
app.include_router(script_library_router)


@app.middleware("http")
async def record_key_action(request: Request, call_next: Any) -> Response:
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        spec = action_spec_for_request(request)
        if spec and not getattr(request.state, "analytics_skip_action", False):
            user = getattr(request.state, "analytics_user", None)
            metadata = {
                **getattr(request.state, "analytics_metadata", {}),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "error_type": "internal_error",
            }
            analytics_service.record_action(
                request,
                action_key=spec.key,
                outcome="failure",
                http_status=500,
                user_id=user["id"] if user else None,
                resource_type=spec.resource_type,
                resource_id=(
                    getattr(request.state, "analytics_resource_id", None)
                    or (
                        request.path_params.get(spec.resource_param)
                        if spec.resource_param
                        else None
                    )
                ),
                metadata=metadata,
                link_user=not getattr(
                    request.state, "analytics_skip_ip_user_link", False
                ),
            )
        raise
    spec = action_spec_for_request(request)
    if spec and not getattr(request.state, "analytics_skip_action", False):
        user = getattr(request.state, "analytics_user", None)
        metadata = {
            **getattr(request.state, "analytics_metadata", {}),
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
        if response.status_code >= 400:
            metadata["error_type"] = f"http_{response.status_code}"
        analytics_service.record_action(
            request,
            action_key=spec.key,
            outcome="success" if response.status_code < 400 else "failure",
            http_status=response.status_code,
            user_id=user["id"] if user else None,
            resource_type=spec.resource_type,
            resource_id=(
                getattr(request.state, "analytics_resource_id", None)
                or (
                    request.path_params.get(spec.resource_param)
                    if spec.resource_param
                    else None
                )
            ),
            metadata=metadata,
            link_user=not getattr(
                request.state, "analytics_skip_ip_user_link", False
            ),
        )
    return response


@app.post("/api/internal/fc/transcription-events", include_in_schema=False)
async def receive_fc_transcription_event(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Callback body is too large")
    timestamp = request.headers.get("x-srt-timestamp")
    nonce = request.headers.get("x-srt-nonce")
    signature = request.headers.get("x-srt-signature")
    try:
        cloud_transcription_service.verify_callback(
            body,
            timestamp,
            nonce,
            signature,
        )
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise CloudTranscriptionError("FC 回调内容无效。")
        processed = cloud_transcription_service.handle_callback(
            payload,
            nonce or "",
        )
    except (CloudTranscriptionError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"ok": True, "processed": processed}


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


def _permissions_for_user(user_id: str, is_admin: bool) -> list[str]:
    if is_admin:
        return sorted(FEATURE_PERMISSIONS)
    with db_session() as db:
        rows = db.execute(
            """
            SELECT permission_key FROM user_permissions
            WHERE user_id = ?
            ORDER BY permission_key
            """,
            (user_id,),
        ).fetchall()
    return [row["permission_key"] for row in rows]


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    is_admin = bool(row["is_admin"])
    result = {
        "id": row["id"],
        "username": row["username"],
        "is_admin": is_admin,
        "permissions": _permissions_for_user(row["id"], is_admin),
    }
    if "created_at" in row.keys():
        result["created_at"] = row["created_at"]
    return result


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analytics/page-view", status_code=202)
def record_page_view(
    payload: PageViewRequest,
    request: Request,
) -> dict[str, str]:
    request_host = (request.url.hostname or "").lower()
    local_development_hosts = {
        (urlparse(origin).hostname or "").lower()
        for origin in settings.allowed_origins
    }
    host_is_allowed = request_host == analytics_service.public_host or (
        not settings.cookie_secure
        and request_host in local_development_hosts
        and not request_host.startswith("admin.")
    )
    if not host_is_allowed:
        raise HTTPException(status_code=403, detail="仅允许主站记录访问")
    if "?" in payload.path or "#" in payload.path or payload.path.startswith("//"):
        raise HTTPException(status_code=422, detail="页面路径无效")
    origin = request.headers.get("origin")
    if origin and (urlparse(origin).hostname or "").lower() != request_host:
        raise HTTPException(status_code=403, detail="仅允许同源记录访问")
    user = analytics_service.optional_user(request)
    if user:
        request.state.analytics_user = user
    result = analytics_service.record_page_view(
        request,
        event_id=str(payload.event_id),
        path=payload.path,
        user_id=user["id"] if user else None,
    )
    if result == "rate_limited":
        raise HTTPException(status_code=429, detail="访问上报过于频繁")
    return {"status": result}


@app.get(
    "/api/admin/analytics/overview",
    response_model=AnalyticsOverviewResponse,
)
def analytics_overview(
    days: int = Query(default=30),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    try:
        return analytics_service.overview(days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/admin/analytics/visits",
    response_model=VisitListResponse,
)
def analytics_visits(
    days: int = Query(default=30),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    try:
        return analytics_service.visits(days, limit, cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/admin/analytics/ip-users",
    response_model=IpUserListResponse,
)
def analytics_ip_users(
    days: int = Query(default=30),
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    try:
        return analytics_service.ip_users(days, limit, cursor, query.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/admin/analytics/actions/overview",
    response_model=ActionOverviewResponse,
)
def analytics_actions_overview(
    days: int = Query(default=30),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    try:
        return analytics_service.actions_overview(days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/admin/analytics/actions",
    response_model=ActionEventListResponse,
)
def analytics_actions(
    days: int = Query(default=30),
    user_id: str | None = Query(default=None, max_length=80),
    action: str | None = Query(default=None, max_length=100),
    outcome: str | None = Query(default=None, pattern="^(success|failure)$"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    try:
        return analytics_service.actions(
            days, limit, cursor, user_id, action, outcome
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/hot-ranks", response_model=HotRanksResponse)
async def hot_ranks(
    response: Response,
    refresh: bool = False,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    result = await hot_rank_service.get_hot_ranks(refresh=refresh)
    if all(
        platform["status"] == "unavailable"
        for platform in result["platforms"]
    ):
        response.status_code = 503
    return result


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


@app.post("/api/douyin/parse", response_model=DouyinParseResponse)
async def parse_douyin(
    payload: DouyinParseRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_action_metadata(request, input_characters=len(payload.text))
    require_csrf(request, user)
    ensure_permission(user, "douyin_download")
    try:
        return await douyin_service.parse(user, payload.text)
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc


@app.post(
    "/api/douyin/transcriptions",
    response_model=DouyinTranscriptionResponse,
    status_code=202,
)
async def create_douyin_transcription(
    payload: DouyinTranscriptionRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    set_action_metadata(
        request,
        backend=payload.backend,
        model_id=payload.model_id,
        input_characters=len(payload.text),
    )
    require_csrf(request, user)
    ensure_permission(user, "douyin_download")
    ensure_permission(user, "subtitle_workspace")
    try:
        if payload.backend == "local_agent":
            if not payload.device_id or not payload.model_id:
                raise TranscriptionError(
                    "请选择已配对的本机 Agent 和本机模型。",
                    status_code=400,
                )
            device = _device_for_user(payload.device_id, user["id"])
            if not _device_online(device["last_seen_at"]):
                raise TranscriptionError(
                    "本机 Agent 当前离线，请启动 Agent 并等待连接后再试。",
                    status_code=409,
                )
            task_id = await create_local_douyin_task(
                user,
                payload.text,
                dict(device),
                payload.model_id,
            )
        else:
            task_id = await create_transcription_task(user, payload.text)
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc
    except TranscriptionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    request.state.analytics_resource_id = task_id
    return {"task_id": task_id}


@app.get("/api/douyin/download/{ticket}")
async def download_douyin(
    ticket: str,
    request: Request,
    quality: str | None = None,
    user: dict[str, Any] = Depends(current_user),
) -> StreamingResponse:
    set_action_metadata(request, quality=quality)
    ensure_permission(user, "douyin_download")
    try:
        stream = await douyin_service.open_download(
            user,
            ticket,
            quality,
            request.headers.get("range"),
        )
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc
    return _douyin_stream_response(stream, attachment=True)


@app.get("/api/douyin/preview/{ticket}")
async def preview_douyin(
    ticket: str,
    request: Request,
    quality: str | None = None,
    user: dict[str, Any] = Depends(current_user),
) -> StreamingResponse:
    ensure_permission(user, "douyin_download")
    try:
        stream = await douyin_service.open_download(
            user,
            ticket,
            quality,
            request.headers.get("range"),
        )
    except DouyinError as exc:
        raise _douyin_http_error(exc) from exc
    return _douyin_stream_response(stream, attachment=False)


@app.get("/api/admin/douyin/status")
def douyin_status(
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    douyin_service.ensure_access(user)
    return {
        **douyin_service.status(),
        "transcription": transcription_status(),
    }


@app.get(
    "/api/prohibited-words/custom",
    response_model=list[CustomProhibitedWordResponse],
)
def list_custom_prohibited_words(
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> list[dict[str, Any]]:
    require_csrf(request, user)
    ensure_permission(user, "prohibited_word_check")
    with db_session() as db:
        rows = db.execute(
            """
            SELECT id, term, created_at
            FROM user_prohibited_words
            WHERE user_id = ?
            ORDER BY created_at, term COLLATE NOCASE
            """,
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post(
    "/api/prohibited-words/custom",
    response_model=CustomProhibitedWordResponse,
    status_code=201,
)
def add_custom_prohibited_word(
    payload: CustomProhibitedWordRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_action_metadata(request, term_length=len(payload.term.strip()))
    require_csrf(request, user)
    ensure_permission(user, "prohibited_word_check")
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=422, detail="违禁词不能为空")
    word = {
        "id": _id(),
        "term": term,
        "created_at": utc_now(),
    }
    try:
        with db_session() as db:
            db.execute(
                """
                INSERT INTO user_prohibited_words(
                    id, user_id, term, normalized_term, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    word["id"],
                    user["id"],
                    word["term"],
                    word["term"].casefold(),
                    word["created_at"],
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="该违禁词已存在") from exc
    request.state.analytics_resource_id = word["id"]
    return word


@app.delete("/api/prohibited-words/custom/{word_id}")
def delete_custom_prohibited_word(
    word_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    ensure_permission(user, "prohibited_word_check")
    with db_session() as db:
        cursor = db.execute(
            """
            DELETE FROM user_prohibited_words
            WHERE id = ? AND user_id = ?
            """,
            (word_id, user["id"]),
        )
        deleted = cursor.rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="违禁词不存在")
    return {"ok": True}


@app.post(
    "/api/prohibited-words/check",
    response_model=ProhibitedWordsCheckResponse,
)
async def check_prohibited_words(
    payload: ProhibitedWordsCheckRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_action_metadata(request, input_characters=len(payload.text))
    require_csrf(request, user)
    ensure_permission(user, "prohibited_word_check")
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="待检测文字不能为空")
    with db_session() as db:
        custom_terms = [
            row["term"]
            for row in db.execute(
                """
                SELECT term
                FROM user_prohibited_words
                WHERE user_id = ?
                ORDER BY created_at
                """,
                (user["id"],),
            ).fetchall()
        ]
    try:
        return await prohibited_word_service.check(payload.text, custom_terms)
    except ProhibitedWordsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    "/api/script-analysis/analyze",
    response_model=ScriptAnalysisResponse,
)
async def analyze_script(
    payload: ScriptAnalysisRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_action_metadata(
        request,
        input_characters=len(payload.text),
        platform=payload.platform,
        target_duration_seconds=payload.target_duration_seconds,
    )
    require_csrf(request, user)
    ensure_permission(user, "script_analysis")
    script = payload.text.strip()
    if not script:
        raise HTTPException(status_code=422, detail="视频脚本不能为空")
    context = {
        key: value
        for key, value in {
            "platform": payload.platform.strip() if payload.platform else None,
            "audience": payload.audience.strip() if payload.audience else None,
            "target_duration_seconds": payload.target_duration_seconds,
            "goal": payload.goal.strip() if payload.goal else None,
        }.items()
        if value not in (None, "")
    }
    try:
        return await script_analysis_service.analyze(script, context)
    except ScriptAnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/script-analysis/analyze/stream")
async def stream_script_analysis(
    payload: ScriptAnalysisRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> StreamingResponse:
    request.state.analytics_skip_action = True
    analysis_started = time.perf_counter()
    set_action_metadata(
        request,
        input_characters=len(payload.text),
        platform=payload.platform,
        target_duration_seconds=payload.target_duration_seconds,
    )
    require_csrf(request, user)
    ensure_permission(user, "script_analysis")
    script = payload.text.strip()
    if not script:
        raise HTTPException(status_code=422, detail="视频脚本不能为空")
    context = {
        key: value
        for key, value in {
            "platform": payload.platform.strip() if payload.platform else None,
            "audience": payload.audience.strip() if payload.audience else None,
            "target_duration_seconds": payload.target_duration_seconds,
            "goal": payload.goal.strip() if payload.goal else None,
        }.items()
        if value not in (None, "")
    }

    async def events() -> Any:
        try:
            async for event, data in script_analysis_service.analyze_stream(
                script, context
            ):
                encoded = json.dumps(
                    data,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: {event}\ndata: {encoded}\n\n"
        except ScriptAnalysisError as exc:
            analytics_service.record_action(
                request,
                action_key="script_analysis.run",
                outcome="failure",
                http_status=exc.status_code,
                user_id=user["id"],
                metadata={
                    **getattr(request.state, "analytics_metadata", {}),
                    "duration_ms": round(
                        (time.perf_counter() - analysis_started) * 1000
                    ),
                    "error_type": f"http_{exc.status_code}",
                    "stream": True,
                },
            )
            encoded = json.dumps(
                {"status_code": exc.status_code, "detail": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: error\ndata: {encoded}\n\n"
        except BaseException:
            analytics_service.record_action(
                request,
                action_key="script_analysis.run",
                outcome="failure",
                http_status=499,
                user_id=user["id"],
                metadata={
                    **getattr(request.state, "analytics_metadata", {}),
                    "duration_ms": round(
                        (time.perf_counter() - analysis_started) * 1000
                    ),
                    "error_type": "stream_interrupted",
                    "stream": True,
                },
            )
            raise
        else:
            analytics_service.record_action(
                request,
                action_key="script_analysis.run",
                outcome="success",
                http_status=200,
                user_id=user["id"],
                metadata={
                    **getattr(request.state, "analytics_metadata", {}),
                    "duration_ms": round(
                        (time.perf_counter() - analysis_started) * 1000
                    ),
                    "stream": True,
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _script_fission_source(
    payload: ScriptFissionPlanRequest | ScriptFissionGenerateRequest,
    user: dict[str, Any],
) -> tuple[str, str]:
    if payload.source_script_id is not None:
        ensure_permission(user, "script_library")
        _, body = script_source_or_404(payload.source_script_id)
        return body.strip(), "library"
    script = (payload.text or "").strip()
    if not script:
        raise HTTPException(status_code=422, detail="来源脚本不能为空")
    return script, "text"


@app.post(
    "/api/script-fission/plan",
    response_model=ScriptFissionPlanResponse,
)
async def plan_script_fission(
    payload: ScriptFissionPlanRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    ensure_permission(user, "script_fission")
    script, source_type = _script_fission_source(payload, user)
    requirements = payload.requirements.strip() if payload.requirements else ""
    set_action_metadata(
        request,
        source_type=source_type,
        input_characters=len(script),
        requirement_characters=len(requirements),
    )
    try:
        return await script_fission_service.plan(script, requirements)
    except ScriptFissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post(
    "/api/script-fission/generate",
    response_model=ScriptFissionGenerateResponse,
)
async def generate_script_fission(
    payload: ScriptFissionGenerateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    require_csrf(request, user)
    ensure_permission(user, "script_fission")
    script, source_type = _script_fission_source(payload, user)
    requirements = payload.requirements.strip() if payload.requirements else ""
    directions = [item.model_dump() for item in payload.directions]
    set_action_metadata(
        request,
        source_type=source_type,
        input_characters=len(script),
        requirement_characters=len(requirements),
        direction_id=payload.direction_id,
    )
    try:
        return await script_fission_service.generate(
            script,
            requirements,
            directions,
            payload.direction_id,
        )
    except ScriptFissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (payload.username,),
        ).fetchone()
    if not row or not verify_password(row["password_hash"], payload.password):
        analytics_service.record_action(
            request,
            action_key="auth.login",
            outcome="failure",
            http_status=401,
            metadata={
                "attempted_username": payload.username[:80],
                "error_type": "invalid_credentials",
            },
        )
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
    request.state.analytics_user = dict(row)
    analytics_service.record_action(
        request,
        action_key="auth.login",
        outcome="success",
        http_status=200,
        user_id=row["id"],
        resource_type="user",
        resource_id=row["id"],
        login_success=True,
    )
    return {
        "user": _public_user(row),
        "csrf_token": csrf,
    }


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {
        "user": _public_user(user),
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
    set_action_metadata(
        request,
        is_admin=payload.is_admin,
        permission_count=len(set(payload.permissions)),
    )
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
            if not payload.is_admin:
                db.executemany(
                    """
                    INSERT INTO user_permissions(user_id, permission_key, created_at)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (user_id, permission_key, utc_now())
                        for permission_key in sorted(set(payload.permissions))
                    ],
                )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    request.state.analytics_resource_id = user_id
    return {
        "id": user_id,
        "username": payload.username,
        "is_admin": payload.is_admin,
        "permissions": (
            sorted(FEATURE_PERMISSIONS)
            if payload.is_admin
            else sorted(set(payload.permissions))
        ),
    }


@app.get("/api/admin/users")
def list_users(
    user: dict[str, Any] = Depends(admin_user),
) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            """
            SELECT id, username, is_admin, created_at
            FROM users
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [_public_user(row) for row in rows]


@app.patch("/api/admin/users/{user_id}/permissions")
def update_user_permissions(
    user_id: str,
    payload: UpdateUserPermissionsRequest,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    set_action_metadata(request, permission_count=len(set(payload.permissions)))
    require_csrf(request, user)
    with db_session() as db:
        target = db.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="账号不存在")
        if target["is_admin"]:
            raise HTTPException(status_code=409, detail="管理员默认拥有全部权限")
        permissions = sorted(set(payload.permissions))
        db.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
        db.executemany(
            """
            INSERT INTO user_permissions(user_id, permission_key, created_at)
            VALUES (?, ?, ?)
            """,
            [(user_id, permission_key, utc_now()) for permission_key in permissions],
        )
    return {
        "id": target["id"],
        "username": target["username"],
        "is_admin": False,
        "permissions": permissions,
        "created_at": target["created_at"],
    }


@app.patch("/api/admin/users/{user_id}/password")
def admin_reset_password(
    user_id: str,
    payload: AdminResetPasswordRequest,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    with db_session() as db:
        target = db.execute(
            "SELECT is_admin FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="账号不存在")
        if target["is_admin"]:
            raise HTTPException(status_code=409, detail="请在主站修改管理员自己的密码")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.password), user_id),
        )
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"ok": True}


@app.patch("/api/auth/password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    raw_session = request.cookies.get("srt_session")
    with db_session() as db:
        target = db.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if not target or not verify_password(
            target["password_hash"], payload.current_password
        ):
            raise HTTPException(status_code=400, detail="当前密码不正确")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.new_password), user["id"]),
        )
        if raw_session:
            db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                (user["id"], token_hash(raw_session)),
            )
    return {"ok": True}


@app.post("/api/devices/pair-code")
def create_pair_code(
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    ensure_any_feature(user)
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
def pair_device(payload: PairDeviceRequest, request: Request) -> dict[str, Any]:
    set_action_metadata(
        request,
        platform=payload.platform,
        model_count=len(payload.models),
    )
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
    request.state.analytics_user = {"id": pair["user_id"]}
    request.state.analytics_skip_ip_user_link = True
    request.state.analytics_resource_id = device_id
    return {
        "device_id": device_id,
        "device_token": raw_token,
        "server_url": settings.public_url,
    }


@app.get("/api/devices")
def list_devices(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    ensure_any_feature(user)
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
    permission_key = "subtitle_workspace" if task_id else "douyin_download"
    ensure_permission(user, permission_key)
    if task_id:
        _task_for_user(task_id, user["id"])
    return {
        "token": sign_local_command(
            user["id"], device_id, task_id, permission_key
        )
    }


@app.post("/api/tasks")
def create_task(
    payload: CreateTaskRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_action_metadata(
        request,
        backend="local_agent",
        model_id=payload.model_id,
        size_bytes=payload.size_bytes,
    )
    require_csrf(request, user)
    ensure_permission(user, "subtitle_workspace")
    _device_for_user(payload.device_id, user["id"])
    task_id = _id()
    now = utc_now()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO tasks(
                id, user_id, device_id, backend, original_name, size_bytes,
                model_id, status, progress, created_at, updated_at
            ) VALUES (?, ?, ?, 'local_agent', ?, ?, ?, 'uploading', 0, ?, ?)
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
    request.state.analytics_resource_id = task_id
    return {
        "id": task_id,
        "command_token": sign_local_command(
            user["id"], payload.device_id, task_id, "subtitle_workspace"
        ),
    }


def _serialize_task(row: sqlite3.Row) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "device_id": row["device_id"],
        "backend": row["backend"],
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
    result.update(task_transcription_metadata(row["id"]))
    return result


@app.get("/api/tasks")
def list_tasks(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    ensure_permission(user, "subtitle_workspace")
    recover_stale_cloud_jobs()
    recover_offline_local_jobs()
    with db_session() as db:
        rows = db.execute(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [_serialize_task(row) for row in rows]


@app.post("/api/tasks/import-srt")
async def import_srt(
    request: Request,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, str]:
    require_csrf(request, user)
    ensure_permission(user, "subtitle_workspace")
    original_name = Path(file.filename or "").name
    if not original_name or Path(original_name).suffix.lower() != ".srt":
        raise HTTPException(status_code=400, detail="请选择 SRT 字幕文件")
    if len(original_name) > 255:
        raise HTTPException(status_code=400, detail="SRT 文件名不能超过 255 个字符")
    content = await file.read(5 * 1024 * 1024 + 1)
    set_action_metadata(request, size_bytes=len(content))
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="SRT 文件不能超过 5MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="SRT 必须使用 UTF-8 编码") from exc
    try:
        parsed = parse_srt(text)
    except SrtError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_id = _id()
    now = utc_now()
    duration_ms = max(segment["end_ms"] for segment in parsed)
    digest = hashlib.sha256(content).hexdigest()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO tasks(
                id, user_id, device_id, backend, original_name, size_bytes,
                duration_ms, sha256, model_id, status, progress,
                created_at, updated_at
            ) VALUES (
                ?, ?, NULL, 'imported', ?, ?, ?, ?,
                'imported-srt', 'ready', 100, ?, ?
            )
            """,
            (
                task_id,
                user["id"],
                original_name,
                len(content),
                duration_ms,
                digest,
                now,
                now,
            ),
        )
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
                    ordinal,
                    segment["start_ms"],
                    segment["end_ms"],
                    segment["text"],
                    segment["text"],
                    now,
                )
                for ordinal, segment in enumerate(parsed)
            ],
        )
    set_action_metadata(request, segment_count=len(parsed), duration_ms=duration_ms)
    request.state.analytics_resource_id = task_id
    return {"id": task_id}


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    ensure_permission(user, "subtitle_workspace")
    recover_stale_cloud_jobs()
    recover_offline_local_jobs()
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


@app.get("/api/tasks/{task_id}/media")
def get_task_media(
    task_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    ensure_permission(user, "subtitle_workspace")
    ensure_permission(user, "douyin_download")
    _task_for_user(task_id, user["id"])
    cleanup_expired_media()
    record = media_record(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="该任务没有服务器视频。")
    if record["oss_media_key"]:
        expires_at = (
            datetime.fromisoformat(record["media_expires_at"])
            if record["media_expires_at"]
            else None
        )
        if not expires_at or expires_at <= datetime.now(UTC):
            raise HTTPException(status_code=410, detail="校对视频已过期，字幕仍可继续编辑。")
        try:
            url = cloud_transcription_service.media_url(record["oss_media_key"])
        except CloudTranscriptionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return RedirectResponse(
            url,
            status_code=302,
            headers={"Cache-Control": "private, no-store"},
        )
    if not record["media_filename"]:
        raise HTTPException(status_code=410, detail="校对视频已过期，字幕仍可继续编辑。")
    path = resolve_media_path(record["media_filename"])
    if not path or not path.is_file():
        raise HTTPException(status_code=410, detail="校对视频已过期，字幕仍可继续编辑。")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "private, no-store"},
    )


@app.patch("/api/tasks/{task_id}/segments/{segment_id}")
def edit_segment(
    task_id: str,
    segment_id: str,
    payload: EditSegmentRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    set_action_metadata(request, task_id=task_id, text_length=len(payload.text))
    require_csrf(request, user)
    ensure_permission(user, "subtitle_workspace")
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
async def retry_task(
    task_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    ensure_permission(user, "subtitle_workspace")
    task = _task_for_user(task_id, user["id"])
    if task["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed tasks can be retried")
    if task["backend"] == "local_agent" and task["device_id"]:
        device = _device_for_user(task["device_id"], user["id"])
        if not _device_online(device["last_seen_at"]):
            raise HTTPException(
                status_code=409,
                detail="本机 Agent 当前离线，请启动 Agent 后再重试。",
            )
        try:
            await retry_local_douyin_task(dict(task), dict(device), user)
            return {"ok": True}
        except TranscriptionError as exc:
            if exc.status_code != 404:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=str(exc),
                ) from exc
    try:
        if await retry_server_job(task_id, user):
            return {"ok": True}
    except (DouyinError, TranscriptionError) as exc:
        status_code = getattr(exc, "status_code", 422)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if not task["device_id"]:
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
    set_action_metadata(request, device_id=device_id)
    require_csrf(request, user)
    ensure_permission(user, "subtitle_workspace")
    _task_for_user(task_id, user["id"])
    _device_for_user(device_id, user["id"])
    return {
        "command_token": sign_local_command(
            user["id"], device_id, task_id, "subtitle_workspace"
        )
    }


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


@app.get("/api/tasks/{task_id}/export")
def export_task(
    task_id: str,
    format: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    set_action_metadata(request, format=format)
    ensure_permission(user, "subtitle_workspace")
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
    ensure_permission(user, "subtitle_workspace")
    _task_for_user(task_id, user["id"])
    is_server_job = False
    with db_session() as db:
        is_server_job = bool(
            db.execute(
                "SELECT 1 FROM server_transcription_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        )
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
    if is_server_job:
        delete_job_media(task_id)
    with db_session() as db:
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
    permission_key = data.get("permission_key")
    if permission_key not in FEATURE_PERMISSIONS:
        raise HTTPException(status_code=403, detail="Command permission invalid")
    ensure_user_id_permission(data["user_id"], permission_key)
    return {"ok": True, "user_id": data["user_id"], "task_id": data.get("task_id")}


def _ensure_agent_task(task_id: str, device: dict[str, Any]) -> sqlite3.Row:
    ensure_user_id_permission(device["user_id"], "subtitle_workspace")
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


@app.post("/api/agent/tasks/{task_id}/claim-douyin")
def agent_claim_douyin_task(
    task_id: str,
    payload: ClaimLocalDouyinTaskRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, Any]:
    ensure_user_id_permission(device["user_id"], "subtitle_workspace")
    try:
        return claim_local_douyin_task(task_id, device, payload.token)
    except TranscriptionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/agent/tasks/{task_id}/progress")
def agent_task_progress(
    task_id: str,
    payload: TaskProgressRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    task = _ensure_agent_task(task_id, device)
    if task["backend"] == "local_agent":
        if payload.status == "ready":
            raise HTTPException(
                status_code=409,
                detail="本机任务必须通过结果接口完成。",
            )
        if task["status"] == "ready":
            return {"ok": True}
        if payload.status not in {"downloading", "transcribing", "failed", "queued"}:
            raise HTTPException(status_code=422, detail="本机任务状态无效。")
        if (
            payload.downloaded_bytes is not None
            and payload.download_total_bytes
            and payload.downloaded_bytes > payload.download_total_bytes
        ):
            raise HTTPException(status_code=422, detail="本机下载进度数据无效。")
        if (
            payload.download_total_bytes is not None
            and payload.download_total_bytes
            > settings.transcription_max_source_bytes
        ):
            raise HTTPException(status_code=422, detail="本机下载文件超过限制。")
    with db_session() as db:
        db.execute(
            """
            UPDATE tasks
            SET status = ?, progress = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload.status, payload.progress, payload.error, utc_now(), task_id),
        )
        if task["backend"] == "local_agent" and any(
            value is not None
            for value in (
                payload.downloaded_bytes,
                payload.download_total_bytes,
                payload.download_speed_bps,
                payload.download_eta_seconds,
            )
        ):
            db.execute(
                """
                UPDATE local_douyin_jobs
                SET downloaded_bytes = COALESCE(?, downloaded_bytes),
                    download_total_bytes = COALESCE(?, download_total_bytes),
                    download_speed_bps = COALESCE(?, download_speed_bps),
                    download_eta_seconds = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    payload.downloaded_bytes,
                    payload.download_total_bytes,
                    payload.download_speed_bps,
                    payload.download_eta_seconds,
                    utc_now(),
                    task_id,
                ),
            )
    return {"ok": True}


@app.post("/api/agent/tasks/{task_id}/result")
def agent_task_result(
    task_id: str,
    payload: TaskResultRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    task = _ensure_agent_task(task_id, device)
    if not payload.segments or len(payload.segments) > 20_000:
        raise HTTPException(status_code=422, detail="字幕段数量无效。")
    if any(
        segment.end_ms <= segment.start_ms
        or segment.end_ms > payload.duration_ms + 1_000
        or not segment.text.strip()
        or len(segment.text) > 10_000
        for segment in payload.segments
    ):
        raise HTTPException(status_code=422, detail="字幕段内容或时间轴无效。")
    local_job = None
    try:
        local_job = validate_local_douyin_result(
            task_id,
            duration_ms=payload.duration_ms,
            size_bytes=payload.size_bytes,
        )
    except TranscriptionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if local_job and task["status"] == "ready":
        with db_session() as db:
            asset = db.execute(
                """
                SELECT sha256, duration_ms, size_bytes
                FROM device_assets
                WHERE task_id = ? AND device_id = ?
                """,
                (task_id, device["id"]),
            ).fetchone()
        if (
            asset
            and asset["sha256"] == payload.sha256
            and asset["duration_ms"] == payload.duration_ms
            and asset["size_bytes"] == payload.size_bytes
        ):
            return {"ok": True, "processed": False}
        raise HTTPException(
            status_code=409,
            detail="任务已经由不同结果完成。",
        )
    if local_job and task["status"] not in {"downloading", "transcribing"}:
        raise HTTPException(status_code=409, detail="本机任务当前不能提交结果。")
    now = utc_now()
    with db_session() as db:
        if local_job:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                """
                SELECT j.completed_at, t.status
                FROM local_douyin_jobs j
                JOIN tasks t ON t.id = j.task_id
                WHERE j.task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if current and current["completed_at"]:
                asset = db.execute(
                    """
                    SELECT sha256, duration_ms, size_bytes
                    FROM device_assets
                    WHERE task_id = ? AND device_id = ?
                    """,
                    (task_id, device["id"]),
                ).fetchone()
                if (
                    asset
                    and asset["sha256"] == payload.sha256
                    and asset["duration_ms"] == payload.duration_ms
                    and asset["size_bytes"] == payload.size_bytes
                ):
                    return {"ok": True, "processed": False}
                raise HTTPException(
                    status_code=409,
                    detail="任务已经由不同结果完成。",
                )
            if not current or current["status"] not in {
                "downloading",
                "transcribing",
            }:
                raise HTTPException(
                    status_code=409,
                    detail="本机任务当前不能提交结果。",
                )
            db.execute(
                """
                UPDATE local_douyin_jobs
                SET completed_at = ?, updated_at = ?
                WHERE task_id = ? AND completed_at IS NULL
                """,
                (now, now, task_id),
            )
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
                    to_simplified_chinese(segment.text),
                    to_simplified_chinese(segment.text),
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
    return {"ok": True, "processed": True}


@app.post("/api/agent/tasks/{task_id}/attach")
def agent_attach_asset(
    task_id: str,
    payload: AttachAssetRequest,
    device: dict[str, Any] = Depends(agent_device),
) -> dict[str, bool]:
    ensure_user_id_permission(device["user_id"], "subtitle_workspace")
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
