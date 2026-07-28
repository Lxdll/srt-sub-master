from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urljoin, urlparse

import httpx

from douyin_engine import (
    BhwaProvider,
    DouyinEngine,
    DouyinError,
    ParseResult,
    Quality,
    SelfHostedProvider,
    TicketRecord,
    TicketStore,
    build_download_filename,
)
from douyin_engine.core import (
    DEFAULT_USER_AGENT,
    UserRateLimiter,
    is_media_url_allowed,
)

from .config import settings


@dataclass
class DownloadStream:
    response: httpx.Response
    filename: str
    permit: "DownloadPermit"

    async def body(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.response.aiter_bytes(1024 * 256):
                yield chunk
        finally:
            await self.response.aclose()
            await self.permit.release()


class DownloadPermit:
    def __init__(self, service: "DouyinService", user_id: str) -> None:
        self.service = service
        self.user_id = user_id
        self.released = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        async with self.service._download_lock:
            self.service._user_downloads[self.user_id] = max(
                0, self.service._user_downloads.get(self.user_id, 1) - 1
            )
        self.service._download_slots.release()


class DouyinService:
    def __init__(self) -> None:
        self.self_hosted = SelfHostedProvider(
            cookie=settings.douyin_cookie,
            cookie_file=settings.douyin_cookie_file,
        )
        self.bhwa = BhwaProvider(settings.bhwa_api_base)
        self.engine = DouyinEngine([self.self_hosted, self.bhwa])
        self.tickets = TicketStore(ttl_seconds=600)
        self.rate_limiter = UserRateLimiter(limit=10, window_seconds=60)
        self._download_slots = asyncio.Semaphore(4)
        self._download_lock = asyncio.Lock()
        self._user_downloads: dict[str, int] = {}
        self._client = httpx.AsyncClient(timeout=60, follow_redirects=False)
        self.download_metrics: dict[str, int] = {
            "started": 0,
            "failed": 0,
            "refreshed": 0,
        }

    async def close(self) -> None:
        await self._client.aclose()

    def ensure_access(self, user: dict[str, Any]) -> None:
        if not settings.douyin_enabled:
            raise DouyinError(
                "抖音下载功能尚未启用。",
                code="FEATURE_DISABLED",
                status_code=404,
            )

    async def parse(self, user: dict[str, Any], text: str) -> dict[str, Any]:
        result = await self.resolve(user, text)
        ticket, expires = self.tickets.create(user["id"], result)
        return self._public_result(ticket, expires.isoformat(), result)

    async def resolve(self, user: dict[str, Any], text: str) -> ParseResult:
        self.ensure_access(user)
        self.rate_limiter.check(user["id"])
        return await self.engine.parse(text)

    async def open_result_source(
        self,
        result: ParseResult,
        quality: Quality,
        range_header: str | None = None,
    ) -> httpx.Response:
        return await self._open_source(result, quality, range_header)

    @staticmethod
    def _public_result(
        ticket: str, expires_at: str, result: ParseResult
    ) -> dict[str, Any]:
        return {
            "ticket": ticket,
            "aweme_id": result.aweme_id,
            "title": result.title,
            "author": result.author,
            "cover_url": result.cover_url,
            "duration_ms": result.duration_ms,
            "qualities": [item.public_dict() for item in result.qualities],
            "recommended_quality": result.recommended_quality,
            "expires_at": expires_at,
        }

    @staticmethod
    def _quality(record: TicketRecord, quality_id: str | None) -> Quality:
        requested = quality_id or record.result.recommended_quality
        for quality in record.result.qualities:
            if quality.id == requested:
                return quality
        raise DouyinError(
            "所选画质已不可用，请重新解析。",
            code="QUALITY_NOT_FOUND",
            status_code=404,
        )

    async def _acquire_permit(self, user_id: str) -> DownloadPermit:
        async with self._download_lock:
            if self._user_downloads.get(user_id, 0) >= 2:
                raise DouyinError(
                    "当前账号已有两个下载任务，请等待其中一个完成。",
                    code="DOWNLOAD_LIMITED",
                    status_code=429,
                )
            self._user_downloads[user_id] = self._user_downloads.get(user_id, 0) + 1
        try:
            await self._download_slots.acquire()
        except BaseException:
            async with self._download_lock:
                self._user_downloads[user_id] = max(
                    0, self._user_downloads.get(user_id, 1) - 1
                )
            raise
        return DownloadPermit(self, user_id)

    def _extra_allowed_hosts(self, result: ParseResult) -> set[str]:
        if result.provider != "bhwa":
            return set()
        host = urlparse(settings.bhwa_api_base).hostname
        return {host.lower()} if host else set()

    async def _open_source(
        self,
        result: ParseResult,
        quality: Quality,
        range_header: str | None,
    ) -> httpx.Response:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": "https://www.douyin.com/",
            "Accept": "*/*",
        }
        if range_header:
            headers["Range"] = range_header
        extra_hosts = self._extra_allowed_hosts(result)
        for source in quality.source_urls:
            current = source
            for _ in range(4):
                if not is_media_url_allowed(current, extra_hosts):
                    break
                request = self._client.build_request("GET", current, headers=headers)
                response = await self._client.send(request, stream=True)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        break
                    current = urljoin(current, location)
                    continue
                if response.status_code in {200, 206}:
                    return response
                await response.aclose()
                break
        raise DouyinError(
            "视频源已经失效，请重新解析后再试。",
            code="VIDEO_SOURCE_EXPIRED",
            status_code=502,
        )

    async def open_download(
        self,
        user: dict[str, Any],
        ticket: str,
        quality_id: str | None,
        range_header: str | None,
    ) -> DownloadStream:
        self.ensure_access(user)
        record = self.tickets.get(ticket, user["id"])
        permit = await self._acquire_permit(user["id"])
        try:
            quality = self._quality(record, quality_id)
            try:
                response = await self._open_source(
                    record.result, quality, range_header
                )
            except DouyinError:
                self.download_metrics["refreshed"] += 1
                self.engine.invalidate(record.result.aweme_id)
                refreshed = await self.engine.parse(record.result.original_url)
                self.tickets.replace_result(ticket, user["id"], refreshed)
                record = self.tickets.get(ticket, user["id"])
                quality = self._quality(record, quality_id)
                response = await self._open_source(
                    record.result, quality, range_header
                )
            filename = build_download_filename(
                record.result.author,
                record.result.title,
                record.result.aweme_id,
                quality.label,
            )
            self.download_metrics["started"] += 1
            return DownloadStream(response=response, filename=filename, permit=permit)
        except Exception:
            self.download_metrics["failed"] += 1
            await permit.release()
            raise

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.douyin_enabled,
            "access": settings.douyin_access,
            **self.engine.status(),
            "downloads": {
                **self.download_metrics,
                "active": sum(self._user_downloads.values()),
            },
        }


douyin_service = DouyinService()
