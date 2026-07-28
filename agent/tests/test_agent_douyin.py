from __future__ import annotations

# Agent-side contract tests use a distinct module name from server tests.
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.app import main, remote_douyin, transcriber
from agent.app.config import save_state
from agent.app.db import initialize_database
from agent.app import douyin as agent_douyin
from agent.app.douyin import local_douyin_service
from douyin_engine import DouyinError, ParseResult, Quality

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


def test_remote_claim_uses_only_server_authorized_media_sources():
    quality = remote_douyin._authorized_quality(
        {
            "source_urls": [CDN_URL],
            "expected_size_bytes": 8,
        }
    )
    assert quality is not None
    assert quality.source_urls == (CDN_URL,)
    assert quality.estimated_bytes == 8

    with pytest.raises(RuntimeError, match="授权的视频来源无效"):
        remote_douyin._authorized_quality(
            {
                "source_urls": ["https://example.com/private.mp4"],
                "expected_size_bytes": 8,
            }
        )

    proxy_url = "https://downloader-api.bhwa233.com/api/download?video=1"
    proxy_quality = remote_douyin._authorized_quality(
        {
            "source_urls": [proxy_url],
            "authorized_source_hosts": ["downloader-api.bhwa233.com"],
            "expected_size_bytes": 0,
        }
    )
    assert proxy_quality is not None
    assert proxy_quality.source_urls == (proxy_url,)


def test_agent_reports_download_metrics(monkeypatch: pytest.MonkeyPatch):
    initialize_database()
    reported: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reported.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    def server_client():
        return (
            httpx.Client(
                base_url="https://subtitles.test",
                transport=httpx.MockTransport(handler),
            ),
            {},
        )

    monkeypatch.setattr(transcriber, "_server_client", server_client)
    transcriber._progress(
        "task-download",
        "downloading",
        8,
        downloaded_bytes=500_000,
        download_total_bytes=2_000_000,
        download_speed_bps=250_000,
        download_eta_seconds=6,
    )
    assert reported == [
        {
            "status": "downloading",
            "progress": 8,
            "error": None,
            "downloaded_bytes": 500_000,
            "download_total_bytes": 2_000_000,
            "download_speed_bps": 250_000,
            "download_eta_seconds": 6,
        }
    ]


@pytest.mark.asyncio
async def test_public_redirect_allows_https_cdn_custom_port():
    assert await agent_douyin._public_https_redirect_allowed(
        "https://8.8.8.8:33443/video.mp4"
    )
    assert not await agent_douyin._public_https_redirect_allowed(
        "https://127.0.0.1:33443/video.mp4"
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


@pytest.mark.asyncio
async def test_authorized_source_follows_public_cdn_redirect(
    monkeypatch: pytest.MonkeyPatch,
):
    redirected_url = "https://rotating-edge.example.net/final.mp4"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == CDN_URL:
            return httpx.Response(302, headers={"Location": redirected_url})
        assert str(request.url) == redirected_url
        return httpx.Response(
            206,
            content=b"mp4-data",
            headers={"Content-Type": "video/mp4"},
        )

    async def public_redirect(url: str) -> bool:
        return url == redirected_url

    monkeypatch.setattr(
        agent_douyin,
        "_public_https_redirect_allowed",
        public_redirect,
    )
    old_client = local_douyin_service.client
    local_douyin_service.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    try:
        response = await local_douyin_service.open_authorized_source(
            result().qualities[0]
        )
        assert await response.aread() == b"mp4-data"
        await response.aclose()
    finally:
        await local_douyin_service.client.aclose()
        local_douyin_service.client = old_client


@pytest.mark.asyncio
async def test_authorized_source_rejects_private_or_untrusted_redirect(
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://127.0.0.1/private.mp4"},
        )

    async def reject_redirect(_: str) -> bool:
        return False

    monkeypatch.setattr(
        agent_douyin,
        "_public_https_redirect_allowed",
        reject_redirect,
    )
    old_client = local_douyin_service.client
    local_douyin_service.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(DouyinError, match="不安全"):
            await local_douyin_service.open_authorized_source(
                result().qualities[0]
            )
    finally:
        await local_douyin_service.client.aclose()
        local_douyin_service.client = old_client


@pytest.mark.asyncio
async def test_authorized_sources_probe_and_download_smallest_candidate():
    large_url = "https://v5-se.douyinvod.com/video/large.mp4"
    small_url = "https://v5-se.douyinvod.com/video/small.mp4"
    full_downloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        size = 1_000 if str(request.url) == large_url else 100
        if request.headers.get("range") == "bytes=0-0":
            return httpx.Response(
                206,
                content=b"0",
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-0/{size}",
                },
            )
        full_downloads.append(str(request.url))
        return httpx.Response(
            200,
            content=b"small-video",
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": "11",
            },
        )

    old_client = local_douyin_service.client
    local_douyin_service.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    quality = Quality(
        id="compact",
        label="紧凑来源",
        width=480,
        height=None,
        bitrate=None,
        estimated_bytes=None,
        source_urls=(large_url, small_url),
    )
    try:
        response = await local_douyin_service.open_smallest_authorized_source(
            quality
        )
        assert await response.aread() == b"small-video"
        await response.aclose()
    finally:
        await local_douyin_service.client.aclose()
        local_douyin_service.client = old_client
    assert full_downloads == [small_url]


@pytest.mark.asyncio
async def test_remote_douyin_job_reports_missing_model(
    monkeypatch: pytest.MonkeyPatch,
):
    save_state(
        {
            "server_url": "https://subtitles.test",
            "device_token": "device-token",
            "device_id": "device-1",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/claim-douyin")
        assert request.headers["authorization"] == "Bearer device-token"
        return httpx.Response(
            200,
            json={
                "task_id": "task-1",
                "source_url": VIDEO_URL,
                "aweme_id": "7372484719365098803",
                "original_name": "video.mp4",
                "model_id": "large-v3",
                "expected_size_bytes": 8,
                "expected_duration_ms": 1000,
                "max_source_bytes": 1024,
                "max_duration_ms": 30_000,
                "replayed": False,
            },
        )

    async_client_class = httpx.AsyncClient
    monkeypatch.setattr(
        remote_douyin.httpx,
        "AsyncClient",
        lambda **kwargs: async_client_class(
            transport=httpx.MockTransport(handler),
            base_url=kwargs.get("base_url"),
            headers=kwargs.get("headers"),
        ),
    )
    monkeypatch.setattr(remote_douyin, "model_path", lambda _model_id: None)
    failures: list[str] = []

    async def report(_task_id: str, message: str) -> None:
        failures.append(message)

    monkeypatch.setattr(remote_douyin, "_report_failure", report)
    await remote_douyin.start_remote_douyin_job("task-1", "claim-token-value")
    assert failures == ["本机缺少所选模型，请先下载模型后再重试。"]
