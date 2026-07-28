from __future__ import annotations

from dataclasses import replace
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app.prohibited_words import (
    ModelCandidate,
    ProhibitedWordService,
    ProhibitedWordsError,
    _extract_json,
    _find_occurrences,
    prohibited_word_service,
)
from server.app.config import settings
from server.tests.conftest import login


def create_user(
    client: TestClient,
    *,
    permissions: list[str],
) -> tuple[str, str, str]:
    admin_csrf = login(client, "admin", "admin-password-123")
    username = f"words-{uuid4().hex[:10]}"
    password = "password-123"
    response = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "username": username,
            "password": password,
            "permissions": permissions,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"], username, password


def test_custom_word_crud_permissions_and_user_isolation(client: TestClient):
    _, username, password = create_user(
        client,
        permissions=["prohibited_word_check"],
    )
    csrf = login(client, username, password)
    headers = {"X-CSRF-Token": csrf}

    added = client.post(
        "/api/prohibited-words/custom",
        headers=headers,
        json={"term": "  Vx  "},
    )
    assert added.status_code == 201, added.text
    word = added.json()
    assert word["term"] == "Vx"

    duplicate = client.post(
        "/api/prohibited-words/custom",
        headers=headers,
        json={"term": "vx"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/prohibited-words/custom", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == [word]

    _, other_username, other_password = create_user(
        client,
        permissions=["prohibited_word_check"],
    )
    other_csrf = login(client, other_username, other_password)
    denied_delete = client.delete(
        f"/api/prohibited-words/custom/{word['id']}",
        headers={"X-CSRF-Token": other_csrf},
    )
    assert denied_delete.status_code == 404

    csrf = login(client, username, password)
    deleted = client.delete(
        f"/api/prohibited-words/custom/{word['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

    _, blocked_username, blocked_password = create_user(client, permissions=[])
    blocked_csrf = login(client, blocked_username, blocked_password)
    blocked = client.get(
        "/api/prohibited-words/custom",
        headers={"X-CSRF-Token": blocked_csrf},
    )
    assert blocked.status_code == 403


def test_check_merges_sources_and_rejects_hallucinated_terms(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    _, username, password = create_user(
        client,
        permissions=["prohibited_word_check"],
    )
    csrf = login(client, username, password)
    headers = {"X-CSRF-Token": csrf}
    added = client.post(
        "/api/prohibited-words/custom",
        headers=headers,
        json={"term": "加微信"},
    )
    assert added.status_code == 201

    async def candidates(_: str) -> list[ModelCandidate]:
        return [
            ModelCandidate("加微信", "引流导流", "可能引导用户转移到站外"),
            ModelCandidate("微信", "引流导流", "包含外部联系方式"),
            ModelCandidate("稳赚不赔", "诈骗违法", "包含绝对收益承诺"),
            ModelCandidate("原文不存在", "其他社交风险", "模型幻觉"),
        ]

    monkeypatch.setattr(prohibited_word_service, "_request_candidates", candidates)
    response = client.post(
        "/api/prohibited-words/check",
        headers=headers,
        json={"text": "加微信即可稳赚不赔，加微信。"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["unique_term_count"] == 3
    assert payload["match_count"] == 5
    assert [item["term"] for item in payload["matches"]] == [
        "加微信",
        "微信",
        "稳赚不赔",
    ]
    assert payload["matches"][0]["sources"] == ["ai", "custom"]
    assert payload["matches"][0]["occurrences"] == [
        {"start": 0, "end": 3},
        {"start": 10, "end": 13},
    ]


def test_check_reports_model_configuration_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    admin_csrf = login(client, "admin", "admin-password-123")

    async def unavailable(_: str) -> list[ModelCandidate]:
        raise ProhibitedWordsError(503, "违禁词检测模型尚未配置")

    monkeypatch.setattr(prohibited_word_service, "_request_candidates", unavailable)
    response = client.post(
        "/api/prohibited-words/check",
        headers={"X-CSRF-Token": admin_csrf},
        json={"text": "测试文本"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "违禁词检测模型尚未配置"


def test_check_validation_and_model_json_parser(client: TestClient):
    admin_csrf = login(client, "admin", "admin-password-123")
    headers = {"X-CSRF-Token": admin_csrf}
    blank = client.post(
        "/api/prohibited-words/check",
        headers=headers,
        json={"text": "   "},
    )
    assert blank.status_code == 422

    too_long = client.post(
        "/api/prohibited-words/check",
        headers=headers,
        json={"text": "字" * 20_001},
    )
    assert too_long.status_code == 422

    assert _extract_json('```json\n{"matches":[]}\n```') == {"matches": []}
    assert _find_occurrences("😀加微信", "加微信") == [{"start": 2, "end": 5}]
    with pytest.raises(ProhibitedWordsError):
        _extract_json("not-json")


@pytest.mark.asyncio
async def test_openai_compatible_request_and_response_parsing():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert "response_format" not in payload
        assert "enable_thinking" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"matches":[{"term":"加微信",'
                                '"category":"引流导流","reason":"站外导流"}]}'
                                "\n```"
                            )
                        }
                    }
                ]
            },
        )

    config = replace(
        settings,
        moderation_api_base="https://model.test/v1",
        moderation_api_key="test-key",
        moderation_model="test-model",
    )
    service = ProhibitedWordService(config, httpx.MockTransport(handler))
    candidates = await service._request_candidates("加微信")
    assert candidates == [ModelCandidate("加微信", "引流导流", "站外导流")]


@pytest.mark.asyncio
async def test_alibaba_model_studio_uses_non_thinking_json_mode():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["enable_thinking"] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"matches":[{"term":"私下交易",'
                                '"category":"交易营销","reason":"存在交易风险"}]}'
                            )
                        }
                    }
                ]
            },
        )

    config = replace(
        settings,
        moderation_api_base=(
            "https://workspace.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1"
        ),
        moderation_api_key="test-key",
        moderation_model="qwen-plus",
    )
    service = ProhibitedWordService(config, httpx.MockTransport(handler))
    candidates = await service._request_candidates("请私下交易")
    assert candidates == [
        ModelCandidate("私下交易", "交易营销", "存在交易风险")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_status", "expected_status"),
    [(500, 502), (408, 502)],
)
async def test_model_http_failures_are_not_reported_as_safe(
    response_status: int,
    expected_status: int,
):
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(response_status)

    config = replace(
        settings,
        moderation_api_base="https://model.test/v1",
        moderation_api_key="test-key",
        moderation_model="test-model",
    )
    service = ProhibitedWordService(config, httpx.MockTransport(handler))
    with pytest.raises(ProhibitedWordsError) as error:
        await service.check("测试文本", [])
    assert error.value.status_code == expected_status


@pytest.mark.asyncio
async def test_model_timeout_is_reported_as_gateway_timeout():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow model", request=request)

    config = replace(
        settings,
        moderation_api_base="https://model.test/v1",
        moderation_api_key="test-key",
        moderation_model="test-model",
    )
    service = ProhibitedWordService(config, httpx.MockTransport(handler))
    with pytest.raises(ProhibitedWordsError) as error:
        await service.check("测试文本", [])
    assert error.value.status_code == 504
