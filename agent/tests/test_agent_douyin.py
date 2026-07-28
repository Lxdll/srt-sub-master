from __future__ import annotations

# Agent-side contract tests use a distinct module name from server tests.

import asyncio
import httpx
from fastapi.testclient import TestClient
import pytest

from agent.app import main
from agent.app.douyin import local_douyin_service
from douyin_engine import ParseResult, Quality


VIDEO_URL = "https://www.douyin.com/video/7372484719365098803"
CDN_URL = "https://v5-se.douyinvod.com/video/test.mp4"


def result() -> ParseResult:
    return ParseResult(
        original_url=VIDEO_URL,
        aweme_id="7372484719365098803",
        title="本机测试",
        author="本机作者",
        cover_url=None,
        duration_ms=1000,
        qualities=(
            Quality(
                id="720p",
                label="720P",
                width=720,
                height=1280,
                bitrate=1_000_000,
                estimated_bytes=8,
                source_urls=(CDN_URL,),
            ),
        ),
        provider="self_hosted",
    )


def test_local_parse_requires_command_and_returns_safe_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    async def verify(_: str, task_id: str | None = None):
        return {"user_id": "local-user", "task_id": task_id}

    async def parse(_: str) -> ParseResult:
        return result()

    monkeypatch.setattr(main, "_verify_command", verify)
    monkeypatch.setattr(local_douyin_service.engine, "parse", parse)
    response = client.post(
        "/douyin/parse",
        headers={
            "Origin": "http://localhost:5173",
            "X-Command-Token": "valid",
        },
        json={"text": VIDEO_URL},
    )
    assert response.status_code == 200
    assert response.json()["recommended_quality"] == "720p"
    assert "source_urls" not in response.text


def test_local_download_stream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    async def verify(_: str, task_id: str | None = None):
        return {"user_id": "local-user", "task_id": task_id}

    monkeypatch.setattr(main, "_verify_command", verify)
    ticket, _ = local_douyin_service.tickets.create("local-user", result())

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"mp4-data",
            headers={"Content-Type": "video/mp4", "Content-Length": "8"},
        )

    old_client = local_douyin_service.client
    local_douyin_service.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    try:
        response = client.get(
            f"/douyin/download/{ticket}?quality=720p",
            headers={
                "Origin": "http://localhost:5173",
                "X-Command-Token": "valid",
            },
        )
        preview = client.get(
            f"/douyin/preview/{ticket}?quality=720p&command_token=valid",
            headers={"Origin": "http://localhost:5173"},
        )
    finally:
        asyncio.run(local_douyin_service.client.aclose())
        local_douyin_service.client = old_client
    assert response.status_code == 200
    assert response.content == b"mp4-data"
    assert "attachment" in response.headers["content-disposition"]
    assert preview.status_code == 200
    assert preview.content == b"mp4-data"
    assert "content-disposition" not in preview.headers
