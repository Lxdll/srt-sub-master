from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .db import db_session, utc_now
from .schemas import (
    ScriptCreateRequest,
    ScriptDetailResponse,
    ScriptListResponse,
    ScriptUpdateRequest,
)
from .security import current_user, ensure_permission, require_csrf


router = APIRouter(prefix="/api/scripts", tags=["scripts"])

_SCRIPT_SELECT = """
SELECT
    s.id,
    s.title,
    s.body,
    s.created_at,
    s.updated_at,
    creator.id AS creator_id,
    creator.username AS creator_username,
    updater.id AS updater_id,
    updater.username AS updater_username
FROM scripts s
JOIN users creator ON creator.id = s.created_by_user_id
JOIN users updater ON updater.id = s.updated_by_user_id
"""


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _find_casefolded(text: str, query: str) -> int:
    return text.casefold().find(query.casefold())


def _excerpt(body: str, query: str, length: int = 180) -> str:
    length = max(length, len(query) + 40)
    if len(body) <= length:
        return body
    match_at = _find_casefolded(body, query) if query else -1
    if match_at < 0:
        return f"{body[:length].rstrip()}…"
    padding = max(20, (length - len(query)) // 2)
    start = max(0, match_at - padding)
    end = min(len(body), start + length)
    if end == len(body):
        start = max(0, end - length)
    value = body[start:end]
    return f"{'…' if start else ''}{value}{'…' if end < len(body) else ''}"


def _authors(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "created_by": {
            "id": row["creator_id"],
            "username": row["creator_username"],
        },
        "updated_by": {
            "id": row["updater_id"],
            "username": row["updater_username"],
        },
    }


def _detail(row: sqlite3.Row) -> dict[str, Any]:
    body = row["body"]
    return {
        "id": row["id"],
        "title": row["title"],
        "body": body,
        "character_count": len(body),
        **_authors(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _script_or_404(script_id: str) -> sqlite3.Row:
    with db_session() as db:
        row = db.execute(
            f"{_SCRIPT_SELECT} WHERE s.id = ?",
            (script_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return row


def _clean_values(
    title: str | None,
    body: str | None,
) -> tuple[str | None, str | None]:
    clean_title = title.strip() if title is not None else None
    if clean_title is not None and not clean_title:
        raise HTTPException(status_code=422, detail="脚本标题不能为空")
    if body is not None and not body.strip():
        raise HTTPException(status_code=422, detail="脚本正文不能为空")
    return clean_title, body


@router.get("", response_model=ScriptListResponse)
def list_scripts(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    ensure_permission(user, "script_library")
    query = q.strip()
    parameters: list[Any] = []
    where = ""
    order_by = "s.updated_at DESC, s.id"
    if query:
        pattern = f"%{_escape_like(query)}%"
        where = (
            "WHERE (s.title LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "OR s.body LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend((pattern, pattern))
        order_by = (
            "CASE WHEN s.title LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "THEN 0 ELSE 1 END, s.updated_at DESC, s.id"
        )

    with db_session() as db:
        total = db.execute(
            f"SELECT COUNT(*) AS count FROM scripts s {where}",
            parameters,
        ).fetchone()["count"]
        list_parameters = list(parameters)
        if query:
            list_parameters.append(pattern)
        list_parameters.extend((limit, offset))
        rows = db.execute(
            f"{_SCRIPT_SELECT} {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            list_parameters,
        ).fetchall()

    items = []
    for row in rows:
        matched_in: list[str] = []
        if query and _find_casefolded(row["title"], query) >= 0:
            matched_in.append("title")
        if query and _find_casefolded(row["body"], query) >= 0:
            matched_in.append("body")
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "excerpt": _excerpt(row["body"], query),
                "matched_in": matched_in,
                "character_count": len(row["body"]),
                **_authors(row),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", response_model=ScriptDetailResponse, status_code=201)
def create_script(
    payload: ScriptCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    ensure_permission(user, "script_library")
    title, body = _clean_values(payload.title, payload.body)
    script_id = str(uuid4())
    timestamp = utc_now()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO scripts(
                id, title, body,
                created_by_user_id, updated_by_user_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                title,
                body,
                user["id"],
                user["id"],
                timestamp,
                timestamp,
            ),
        )
    return _detail(_script_or_404(script_id))


@router.get("/{script_id}", response_model=ScriptDetailResponse)
def get_script(
    script_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    ensure_permission(user, "script_library")
    return _detail(_script_or_404(script_id))


@router.patch("/{script_id}", response_model=ScriptDetailResponse)
def update_script(
    script_id: str,
    payload: ScriptUpdateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    ensure_permission(user, "script_library")
    _script_or_404(script_id)
    title, body = _clean_values(payload.title, payload.body)
    assignments = ["updated_by_user_id = ?", "updated_at = ?"]
    parameters: list[Any] = [user["id"], utc_now()]
    if title is not None:
        assignments.append("title = ?")
        parameters.append(title)
    if body is not None:
        assignments.append("body = ?")
        parameters.append(body)
    parameters.append(script_id)
    with db_session() as db:
        db.execute(
            f"UPDATE scripts SET {', '.join(assignments)} WHERE id = ?",
            parameters,
        )
    return _detail(_script_or_404(script_id))


@router.delete("/{script_id}")
def delete_script(
    script_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, bool]:
    require_csrf(request, user)
    ensure_permission(user, "script_library")
    _script_or_404(script_id)
    with db_session() as db:
        db.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
    return {"ok": True}
