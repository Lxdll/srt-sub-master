from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app.config import settings
from server.app.db import db_session, initialize_database
from server.app.hot_ranks import PLATFORMS, HotRankService, hot_rank_service


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def clear_hot_rank_snapshots():
    initialize_database()
    with db_session() as db:
        db.execute("DELETE FROM hot_rank_snapshots")
    yield
    with db_session() as db:
        db.execute("DELETE FROM hot_rank_snapshots")


def _url(platform: str, index: int) -> str:
    if platform == "rednote":
        return f"https://www.xiaohongshu.com/search_result?keyword=item-{index}"
    if platform == "douyin":
        return f"https://www.douyin.com/search/item-{index}"
    return f"https://www.bilibili.com/video/BV{index:010d}"


def _primary_payload(platform: str, count: int = 12) -> dict[str, Any]:
    items = []
    for index in range(1, count + 1):
        item: dict[str, Any] = {
            "title": f"{platform}-title-{index}",
            "link": _url(platform, index),
        }
        if platform == "rednote":
            item.update(
                rank=index,
                score=f"{1000 - index}w",
                word_type="热" if index == 1 else "无",
            )
        else:
            item["hot_value"] = 1000 - index
        items.append(item)
    return {"code": 200, "message": "ok", "data": items}


def _fallback_payload(platform: str, count: int = 12) -> dict[str, Any]:
    items = [
        {
            "index": index,
            "title": f"fallback-{platform}-{index}",
            "url": _url(platform, index + 100),
            "hot_value": str(2000 - index),
            "extra": {"type": "新" if index == 1 else ""},
        }
        for index in range(1, count + 1)
    ]
    return {
        "type": {
            "rednote": "xiaohongshu",
            "douyin": "douyin",
            "bilibili": "bilibili",
        }[platform],
        "update_time": "2026-07-29T04:00:00.000Z",
        "list": items,
    }


def _test_settings(**overrides: Any):
    defaults = {
        "hot_rank_primary_base": "http://primary.test",
        "hot_rank_fallback_base": "https://fallback.test",
        "hot_rank_fallback_api_key": "",
        "hot_rank_timeout_seconds": 1,
        "hot_rank_refresh_seconds": 900,
        "hot_rank_stale_seconds": 86400,
    }
    defaults.update(overrides)
    return replace(settings, **defaults)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform_index", "expected_hot_value", "expected_badge"),
    [
        (0, "999w", "热"),
        (1, "999", None),
        (2, "999", None),
    ],
)
async def test_primary_formats_are_normalised(
    platform_index: int,
    expected_hot_value: str,
    expected_badge: str | None,
):
    platform = PLATFORMS[platform_index]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_primary_payload(platform.key))

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), Clock()
    )
    try:
        items = await service._fetch_source(platform, "60s")
    finally:
        await service.close()

    assert len(items) == 10
    assert [item["rank"] for item in items] == list(range(1, 11))
    assert items[0]["hot_value"] == expected_hot_value
    assert items[0].get("badge") == expected_badge
    assert "cover" not in items[0]


@pytest.mark.asyncio
async def test_primary_success_skips_fallback_and_returns_fixed_order():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        platform = {
            "/v2/rednote": "rednote",
            "/v2/douyin": "douyin",
            "/v2/bili": "bilibili",
        }[request.url.path]
        return httpx.Response(200, json=_primary_payload(platform))

    clock = Clock()
    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), clock
    )
    try:
        result = await service.get_hot_ranks()
    finally:
        await service.close()

    assert calls == ["/v2/rednote", "/v2/douyin", "/v2/bili"]
    assert [item["platform"] for item in result["platforms"]] == [
        "rednote",
        "douyin",
        "bilibili",
    ]
    assert all(item["status"] == "fresh" for item in result["platforms"])
    assert all(item["source"] == "60s" for item in result["platforms"])
    assert all(len(item["items"]) == 10 for item in result["platforms"])


@pytest.mark.asyncio
async def test_one_platform_failure_does_not_hide_other_platforms():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/rednote" or (
            request.url.path == "/api/v1/misc/hotboard"
            and request.url.params["type"] == "xiaohongshu"
        ):
            return httpx.Response(500)
        if request.url.path == "/v2/douyin":
            return httpx.Response(200, json=_primary_payload("douyin"))
        if request.url.path == "/v2/bili":
            return httpx.Response(200, json=_primary_payload("bilibili"))
        raise AssertionError(f"unexpected request: {request.url}")

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), Clock()
    )
    try:
        result = await service.get_hot_ranks()
    finally:
        await service.close()

    assert [platform["status"] for platform in result["platforms"]] == [
        "unavailable",
        "fresh",
        "fresh",
    ]
    assert result["platforms"][0]["items"] == []
    assert all(
        len(platform["items"]) == 10 for platform in result["platforms"][1:]
    )


@pytest.mark.asyncio
async def test_invalid_and_insufficient_primary_items_use_fallback():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v2/rednote":
            payload = _primary_payload("rednote", 10)
            payload["data"][0]["link"] = "https://xiaohongshu.com.evil.test/item"
            payload["data"][1]["title"] = payload["data"][2]["title"]
            return httpx.Response(200, json=payload)
        assert request.headers["Authorization"] == "Bearer fallback-secret"
        assert request.url.params["type"] == "xiaohongshu"
        return httpx.Response(200, json=_fallback_payload("rednote"))

    service = HotRankService(
        _test_settings(hot_rank_fallback_api_key="fallback-secret"),
        httpx.MockTransport(handler),
        Clock(),
    )
    try:
        result = await service._platform_result(PLATFORMS[0], False)
    finally:
        await service.close()

    assert calls == ["/v2/rednote", "/api/v1/misc/hotboard"]
    assert result["source"] == "uapi"
    assert result["status"] == "fresh"
    assert result["items"][0]["badge"] == "新"
    assert all("evil.test" not in item["url"] for item in result["items"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "primary_response",
    [
        httpx.Response(500),
        httpx.Response(429),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"code": 200, "data": []}),
    ],
)
async def test_primary_errors_switch_to_fallback(primary_response: httpx.Response):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/v2/douyin":
            return primary_response
        return httpx.Response(200, json=_fallback_payload("douyin"))

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), Clock()
    )
    try:
        result = await service._platform_result(PLATFORMS[1], False)
    finally:
        await service.close()

    assert calls == 2
    assert result["source"] == "uapi"


@pytest.mark.asyncio
async def test_timeout_switches_to_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/douyin":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=_fallback_payload("douyin"))

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), Clock()
    )
    try:
        result = await service._platform_result(PLATFORMS[1], False)
    finally:
        await service.close()
    assert result["source"] == "uapi"


@pytest.mark.asyncio
async def test_snapshot_survives_restart_and_expires_after_stale_window():
    clock = Clock()

    def success_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_primary_payload("bilibili"))

    service = HotRankService(
        _test_settings(), httpx.MockTransport(success_handler), clock
    )
    initial = await service._platform_result(PLATFORMS[2], False)
    await service.close()
    assert initial["status"] == "fresh"

    def failure_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    clock.advance(901)
    restarted = HotRankService(
        _test_settings(), httpx.MockTransport(failure_handler), clock
    )
    stale = await restarted._platform_result(PLATFORMS[2], False)
    assert stale["status"] == "stale"
    assert stale["source"] == "60s"
    assert len(stale["items"]) == 10

    clock.advance(86401)
    unavailable = await restarted._platform_result(PLATFORMS[2], False)
    await restarted.close()
    assert unavailable["status"] == "unavailable"
    assert unavailable["source"] is None
    assert unavailable["items"] == []


@pytest.mark.asyncio
async def test_circuit_opens_after_three_failures_and_half_open_retries():
    calls = 0
    clock = Clock()
    recovered = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, recovered
        calls += 1
        if recovered and request.url.path == "/v2/rednote":
            return httpx.Response(200, json=_primary_payload("rednote"))
        return httpx.Response(500)

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), clock
    )
    platform = PLATFORMS[0]
    for _ in range(3):
        assert await service._refresh_platform(platform) is None
    assert calls == 6

    assert await service._refresh_platform(platform) is None
    assert calls == 6

    clock.advance(301)
    recovered = True
    result = await service._refresh_platform(platform)
    assert result is not None
    assert result["source"] == "60s"
    assert calls == 7
    assert service._circuits[("rednote", "60s")].failures == 0
    await service.close()


@pytest.mark.asyncio
async def test_platform_lock_prevents_duplicate_cache_fill():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=_primary_payload("rednote"))

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), Clock()
    )
    try:
        first, second = await asyncio.gather(
            service._platform_result(PLATFORMS[0], False),
            service._platform_result(PLATFORMS[0], False),
        )
    finally:
        await service.close()
    assert calls == 1
    assert first == second


@pytest.mark.asyncio
async def test_manual_refresh_has_sixty_second_cooldown():
    calls = 0
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        platform = {
            "/v2/rednote": "rednote",
            "/v2/douyin": "douyin",
            "/v2/bili": "bilibili",
        }[request.url.path]
        return httpx.Response(200, json=_primary_payload(platform))

    service = HotRankService(
        _test_settings(), httpx.MockTransport(handler), clock
    )
    try:
        await service.get_hot_ranks()
        assert calls == 3
        await service.get_hot_ranks(refresh=True)
        assert calls == 6
        await service.get_hot_ranks(refresh=True)
        assert calls == 6
        clock.advance(60)
        await service.get_hot_ranks(refresh=True)
        assert calls == 9
    finally:
        await service.close()


def test_hot_rank_endpoint_requires_login_and_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    client.cookies.clear()
    assert client.get("/api/hot-ranks").status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin-password-123"},
    )
    assert login.status_code == 200

    async def unavailable(refresh: bool = False) -> dict[str, Any]:
        assert refresh is True
        return {
            "generated_at": "2026-07-29T04:00:00+00:00",
            "platforms": [
                {
                    "platform": platform.key,
                    "display_name": platform.display_name,
                    "status": "unavailable",
                    "source": None,
                    "updated_at": None,
                    "items": [],
                }
                for platform in PLATFORMS
            ],
        }

    monkeypatch.setattr(hot_rank_service, "get_hot_ranks", unavailable)
    response = client.get("/api/hot-ranks?refresh=true")
    assert response.status_code == 503
    assert [
        platform["platform"] for platform in response.json()["platforms"]
    ] == ["rednote", "douyin", "bilibili"]

    async def partially_available(refresh: bool = False) -> dict[str, Any]:
        result = await unavailable(refresh)
        result["platforms"][1] = {
            "platform": "douyin",
            "display_name": "抖音",
            "status": "fresh",
            "source": "60s",
            "updated_at": "2026-07-29T04:00:00+00:00",
            "items": _primary_payload("douyin")["data"][:10],
        }
        for rank, item in enumerate(result["platforms"][1]["items"], start=1):
            item["rank"] = rank
            item["url"] = item.pop("link")
            item["hot_value"] = str(item["hot_value"])
        return result

    monkeypatch.setattr(
        hot_rank_service, "get_hot_ranks", partially_available
    )
    response = client.get("/api/hot-ranks?refresh=true")
    assert response.status_code == 200
