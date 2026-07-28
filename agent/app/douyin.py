from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import socket
from typing import Any, AsyncIterator
from urllib.parse import urljoin, urlparse

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


async def _public_https_redirect_allowed(url: str) -> bool:
    parsed = urlparse(url)
    try:
        port = parsed.port or 443
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not 1 <= port <= 65_535
    ):
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        return False
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError:
            return False
        addresses = list(
            {
                ipaddress.ip_address(record[4][0])
                for record in records
                if record[4]
            }
        )
    return bool(addresses) and all(address.is_global for address in addresses)


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
        unsafe_redirect = False
        rejected_status: int | None = None
        for source in quality.source_urls:
            current = source
            for _ in range(4):
                if current == source:
                    allowed = is_media_url_allowed(current)
                else:
                    allowed = await _public_https_redirect_allowed(current)
                if not allowed:
                    unsafe_redirect = True
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
                    content_type = response.headers.get("content-type", "").lower()
                    if (
                        content_type.startswith("video/")
                        or content_type.startswith("application/octet-stream")
                        or not content_type
                    ):
                        return response
                rejected_status = response.status_code
                await response.aclose()
                break
        if unsafe_redirect:
            raise DouyinError(
                "视频源跳转到了不安全的地址，本机已停止下载。",
                code="UNSAFE_VIDEO_REDIRECT",
                status_code=502,
            )
        if rejected_status in {401, 403, 404, 410}:
            raise DouyinError(
                "本机视频源已经失效，请重新解析。",
                code="VIDEO_SOURCE_EXPIRED",
                status_code=502,
            )
        raise DouyinError(
            "本机暂时无法下载该视频，请稍后重试。",
            code="VIDEO_SOURCE_FAILED",
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

    async def open_result_source(
        self,
        result: ParseResult,
        quality: Quality,
    ) -> httpx.Response:
        return await self._open_source(quality, None)

    async def open_authorized_source(self, quality: Quality) -> httpx.Response:
        if not quality.source_urls or any(
            not is_media_url_allowed(source) for source in quality.source_urls
        ):
            raise DouyinError(
                "服务器授权的视频来源无效。",
                code="INVALID_AUTHORIZED_SOURCE",
                status_code=400,
            )
        return await self._open_source(quality, None)

    async def open_smallest_authorized_source(
        self,
        quality: Quality,
    ) -> httpx.Response:
        if not quality.source_urls or any(
            not is_media_url_allowed(source) for source in quality.source_urls
        ):
            raise DouyinError(
                "服务器授权的视频来源无效。",
                code="INVALID_AUTHORIZED_SOURCE",
                status_code=400,
            )
        measured: list[tuple[int, str]] = []
        unmeasured: list[str] = []
        for source in quality.source_urls:
            candidate = Quality(
                id=quality.id,
                label=quality.label,
                width=quality.width,
                height=quality.height,
                bitrate=quality.bitrate,
                estimated_bytes=quality.estimated_bytes,
                source_urls=(source,),
            )
            try:
                response = await self._open_source(candidate, "bytes=0-0")
            except DouyinError:
                unmeasured.append(source)
                continue
            content_range = response.headers.get("content-range", "")
            total_text = content_range.rsplit("/", 1)[-1] if "/" in content_range else ""
            total = int(total_text) if total_text.isdigit() else 0
            if not total and response.status_code == 200:
                total = int(response.headers.get("content-length") or 0)
            await response.aclose()
            if total:
                measured.append((total, source))
            else:
                unmeasured.append(source)
        ordered_sources = [
            source for _, source in sorted(measured, key=lambda item: item[0])
        ] + unmeasured
        if not ordered_sources:
            return await self._open_source(quality, None)
        selected = Quality(
            id=quality.id,
            label=quality.label,
            width=quality.width,
            height=quality.height,
            bitrate=quality.bitrate,
            estimated_bytes=(
                min(size for size, _ in measured)
                if measured
                else quality.estimated_bytes
            ),
            source_urls=tuple(ordered_sources),
        )
        return await self._open_source(selected, None)


local_douyin_service = LocalDouyinService()
