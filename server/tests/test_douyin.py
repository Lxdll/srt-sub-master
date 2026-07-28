from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from douyin_engine import (
    DouyinEngine,
    DouyinError,
    ParseResult,
    Quality,
    SelfHostedProvider,
    TicketStore,
    build_download_filename,
    extract_aweme_id,
    extract_share_url,
)
from server.app.douyin import douyin_service
from server.tests.conftest import login


VIDEO_URL = "https://www.douyin.com/video/7372484719365098803"
CDN_URL = "https://v5-se.douyinvod.com/video/test.mp4"


def parsed_result(provider: str = "self_hosted") -> ParseResult:
    return ParseResult(
        original_url=VIDEO_URL,
        aweme_id="7372484719365098803",
        title="测试视频",
        author="测试作者",
        cover_url="https://p3.douyinpic.com/test.webp",
        duration_ms=12_300,
        qualities=(
            Quality(
                id="1080p",
                label="1080P",
                width=1080,
                height=1920,
                bitrate=2_000_000,
                estimated_bytes=3_000_000,
                source_urls=(CDN_URL,),
            ),
        ),
        provider=provider,
    )


def test_extract_url_id_and_safe_filename():
    share = f"3.21 复制打开抖音 {VIDEO_URL} 一起看看"
    assert extract_share_url(share) == VIDEO_URL
    assert extract_aweme_id(VIDEO_URL) == "7372484719365098803"
    assert (
        build_download_filename("作/者", "标:题", "7372484719365098803", "1080P")
        == "作_者_标_题_7372484719365098803_1080P.mp4"
    )
    with pytest.raises(DouyinError, match="只支持抖音"):
        extract_share_url("https://example.com/video/7372484719365098803")


def test_ticket_is_bound_to_owner_and_expires():
    store = TicketStore(ttl_seconds=600)
    ticket, _ = store.create("alice", parsed_result())
    assert store.get(ticket, "alice").result.aweme_id == "7372484719365098803"
    with pytest.raises(DouyinError, match="无效或已过期"):
        store.get(ticket, "bob")
    store._records[ticket] = store._records[ticket].__class__(
        owner_id="alice",
        result=parsed_result(),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(DouyinError, match="无效或已过期"):
        store.get(ticket, "alice")


@pytest.mark.asyncio
async def test_self_hosted_provider_normalizes_quality():
    payload = {
        "status_code": 0,
        "aweme_detail": {
            "aweme_id": "7372484719365098803",
            "desc": "测试视频",
            "author": {"nickname": "测试作者"},
            "video": {
                "duration": 12300,
                "cover": {"url_list": ["https://p3.douyinpic.com/test.webp"]},
                "bit_rate": [
                    {
                        "bit_rate": 2000000,
                        "play_addr": {
                            "width": 1080,
                            "height": 1920,
                            "data_size": 3000000,
                            "url_list": [CDN_URL],
                        },
                    }
                ],
            },
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.douyin.com"
        assert request.url.params.get("X-Bogus")
        return httpx.Response(200, json=payload)

    provider = SelfHostedProvider(transport=httpx.MockTransport(handler))
    result = await provider.parse(VIDEO_URL, "7372484719365098803")
    assert result.title == "测试视频"
    assert result.qualities[0].id == "1080p"
    assert result.qualities[0].estimated_bytes == 3_000_000


@pytest.mark.asyncio
async def test_engine_falls_back_without_repeating_risk_error():
    class Failing:
        name = "primary"

        async def parse(self, url: str, aweme_id: str) -> ParseResult:
            raise DouyinError("session", code="SESSION_REQUIRED", retryable=False)

    class Working:
        name = "fallback"

        async def parse(self, url: str, aweme_id: str) -> ParseResult:
            return parsed_result("fallback")

    engine = DouyinEngine(
        [Failing(), Working()],
        minimum_interval_seconds=0,
    )
    result = await engine.parse(VIDEO_URL)
    assert result.provider == "fallback"
    assert engine.metrics["primary_attempts"] == 1
    assert engine.metrics["fallbacks"] == 1


@pytest.mark.asyncio
async def test_engine_invalidate_forces_fresh_media_urls():
    calls = 0

    class RotatingProvider:
        name = "primary"

        async def parse(self, url: str, aweme_id: str) -> ParseResult:
            nonlocal calls
            calls += 1
            result = parsed_result()
            quality = result.qualities[0]
            return ParseResult(
                original_url=result.original_url,
                aweme_id=result.aweme_id,
                title=result.title,
                author=result.author,
                cover_url=result.cover_url,
                duration_ms=result.duration_ms,
                qualities=(
                    Quality(
                        id=quality.id,
                        label=quality.label,
                        width=quality.width,
                        height=quality.height,
                        bitrate=quality.bitrate,
                        estimated_bytes=quality.estimated_bytes,
                        source_urls=(f"{CDN_URL}?generation={calls}",),
                    ),
                ),
                provider=result.provider,
            )

    engine = DouyinEngine([RotatingProvider()], minimum_interval_seconds=0)
    first = await engine.parse(VIDEO_URL)
    cached = await engine.parse(VIDEO_URL)
    assert cached.qualities[0].source_urls == first.qualities[0].source_urls
    assert calls == 1

    engine.invalidate(first.aweme_id)
    refreshed = await engine.parse(VIDEO_URL)
    assert refreshed.qualities[0].source_urls != first.qualities[0].source_urls
    assert calls == 2


def test_parse_endpoint_and_range_stream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    csrf = login(client, "admin", "admin-password-123")

    async def fake_parse(_: str) -> ParseResult:
        return parsed_result()

    monkeypatch.setattr(douyin_service.engine, "parse", fake_parse)
    response = client.post(
        "/api/douyin/parse",
        headers={"X-CSRF-Token": csrf},
        json={"text": VIDEO_URL},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recommended_quality"] == "1080p"
    assert "source_urls" not in response.text

    def stream_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("range") == "bytes=0-3"
        return httpx.Response(
            206,
            content=b"\x00\x00\x00\x18",
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": "4",
                "Content-Range": "bytes 0-3/24",
                "Accept-Ranges": "bytes",
            },
        )

    old_client = douyin_service._client
    douyin_service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(stream_handler)
    )
    try:
        downloaded = client.get(
            f"/api/douyin/download/{body['ticket']}?quality=1080p",
            headers={"Range": "bytes=0-3"},
        )
        previewed = client.get(
            f"/api/douyin/preview/{body['ticket']}?quality=1080p",
            headers={"Range": "bytes=0-3"},
        )
    finally:
        asyncio.run(douyin_service._client.aclose())
        douyin_service._client = old_client
    assert downloaded.status_code == 206
    assert downloaded.content == b"\x00\x00\x00\x18"
    assert downloaded.headers["content-range"] == "bytes 0-3/24"
    assert "filename*=UTF-8" in downloaded.headers["content-disposition"]
    assert previewed.status_code == 206
    assert previewed.content == b"\x00\x00\x00\x18"
    assert "content-disposition" not in previewed.headers


def test_admin_status_requires_admin(client: TestClient):
    csrf = login(client, "admin", "admin-password-123")
    created = client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": csrf},
        json={"username": "viewer", "password": "viewer-password-123"},
    )
    if created.status_code not in {200, 409}:
        pytest.fail(created.text)
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    login(client, "viewer", "viewer-password-123")
    assert client.get("/api/admin/douyin/status").status_code == 403
