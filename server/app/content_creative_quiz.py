from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import random
import sqlite3
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from .db import db_session, utc_now
from .security import admin_user, current_user, ensure_permission, require_csrf


router = APIRouter()
SEED_PATH = Path(__file__).with_name("content_creative_questions_seed.json")
QuestionType = Literal["single", "multiple", "judgment"]
QuizMode = Literal["sequential", "random", "mistakes", "mock"]
OPTION_KEYS = tuple("ABCDEFGH")


class QuizOption(BaseModel):
    key: Literal["A", "B", "C", "D", "E", "F", "G", "H"]
    text: str = Field(min_length=1, max_length=1_000)


class QuestionWrite(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    question_type: QuestionType
    prompt: str = Field(min_length=1, max_length=10_000)
    options: list[QuizOption] = Field(min_length=2, max_length=8)
    correct_options: list[str] = Field(min_length=1, max_length=8)
    note: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def validate_question(self) -> "QuestionWrite":
        self.source = self.source.strip()
        self.prompt = self.prompt.strip()
        self.note = self.note.strip() if self.note and self.note.strip() else None
        keys = [item.key for item in self.options]
        expected = list(OPTION_KEYS[: len(keys)])
        if keys != expected:
            raise ValueError("选项必须从 A 开始连续排列")
        if any(not item.text.strip() for item in self.options):
            raise ValueError("选项内容不能为空")
        answers = sorted(set(self.correct_options))
        if answers != sorted(self.correct_options):
            raise ValueError("正确答案不能重复且必须按选项顺序排列")
        if any(item not in keys for item in answers):
            raise ValueError("正确答案必须对应现有选项")
        if self.question_type == "single" and len(answers) != 1:
            raise ValueError("单选题只能有一个正确答案")
        if self.question_type == "multiple" and len(answers) < 2:
            raise ValueError("多选题至少需要两个正确答案")
        if self.question_type == "judgment":
            if [(item.key, item.text.strip()) for item in self.options] != [
                ("A", "正确"),
                ("B", "错误"),
            ]:
                raise ValueError("判断题选项固定为正确和错误")
            if len(answers) != 1:
                raise ValueError("判断题只能有一个正确答案")
        self.correct_options = answers
        self.options = [
            QuizOption(key=item.key, text=item.text.strip()) for item in self.options
        ]
        return self


class QuestionUpdate(QuestionWrite):
    expected_version: int = Field(ge=1)


class QuestionStatusUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    is_active: bool


class QuestionRestoreRequest(BaseModel):
    expected_version: int = Field(ge=1)


class SessionCreateRequest(BaseModel):
    mode: QuizMode
    sources: list[str] = Field(default_factory=list)
    question_types: list[QuestionType] = Field(default_factory=list)
    question_count: int | None = Field(default=None, ge=1)
    duration_minutes: int | None = Field(default=None, ge=1, le=300)
    all_questions: bool = False

    @model_validator(mode="after")
    def validate_mode(self) -> "SessionCreateRequest":
        if self.mode == "mock":
            if self.question_count is None or self.duration_minutes is None:
                raise ValueError("模拟考试必须填写题数和时长")
        elif self.duration_minutes is not None:
            raise ValueError("只有模拟考试可以设置时长")
        if self.all_questions and self.mode != "random":
            raise ValueError("只有随机练习可以选择全部题目")
        return self


class AnswerRequest(BaseModel):
    selected_options: list[str] = Field(max_length=8)

    @model_validator(mode="after")
    def normalize(self) -> "AnswerRequest":
        selected = sorted(set(self.selected_options))
        if selected != sorted(self.selected_options):
            raise ValueError("答案不能重复且必须按选项顺序排列")
        if any(item not in OPTION_KEYS for item in selected):
            raise ValueError("答案选项无效")
        self.selected_options = selected
        return self


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _now() -> datetime:
    return datetime.now(UTC)


def _snapshot_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "serial": row["serial"],
        "source": row["source"],
        "question_type": row["question_type"],
        "prompt": row["prompt"],
        "options": _loads(row["options_json"], []),
        "correct_options": _loads(row["correct_options_json"], []),
        "note": row["note"],
        "is_active": bool(row["is_active"]),
        "needs_review": bool(row["needs_review"]),
        "review_notes": _loads(row["review_notes_json"], []),
        "content_version": row["content_version"],
        "grading_version": row["grading_version"],
    }


def _grading_signature(snapshot: dict[str, Any]) -> str:
    return _json(
        {
            "question_type": snapshot["question_type"],
            "options": snapshot["options"],
            "correct_options": snapshot["correct_options"],
        }
    )


def _write_version(
    db: sqlite3.Connection,
    question: sqlite3.Row | dict[str, Any],
    action: str,
    admin_user_id: str | None,
) -> None:
    snapshot = _snapshot_from_row(question)
    db.execute(
        """
        INSERT INTO content_creative_question_versions(
            id, question_id, version_number, snapshot_json, action,
            admin_user_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            snapshot["id"],
            snapshot["content_version"],
            _json(snapshot),
            action,
            admin_user_id,
            utc_now(),
        ),
    )


def initialize_content_creative_questions() -> None:
    with db_session() as db:
        existing = db.execute(
            "SELECT COUNT(*) AS count FROM content_creative_questions"
        ).fetchone()["count"]
        if existing:
            return
        payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        created_at = utc_now()
        for item in payload["questions"]:
            db.execute(
                """
                INSERT INTO content_creative_questions(
                    id, serial, source, question_type, prompt, options_json,
                    correct_options_json, note, is_active, needs_review,
                    review_notes_json, content_version, grading_version,
                    created_by_user_id, updated_by_user_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 1, 1, NULL, NULL, ?, ?)
                """,
                (
                    item["id"],
                    item["serial"],
                    item["source"],
                    item["type"],
                    item["prompt"],
                    _json(item["options"]),
                    _json(item["correct_options"]),
                    item["note"],
                    int(item.get("needs_review", False)),
                    _json(item.get("review_notes", [])),
                    created_at,
                    created_at,
                ),
            )
            question = db.execute(
                "SELECT * FROM content_creative_questions WHERE id = ?",
                (item["id"],),
            ).fetchone()
            _write_version(db, question, "import", None)


def _admin_question(row: sqlite3.Row) -> dict[str, Any]:
    result = _snapshot_from_row(row)
    result.update(
        {
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "updated_by_username": row["updated_by_username"]
            if "updated_by_username" in row.keys()
            else None,
        }
    )
    return result


def _question_join_sql() -> str:
    return """
        SELECT q.*, u.username AS updated_by_username
        FROM content_creative_questions q
        LEFT JOIN users u ON u.id = q.updated_by_user_id
    """


@router.get("/api/admin/content-creative-questions")
def admin_list_questions(
    query: str = Query(default="", max_length=200),
    source: str = Query(default="", max_length=200),
    question_type: QuestionType | None = None,
    status: Literal["all", "active", "inactive"] = "all",
    needs_review: bool | None = None,
    sort: Literal["serial", "updated"] = "serial",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if query.strip():
        clauses.append("(q.prompt LIKE ? OR q.source LIKE ?)")
        value = f"%{query.strip()}%"
        params.extend([value, value])
    if source.strip():
        clauses.append("q.source = ?")
        params.append(source.strip())
    if question_type:
        clauses.append("q.question_type = ?")
        params.append(question_type)
    if status != "all":
        clauses.append("q.is_active = ?")
        params.append(1 if status == "active" else 0)
    if needs_review is not None:
        clauses.append("q.needs_review = ?")
        params.append(int(needs_review))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "q.serial ASC" if sort == "serial" else "q.updated_at DESC, q.serial ASC"
    with db_session() as db:
        total = db.execute(
            f"SELECT COUNT(*) AS count FROM content_creative_questions q{where}",
            params,
        ).fetchone()["count"]
        rows = db.execute(
            f"{_question_join_sql()}{where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        summary_rows = db.execute(
            """
            SELECT question_type, is_active, COUNT(*) AS count
            FROM content_creative_questions
            GROUP BY question_type, is_active
            """
        ).fetchall()
        sources = [
            row["source"]
            for row in db.execute(
                "SELECT DISTINCT source FROM content_creative_questions ORDER BY source"
            ).fetchall()
        ]
        review_count = db.execute(
            "SELECT COUNT(*) AS count FROM content_creative_questions WHERE needs_review = 1"
        ).fetchone()["count"]
    by_type = {item: 0 for item in ("single", "multiple", "judgment")}
    active_count = 0
    inactive_count = 0
    for row in summary_rows:
        by_type[row["question_type"]] += row["count"]
        if row["is_active"]:
            active_count += row["count"]
        else:
            inactive_count += row["count"]
    return {
        "items": [_admin_question(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": {
            "active": active_count,
            "inactive": inactive_count,
            "needs_review": review_count,
            "by_type": by_type,
            "sources": sources,
        },
    }


@router.get("/api/admin/content-creative-questions/{question_id}")
def admin_get_question(
    question_id: str,
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    with db_session() as db:
        row = db.execute(
            f"{_question_join_sql()} WHERE q.id = ?", (question_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="题目不存在")
    return _admin_question(row)


@router.post("/api/admin/content-creative-questions")
def admin_create_question(
    payload: QuestionWrite,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    question_id = f"content-creative-{uuid4()}"
    with db_session() as db:
        serial = db.execute(
            "SELECT COALESCE(MAX(serial), 0) + 1 AS serial FROM content_creative_questions"
        ).fetchone()["serial"]
        created_at = utc_now()
        db.execute(
            """
            INSERT INTO content_creative_questions(
                id, serial, source, question_type, prompt, options_json,
                correct_options_json, note, is_active, needs_review,
                review_notes_json, content_version, grading_version,
                created_by_user_id, updated_by_user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, '[]', 1, 1, ?, ?, ?, ?)
            """,
            (
                question_id,
                serial,
                payload.source,
                payload.question_type,
                payload.prompt,
                _json([item.model_dump() for item in payload.options]),
                _json(payload.correct_options),
                payload.note,
                user["id"],
                user["id"],
                created_at,
                created_at,
            ),
        )
        row = db.execute(
            f"{_question_join_sql()} WHERE q.id = ?", (question_id,)
        ).fetchone()
        _write_version(db, row, "create", user["id"])
    request.state.analytics_resource_id = question_id
    return _admin_question(row)


def _require_version(row: sqlite3.Row | None, expected: int) -> sqlite3.Row:
    if not row:
        raise HTTPException(status_code=404, detail="题目不存在")
    if row["content_version"] != expected:
        raise HTTPException(status_code=409, detail="题目已被其他管理员修改，请刷新后重试")
    return row


@router.patch("/api/admin/content-creative-questions/{question_id}")
def admin_update_question(
    question_id: str,
    payload: QuestionUpdate,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    with db_session() as db:
        current = _require_version(
            db.execute(
                "SELECT * FROM content_creative_questions WHERE id = ?",
                (question_id,),
            ).fetchone(),
            payload.expected_version,
        )
        before = _snapshot_from_row(current)
        after = {
            **before,
            "source": payload.source,
            "question_type": payload.question_type,
            "prompt": payload.prompt,
            "options": [item.model_dump() for item in payload.options],
            "correct_options": payload.correct_options,
            "note": payload.note,
        }
        grading_changed = _grading_signature(before) != _grading_signature(after)
        content_version = current["content_version"] + 1
        grading_version = current["grading_version"] + int(grading_changed)
        db.execute(
            """
            UPDATE content_creative_questions
            SET source = ?, question_type = ?, prompt = ?, options_json = ?,
                correct_options_json = ?, note = ?, needs_review = 0,
                review_notes_json = '[]', content_version = ?, grading_version = ?,
                updated_by_user_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.source,
                payload.question_type,
                payload.prompt,
                _json([item.model_dump() for item in payload.options]),
                _json(payload.correct_options),
                payload.note,
                content_version,
                grading_version,
                user["id"],
                utc_now(),
                question_id,
            ),
        )
        row = db.execute(
            f"{_question_join_sql()} WHERE q.id = ?", (question_id,)
        ).fetchone()
        _write_version(db, row, "update", user["id"])
    request.state.analytics_resource_id = question_id
    return _admin_question(row)


@router.patch("/api/admin/content-creative-questions/{question_id}/status")
def admin_update_question_status(
    question_id: str,
    payload: QuestionStatusUpdate,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    with db_session() as db:
        current = _require_version(
            db.execute(
                "SELECT * FROM content_creative_questions WHERE id = ?",
                (question_id,),
            ).fetchone(),
            payload.expected_version,
        )
        if bool(current["is_active"]) != payload.is_active:
            db.execute(
                """
                UPDATE content_creative_questions
                SET is_active = ?, content_version = content_version + 1,
                    updated_by_user_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(payload.is_active), user["id"], utc_now(), question_id),
            )
        row = db.execute(
            f"{_question_join_sql()} WHERE q.id = ?", (question_id,)
        ).fetchone()
        if bool(current["is_active"]) != payload.is_active:
            _write_version(
                db, row, "enable" if payload.is_active else "disable", user["id"]
            )
    request.state.analytics_resource_id = question_id
    return _admin_question(row)


@router.get("/api/admin/content-creative-questions/{question_id}/versions")
def admin_question_versions(
    question_id: str,
    _: dict[str, Any] = Depends(admin_user),
) -> list[dict[str, Any]]:
    with db_session() as db:
        if not db.execute(
            "SELECT 1 FROM content_creative_questions WHERE id = ?", (question_id,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="题目不存在")
        rows = db.execute(
            """
            SELECT v.*, u.username AS admin_username
            FROM content_creative_question_versions v
            LEFT JOIN users u ON u.id = v.admin_user_id
            WHERE v.question_id = ?
            ORDER BY v.version_number DESC
            """,
            (question_id,),
        ).fetchall()
    return [
        {
            "version_number": row["version_number"],
            "action": row["action"],
            "admin_username": row["admin_username"],
            "created_at": row["created_at"],
            "snapshot": _loads(row["snapshot_json"], {}),
        }
        for row in rows
    ]


@router.post(
    "/api/admin/content-creative-questions/{question_id}/versions/{version}/restore"
)
def admin_restore_question(
    question_id: str,
    version: int,
    payload: QuestionRestoreRequest,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    with db_session() as db:
        current = _require_version(
            db.execute(
                "SELECT * FROM content_creative_questions WHERE id = ?",
                (question_id,),
            ).fetchone(),
            payload.expected_version,
        )
        version_row = db.execute(
            """
            SELECT snapshot_json FROM content_creative_question_versions
            WHERE question_id = ? AND version_number = ?
            """,
            (question_id, version),
        ).fetchone()
        if not version_row:
            raise HTTPException(status_code=404, detail="历史版本不存在")
        target = _loads(version_row["snapshot_json"], {})
        before = _snapshot_from_row(current)
        grading_changed = _grading_signature(before) != _grading_signature(target)
        db.execute(
            """
            UPDATE content_creative_questions
            SET source = ?, question_type = ?, prompt = ?, options_json = ?,
                correct_options_json = ?, note = ?, is_active = ?, needs_review = ?,
                review_notes_json = ?, content_version = content_version + 1,
                grading_version = grading_version + ?, updated_by_user_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                target["source"],
                target["question_type"],
                target["prompt"],
                _json(target["options"]),
                _json(target["correct_options"]),
                target.get("note"),
                int(target.get("is_active", True)),
                int(target.get("needs_review", False)),
                _json(target.get("review_notes", [])),
                int(grading_changed),
                user["id"],
                utc_now(),
                question_id,
            ),
        )
        row = db.execute(
            f"{_question_join_sql()} WHERE q.id = ?", (question_id,)
        ).fetchone()
        _write_version(db, row, "restore", user["id"])
    request.state.analytics_resource_id = question_id
    return _admin_question(row)


def _quiz_user(user: dict[str, Any]) -> dict[str, Any]:
    ensure_permission(user, "content_creative_quiz")
    return user


def _session_or_404(
    db: sqlite3.Connection, session_id: str, user_id: str
) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM content_creative_quiz_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="练习场次不存在")
    return row


def _record_progress(
    db: sqlite3.Connection,
    user_id: str,
    question_id: str,
    grading_version: int,
    is_correct: bool,
    answered_at: str,
) -> None:
    db.execute(
        """
        INSERT INTO content_creative_question_progress(
            user_id, question_id, grading_version, attempts, correct_count,
            wrong_count, last_is_correct, last_answered_at
        ) VALUES (?, ?, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(user_id, question_id, grading_version) DO UPDATE SET
            attempts = attempts + 1,
            correct_count = correct_count + excluded.correct_count,
            wrong_count = wrong_count + excluded.wrong_count,
            last_is_correct = excluded.last_is_correct,
            last_answered_at = excluded.last_answered_at
        """,
        (
            user_id,
            question_id,
            grading_version,
            int(is_correct),
            int(not is_correct),
            int(is_correct),
            answered_at,
        ),
    )


def _finalize_mock(db: sqlite3.Connection, session: sqlite3.Row) -> sqlite3.Row:
    if session["status"] != "active":
        return session
    questions = db.execute(
        """
        SELECT * FROM content_creative_quiz_session_questions
        WHERE session_id = ? ORDER BY ordinal
        """,
        (session["id"],),
    ).fetchall()
    answers = {
        row["question_id"]: row
        for row in db.execute(
            "SELECT * FROM content_creative_quiz_answers WHERE session_id = ?",
            (session["id"],),
        ).fetchall()
    }
    completed_at = utc_now()
    correct_count = 0
    for question in questions:
        snapshot = _loads(question["snapshot_json"], {})
        answer = answers.get(question["question_id"])
        selected = _loads(answer["selected_options_json"], []) if answer else []
        is_correct = selected == snapshot["correct_options"]
        correct_count += int(is_correct)
        if answer:
            db.execute(
                """
                UPDATE content_creative_quiz_answers
                SET is_correct = ?, answered_at = ?
                WHERE session_id = ? AND question_id = ?
                """,
                (
                    int(is_correct),
                    answer["answered_at"],
                    session["id"],
                    question["question_id"],
                ),
            )
        else:
            db.execute(
                """
                INSERT INTO content_creative_quiz_answers(
                    session_id, question_id, selected_options_json,
                    is_correct, answered_at
                ) VALUES (?, ?, '[]', 0, ?)
                """,
                (session["id"], question["question_id"], completed_at),
            )
        _record_progress(
            db,
            session["user_id"],
            question["question_id"],
            question["grading_version"],
            is_correct,
            completed_at,
        )
    db.execute(
        """
        UPDATE content_creative_quiz_sessions
        SET status = 'completed', completed_at = ?, score_correct = ?,
            score_total = ?, updated_at = ? WHERE id = ?
        """,
        (completed_at, correct_count, len(questions), completed_at, session["id"]),
    )
    return db.execute(
        "SELECT * FROM content_creative_quiz_sessions WHERE id = ?",
        (session["id"],),
    ).fetchone()


def _finalize_practice_if_complete(
    db: sqlite3.Connection, session: sqlite3.Row
) -> sqlite3.Row:
    if session["status"] != "active":
        return session
    totals = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM content_creative_quiz_session_questions
             WHERE session_id = ?) AS total,
            (SELECT COUNT(*) FROM content_creative_quiz_answers
             WHERE session_id = ?) AS answered,
            (SELECT COUNT(*) FROM content_creative_quiz_answers
             WHERE session_id = ? AND is_correct = 1) AS correct
        """,
        (session["id"], session["id"], session["id"]),
    ).fetchone()
    if totals["answered"] != totals["total"]:
        return session
    completed_at = utc_now()
    db.execute(
        """
        UPDATE content_creative_quiz_sessions
        SET status = 'completed', completed_at = ?, score_correct = ?,
            score_total = ?, updated_at = ? WHERE id = ?
        """,
        (
            completed_at,
            totals["correct"],
            totals["total"],
            completed_at,
            session["id"],
        ),
    )
    return db.execute(
        "SELECT * FROM content_creative_quiz_sessions WHERE id = ?",
        (session["id"],),
    ).fetchone()


def _expire_mock_if_needed(
    db: sqlite3.Connection, session: sqlite3.Row
) -> sqlite3.Row:
    if (
        session["status"] == "active"
        and session["mode"] == "mock"
        and session["deadline_at"]
        and datetime.fromisoformat(session["deadline_at"]) <= _now()
    ):
        return _finalize_mock(db, session)
    return session


def _public_session(db: sqlite3.Connection, session: sqlite3.Row) -> dict[str, Any]:
    questions = db.execute(
        """
        SELECT sq.*, a.selected_options_json, a.is_correct, a.answered_at
        FROM content_creative_quiz_session_questions sq
        LEFT JOIN content_creative_quiz_answers a
          ON a.session_id = sq.session_id AND a.question_id = sq.question_id
        WHERE sq.session_id = ? ORDER BY sq.ordinal
        """,
        (session["id"],),
    ).fetchall()
    public_questions: list[dict[str, Any]] = []
    breakdown: dict[str, dict[str, int]] = {
        item: {"total": 0, "correct": 0}
        for item in ("single", "multiple", "judgment")
    }
    for row in questions:
        snapshot = _loads(row["snapshot_json"], {})
        answered = row["selected_options_json"] is not None
        reveal = session["status"] == "completed" or (
            session["mode"] != "mock" and answered
        )
        if session["status"] == "completed":
            breakdown[snapshot["question_type"]]["total"] += 1
            breakdown[snapshot["question_type"]]["correct"] += int(
                bool(row["is_correct"])
            )
        public_questions.append(
            {
                "id": snapshot["id"],
                "serial": snapshot["serial"],
                "source": snapshot["source"],
                "question_type": snapshot["question_type"],
                "prompt": snapshot["prompt"],
                "options": snapshot["options"],
                "selected_options": _loads(row["selected_options_json"], [])
                if answered
                else [],
                "answered_at": row["answered_at"],
                "is_correct": bool(row["is_correct"]) if reveal and answered else None,
                "correct_options": snapshot["correct_options"] if reveal else None,
                "note": snapshot.get("note") if reveal else None,
            }
        )
    completed_at = session["completed_at"]
    end = datetime.fromisoformat(completed_at) if completed_at else _now()
    started = datetime.fromisoformat(session["started_at"])
    return {
        "id": session["id"],
        "mode": session["mode"],
        "status": session["status"],
        "filters": _loads(session["filters_json"], {}),
        "duration_seconds": session["duration_seconds"],
        "deadline_at": session["deadline_at"],
        "started_at": session["started_at"],
        "completed_at": completed_at,
        "elapsed_seconds": max(0, int((end - started).total_seconds())),
        "question_count": len(public_questions),
        "answered_count": sum(bool(item["answered_at"]) for item in public_questions),
        "score_correct": session["score_correct"],
        "score_total": session["score_total"],
        "breakdown": breakdown if session["status"] == "completed" else None,
        "questions": public_questions,
    }


@router.get("/api/content-creative-quiz/overview")
def quiz_overview(
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    _quiz_user(user)
    with db_session() as db:
        active = db.execute(
            """
            SELECT * FROM content_creative_quiz_sessions
            WHERE user_id = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (user["id"],),
        ).fetchone()
        if active:
            active = _expire_mock_if_needed(db, active)
        count_rows = db.execute(
            """
            SELECT question_type, COUNT(*) AS count
            FROM content_creative_questions WHERE is_active = 1
            GROUP BY question_type
            """
        ).fetchall()
        sources = [
            {"source": row["source"], "count": row["count"]}
            for row in db.execute(
                """
                SELECT source, COUNT(*) AS count FROM content_creative_questions
                WHERE is_active = 1 GROUP BY source ORDER BY source
                """
            ).fetchall()
        ]
        progress = db.execute(
            """
            SELECT COALESCE(SUM(p.attempts), 0) AS attempts,
                   COALESCE(SUM(p.correct_count), 0) AS correct,
                   COALESCE(SUM(CASE WHEN p.last_is_correct = 0 THEN 1 ELSE 0 END), 0)
                     AS mistakes
            FROM content_creative_question_progress p
            JOIN content_creative_questions q
              ON q.id = p.question_id AND q.grading_version = p.grading_version
            WHERE p.user_id = ? AND q.is_active = 1
            """,
            (user["id"],),
        ).fetchone()
        recent = db.execute(
            """
            SELECT id, mode, status, started_at, completed_at, score_correct,
                   score_total, duration_seconds
            FROM content_creative_quiz_sessions
            WHERE user_id = ? AND status != 'active'
            ORDER BY updated_at DESC LIMIT 6
            """,
            (user["id"],),
        ).fetchall()
        active_public = (
            _public_session(db, active)
            if active and active["status"] == "active"
            else None
        )
    by_type = {item: 0 for item in ("single", "multiple", "judgment")}
    for row in count_rows:
        by_type[row["question_type"]] = row["count"]
    attempts = progress["attempts"]
    return {
        "question_count": sum(by_type.values()),
        "by_type": by_type,
        "sources": sources,
        "progress": {
            "attempts": attempts,
            "correct": progress["correct"],
            "correct_rate": progress["correct"] / attempts if attempts else 0,
            "mistakes": progress["mistakes"],
        },
        "active_session": active_public,
        "recent_sessions": [dict(row) for row in recent],
    }


def _question_pool(
    db: sqlite3.Connection,
    user_id: str,
    payload: SessionCreateRequest,
) -> list[sqlite3.Row]:
    clauses = ["q.is_active = 1"]
    params: list[Any] = []
    if payload.sources:
        clauses.append(f"q.source IN ({','.join('?' for _ in payload.sources)})")
        params.extend(payload.sources)
    if payload.question_types:
        clauses.append(
            f"q.question_type IN ({','.join('?' for _ in payload.question_types)})"
        )
        params.extend(payload.question_types)
    if payload.mode == "mistakes":
        sql = f"""
            SELECT q.* FROM content_creative_questions q
            JOIN content_creative_question_progress p
              ON p.question_id = q.id AND p.grading_version = q.grading_version
            WHERE {' AND '.join(clauses)} AND p.user_id = ?
              AND p.last_is_correct = 0
            ORDER BY q.serial
        """
        params.append(user_id)
    else:
        sql = f"""
            SELECT q.* FROM content_creative_questions q
            WHERE {' AND '.join(clauses)} ORDER BY q.serial
        """
    return db.execute(sql, params).fetchall()


@router.post("/api/content-creative-quiz/sessions")
def create_quiz_session(
    payload: SessionCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    _quiz_user(user)
    require_csrf(request, user)
    with db_session() as db:
        pool = _question_pool(db, user["id"], payload)
        if not pool:
            detail = "当前没有可练习的错题" if payload.mode == "mistakes" else "筛选条件下没有可用题目"
            raise HTTPException(status_code=409, detail=detail)
        if payload.mode == "random":
            count = (
                len(pool)
                if payload.all_questions
                else payload.question_count
                if payload.question_count is not None
                else min(20, len(pool))
            )
        elif payload.mode == "mock":
            count = payload.question_count or 0
        else:
            count = len(pool)
        if count > len(pool):
            raise HTTPException(status_code=422, detail=f"当前筛选条件最多只有 {len(pool)} 题")
        selected = list(pool)
        if payload.mode in {"random", "mistakes", "mock"}:
            random.shuffle(selected)
        selected = selected[:count]

        now = _now()
        now_text = now.isoformat()
        db.execute(
            """
            UPDATE content_creative_quiz_sessions
            SET status = 'abandoned', abandoned_at = ?, updated_at = ?
            WHERE user_id = ? AND status = 'active'
            """,
            (now_text, now_text, user["id"]),
        )
        session_id = str(uuid4())
        duration_seconds = (
            payload.duration_minutes * 60 if payload.duration_minutes is not None else None
        )
        deadline_at = (
            (now + timedelta(seconds=duration_seconds)).isoformat()
            if duration_seconds
            else None
        )
        filters = {
            "sources": payload.sources,
            "question_types": payload.question_types,
            "question_count": count,
        }
        db.execute(
            """
            INSERT INTO content_creative_quiz_sessions(
                id, user_id, mode, status, filters_json, duration_seconds,
                started_at, deadline_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user["id"],
                payload.mode,
                _json(filters),
                duration_seconds,
                now_text,
                deadline_at,
                now_text,
                now_text,
            ),
        )
        for ordinal, row in enumerate(selected):
            db.execute(
                """
                INSERT INTO content_creative_quiz_session_questions(
                    session_id, ordinal, question_id, grading_version, snapshot_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    ordinal,
                    row["id"],
                    row["grading_version"],
                    _json(_snapshot_from_row(row)),
                ),
            )
        session = _session_or_404(db, session_id, user["id"])
        result = _public_session(db, session)
    request.state.analytics_resource_id = session_id
    return result


@router.get("/api/content-creative-quiz/sessions/{session_id}")
def get_quiz_session(
    session_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    _quiz_user(user)
    with db_session() as db:
        session = _session_or_404(db, session_id, user["id"])
        session = _expire_mock_if_needed(db, session)
        return _public_session(db, session)


@router.put(
    "/api/content-creative-quiz/sessions/{session_id}/answers/{question_id}"
)
def answer_quiz_question(
    session_id: str,
    question_id: str,
    payload: AnswerRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    _quiz_user(user)
    require_csrf(request, user)
    with db_session() as db:
        session = _session_or_404(db, session_id, user["id"])
        session = _expire_mock_if_needed(db, session)
        if session["status"] != "active":
            raise HTTPException(status_code=409, detail="当前场次已经结束")
        question = db.execute(
            """
            SELECT * FROM content_creative_quiz_session_questions
            WHERE session_id = ? AND question_id = ?
            """,
            (session_id, question_id),
        ).fetchone()
        if not question:
            raise HTTPException(status_code=404, detail="场次中不存在这道题")
        snapshot = _loads(question["snapshot_json"], {})
        option_keys = {item["key"] for item in snapshot["options"]}
        if any(item not in option_keys for item in payload.selected_options):
            raise HTTPException(status_code=422, detail="答案包含不存在的选项")
        if (
            snapshot["question_type"] in {"single", "judgment"}
            and not (session["mode"] == "mock" and not payload.selected_options)
            and len(payload.selected_options) != 1
        ):
            raise HTTPException(status_code=422, detail="请选择一个答案")
        if session["mode"] != "mock" and not payload.selected_options:
            raise HTTPException(status_code=422, detail="请先选择答案")
        existing = db.execute(
            """
            SELECT * FROM content_creative_quiz_answers
            WHERE session_id = ? AND question_id = ?
            """,
            (session_id, question_id),
        ).fetchone()
        if existing and session["mode"] != "mock":
            raise HTTPException(status_code=409, detail="练习题确认后不能修改答案")
        is_correct = payload.selected_options == snapshot["correct_options"]
        answered_at = utc_now()
        db.execute(
            """
            INSERT INTO content_creative_quiz_answers(
                session_id, question_id, selected_options_json, is_correct, answered_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, question_id) DO UPDATE SET
                selected_options_json = excluded.selected_options_json,
                is_correct = excluded.is_correct,
                answered_at = excluded.answered_at
            """,
            (
                session_id,
                question_id,
                _json(payload.selected_options),
                int(is_correct),
                answered_at,
            ),
        )
        if session["mode"] != "mock":
            _record_progress(
                db,
                user["id"],
                question_id,
                question["grading_version"],
                is_correct,
                answered_at,
            )
            session = _finalize_practice_if_complete(db, session)
        result = _public_session(db, session)
    request.state.analytics_resource_id = session_id
    return result


@router.post("/api/content-creative-quiz/sessions/{session_id}/submit")
def submit_quiz_session(
    session_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    _quiz_user(user)
    require_csrf(request, user)
    with db_session() as db:
        session = _session_or_404(db, session_id, user["id"])
        session = _expire_mock_if_needed(db, session)
        if session["status"] == "completed":
            return _public_session(db, session)
        if session["status"] != "active":
            raise HTTPException(status_code=409, detail="当前场次无法交卷")
        if session["mode"] == "mock":
            session = _finalize_mock(db, session)
        else:
            session = _finalize_practice_if_complete(db, session)
            if session["status"] != "completed":
                raise HTTPException(status_code=409, detail="请完成全部练习题后再结束")
        result = _public_session(db, session)
    request.state.analytics_resource_id = session_id
    return result
