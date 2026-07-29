from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app.config import settings
from server.app.script_analysis import (
    ScriptAnalysisError,
    ScriptAnalysisService,
    _extract_json,
    _normalize_result,
    script_analysis_service,
)
from server.tests.conftest import login

SCRIPT = "你知道为什么大多数人坚持不下来吗？因为他们一开始就把目标定得太大。先从每天五分钟开始。"


def model_result(*, excerpt: str = "你知道为什么大多数人坚持不下来吗？"):
    return {
        "highlights": [
            {
                "excerpt": excerpt,
                "reason": "问题具有普遍共鸣。",
                "leverage": "保留反问，并尽快接上答案。",
            }
        ],
        "hooks": [
            {
                "excerpt": excerpt,
                "hook_type": "问题",
                "position": "开场",
                "mechanism": "激发观众寻找答案。",
                "strength": "强",
                "suggestion": "压缩停顿后立即给出反差答案。",
            }
        ],
        "suggestions": [
            {
                "area": "行动引导",
                "issue": "结尾缺少互动。",
                "recommendation": "邀请观众留言自己的五分钟目标。",
            }
        ],
    }


def create_user(
    client: TestClient,
    permissions: list[str],
) -> tuple[str, str]:
    admin_csrf = login(client, "admin", "admin-password-123")
    username = f"script-{uuid4().hex[:10]}"
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
    return username, password


def test_script_analysis_permission_validation_and_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    username, password = create_user(client, ["script_analysis"])
    csrf = login(client, username, password)

    async def analyze(script: str, context: dict[str, object]):
        assert script == SCRIPT
        assert context == {
            "platform": "抖音",
            "audience": "习惯养成新手",
            "target_duration_seconds": 30,
            "goal": "提高收藏",
        }
        return model_result()

    monkeypatch.setattr(script_analysis_service, "analyze", analyze)
    response = client.post(
        "/api/script-analysis/analyze",
        headers={"X-CSRF-Token": csrf},
        json={
            "text": SCRIPT,
            "platform": "抖音",
            "audience": "习惯养成新手",
            "target_duration_seconds": 30,
            "goal": "提高收藏",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["highlights"][0]["reason"] == "问题具有普遍共鸣。"
    assert set(response.json()) == {"highlights", "hooks", "suggestions"}

    blank = client.post(
        "/api/script-analysis/analyze",
        headers={"X-CSRF-Token": csrf},
        json={"text": "   "},
    )
    assert blank.status_code == 422

    too_long = client.post(
        "/api/script-analysis/analyze",
        headers={"X-CSRF-Token": csrf},
        json={"text": "字" * 30_001},
    )
    assert too_long.status_code == 422

    invalid_duration = client.post(
        "/api/script-analysis/analyze",
        headers={"X-CSRF-Token": csrf},
        json={"text": SCRIPT, "target_duration_seconds": 0},
    )
    assert invalid_duration.status_code == 422

    blocked_username, blocked_password = create_user(client, [])
    blocked_csrf = login(client, blocked_username, blocked_password)
    blocked = client.post(
        "/api/script-analysis/analyze",
        headers={"X-CSRF-Token": blocked_csrf},
        json={"text": SCRIPT},
    )
    assert blocked.status_code == 403


def test_normalization_drops_hallucinated_excerpts():
    parsed = model_result(excerpt="原文中不存在的句子")
    normalized = _normalize_result(SCRIPT, parsed)
    assert normalized["highlights"] == []
    assert normalized["hooks"] == []
    assert normalized["suggestions"][0]["area"] == "行动引导"


def test_json_parser_accepts_fences_missing_fields_and_empty_arrays():
    payload = model_result()
    assert _extract_json(f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```")[
        "highlights"
    ][0]["reason"] == "问题具有普遍共鸣。"
    assert _normalize_result(SCRIPT, _extract_json("{}")) == {
        "highlights": [],
        "hooks": [],
        "suggestions": [],
    }
    assert _normalize_result(
        SCRIPT,
        _extract_json('{"highlights":[],"hooks":[],"suggestions":[]}'),
    ) == {"highlights": [], "hooks": [], "suggestions": []}
    with pytest.raises(ScriptAnalysisError, match="无效"):
        _extract_json('{"highlights":{}}')
    with pytest.raises(ScriptAnalysisError, match="无效"):
        _extract_json('{"hooks":null}')
    with pytest.raises(ScriptAnalysisError, match="无效"):
        _extract_json("[]")
    with pytest.raises(ScriptAnalysisError):
        _extract_json("not-json")


@pytest.mark.asyncio
async def test_openai_compatible_script_analysis_request():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["temperature"] == 0.2
        assert "response_format" not in payload
        assert "<文字脚本>" in payload["messages"][1]["content"]
        assert "画面、拍摄、道具" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(model_result(), ensure_ascii=False)
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
    result = await ScriptAnalysisService(
        config, httpx.MockTransport(handler)
    ).analyze(SCRIPT, {"platform": "抖音"})
    assert result["hooks"][0]["strength"] == "强"


@pytest.mark.asyncio
async def test_alibaba_script_analysis_json_mode_and_timeout():
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
                            "content": json.dumps(model_result(), ensure_ascii=False)
                        }
                    }
                ]
            },
        )

    config = replace(
        settings,
        moderation_api_base=(
            "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        moderation_api_key="test-key",
        moderation_model="qwen-plus",
    )
    result = await ScriptAnalysisService(
        config, httpx.MockTransport(handler)
    ).analyze(SCRIPT, {})
    assert result["highlights"][0]["excerpt"] in SCRIPT

    async def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ScriptAnalysisError, match="超时") as error:
        await ScriptAnalysisService(
            config, httpx.MockTransport(timeout)
        ).analyze(SCRIPT, {})
    assert error.value.status_code == 504


@pytest.mark.asyncio
async def test_script_analysis_uses_its_dedicated_timeout(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, float] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(model_result(), ensure_ascii=False)
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: float, transport: object):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object):
            return None

        async def post(self, *_: object, **__: object) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        "server.app.script_analysis.httpx.AsyncClient",
        FakeClient,
    )
    config = replace(
        settings,
        moderation_api_base="https://model.test/v1",
        moderation_api_key="test-key",
        moderation_model="test-model",
        moderation_timeout_seconds=1,
        script_analysis_timeout_seconds=150,
    )
    await ScriptAnalysisService(config).analyze(SCRIPT, {})
    assert captured["timeout"] == 150


@pytest.mark.asyncio
async def test_streaming_analysis_emits_normalized_semantic_events():
    highlight_line = json.dumps(
        {
            "type": "highlight",
            "data": model_result()["highlights"][0],
        },
        ensure_ascii=False,
    )
    hook_line = json.dumps(
        {"type": "hook", "data": model_result()["hooks"][0]},
        ensure_ascii=False,
    )
    suggestion_line = json.dumps(
        {
            "type": "suggestion",
            "data": model_result()["suggestions"][0],
        },
        ensure_ascii=False,
    )
    chunks = [
        highlight_line[:25],
        highlight_line[25:] + "\n" + hook_line + "\n",
        suggestion_line,
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert "NDJSON" in payload["messages"][0]["content"]
        body = "".join(
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": chunk}}]},
                ensure_ascii=False,
            )
            + "\n\n"
            for chunk in chunks
        )
        body += "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode())

    config = replace(
        settings,
        moderation_api_base="https://model.test/v1",
        moderation_api_key="test-key",
        moderation_model="test-model",
    )
    events = [
        item
        async for item in ScriptAnalysisService(
            config, httpx.MockTransport(handler)
        ).analyze_stream(SCRIPT, {})
    ]

    assert [event for event, _ in events] == [
        "highlight",
        "hook",
        "suggestion",
        "result",
        "done",
    ]
    assert events[0][1]["excerpt"] in SCRIPT
    assert events[-2][1] == model_result()


def test_script_analysis_stream_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    username, password = create_user(client, ["script_analysis"])
    csrf = login(client, username, password)

    async def analyze_stream(script: str, context: dict[str, object]):
        assert script == SCRIPT
        assert context == {}
        yield "highlight", model_result()["highlights"][0]
        yield "result", model_result()
        yield "done", {"ok": True}

    monkeypatch.setattr(script_analysis_service, "analyze_stream", analyze_stream)
    response = client.post(
        "/api/script-analysis/analyze/stream",
        headers={"X-CSRF-Token": csrf},
        json={"text": SCRIPT},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: highlight" in response.text
    assert "event: result" in response.text
    assert "坚持不下来" in response.text


def test_script_analysis_stream_endpoint_serializes_model_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    username, password = create_user(client, ["script_analysis"])
    csrf = login(client, username, password)

    async def analyze_stream(_: str, __: dict[str, object]):
        if False:
            yield "done", {"ok": True}
        raise ScriptAnalysisError(504, "脚本拆解超时，请稍后重试")

    monkeypatch.setattr(script_analysis_service, "analyze_stream", analyze_stream)
    response = client.post(
        "/api/script-analysis/analyze/stream",
        headers={"X-CSRF-Token": csrf},
        json={"text": SCRIPT},
    )
    assert response.status_code == 200, response.text
    assert "event: error" in response.text
    assert '"status_code":504' in response.text
    assert "脚本拆解超时" in response.text
