from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from .config import Settings, settings
from .db import db_session

logger = logging.getLogger(__name__)

HotRankSource = Literal["60s", "uapi"]


@dataclass(frozen=True)
class PlatformSpec:
    key: Literal["rednote", "douyin", "bilibili"]
    display_name: str
    primary_path: str
    fallback_type: str
    allowed_domains: tuple[str, ...]


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: datetime | None = None


PLATFORMS = (
    PlatformSpec(
        key="rednote",
        display_name="小红书",
        primary_path="/v2/rednote",
        fallback_type="xiaohongshu",
        allowed_domains=("xiaohongshu.com",),
    ),
    PlatformSpec(
        key="douyin",
        display_name="抖音",
        primary_path="/v2/douyin",
        fallback_type="douyin",
        allowed_domains=("douyin.com",),
    ),
    PlatformSpec(
        key="bilibili",
        display_name="B站热门",
        primary_path="/v2/bili",
        fallback_type="bilibili",
        allowed_domains=("bilibili.com",),
    ),
)


class HotRankUpstreamError(RuntimeError):
    pass


class HotRankService:
    circuit_failure_threshold = 3
    circuit_open_seconds = 300
    manual_refresh_cooldown_seconds = 60

    def __init__(
        self,
        config: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._now = now or (lambda: datetime.now(UTC))
        self._client: httpx.AsyncClient | None = None
        self._locks = {platform.key: asyncio.Lock() for platform in PLATFORMS}
        self._circuits: dict[tuple[str, HotRankSource], CircuitState] = {}
        self._manual_refresh_lock = asyncio.Lock()
        self._last_manual_refresh: datetime | None = None
        self._background_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    def start(self) -> None:
        if self._background_task and not self._background_task.done():
            return
        self._stop_event = asyncio.Event()
        self._background_task = asyncio.create_task(
            self._refresh_loop(), name="hot-rank-refresh"
        )

    async def close(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
            self._background_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_hot_ranks(self, refresh: bool = False) -> dict[str, Any]:
        force = await self._claim_manual_refresh() if refresh else False
        platforms = await asyncio.gather(
            *(self._platform_result(platform, force) for platform in PLATFORMS)
        )
        return {
            "generated_at": self._now().isoformat(),
            "platforms": list(platforms),
        }

    async def _claim_manual_refresh(self) -> bool:
        async with self._manual_refresh_lock:
            now = self._now()
            if (
                self._last_manual_refresh is not None
                and now - self._last_manual_refresh
                < timedelta(seconds=self.manual_refresh_cooldown_seconds)
            ):
                return False
            self._last_manual_refresh = now
            return True

    async def _refresh_loop(self) -> None:
        assert self._stop_event is not None
        while True:
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.hot_rank_refresh_seconds,
                )
                return
            except TimeoutError:
                try:
                    await self.get_hot_ranks()
                except Exception:
                    logger.exception("hot_rank_background_refresh_failed")

    async def _platform_result(
        self, platform: PlatformSpec, force: bool
    ) -> dict[str, Any]:
        async with self._locks[platform.key]:
            snapshot = self._load_snapshot(platform)
            now = self._now()
            snapshot_age = self._snapshot_age(snapshot, now)
            should_refresh = (
                force
                or snapshot is None
                or snapshot_age >= self._config.hot_rank_refresh_seconds
            )
            if not should_refresh and snapshot:
                return self._snapshot_result(platform, snapshot, "fresh")

            fetched = await self._refresh_platform(platform)
            if fetched:
                return self._snapshot_result(platform, fetched, "fresh")

            snapshot = self._load_snapshot(platform)
            snapshot_age = self._snapshot_age(snapshot, now)
            if snapshot and snapshot_age <= self._config.hot_rank_stale_seconds:
                logger.warning(
                    "hot_rank_stale_snapshot platform=%s age_seconds=%d",
                    platform.key,
                    int(snapshot_age),
                )
                return self._snapshot_result(platform, snapshot, "stale")
            return {
                "platform": platform.key,
                "display_name": platform.display_name,
                "status": "unavailable",
                "source": None,
                "updated_at": None,
                "items": [],
            }

    async def _refresh_platform(
        self, platform: PlatformSpec
    ) -> dict[str, Any] | None:
        for source in ("60s", "uapi"):
            typed_source: HotRankSource = source
            if self._circuit_is_open(platform.key, typed_source):
                logger.warning(
                    "hot_rank_circuit_open platform=%s source=%s",
                    platform.key,
                    source,
                )
                continue
            started = time.monotonic()
            try:
                items = await self._fetch_source(platform, typed_source)
            except (HotRankUpstreamError, httpx.HTTPError, ValueError, TypeError) as exc:
                self._record_failure(platform.key, typed_source)
                logger.warning(
                    "hot_rank_source_failed platform=%s source=%s "
                    "duration_ms=%d error=%s",
                    platform.key,
                    source,
                    int((time.monotonic() - started) * 1000),
                    type(exc).__name__,
                )
                continue

            self._record_success(platform.key, typed_source)
            updated_at = self._now().isoformat()
            snapshot = {
                "source": source,
                "updated_at": updated_at,
                "items": items,
            }
            self._save_snapshot(platform.key, snapshot)
            logger.info(
                "hot_rank_source_succeeded platform=%s source=%s duration_ms=%d",
                platform.key,
                source,
                int((time.monotonic() - started) * 1000),
            )
            return snapshot
        return None

    async def _fetch_source(
        self, platform: PlatformSpec, source: HotRankSource
    ) -> list[dict[str, Any]]:
        if source == "60s":
            url = f"{self._config.hot_rank_primary_base}{platform.primary_path}"
            headers: dict[str, str] = {}
        else:
            fallback_base = self._config.hot_rank_fallback_base
            if fallback_base.endswith("/api/v1"):
                url = f"{fallback_base}/misc/hotboard"
            else:
                url = f"{fallback_base}/api/v1/misc/hotboard"
            headers = {}
            if self._config.hot_rank_fallback_api_key:
                headers["Authorization"] = (
                    f"Bearer {self._config.hot_rank_fallback_api_key}"
                )

        response = await self._get_client().get(
            url,
            params=(
                {"type": platform.fallback_type} if source == "uapi" else None
            ),
            headers=headers,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HotRankUpstreamError("invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HotRankUpstreamError("invalid response")
        if source == "60s":
            if payload.get("code") != 200:
                raise HotRankUpstreamError("unsuccessful response")
            raw_items = payload.get("data")
        else:
            raw_items = payload.get("list")
        if not isinstance(raw_items, list):
            raise HotRankUpstreamError("missing item list")
        return self._normalise_items(platform, raw_items)

    def _normalise_items(
        self, platform: PlatformSpec, raw_items: list[Any]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        seen_urls: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            title = self._clean_text(
                self._first_value(raw_item, "title", "keyword", "word", "name"),
                200,
            )
            url = self._clean_text(
                self._first_value(raw_item, "url", "link", "uri"), 2048
            )
            if not title or not url or not self._safe_url(url, platform.allowed_domains):
                continue
            title_key = title.casefold()
            if title_key in seen_titles or url in seen_urls:
                continue
            seen_titles.add(title_key)
            seen_urls.add(url)

            item: dict[str, Any] = {
                "rank": len(result) + 1,
                "title": title,
                "url": url,
            }
            hot_value = self._clean_text(
                self._first_value(raw_item, "hot_value", "score", "hot", "heat"),
                64,
            )
            if hot_value:
                item["hot_value"] = hot_value
            badge = self._extract_badge(raw_item)
            if badge:
                item["badge"] = badge
            result.append(item)
            if len(result) == 10:
                break
        if len(result) < 10:
            raise HotRankUpstreamError("fewer than ten valid items")
        return result

    @staticmethod
    def _first_value(item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = item.get(key)
            if value is not None:
                return value
        return None

    def _extract_badge(self, item: dict[str, Any]) -> str | None:
        badge = self._clean_text(
            self._first_value(item, "word_type", "badge", "tag"), 32
        )
        if not badge:
            extra = item.get("extra")
            if isinstance(extra, dict):
                badge = self._clean_text(
                    self._first_value(extra, "type", "badge", "tag", "status"), 32
                )
        if badge in {"无", "none", "None", "0"}:
            return None
        return badge

    @staticmethod
    def _clean_text(value: Any, max_length: int) -> str | None:
        if not isinstance(value, (str, int, float)):
            return None
        cleaned = " ".join(str(value).split()).strip()
        if not cleaned:
            return None
        return cleaned[:max_length]

    @staticmethod
    def _safe_url(url: str, allowed_domains: tuple[str, ...]) -> bool:
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
        except ValueError:
            return False
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            return False
        return any(
            host == domain or host.endswith(f".{domain}")
            for domain in allowed_domains
        )

    def _load_snapshot(self, platform: PlatformSpec) -> dict[str, Any] | None:
        with db_session() as db:
            row = db.execute(
                """
                SELECT source, items_json, updated_at
                FROM hot_rank_snapshots
                WHERE platform = ?
                """,
                (platform.key,),
            ).fetchone()
        if not row or row["source"] not in {"60s", "uapi"}:
            return None
        try:
            raw_items = json.loads(row["items_json"])
            updated_at = datetime.fromisoformat(row["updated_at"])
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            items = self._normalise_items(platform, raw_items)
        except (json.JSONDecodeError, ValueError, TypeError, HotRankUpstreamError):
            logger.warning("hot_rank_snapshot_invalid platform=%s", platform.key)
            return None
        return {
            "source": row["source"],
            "updated_at": updated_at.astimezone(UTC).isoformat(),
            "items": items,
        }

    @staticmethod
    def _save_snapshot(platform: str, snapshot: dict[str, Any]) -> None:
        with db_session() as db:
            db.execute(
                """
                INSERT INTO hot_rank_snapshots(
                    platform, source, items_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    source = excluded.source,
                    items_json = excluded.items_json,
                    updated_at = excluded.updated_at
                """,
                (
                    platform,
                    snapshot["source"],
                    json.dumps(
                        snapshot["items"], ensure_ascii=False, separators=(",", ":")
                    ),
                    snapshot["updated_at"],
                ),
            )

    @staticmethod
    def _snapshot_result(
        platform: PlatformSpec, snapshot: dict[str, Any], status: str
    ) -> dict[str, Any]:
        return {
            "platform": platform.key,
            "display_name": platform.display_name,
            "status": status,
            "source": snapshot["source"],
            "updated_at": snapshot["updated_at"],
            "items": snapshot["items"],
        }

    @staticmethod
    def _snapshot_age(snapshot: dict[str, Any] | None, now: datetime) -> float:
        if not snapshot:
            return float("inf")
        updated_at = datetime.fromisoformat(snapshot["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return max(0.0, (now - updated_at).total_seconds())

    def _circuit_is_open(self, platform: str, source: HotRankSource) -> bool:
        state = self._circuits.get((platform, source))
        if not state or not state.opened_until:
            return False
        if self._now() < state.opened_until:
            return True
        state.opened_until = None
        return False

    def _record_failure(self, platform: str, source: HotRankSource) -> None:
        state = self._circuits.setdefault((platform, source), CircuitState())
        state.failures += 1
        if state.failures >= self.circuit_failure_threshold:
            state.opened_until = self._now() + timedelta(
                seconds=self.circuit_open_seconds
            )

    def _record_success(self, platform: str, source: HotRankSource) -> None:
        self._circuits[(platform, source)] = CircuitState()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._config.hot_rank_timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            )
        return self._client


hot_rank_service = HotRankService(settings)
