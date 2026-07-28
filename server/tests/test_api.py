from __future__ import annotations

from fastapi.testclient import TestClient

def login(test_client: TestClient, username: str, password: str) -> str:
    response = test_client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_full_subtitle_workflow_and_permissions(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "username": "alice",
            "password": "alice-password-123",
            "permissions": ["subtitle_workspace"],
        },
    )
    assert created.status_code == 200

    client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": admin_csrf},
    )
    alice_csrf = login(client, "alice", "alice-password-123")
    pair_code = client.post(
        "/api/devices/pair-code",
        headers={"X-CSRF-Token": alice_csrf},
    ).json()["code"]
    paired = client.post(
        "/api/agent/pair",
        json={
            "code": pair_code,
            "name": "Alice Mac",
            "platform": "Darwin",
            "origin": "https://subtitles.test",
            "hardware": {"memory_gb": 18},
            "models": [],
        },
    )
    assert paired.status_code == 200
    device = paired.json()

    task_response = client.post(
        "/api/tasks",
        headers={"X-CSRF-Token": alice_csrf},
        json={
            "device_id": device["device_id"],
            "original_name": "中文 课程.mp4",
            "size_bytes": 123456,
            "model_id": "large-v3",
        },
    )
    assert task_response.status_code == 200
    task_id = task_response.json()["id"]
    agent_headers = {"Authorization": f"Bearer {device['device_token']}"}
    result = client.post(
        f"/api/agent/tasks/{task_id}/result",
        headers=agent_headers,
        json={
            "local_asset_id": "local-video-1",
            "sha256": "a" * 64,
            "duration_ms": 4200,
            "size_bytes": 123456,
            "segments": [
                {"start_ms": 0, "end_ms": 1800, "text": "第一句"},
                {"start_ms": 1900, "end_ms": 4200, "text": "second line"},
            ],
        },
    )
    assert result.status_code == 200

    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    first_segment = detail.json()["segments"][0]
    edited = client.patch(
        f"/api/tasks/{task_id}/segments/{first_segment['id']}",
        headers={"X-CSRF-Token": alice_csrf},
        json={"text": "修改后的第一句"},
    )
    assert edited.status_code == 200

    txt = client.get(f"/api/tasks/{task_id}/export?format=txt")
    srt = client.get(f"/api/tasks/{task_id}/export?format=srt")
    assert txt.text == "修改后的第一句\nsecond line\n"
    assert "00:00:00,000 --> 00:00:01,800" in srt.text
    assert "修改后的第一句" in srt.text

    client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": alice_csrf},
    )
    admin_csrf = login(client, "admin", "admin-password-123")
    client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "username": "bob",
            "password": "bob-password-123",
            "permissions": ["subtitle_workspace"],
        },
    )
    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
    bob_csrf = login(client, "bob", "bob-password-123")
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    assert (
        client.patch(
            f"/api/tasks/{task_id}/segments/{first_segment['id']}",
            headers={"X-CSRF-Token": bob_csrf},
            json={"text": "越权修改"},
        ).status_code
        == 404
    )

    client.post("/api/auth/logout", headers={"X-CSRF-Token": bob_csrf})
    alice_csrf = login(client, "alice", "alice-password-123")
    deleted = client.delete(
        f"/api/tasks/{task_id}",
        headers={"X-CSRF-Token": alice_csrf},
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_csrf_is_required(client: TestClient):
    login(client, "admin", "admin-password-123")
    response = client.post(
        "/api/admin/users",
        json={"username": "mallory", "password": "mallory-password-123"},
    )
    assert response.status_code == 403


def test_admin_can_list_users_and_regular_user_cannot(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={"username": "listed-user", "password": "listed-password-123"},
    )
    assert created.status_code == 200

    listed = client.get("/api/admin/users")
    assert listed.status_code == 200
    users = listed.json()
    assert any(
        item["username"] == "listed-user"
        and item["is_admin"] is False
        and item["created_at"]
        for item in users
    )
    assert all("password_hash" not in item for item in users)
    assert next(
        item for item in users if item["username"] == "listed-user"
    )["permissions"] == []

    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
    login(client, "listed-user", "listed-password-123")
    assert client.get("/api/admin/users").status_code == 403


def test_feature_permissions_and_password_management(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "username": "permission-user",
            "password": "permission-password-123",
            "permissions": ["douyin_download"],
        },
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]
    assert created.json()["permissions"] == ["douyin_download"]

    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
    user_csrf = login(client, "permission-user", "permission-password-123")
    me = client.get("/api/auth/me")
    assert me.json()["user"]["permissions"] == ["douyin_download"]
    assert client.get("/api/tasks").status_code == 403
    assert client.get("/api/devices").status_code == 200

    client.post("/api/auth/logout", headers={"X-CSRF-Token": user_csrf})
    admin_csrf = login(client, "admin", "admin-password-123")
    updated = client.patch(
        f"/api/admin/users/{user_id}/permissions",
        headers={"X-CSRF-Token": admin_csrf},
        json={"permissions": ["subtitle_workspace"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["permissions"] == ["subtitle_workspace"]

    reset = client.patch(
        f"/api/admin/users/{user_id}/password",
        headers={"X-CSRF-Token": admin_csrf},
        json={"password": "reset-password-456"},
    )
    assert reset.status_code == 200
    client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})
    assert client.post(
        "/api/auth/login",
        json={
            "username": "permission-user",
            "password": "permission-password-123",
        },
    ).status_code == 401

    user_csrf = login(client, "permission-user", "reset-password-456")
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/api/devices").status_code == 200
    changed = client.patch(
        "/api/auth/password",
        headers={"X-CSRF-Token": user_csrf},
        json={
            "current_password": "reset-password-456",
            "new_password": "self-changed-password-789",
        },
    )
    assert changed.status_code == 200, changed.text
    client.post("/api/auth/logout", headers={"X-CSRF-Token": user_csrf})
    assert client.post(
        "/api/auth/login",
        json={"username": "permission-user", "password": "reset-password-456"},
    ).status_code == 401
    login(client, "permission-user", "self-changed-password-789")


def test_import_srt_edit_and_export(client: TestClient):
    csrf = login(client, "admin", "admin-password-123")
    imported = client.post(
        "/api/tasks/import-srt",
        headers={"X-CSRF-Token": csrf},
        files={
            "file": (
                "课程字幕.srt",
                (
                    "1\r\n"
                    "00:00:00,000 --> 00:00:01,250\r\n"
                    "第一句\r\n\r\n"
                    "2\r\n"
                    "00:00:01.500 --> 00:00:03.000\r\n"
                    "second line\r\n"
                ).encode(),
                "application/x-subrip",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    task_id = imported.json()["id"]

    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "ready"
    assert payload["device_id"] is None
    assert payload["model_id"] == "imported-srt"
    assert payload["duration_ms"] == 3000
    assert [segment["edited_text"] for segment in payload["segments"]] == [
        "第一句",
        "second line",
    ]

    first = payload["segments"][0]
    edited = client.patch(
        f"/api/tasks/{task_id}/segments/{first['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"text": "校对后的第一句"},
    )
    assert edited.status_code == 200
    exported = client.get(f"/api/tasks/{task_id}/export?format=srt")
    assert exported.status_code == 200
    assert "校对后的第一句" in exported.text
    assert "00:00:01,500 --> 00:00:03,000" in exported.text


def test_import_srt_rejects_invalid_content(client: TestClient):
    csrf = login(client, "admin", "admin-password-123")
    response = client.post(
        "/api/tasks/import-srt",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("broken.srt", b"not an srt", "application/x-subrip")},
    )
    assert response.status_code == 400
    assert "时间轴" in response.json()["detail"]
