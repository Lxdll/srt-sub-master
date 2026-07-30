from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from server.app.analytics import analytics_service
from server.app.db import db_session
from server.app.main import app


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_page_views_login_links_and_admin_analytics():
    event_id = str(uuid4())
    with TestClient(
        app,
        base_url="https://subtitles.test",
        client=("8.8.8.8", 50_000),
    ) as visitor:
        anonymous = visitor.post(
            "/api/analytics/page-view",
            headers={"Origin": "https://subtitles.test"},
            json={"event_id": event_id, "path": "/login"},
        )
        assert anonymous.status_code == 202
        assert anonymous.json()["status"] == "accepted"
        duplicate = visitor.post(
            "/api/analytics/page-view",
            headers={"Origin": "https://subtitles.test"},
            json={"event_id": event_id, "path": "/login"},
        )
        assert duplicate.json()["status"] == "duplicate"

        failed = visitor.post(
            "/api/auth/login",
            json={"username": "admin", "password": "definitely-wrong"},
        )
        assert failed.status_code == 401
        _login(visitor, "admin", "admin-password-123")

        authenticated_event = str(uuid4())
        assert visitor.post(
            "/api/analytics/page-view",
            headers={"Origin": "https://subtitles.test"},
            json={"event_id": authenticated_event, "path": "/tools"},
        ).status_code == 202

        overview = visitor.get("/api/admin/analytics/overview?days=7")
        assert overview.status_code == 200, overview.text
        assert overview.json()["summary"]["period_page_views"] >= 2

        visits = visitor.get("/api/admin/analytics/visits?days=7")
        assert visits.status_code == 200
        matching = [
            item
            for item in visits.json()["items"]
            if item["id"] and item["ip_address"] == "8.8.8.8"
        ]
        assert any(item["path"] == "/login" and item["user_id"] is None for item in matching)
        assert any(item["path"] == "/tools" and item["username"] == "admin" for item in matching)

        links = visitor.get("/api/admin/analytics/ip-users?days=7&query=admin")
        assert links.status_code == 200
        linked = next(
            item for item in links.json()["items"] if item["ip_address"] == "8.8.8.8"
        )
        assert any(item["username"] == "admin" for item in linked["users"])

        actions = visitor.get(
            "/api/admin/analytics/actions?days=7&action=auth.login"
        )
        assert actions.status_code == 200
        outcomes = {item["outcome"] for item in actions.json()["items"]}
        assert {"success", "failure"}.issubset(outcomes)
        encoded = json.dumps(actions.json(), ensure_ascii=False)
        assert "definitely-wrong" not in encoded


def test_analytics_rejects_admin_host_and_regular_users(client: TestClient):
    rejected = client.post(
        "/api/analytics/page-view",
        headers={"Host": "admin.chenjianru.asia", "Origin": "https://admin.chenjianru.asia"},
        json={"event_id": str(uuid4()), "path": "/"},
    )
    assert rejected.status_code == 403

    admin_csrf = _login(client, "admin", "admin-password-123")
    username = f"analytics-user-{uuid4().hex[:8]}"
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={"username": username, "password": "analytics-password-123"},
    )
    assert created.status_code == 200
    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
    _login(client, username, "analytics-password-123")
    assert client.get("/api/admin/analytics/overview?days=30").status_code == 403


def test_cleanup_removes_raw_rows_but_keeps_aggregates():
    old = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    page_id = str(uuid4())
    action_id = str(uuid4())
    event_id = str(uuid4())
    day = old[:10]
    with db_session() as db:
        db.execute(
            """
            INSERT INTO page_views(
                id, event_id, ip_address, country, path, occurred_at
            ) VALUES (?, ?, '9.9.9.9', '未知', '/', ?)
            """,
            (page_id, event_id, old),
        )
        db.execute(
            """
            INSERT INTO action_events(
                id, ip_address, country, action_key, outcome,
                http_status, metadata_json, occurred_at
            ) VALUES (?, '9.9.9.9', '未知', 'auth.login', 'failure', 401, '{}', ?)
            """,
            (action_id, old),
        )
        db.execute(
            """
            INSERT OR REPLACE INTO analytics_daily(day, page_views, unique_ips)
            VALUES (?, 12, 4)
            """,
            (day,),
        )
    analytics_service.cleanup_expired()
    with db_session() as db:
        assert not db.execute(
            "SELECT 1 FROM page_views WHERE id = ?", (page_id,)
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM action_events WHERE id = ?", (action_id,)
        ).fetchone()
        aggregate = db.execute(
            "SELECT page_views, unique_ips FROM analytics_daily WHERE day = ?",
            (day,),
        ).fetchone()
    assert dict(aggregate) == {"page_views": 12, "unique_ips": 4}
