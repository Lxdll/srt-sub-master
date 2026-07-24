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
        json={"username": "alice", "password": "alice-password-123"},
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
        json={"username": "bob", "password": "bob-password-123"},
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
