from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings
from .db import db_session, utc_now


password_hasher = PasswordHasher()
FEATURE_PERMISSIONS = frozenset(
    {
        "subtitle_workspace",
        "douyin_download",
        "prohibited_word_check",
        "script_analysis",
        "script_fission",
        "script_library",
    }
)
command_serializer = URLSafeTimedSerializer(
    settings.session_secret, salt="srt-local-command"
)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_token(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def create_session(user_id: str) -> tuple[str, str, str]:
    token = new_token()
    csrf = new_token(18)
    expires = datetime.now(UTC) + timedelta(days=settings.session_days)
    with db_session() as db:
        db.execute(
            """
            INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash(token), user_id, csrf, expires.isoformat(), utc_now()),
        )
    return token, csrf, expires.isoformat()


def _load_session(raw_token: str | None) -> dict[str, Any]:
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    with db_session() as db:
        row = db.execute(
            """
            SELECT u.id, u.username, u.is_admin, s.csrf_token, s.expires_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash(raw_token),),
        ).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    result = dict(row)
    if result["is_admin"]:
        result["permissions"] = sorted(FEATURE_PERMISSIONS)
    else:
        with db_session() as db:
            permissions = db.execute(
                "SELECT permission_key FROM user_permissions WHERE user_id = ?",
                (result["id"],),
            ).fetchall()
        result["permissions"] = [item["permission_key"] for item in permissions]
    return result


def current_user(
    request: Request,
    srt_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    user = _load_session(srt_session)
    request.state.analytics_user = user
    return user


def admin_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not user["is_admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return user


def ensure_permission(user: dict[str, Any], permission_key: str) -> None:
    if user["is_admin"] or permission_key in user.get("permissions", []):
        return
    raise HTTPException(status_code=403, detail="当前账号没有此功能的使用权限")


def ensure_any_feature(user: dict[str, Any]) -> None:
    if user["is_admin"] or FEATURE_PERMISSIONS.intersection(
        user.get("permissions", [])
    ):
        return
    raise HTTPException(status_code=403, detail="当前账号尚未分配功能权限")


def ensure_user_id_permission(user_id: str, permission_key: str) -> None:
    with db_session() as db:
        row = db.execute(
            "SELECT is_admin FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        permitted = db.execute(
            """
            SELECT 1 FROM user_permissions
            WHERE user_id = ? AND permission_key = ?
            """,
            (user_id, permission_key),
        ).fetchone()
    if row and (row["is_admin"] or permitted):
        return
    raise HTTPException(status_code=403, detail="当前账号没有此功能的使用权限")


def require_csrf(
    request: Request,
    user: dict[str, Any],
    supplied: str | None = None,
) -> None:
    token = supplied or request.headers.get("x-csrf-token")
    if not token or not secrets.compare_digest(token, user["csrf_token"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token invalid"
        )


def agent_device(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    raw_token = authorization.split(" ", 1)[1]
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM devices WHERE token_hash = ?",
            (token_hash(raw_token),),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return dict(row)


def sign_local_command(
    user_id: str,
    device_id: str,
    task_id: str | None,
    permission_key: str,
) -> str:
    return command_serializer.dumps(
        {
            "user_id": user_id,
            "device_id": device_id,
            "task_id": task_id,
            "permission_key": permission_key,
        }
    )


def verify_local_command(token: str, max_age: int = 21_600) -> dict[str, Any]:
    try:
        return command_serializer.loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise HTTPException(status_code=401, detail="Command token expired") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail="Command token invalid") from exc
