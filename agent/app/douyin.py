from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import httpx

from douyin_engine import (
    DouyinEngine,
    DouyinError,
    ParseResult,
    Quality,
    SelfHostedProvider,
    TicketStore,
    build_download_filename,
)
from douyin_engine.core import DEFAULT_USER_AGENT, is_media_url_allowed


@dataclass
class LocalDownloadStream:
    response: httpx.Response
    filename: str

    async def body(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.response.aiter_bytes(1024 * 256):
                yield chunk
        finally:
            await self.response.aclose()


class LocalDouyinService:
    def __init__(self) -> None:
        self.engine = DouyinEngine(
            [SelfHostedProvider()],
            cache_ttl_seconds=900,
            minimum_interval_seconds=1,
        )
        self.tickets = TicketStore(ttl_seconds=600)
        self.client = httpx.AsyncClient(timeout=60, follow_redirects=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def parse(self, owner_id: str, text: str) -> dict[str, Any]:
        result = await self.engine.parse(text)
        ticket, expires = self.tickets.create(owner_id, result)
        return {
            "ticket": ticket,
            "aweme_id": result.aweme_id,
            "title": result.title,
            "author": result.author,
            "cover_url": result.cover_url,
            "duration_ms": result.duration_ms,
            "qualities": [quality.public_dict() for quality in result.qualities],
            "recommended_quality": result.recommended_quality,
            "expires_at": expires.isoformat(),
        }

    @staticmethod
    def _quality(result: ParseResult, quality_id: str | None) -> Quality:
        requested = quality_id or result.recommended_quality
        for item in result.qualities:
            if item.id == requested:
                return item
        raise DouyinError(
            "所选画质已不可用，请重新解析。",
            code="QUALITY_NOT_FOUND",
            status_code=404,
        )

    async def _open_source(
        self,
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
        for source in quality.source_urls:
            current = source
            for _ in range(4):
                if not is_media_url_allowed(current):
                    break
                request = self.client.build_request("GET", current, headers=headers)
                response = await self.client.send(request, stream=True)
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
            "本机视频源已经失效，请重新解析。",
            code="VIDEO_SOURCE_EXPIRED",
            status_code=502,
        )

    async def open_download(
        self,
        owner_id: str,
        ticket: str,
        quality_id: str | None,
        range_header: str | None,
    ) -> LocalDownloadStream:
        record = self.tickets.get(ticket, owner_id)
        quality = self._quality(record.result, quality_id)
        try:
            response = await self._open_source(quality, range_header)
        except DouyinError:
            self.engine.invalidate(record.result.aweme_id)
            refreshed = await self.engine.parse(record.result.original_url)
            self.tickets.replace_result(ticket, owner_id, refreshed)
            record = self.tickets.get(ticket, owner_id)
            quality = self._quality(record.result, quality_id)
            response = await self._open_source(quality, range_header)
        return LocalDownloadStream(
            response=response,
            filename=build_download_filename(
                record.result.author,
                record.result.title,
                record.result.aweme_id,
                quality.label,
            ),
        )


local_douyin_service = LocalDouyinService()
