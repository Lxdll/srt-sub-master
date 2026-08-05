from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse

import httpx

from .xbogus import XBogus

SHARE_HOSTS = {
    "douyin.com",
    "www.douyin.com",
    "v.douyin.com",
    "iesdouyin.com",
    "www.iesdouyin.com",
    "v.iesdouyin.com",
}
MEDIA_HOST_SUFFIXES = (
    ".douyinvod.com",
    ".bytecdn.cn",
    ".douyin.com",
    ".snssdk.com",
)
URL_PATTERN = re.compile(r"https?://[^\s<>'\"，。；]+", re.IGNORECASE)
AWEME_PATTERN = re.compile(r"/(?:video|note)/(\d{15,20})(?:/|$)")
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)


class DouyinError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "PARSE_FAILED",
        retryable: bool = False,
        status_code: int = 422,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class Quality:
    id: str
    label: str
    width: int | None
    height: int | None
    bitrate: int | None
    estimated_bytes: int | None
    source_urls: tuple[str, ...] = field(repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "width": self.width,
            "height": self.height,
            "bitrate": self.bitrate,
            "estimated_bytes": self.estimated_bytes,
        }


@dataclass(frozen=True)
class ParseResult:
    original_url: str
    aweme_id: str
    title: str
    author: str
    cover_url: str | None
    duration_ms: int | None
    qualities: tuple[Quality, ...]
    provider: str

    @property
    def recommended_quality(self) -> str:
        return self.qualities[0].id


@dataclass(frozen=True)
class TicketRecord:
    owner_id: str
    result: ParseResult
    expires_at: datetime


class TicketStore:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, TicketRecord] = {}

    def create(self, owner_id: str, result: ParseResult) -> tuple[str, datetime]:
        self._cleanup()
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        self._records[token] = TicketRecord(owner_id, result, expires)
        return token, expires

    def get(self, token: str, owner_id: str) -> TicketRecord:
        self._cleanup()
        record = self._records.get(token)
        if not record or record.owner_id != owner_id:
            raise DouyinError(
                "下载凭证无效或已过期，请重新解析。",
                code="TICKET_INVALID",
                status_code=404,
            )
        return record

    def replace_result(self, token: str, owner_id: str, result: ParseResult) -> None:
        record = self.get(token, owner_id)
        self._records[token] = TicketRecord(
            owner_id=record.owner_id,
            result=result,
            expires_at=record.expires_at,
        )

    def _cleanup(self) -> None:
        now_value = datetime.now(UTC)
        expired = [
            token
            for token, record in self._records.items()
            if record.expires_at <= now_value
        ]
        for token in expired:
            self._records.pop(token, None)


def _hostname_allowed(hostname: str | None, allowed: set[str]) -> bool:
    if not hostname:
        return False
    host = hostname.lower().rstrip(".")
    return host in allowed


def extract_share_url(text: str) -> str:
    match = URL_PATTERN.search(text.strip())
    if not match:
        raise DouyinError("没有找到抖音链接。", code="INVALID_URL", status_code=400)
    url = match.group(0).rstrip(".,;!?)]}")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not _hostname_allowed(
        parsed.hostname, SHARE_HOSTS
    ):
        raise DouyinError(
            "只支持抖音分享链接。", code="INVALID_HOST", status_code=400
        )
    return url


def extract_aweme_id(url: str) -> str | None:
    parsed = urlparse(url)
    match = AWEME_PATTERN.search(parsed.path)
    if match:
        return match.group(1)
    modal_ids = parse_qs(parsed.query).get("modal_id", [])
    if modal_ids and modal_ids[0].isdigit():
        return modal_ids[0]
    return None


def is_media_url_allowed(url: str, extra_hosts: set[str] | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if extra_hosts and host in extra_hosts:
        return True
    return any(host.endswith(suffix) for suffix in MEDIA_HOST_SUFFIXES)


def build_download_filename(
    author: str, title: str, aweme_id: str, quality: str
) -> str:
    pieces = [
        INVALID_FILENAME.sub("_", value).strip(" ._")
        for value in (author, title, aweme_id, quality)
    ]
    stem = "_".join(piece for piece in pieces if piece)
    stem = re.sub(r"\s+", " ", stem)[:180].rstrip(" ._")
    return f"{stem or aweme_id}.mp4"


def content_disposition(filename: str) -> str:
    return (
        "attachment; filename=douyin-video.mp4; "
        f"filename*=UTF-8''{quote(filename)}"
    )


def _cookie_dict(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip():
            result[key.strip()] = value.strip()
    return result


def _first_url(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for item in value.get("url_list") or []:
        if isinstance(item, str) and item.startswith("https://"):
            return item
    return None


def _cover_url(detail: dict[str, Any]) -> str | None:
    video = detail.get("video") if isinstance(detail.get("video"), dict) else {}
    for key in ("cover", "origin_cover", "dynamic_cover"):
        candidate = _first_url(video.get(key))
        if candidate:
            return candidate
    return None


def _quality_label(width: int, height: int, fallback: str) -> str:
    short_edge = min(value for value in (width, height) if value > 0) if (
        width > 0 and height > 0
    ) else 0
    if short_edge:
        known = min((360, 480, 540, 720, 1080, 1440), key=lambda v: abs(v - short_edge))
        return f"{known}p"
    match = re.search(r"(\d{3,4})p", fallback.lower())
    return match.group(0) if match else "原画"


def _extract_qualities(detail: dict[str, Any]) -> tuple[Quality, ...]:
    video = detail.get("video")
    if not isinstance(video, dict):
        raise DouyinError("该作品不是可下载的视频。", code="NOT_VIDEO")
    if detail.get("images") and not video.get("play_addr"):
        raise DouyinError("首版暂不支持图集作品。", code="GALLERY_UNSUPPORTED")

    rows: list[Quality] = []
    for index, entry in enumerate(video.get("bit_rate") or []):
        if not isinstance(entry, dict):
            continue
        play = entry.get("play_addr")
        if not isinstance(play, dict):
            continue
        urls = tuple(
            url
            for url in (play.get("url_list") or [])
            if isinstance(url, str) and is_media_url_allowed(url)
        )
        if not urls:
            continue
        width = int(play.get("width") or entry.get("width") or 0)
        height = int(play.get("height") or entry.get("height") or 0)
        bitrate = int(entry.get("bit_rate") or 0)
        size = int(play.get("data_size") or entry.get("data_size") or 0)
        label = _quality_label(
            width, height, str(entry.get("gear_name") or entry.get("quality_type") or "")
        )
        rows.append(
            Quality(
                id=label,
                label=label.upper(),
                width=width or None,
                height=height or None,
                bitrate=bitrate or None,
                estimated_bytes=size or None,
                source_urls=urls,
            )
        )

    if not rows:
        play = video.get("play_addr")
        urls = tuple(
            url
            for url in ((play or {}).get("url_list") or [])
            if isinstance(url, str) and is_media_url_allowed(url)
        )
        if urls:
            rows.append(
                Quality(
                    id="original",
                    label="原画",
                    width=int(video.get("width") or 0) or None,
                    height=int(video.get("height") or 0) or None,
                    bitrate=None,
                    estimated_bytes=int((play or {}).get("data_size") or 0) or None,
                    source_urls=urls,
                )
            )
    if not rows:
        raise DouyinError("没有找到可用的视频地址。", code="NO_VIDEO_SOURCE")

    deduplicated: dict[str, Quality] = {}
    for quality in sorted(
        rows,
        key=lambda item: (
            -((item.width or 0) * (item.height or 0)),
            -(item.bitrate or 0),
        ),
    ):
        key = quality.id
        suffix = 2
        while key in deduplicated:
            key = f"{quality.id}-{suffix}"
            suffix += 1
        deduplicated[key] = Quality(
            id=key,
            label=quality.label,
            width=quality.width,
            height=quality.height,
            bitrate=quality.bitrate,
            estimated_bytes=quality.estimated_bytes,
            source_urls=quality.source_urls,
        )
    return tuple(deduplicated.values())


class Provider(Protocol):
    name: str

    async def parse(self, url: str, aweme_id: str) -> ParseResult: ...


class SelfHostedProvider:
    name = "self_hosted"
    DETAIL_ENDPOINT = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

    def __init__(
        self,
        *,
        cookie: str = "",
        cookie_file: str | Path | None = None,
        timeout: float = 20,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._inline_cookie = cookie.strip()
        self._cookie_file = Path(cookie_file).expanduser() if cookie_file else None
        self._cookie_mtime: float | None = None
        self._file_cookie = ""
        self.timeout = timeout
        self.transport = transport

    @property
    def cookie_configured(self) -> bool:
        return bool(self._read_cookie())

    def _read_cookie(self) -> str:
        if self._cookie_file and self._cookie_file.exists():
            try:
                mtime = self._cookie_file.stat().st_mtime
                if mtime != self._cookie_mtime:
                    self._file_cookie = self._cookie_file.read_text(
                        encoding="utf-8"
                    ).strip()
                    self._cookie_mtime = mtime
            except OSError:
                self._file_cookie = ""
        return self._file_cookie or self._inline_cookie

    async def parse(self, url: str, aweme_id: str) -> ParseResult:
        cookie = self._read_cookie()
        cookies = _cookie_dict(cookie)
        ms_token = cookies.get("msToken") or secrets.token_urlsafe(96)
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "aweme_id": aweme_id,
            "pc_client_type": "1",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "139.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "139.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "8",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "100",
            "msToken": ms_token,
        }
        unsigned = f"{self.DETAIL_ENDPOINT}?{urlencode(params)}"
        signed, _, user_agent = XBogus(DEFAULT_USER_AGENT).build(unsigned)
        headers = {
            "User-Agent": user_agent,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if cookie:
            headers["Cookie"] = cookie
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                response = await client.get(signed, headers=headers)
            except httpx.HTTPError as exc:
                raise DouyinError(
                    "自建解析服务暂时无法连接抖音。",
                    code="UPSTREAM_NETWORK",
                    retryable=True,
                    status_code=503,
                ) from exc
        if response.status_code in {401, 403, 429}:
            raise DouyinError(
                "抖音要求更新访问会话。",
                code="SESSION_REQUIRED",
                status_code=503,
            )
        if response.status_code >= 500:
            raise DouyinError(
                "抖音上游暂时不可用。",
                code="UPSTREAM_SERVER",
                retryable=True,
                status_code=503,
            )
        if response.status_code != 200 or not response.content:
            raise DouyinError(
                "抖音未返回作品数据。",
                code="EMPTY_UPSTREAM",
                status_code=503,
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DouyinError(
                "抖音返回了无法识别的数据。",
                code="INVALID_UPSTREAM",
                status_code=503,
            ) from exc
        status_code = int(payload.get("status_code") or 0)
        if status_code:
            message = str(payload.get("status_msg") or "")
            raise DouyinError(
                "该作品暂时无法解析。" if not message else message[:120],
                code="UPSTREAM_REJECTED",
                status_code=422,
            )
        detail = payload.get("aweme_detail")
        if not isinstance(detail, dict):
            raise DouyinError("作品不存在、不可见或已删除。", code="VIDEO_NOT_FOUND")
        qualities = _extract_qualities(detail)
        author_data = detail.get("author") or {}
        return ParseResult(
            original_url=url,
            aweme_id=str(detail.get("aweme_id") or aweme_id),
            title=str(detail.get("desc") or f"抖音视频 {aweme_id}").strip(),
            author=str(author_data.get("nickname") or "抖音作者").strip(),
            cover_url=_cover_url(detail),
            duration_ms=int((detail.get("video") or {}).get("duration") or 0) or None,
            qualities=qualities,
            provider=self.name,
        )


class SharePageProvider:
    """Parse Douyin's server-rendered mobile share page without a third party."""

    name = "share_page"
    SHARE_BASE = "https://www.iesdouyin.com/share/video"
    MOBILE_USER_AGENT = (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "Chrome/131.0.0.0 Mobile Safari/537.36"
    )

    def __init__(
        self,
        *,
        timeout: float = 20,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout = timeout
        self.transport = transport

    @staticmethod
    def _router_data(html: str) -> dict[str, Any]:
        marker = "window._ROUTER_DATA = "
        start = html.find(marker)
        if start < 0:
            raise DouyinError(
                "抖音官方分享页没有返回作品数据。",
                code="SHARE_PAGE_EMPTY",
                status_code=503,
            )
        start += len(marker)
        end = html.find("</script>", start)
        if end < 0:
            raise DouyinError(
                "抖音官方分享页返回了无法识别的数据。",
                code="SHARE_PAGE_INVALID",
                status_code=503,
            )
        try:
            payload = json.loads(html[start:end].strip().removesuffix(";"))
        except json.JSONDecodeError as exc:
            raise DouyinError(
                "抖音官方分享页返回了无法识别的数据。",
                code="SHARE_PAGE_INVALID",
                status_code=503,
            ) from exc
        if not isinstance(payload, dict):
            raise DouyinError(
                "抖音官方分享页返回了无法识别的数据。",
                code="SHARE_PAGE_INVALID",
                status_code=503,
            )
        return payload

    @staticmethod
    def _detail(payload: dict[str, Any]) -> dict[str, Any]:
        loader_data = payload.get("loaderData")
        if not isinstance(loader_data, dict):
            raise DouyinError(
                "作品不存在、不可见或已删除。",
                code="VIDEO_NOT_FOUND",
            )
        for route_data in loader_data.values():
            if not isinstance(route_data, dict):
                continue
            video_info = route_data.get("videoInfoRes")
            if not isinstance(video_info, dict):
                continue
            items = video_info.get("item_list")
            if isinstance(items, list) and items and isinstance(items[0], dict):
                return items[0]
        raise DouyinError(
            "作品不存在、不可见或已删除。",
            code="VIDEO_NOT_FOUND",
        )

    @staticmethod
    def _remove_watermark(detail: dict[str, Any]) -> None:
        video = detail.get("video")
        if not isinstance(video, dict):
            return
        addresses = [video.get("play_addr")]
        addresses.extend(
            entry.get("play_addr")
            for entry in (video.get("bit_rate") or [])
            if isinstance(entry, dict)
        )
        for address in addresses:
            if not isinstance(address, dict):
                continue
            urls = address.get("url_list")
            if not isinstance(urls, list):
                continue
            address["url_list"] = [
                url.replace("/aweme/v1/playwm/", "/aweme/v1/play/")
                if isinstance(url, str)
                else url
                for url in urls
            ]

    async def parse(self, url: str, aweme_id: str) -> ParseResult:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                response = await client.get(
                    f"{self.SHARE_BASE}/{aweme_id}/",
                    headers={
                        "User-Agent": self.MOBILE_USER_AGENT,
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    },
                )
            except httpx.HTTPError as exc:
                raise DouyinError(
                    "Linux 服务器暂时无法连接抖音官方分享页。",
                    code="SHARE_PAGE_NETWORK",
                    retryable=True,
                    status_code=503,
                ) from exc
        if response.status_code >= 500:
            raise DouyinError(
                "抖音官方分享页暂时不可用。",
                code="SHARE_PAGE_SERVER",
                retryable=True,
                status_code=503,
            )
        if response.status_code != 200 or not response.content:
            raise DouyinError(
                "抖音官方分享页没有返回作品数据。",
                code="SHARE_PAGE_EMPTY",
                status_code=503,
            )
        detail = self._detail(self._router_data(response.text))
        if str(detail.get("aweme_id") or "") != aweme_id:
            raise DouyinError(
                "抖音官方分享页返回了其他作品。",
                code="SHARE_PAGE_MISMATCH",
                status_code=503,
            )
        self._remove_watermark(detail)
        author_data = detail.get("author") or {}
        return ParseResult(
            original_url=url,
            aweme_id=aweme_id,
            title=str(detail.get("desc") or f"抖音视频 {aweme_id}").strip(),
            author=str(author_data.get("nickname") or "抖音作者").strip(),
            cover_url=_cover_url(detail),
            duration_ms=int((detail.get("video") or {}).get("duration") or 0)
            or None,
            qualities=_extract_qualities(detail),
            provider=self.name,
        )


class BhwaProvider:
    name = "bhwa"

    def __init__(
        self,
        base_url: str = "https://downloader-api.bhwa233.com",
        *,
        timeout: float = 20,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("bhwa API must use an absolute HTTPS URL")
        self.allowed_host = parsed.hostname.lower()

    async def parse(self, url: str, aweme_id: str) -> ParseResult:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/parse", params={"url": url}
                )
            except httpx.HTTPError as exc:
                raise DouyinError(
                    "备用解析服务暂时不可用。",
                    code="FALLBACK_NETWORK",
                    retryable=True,
                    status_code=503,
                ) from exc
        if response.status_code != 200:
            raise DouyinError(
                "备用解析服务未能解析该作品。",
                code="FALLBACK_FAILED",
                status_code=503,
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DouyinError(
                "备用解析服务返回了无效数据。",
                code="FALLBACK_INVALID",
                status_code=503,
            ) from exc
        if isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if str(payload.get("noteType") or payload.get("type") or "video") not in {
            "video",
        }:
            raise DouyinError(
                "首版暂不支持图集作品。",
                code="GALLERY_UNSUPPORTED",
                status_code=422,
            )
        source = next(
            (
                candidate
                for candidate in (
                    payload.get("originDownloadVideoUrl"),
                    payload.get("downloadVideoUrl"),
                    payload.get("videoDownloadUrl"),
                    payload.get("downloadUrl"),
                )
                if isinstance(candidate, str)
                and is_media_url_allowed(candidate, {self.allowed_host})
            ),
            None,
        )
        if source is None:
            raise DouyinError(
                "备用解析服务没有返回安全的视频地址。",
                code="FALLBACK_NO_SOURCE",
                status_code=503,
            )
        author_data = payload.get("author")
        author = (
            author_data.get("nickname")
            if isinstance(author_data, dict)
            else payload.get("authorName")
        )
        cover = payload.get("cover") or payload.get("coverUrl")
        return ParseResult(
            original_url=url,
            aweme_id=str(payload.get("awemeId") or payload.get("id") or aweme_id),
            title=str(payload.get("title") or f"抖音视频 {aweme_id}").strip(),
            author=str(author or "抖音作者").strip(),
            cover_url=str(cover) if cover else None,
            duration_ms=int(payload.get("durationMs") or 0) or None,
            qualities=(
                Quality(
                    id="original",
                    label="推荐画质",
                    width=None,
                    height=None,
                    bitrate=None,
                    estimated_bytes=None,
                    source_urls=(source,),
                ),
            ),
            provider=self.name,
        )


@dataclass
class CircuitState:
    failures: int = 0
    open_until: float = 0
    last_success_at: str | None = None
    last_error_code: str | None = None


class DouyinEngine:
    def __init__(
        self,
        providers: list[Provider],
        *,
        cache_ttl_seconds: int = 900,
        minimum_interval_seconds: float = 1,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = providers
        self.cache_ttl_seconds = cache_ttl_seconds
        self.minimum_interval_seconds = minimum_interval_seconds
        self._cache: dict[str, tuple[float, ParseResult]] = {}
        self._inflight: dict[str, asyncio.Task[ParseResult]] = {}
        self._inflight_lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._circuits = {provider.name: CircuitState() for provider in providers}
        self.metrics: defaultdict[str, int] = defaultdict(int)

    async def parse(self, text: str) -> ParseResult:
        original = extract_share_url(text)
        resolved = await self._resolve_url(original)
        aweme_id = extract_aweme_id(resolved)
        if not aweme_id:
            raise DouyinError(
                "链接中没有找到单个视频作品 ID。",
                code="UNSUPPORTED_LINK",
                status_code=400,
            )
        cached = self._cache.get(aweme_id)
        now_value = time.monotonic()
        if cached and cached[0] > now_value:
            self.metrics["cache_hits"] += 1
            return cached[1]

        async with self._inflight_lock:
            existing = self._inflight.get(aweme_id)
            if existing is None:
                existing = asyncio.create_task(self._parse_uncached(resolved, aweme_id))
                self._inflight[aweme_id] = existing
        try:
            result = await existing
            self._cache[aweme_id] = (
                time.monotonic() + self.cache_ttl_seconds,
                result,
            )
            return result
        finally:
            async with self._inflight_lock:
                if self._inflight.get(aweme_id) is existing:
                    self._inflight.pop(aweme_id, None)

    def invalidate(self, aweme_id: str) -> None:
        """Discard one cached work so an expired media URL is resolved again."""
        self._cache.pop(aweme_id, None)

    async def _resolve_url(self, original: str) -> str:
        if extract_aweme_id(original):
            return original
        current = original
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            for _ in range(5):
                parsed = urlparse(current)
                if not _hostname_allowed(parsed.hostname, SHARE_HOSTS):
                    raise DouyinError(
                        "短链跳转到了不受信任的地址。",
                        code="UNSAFE_REDIRECT",
                        status_code=400,
                    )
                try:
                    response = await client.get(
                        current,
                        headers={"User-Agent": DEFAULT_USER_AGENT},
                    )
                except httpx.HTTPError as exc:
                    raise DouyinError(
                        "暂时无法展开抖音短链接。",
                        code="SHORT_URL_FAILED",
                        retryable=True,
                        status_code=503,
                    ) from exc
                location = response.headers.get("location")
                if not location:
                    return str(response.url)
                current = urljoin(str(response.url), location)
            raise DouyinError(
                "抖音短链接跳转次数过多。",
                code="TOO_MANY_REDIRECTS",
                status_code=400,
            )

    async def _wait_for_rate_slot(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.minimum_interval_seconds:
                await asyncio.sleep(self.minimum_interval_seconds - elapsed)
            self._last_request_at = time.monotonic()

    async def _parse_uncached(self, url: str, aweme_id: str) -> ParseResult:
        last_error: DouyinError | None = None
        for index, provider in enumerate(self.providers):
            state = self._circuits[provider.name]
            if state.open_until > time.monotonic():
                self.metrics[f"{provider.name}_circuit_skips"] += 1
                continue
            # The fallback is an external service and can occasionally time out.
            # Give a retryable fallback failure one extra chance instead of
            # turning a brief network wobble into a user-visible hard failure.
            attempts = 3 if index == 0 else 2
            for attempt in range(attempts):
                await self._wait_for_rate_slot()
                self.metrics[f"{provider.name}_attempts"] += 1
                try:
                    result = await provider.parse(url, aweme_id)
                    state.failures = 0
                    state.open_until = 0
                    state.last_error_code = None
                    state.last_success_at = datetime.now(UTC).isoformat()
                    self.metrics[f"{provider.name}_success"] += 1
                    return result
                except DouyinError as exc:
                    last_error = exc
                    state.last_error_code = exc.code
                    self.metrics[f"{provider.name}_failures"] += 1
                    if not exc.retryable or attempt == attempts - 1:
                        break
                    await asyncio.sleep(1 if attempt == 0 else 2)
            state.failures += 1
            if index == 0 and state.failures >= 3:
                state.open_until = time.monotonic() + 60
                self.metrics[f"{provider.name}_circuit_opens"] += 1
            if index < len(self.providers) - 1:
                self.metrics["fallbacks"] += 1
        raise last_error or DouyinError(
            "所有解析线路暂时不可用。",
            code="ALL_PROVIDERS_FAILED",
            status_code=503,
        )

    def status(self) -> dict[str, Any]:
        now_value = time.monotonic()
        return {
            "cache_entries": sum(
                1 for expires, _ in self._cache.values() if expires > now_value
            ),
            "inflight": len(self._inflight),
            "providers": {
                provider.name: {
                    "circuit_open": self._circuits[provider.name].open_until
                    > now_value,
                    "failures": self._circuits[provider.name].failures,
                    "last_success_at": self._circuits[provider.name].last_success_at,
                    "last_error_code": self._circuits[provider.name].last_error_code,
                    **(
                        {"cookie_configured": provider.cookie_configured}
                        if isinstance(provider, SelfHostedProvider)
                        else {}
                    ),
                }
                for provider in self.providers
            },
            "metrics": dict(self.metrics),
        }


class UserRateLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, user_id: str) -> None:
        now_value = time.monotonic()
        events = self._events[user_id]
        while events and events[0] <= now_value - self.window_seconds:
            events.popleft()
        if len(events) >= self.limit:
            raise DouyinError(
                "解析请求过于频繁，请稍后再试。",
                code="RATE_LIMITED",
                status_code=429,
            )
        events.append(now_value)
