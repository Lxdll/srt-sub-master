from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from server.app.db import db_session


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def logout(client: TestClient, csrf: str) -> None:
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200


def create_quiz_user(client: TestClient, suffix: str) -> tuple[str, str]:
    admin_csrf = login(client, "admin", "admin-password-123")
    username = f"quiz-{suffix}-{uuid4().hex[:6]}"
    password = "quiz-password-123"
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "username": username,
            "password": password,
            "permissions": ["content_creative_quiz"],
        },
    )
    assert created.status_code == 200, created.text
    logout(client, admin_csrf)
    return username, password


def correct_answer(question_id: str) -> list[str]:
    with db_session() as db:
        row = db.execute(
            "SELECT correct_options_json FROM content_creative_questions WHERE id = ?",
            (question_id,),
        ).fetchone()
    assert row
    return json.loads(row["correct_options_json"])


def test_seed_import_is_complete_and_flags_source_anomaly(client: TestClient):
    login(client, "admin", "admin-password-123")
    response = client.get(
        "/api/admin/content-creative-questions?limit=1&needs_review=true"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["active"] == 628
    assert payload["summary"]["by_type"] == {
        "single": 352,
        "multiple": 181,
        "judgment": 95,
    }
    assert payload["summary"]["needs_review"] == 1
    assert payload["items"][0]["serial"] == 379
    assert "少于两个" in payload["items"][0]["review_notes"][0]


def test_admin_question_crud_versions_restore_and_conflict(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    source = f"自动化测试-{uuid4().hex[:6]}"
    created = client.post(
        "/api/admin/content-creative-questions",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "source": source,
            "question_type": "single",
            "prompt": "初始题目",
            "options": [
                {"key": "A", "text": "选项一"},
                {"key": "B", "text": "选项二"},
            ],
            "correct_options": ["A"],
            "note": "初始解析",
        },
    )
    assert created.status_code == 200, created.text
    question = created.json()
    question_id = question["id"]

    text_only = client.patch(
        f"/api/admin/content-creative-questions/{question_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "source": source,
            "question_type": "single",
            "prompt": "修改后的题目",
            "options": question["options"],
            "correct_options": ["A"],
            "note": "初始解析",
            "expected_version": 1,
        },
    )
    assert text_only.status_code == 200, text_only.text
    assert text_only.json()["content_version"] == 2
    assert text_only.json()["grading_version"] == 1

    grading = client.patch(
        f"/api/admin/content-creative-questions/{question_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "source": source,
            "question_type": "single",
            "prompt": "修改后的题目",
            "options": question["options"],
            "correct_options": ["B"],
            "note": "初始解析",
            "expected_version": 2,
        },
    )
    assert grading.status_code == 200, grading.text
    assert grading.json()["grading_version"] == 2

    conflict = client.patch(
        f"/api/admin/content-creative-questions/{question_id}/status",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_version": 2, "is_active": False},
    )
    assert conflict.status_code == 409

    disabled = client.patch(
        f"/api/admin/content-creative-questions/{question_id}/status",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_version": 3, "is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    versions = client.get(
        f"/api/admin/content-creative-questions/{question_id}/versions"
    )
    assert [item["action"] for item in versions.json()] == [
        "disable",
        "update",
        "update",
        "create",
    ]
    restored = client.post(
        f"/api/admin/content-creative-questions/{question_id}/versions/1/restore",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_version": 4},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["prompt"] == "初始题目"
    assert restored.json()["is_active"] is True
    assert restored.json()["content_version"] == 5


def test_practice_mock_mistakes_and_permission_isolation(client: TestClient):
    username, password = create_quiz_user(client, "flow")
    csrf = login(client, username, password)
    overview = client.get("/api/content-creative-quiz/overview")
    assert overview.status_code == 200
    assert overview.json()["question_count"] >= 628

    practice = client.post(
        "/api/content-creative-quiz/sessions",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "random", "question_count": 1},
    )
    assert practice.status_code == 200, practice.text
    session = practice.json()
    question = session["questions"][0]
    answer = correct_answer(question["id"])
    wrong = next(
        ([item["key"]] for item in question["options"] if item["key"] not in answer),
        answer[:-1],
    )
    answered = client.put(
        f"/api/content-creative-quiz/sessions/{session['id']}/answers/{question['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"selected_options": wrong},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "completed"
    assert answered.json()["questions"][0]["is_correct"] is False
    assert client.get("/api/content-creative-quiz/overview").json()["progress"]["mistakes"] == 1

    mistakes = client.post(
        "/api/content-creative-quiz/sessions",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "mistakes"},
    )
    mistake_session = mistakes.json()
    mistake_question = mistake_session["questions"][0]
    corrected = client.put(
        f"/api/content-creative-quiz/sessions/{mistake_session['id']}/answers/{mistake_question['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"selected_options": correct_answer(mistake_question["id"])},
    )
    assert corrected.status_code == 200
    assert client.get("/api/content-creative-quiz/overview").json()["progress"]["mistakes"] == 0

    mock = client.post(
        "/api/content-creative-quiz/sessions",
        headers={"X-CSRF-Token": csrf},
        json={"mode": "mock", "question_count": 2, "duration_minutes": 1},
    )
    assert mock.status_code == 200, mock.text
    mock_session = mock.json()
    first = mock_session["questions"][0]
    saved = client.put(
        f"/api/content-creative-quiz/sessions/{mock_session['id']}/answers/{first['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"selected_options": correct_answer(first["id"])},
    )
    assert saved.status_code == 200
    assert saved.json()["questions"][0]["correct_options"] is None
    assert saved.json()["questions"][0]["is_correct"] is None
    submitted = client.post(
        f"/api/content-creative-quiz/sessions/{mock_session['id']}/submit",
        headers={"X-CSRF-Token": csrf},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "completed"
    assert all(item["correct_options"] for item in submitted.json()["questions"])

    logout(client, csrf)
    admin_csrf = login(client, "admin", "admin-password-123")
    blocked_name = f"quiz-blocked-{uuid4().hex[:6]}"
    client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={"username": blocked_name, "password": "quiz-password-123"},
    )
    logout(client, admin_csrf)
    login(client, blocked_name, "quiz-password-123")
    assert client.get("/api/content-creative-quiz/overview").status_code == 403


def test_active_session_keeps_snapshot_after_admin_edit(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    source = f"快照测试-{uuid4().hex[:6]}"
    created = client.post(
        "/api/admin/content-creative-questions",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "source": source,
            "question_type": "single",
            "prompt": "开始场次时的题目",
            "options": [
                {"key": "A", "text": "旧正确答案"},
                {"key": "B", "text": "新正确答案"},
            ],
            "correct_options": ["A"],
        },
    ).json()
    logout(client, admin_csrf)

    username, password = create_quiz_user(client, "snapshot")
    user_csrf = login(client, username, password)
    session = client.post(
        "/api/content-creative-quiz/sessions",
        headers={"X-CSRF-Token": user_csrf},
        json={"mode": "sequential", "sources": [source]},
    ).json()
    logout(client, user_csrf)

    admin_csrf = login(client, "admin", "admin-password-123")
    changed = client.patch(
        f"/api/admin/content-creative-questions/{created['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "source": source,
            "question_type": "single",
            "prompt": "管理员后来修改的题目",
            "options": created["options"],
            "correct_options": ["B"],
            "note": None,
            "expected_version": 1,
        },
    )
    assert changed.status_code == 200
    logout(client, admin_csrf)

    user_csrf = login(client, username, password)
    answered = client.put(
        f"/api/content-creative-quiz/sessions/{session['id']}/answers/{created['id']}",
        headers={"X-CSRF-Token": user_csrf},
        json={"selected_options": ["A"]},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["questions"][0]["prompt"] == "开始场次时的题目"
    assert answered.json()["questions"][0]["is_correct"] is True
