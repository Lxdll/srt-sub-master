from __future__ import annotations

from fastapi.testclient import TestClient

from server.app.db import db_session


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def logout(client: TestClient, csrf: str) -> None:
    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text


def create_user(
    client: TestClient,
    csrf: str,
    *,
    username: str,
    permissions: list[str],
) -> dict:
    response = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "username": username,
            "password": f"{username}-password-123",
            "permissions": permissions,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_script(
    client: TestClient,
    csrf: str,
    *,
    title: str,
    body: str,
) -> dict:
    response = client.post(
        "/api/scripts",
        headers={"X-CSRF-Token": csrf},
        json={"title": title, "body": body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_script_schema_and_admin_permission(client: TestClient):
    csrf = login(client, "admin", "admin-password-123")
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert "script_library" in me.json()["user"]["permissions"]

    with db_session() as db:
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(scripts)").fetchall()
        }
        indexes = {
            row["name"] for row in db.execute("PRAGMA index_list(scripts)").fetchall()
        }
    assert {
        "id",
        "title",
        "body",
        "created_by_user_id",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    } <= columns
    assert "idx_scripts_updated_at" in indexes
    logout(client, csrf)


def test_script_library_is_shared_and_tracks_authors(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    editor = create_user(
        client,
        admin_csrf,
        username="script-editor",
        permissions=["script_library"],
    )
    created = create_script(
        client,
        admin_csrf,
        title="  团队脚本  ",
        body="第一行\n第二行",
    )
    assert created["title"] == "团队脚本"
    assert created["body"] == "第一行\n第二行"
    assert created["character_count"] == len(created["body"])
    assert created["created_by"]["username"] == "admin"
    assert created["updated_by"]["username"] == "admin"

    logout(client, admin_csrf)
    editor_csrf = login(
        client,
        "script-editor",
        "script-editor-password-123",
    )
    listed = client.get("/api/scripts")
    assert listed.status_code == 200, listed.text
    shared_item = next(
        item for item in listed.json()["items"] if item["id"] == created["id"]
    )
    assert shared_item["created_by"]["username"] == "admin"
    assert shared_item["excerpt"] == "第一行\n第二行"
    assert shared_item["matched_in"] == []

    updated = client.patch(
        f"/api/scripts/{created['id']}",
        headers={"X-CSRF-Token": editor_csrf},
        json={"body": "第一行\n由另一位成员修改"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["created_by"]["username"] == "admin"
    assert updated.json()["updated_by"] == {
        "id": editor["id"],
        "username": "script-editor",
    }
    assert updated.json()["title"] == "团队脚本"
    detail = client.get(f"/api/scripts/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["body"] == "第一行\n由另一位成员修改"
    assert detail.json()["created_by"]["username"] == "admin"
    logout(client, editor_csrf)


def test_script_crud_validation_csrf_and_permission(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    create_user(
        client,
        admin_csrf,
        username="no-script-access",
        permissions=[],
    )
    assert client.post(
        "/api/scripts",
        json={"title": "缺少令牌", "body": "正文"},
    ).status_code == 403
    assert client.post(
        "/api/scripts",
        headers={"X-CSRF-Token": admin_csrf},
        json={"title": "   ", "body": "正文"},
    ).status_code == 422
    assert client.post(
        "/api/scripts",
        headers={"X-CSRF-Token": admin_csrf},
        json={"title": "空正文", "body": "\n\t "},
    ).status_code == 422

    created = create_script(
        client,
        admin_csrf,
        title="待编辑",
        body="原正文",
    )
    script_id = created["id"]
    assert client.patch(
        f"/api/scripts/{script_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={},
    ).status_code == 422
    assert client.patch(
        f"/api/scripts/{script_id}",
        json={"title": "没有 CSRF"},
    ).status_code == 403
    assert client.delete(f"/api/scripts/{script_id}").status_code == 403

    deleted = client.delete(
        f"/api/scripts/{script_id}",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get(f"/api/scripts/{script_id}").status_code == 404
    assert client.patch(
        f"/api/scripts/{script_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"title": "不存在"},
    ).status_code == 404
    assert client.delete(
        f"/api/scripts/{script_id}",
        headers={"X-CSRF-Token": admin_csrf},
    ).status_code == 404

    logout(client, admin_csrf)
    no_access_csrf = login(
        client,
        "no-script-access",
        "no-script-access-password-123",
    )
    assert client.get("/api/scripts").status_code == 403
    assert client.get("/api/scripts/not-found").status_code == 403
    assert client.post(
        "/api/scripts",
        headers={"X-CSRF-Token": no_access_csrf},
        json={"title": "越权", "body": "正文"},
    ).status_code == 403
    logout(client, no_access_csrf)


def test_script_search_ranking_pagination_and_literal_wildcards(
    client: TestClient,
):
    csrf = login(client, "admin", "admin-password-123")
    title_match = create_script(
        client,
        csrf,
        title="增长方法",
        body="普通正文",
    )
    body_match = create_script(
        client,
        csrf,
        title="最新发布",
        body="正文中讲解增长方法以及案例",
    )
    both_match = create_script(
        client,
        csrf,
        title="增长方法进阶",
        body="再次出现增长方法",
    )

    result = client.get(
        "/api/scripts",
        params={"q": "增长方法", "limit": 2, "offset": 0},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 0
    assert [item["id"] for item in payload["items"]] == [
        both_match["id"],
        title_match["id"],
    ]
    assert payload["items"][0]["matched_in"] == ["title", "body"]

    second_page = client.get(
        "/api/scripts",
        params={"q": "增长方法", "limit": 2, "offset": 2},
    ).json()
    assert [item["id"] for item in second_page["items"]] == [body_match["id"]]
    assert second_page["items"][0]["matched_in"] == ["body"]
    assert "增长方法" in second_page["items"][0]["excerpt"]

    percent = create_script(
        client,
        csrf,
        title="完成度",
        body="当前已经完成 100% 的内容",
    )
    create_script(
        client,
        csrf,
        title="相似但不是百分号",
        body="当前已经完成 100X 的内容",
    )
    underscore = create_script(
        client,
        csrf,
        title="下划线",
        body="变量名是 item_name",
    )
    backslash = create_script(
        client,
        csrf,
        title="路径",
        body=r"保存位置是 C:\scripts",
    )
    assert [
        item["id"]
        for item in client.get("/api/scripts", params={"q": "100%"}).json()["items"]
    ] == [percent["id"]]
    assert [
        item["id"]
        for item in client.get("/api/scripts", params={"q": "item_"}).json()["items"]
    ] == [underscore["id"]]
    assert [
        item["id"]
        for item in client.get("/api/scripts", params={"q": "C:\\"}).json()["items"]
    ] == [backslash["id"]]
    logout(client, csrf)


def test_script_limits_and_missing_authentication(client: TestClient):
    client.cookies.clear()
    assert client.get("/api/scripts").status_code == 401
    csrf = login(client, "admin", "admin-password-123")
    assert client.get("/api/scripts", params={"limit": 0}).status_code == 422
    assert client.get("/api/scripts", params={"limit": 101}).status_code == 422
    assert client.get("/api/scripts", params={"offset": -1}).status_code == 422
    assert client.post(
        "/api/scripts",
        headers={"X-CSRF-Token": csrf},
        json={"title": "a" * 256, "body": "正文"},
    ).status_code == 422
    assert client.post(
        "/api/scripts",
        headers={"X-CSRF-Token": csrf},
        json={"title": "标题", "body": "a" * 30_001},
    ).status_code == 422
    logout(client, csrf)


def test_long_search_keyword_is_preserved_in_excerpt(client: TestClient):
    csrf = login(client, "admin", "admin-password-123")
    keyword = "长" * 200
    created = create_script(
        client,
        csrf,
        title="长关键词测试",
        body=f"开头内容{keyword}结尾内容",
    )

    response = client.get("/api/scripts", params={"q": keyword})

    assert response.status_code == 200, response.text
    item = next(
        value for value in response.json()["items"] if value["id"] == created["id"]
    )
    assert keyword in item["excerpt"]
    assert item["matched_in"] == ["body"]
    logout(client, csrf)
