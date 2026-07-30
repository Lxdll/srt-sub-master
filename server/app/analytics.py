from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
import hashlib
import hmac
import ipaddress
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Request

from .config import Settings, settings
from .db import db_session

try:
    import ip2region.searcher as ip2region_searcher
    import ip2region.util as ip2region_util
except ImportError:  # pragma: no cover - deployment installs the pinned package
    ip2region_searcher = None
    ip2region_util = None


logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
ALLOWED_RANGES = frozenset({7, 30, 90})


@dataclass(frozen=True)
class GeoLocation:
    country: str | None = None
    province: str | None = None
    city: str | None = None
    isp: str | None = None

    @property
    def label(self) -> str:
        parts = [
            item
            for item in (self.country, self.province, self.city)
            if item and item not in {"0", "未知"}
        ]
        return " · ".join(dict.fromkeys(parts)) if parts else (self.country or "未知")


@dataclass(frozen=True)
class ActionSpec:
    key: str
    resource_type: str | None = None
    resource_param: str | None = None


ACTION_ROUTES: dict[tuple[str, str], ActionSpec] = {
    ("POST", "/api/auth/logout"): ActionSpec("auth.logout"),
    ("PATCH", "/api/auth/password"): ActionSpec("auth.password_change", "user"),
    ("POST", "/api/admin/users"): ActionSpec("admin.user.create", "user"),
    (
        "PATCH",
        "/api/admin/users/{user_id}/permissions",
    ): ActionSpec("admin.user.permissions_update", "user", "user_id"),
    (
        "PATCH",
        "/api/admin/users/{user_id}/password",
    ): ActionSpec("admin.user.password_reset", "user", "user_id"),
    ("POST", "/api/devices/pair-code"): ActionSpec("device.pair_code.create"),
    ("POST", "/api/agent/pair"): ActionSpec("device.pair.complete", "device"),
    ("POST", "/api/tasks"): ActionSpec("subtitle.task.create", "task"),
    ("POST", "/api/tasks/import-srt"): ActionSpec("subtitle.srt.import", "task"),
    (
        "PATCH",
        "/api/tasks/{task_id}/segments/{segment_id}",
    ): ActionSpec("subtitle.segment.edit", "segment", "segment_id"),
    (
        "POST",
        "/api/tasks/{task_id}/retry",
    ): ActionSpec("subtitle.task.retry", "task", "task_id"),
    (
        "POST",
        "/api/tasks/{task_id}/relink",
    ): ActionSpec("subtitle.task.relink", "task", "task_id"),
    (
        "GET",
        "/api/tasks/{task_id}/export",
    ): ActionSpec("subtitle.task.export", "task", "task_id"),
    (
        "DELETE",
        "/api/tasks/{task_id}",
    ): ActionSpec("subtitle.task.delete", "task", "task_id"),
    ("POST", "/api/douyin/parse"): ActionSpec("douyin.parse"),
    (
        "POST",
        "/api/douyin/transcriptions",
    ): ActionSpec("douyin.transcription.create", "task"),
    ("GET", "/api/douyin/download/{ticket}"): ActionSpec("douyin.download"),
    (
        "POST",
        "/api/prohibited-words/check",
    ): ActionSpec("prohibited_words.check"),
    (
        "POST",
        "/api/prohibited-words/custom",
    ): ActionSpec("prohibited_words.custom.add", "prohibited_word"),
    (
        "DELETE",
        "/api/prohibited-words/custom/{word_id}",
    ): ActionSpec("prohibited_words.custom.delete", "prohibited_word", "word_id"),
    ("POST", "/api/script-analysis/analyze"): ActionSpec("script_analysis.run"),
    ("POST", "/api/scripts"): ActionSpec("script_library.create", "script"),
    (
        "PATCH",
        "/api/scripts/{script_id}",
    ): ActionSpec("script_library.update", "script", "script_id"),
    (
        "DELETE",
        "/api/scripts/{script_id}",
    ): ActionSpec("script_library.delete", "script", "script_id"),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _location_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    location = GeoLocation(
        row.get("country"),
        row.get("province"),
        row.get("city"),
        row.get("isp"),
    )
    return {
        "country": location.country,
        "province": location.province,
        "city": location.city,
        "isp": location.isp,
        "label": location.label,
    }


def _cursor_encode(occurred_at: str, item_id: str) -> str:
    raw = json.dumps([occurred_at, item_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_decode(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) for item in value)
        ):
            raise ValueError
        datetime.fromisoformat(value[0])
        return value[0], value[1]
    except Exception as exc:
        raise ValueError("分页游标无效") from exc


def _safe_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if len(result) >= 16:
            break
        if not isinstance(key, str) or len(key) > 64:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:200]
        elif isinstance(value, list):
            result[key] = [
                item[:100] if isinstance(item, str) else item
                for item in value[:20]
                if isinstance(item, (str, bool, int, float))
            ]
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return result if len(encoded.encode()) <= 2048 else {}


class AnalyticsService:
    def __init__(self, config: Settings) -> None:
        self._config = config
        self._geo_searchers: dict[int, Any] = {}
        self._background_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def public_host(self) -> str:
        return (urlparse(self._config.public_url).hostname or "").lower()

    @property
    def geo_status(self) -> dict[str, bool]:
        return {
            "ipv4": 4 in self._geo_searchers,
            "ipv6": 6 in self._geo_searchers,
        }

    def start(self) -> None:
        self._load_geo_databases()
        self.cleanup_expired()
        if self._background_task and not self._background_task.done():
            return
        self._stop_event = asyncio.Event()
        self._background_task = asyncio.create_task(
            self._cleanup_loop(), name="analytics-retention-cleanup"
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

    def _load_geo_databases(self) -> None:
        if not ip2region_searcher or not ip2region_util:
            logger.warning("ip2region_client_unavailable")
            return
        for version, path in (
            (4, self._config.ip2region_v4_path),
            (6, self._config.ip2region_v6_path),
        ):
            try:
                ip2region_util.verify_from_file(str(path))
                content = ip2region_util.load_content_from_file(str(path))
                ip_version = (
                    ip2region_util.IPv4 if version == 4 else ip2region_util.IPv6
                )
                self._geo_searchers[version] = ip2region_searcher.new_with_buffer(
                    ip_version, content
                )
            except Exception:
                logger.exception(
                    "ip2region_database_load_failed",
                    extra={"path": str(path), "version": version},
                )

    async def _cleanup_loop(self) -> None:
        assert self._stop_event is not None
        while True:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=86_400)
                return
            except TimeoutError:
                try:
                    self.cleanup_expired()
                except Exception:
                    logger.exception("analytics_cleanup_failed")

    def client_ip(self, request: Request) -> str:
        raw = request.client.host if request.client else ""
        try:
            return str(ipaddress.ip_address(raw.split("%", 1)[0]))
        except ValueError:
            return "0.0.0.0"

    def resolve_geo(self, ip_address: str) -> GeoLocation:
        try:
            parsed = ipaddress.ip_address(ip_address)
        except ValueError:
            return GeoLocation()
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_unspecified
        ):
            return GeoLocation(country="内网")
        searcher = self._geo_searchers.get(parsed.version)
        if not searcher:
            return GeoLocation()
        try:
            region = searcher.search(str(parsed))
            if not region:
                return GeoLocation()
            parts = [None if item in {"", "0"} else item for item in region.split("|")]
            parts += [None] * (5 - len(parts))
            return GeoLocation(parts[0], parts[1], parts[2], parts[3])
        except Exception:
            logger.exception("ip2region_lookup_failed", extra={"ip_version": parsed.version})
            return GeoLocation()

    def optional_user(self, request: Request) -> dict[str, Any] | None:
        raw_token = request.cookies.get("srt_session")
        if not raw_token:
            return None
        digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with db_session() as db:
            row = db.execute(
                """
                SELECT u.id, u.username, u.is_admin, s.expires_at
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (digest,),
            ).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= _utc_now():
            return None
        return dict(row)

    def _day(self, occurred_at: datetime) -> str:
        return occurred_at.astimezone(SHANGHAI).date().isoformat()

    def _range(self, days: int) -> tuple[datetime, datetime, list[str]]:
        if days not in ALLOWED_RANGES:
            raise ValueError("days 只允许 7、30 或 90")
        local_now = _utc_now().astimezone(SHANGHAI)
        start_date = local_now.date() - timedelta(days=days - 1)
        start = datetime.combine(start_date, time.min, SHANGHAI).astimezone(UTC)
        end = _utc_now()
        day_keys = [
            (start_date + timedelta(days=offset)).isoformat()
            for offset in range(days)
        ]
        return start, end, day_keys

    def _touch_link(
        self,
        db: sqlite3.Connection,
        *,
        ip_address: str,
        user_id: str,
        geo: GeoLocation,
        occurred_at: str,
        login_delta: int = 0,
        page_view_delta: int = 0,
        action_delta: int = 0,
    ) -> None:
        login_at = occurred_at if login_delta else None
        db.execute(
            """
            INSERT INTO ip_user_links(
                ip_address, user_id, country, province, city, isp,
                first_seen_at, last_seen_at, first_login_at, last_login_at,
                login_count, page_view_count, action_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ip_address, user_id) DO UPDATE SET
                country = COALESCE(excluded.country, ip_user_links.country),
                province = COALESCE(excluded.province, ip_user_links.province),
                city = COALESCE(excluded.city, ip_user_links.city),
                isp = COALESCE(excluded.isp, ip_user_links.isp),
                last_seen_at = excluded.last_seen_at,
                first_login_at = COALESCE(
                    ip_user_links.first_login_at, excluded.first_login_at
                ),
                last_login_at = COALESCE(
                    excluded.last_login_at, ip_user_links.last_login_at
                ),
                login_count = ip_user_links.login_count + excluded.login_count,
                page_view_count = (
                    ip_user_links.page_view_count + excluded.page_view_count
                ),
                action_count = ip_user_links.action_count + excluded.action_count
            """,
            (
                ip_address,
                user_id,
                geo.country,
                geo.province,
                geo.city,
                geo.isp,
                occurred_at,
                occurred_at,
                login_at,
                login_at,
                login_delta,
                page_view_delta,
                action_delta,
            ),
        )

    def record_page_view(
        self,
        request: Request,
        *,
        event_id: str,
        path: str,
        user_id: str | None,
    ) -> str:
        ip_address = self.client_ip(request)
        now = _utc_now()
        occurred_at = _iso(now)
        geo = self.resolve_geo(ip_address)
        day = self._day(now)
        unique_digest = hmac.new(
            self._config.session_secret.encode(),
            f"{day}|{ip_address}".encode(),
            hashlib.sha256,
        ).hexdigest()
        with db_session() as db:
            if db.execute(
                "SELECT 1 FROM page_views WHERE event_id = ?", (event_id,)
            ).fetchone():
                return "duplicate"
            minute_ago = _iso(now - timedelta(minutes=1))
            recent = db.execute(
                """
                SELECT COUNT(*) AS count FROM page_views
                WHERE ip_address = ? AND occurred_at >= ?
                """,
                (ip_address, minute_ago),
            ).fetchone()["count"]
            if recent >= 60:
                return "rate_limited"
            db.execute(
                """
                INSERT INTO page_views(
                    id, event_id, user_id, ip_address, country, province,
                    city, isp, path, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    event_id,
                    user_id,
                    ip_address,
                    geo.country,
                    geo.province,
                    geo.city,
                    geo.isp,
                    path,
                    occurred_at,
                ),
            )
            unique_cursor = db.execute(
                """
                INSERT OR IGNORE INTO analytics_daily_uniques(day, ip_hash)
                VALUES (?, ?)
                """,
                (day, unique_digest),
            )
            db.execute(
                """
                INSERT INTO analytics_daily(day, page_views, unique_ips)
                VALUES (?, 1, ?)
                ON CONFLICT(day) DO UPDATE SET
                    page_views = analytics_daily.page_views + 1,
                    unique_ips = analytics_daily.unique_ips + excluded.unique_ips
                """,
                (day, 1 if unique_cursor.rowcount else 0),
            )
            if user_id:
                self._touch_link(
                    db,
                    ip_address=ip_address,
                    user_id=user_id,
                    geo=geo,
                    occurred_at=occurred_at,
                    page_view_delta=1,
                )
        return "accepted"

    def record_action(
        self,
        request: Request,
        *,
        action_key: str,
        outcome: str,
        http_status: int,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        login_success: bool = False,
        link_user: bool = True,
    ) -> None:
        try:
            ip_address = self.client_ip(request)
            now = _utc_now()
            occurred_at = _iso(now)
            day = self._day(now)
            geo = self.resolve_geo(ip_address)
            safe_metadata = _safe_metadata(metadata)
            with db_session() as db:
                db.execute(
                    """
                    INSERT INTO action_events(
                        id, user_id, ip_address, country, province, city, isp,
                        action_key, outcome, http_status, resource_type,
                        resource_id, metadata_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        user_id,
                        ip_address,
                        geo.country,
                        geo.province,
                        geo.city,
                        geo.isp,
                        action_key,
                        outcome,
                        http_status,
                        resource_type,
                        resource_id,
                        json.dumps(
                            safe_metadata, ensure_ascii=False, separators=(",", ":")
                        ),
                        occurred_at,
                    ),
                )
                user_key = user_id or "-"
                db.execute(
                    """
                    INSERT INTO action_daily_stats(
                        day, user_key, user_id, action_key, outcome, event_count
                    ) VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(day, user_key, action_key, outcome) DO UPDATE SET
                        event_count = action_daily_stats.event_count + 1
                    """,
                    (day, user_key, user_id, action_key, outcome),
                )
                if user_id and link_user:
                    self._touch_link(
                        db,
                        ip_address=ip_address,
                        user_id=user_id,
                        geo=geo,
                        occurred_at=occurred_at,
                        login_delta=1 if login_success else 0,
                        action_delta=1,
                    )
        except Exception:
            logger.exception("analytics_action_record_failed", extra={"action": action_key})

    def cleanup_expired(self) -> dict[str, int]:
        cutoff = _iso(_utc_now() - timedelta(days=self._config.analytics_retention_days))
        unique_cutoff = (
            _utc_now().astimezone(SHANGHAI).date() - timedelta(days=2)
        ).isoformat()
        with db_session() as db:
            page_views = db.execute(
                "DELETE FROM page_views WHERE occurred_at < ?", (cutoff,)
            ).rowcount
            actions = db.execute(
                "DELETE FROM action_events WHERE occurred_at < ?", (cutoff,)
            ).rowcount
            links = db.execute(
                "DELETE FROM ip_user_links WHERE last_seen_at < ?", (cutoff,)
            ).rowcount
            uniques = db.execute(
                "DELETE FROM analytics_daily_uniques WHERE day < ?", (unique_cutoff,)
            ).rowcount
        return {
            "page_views": page_views,
            "action_events": actions,
            "ip_user_links": links,
            "daily_uniques": uniques,
        }

    def overview(self, days: int) -> dict[str, Any]:
        start, end, day_keys = self._range(days)
        start_iso = _iso(start)
        with db_session() as db:
            daily_rows = db.execute(
                """
                SELECT day, page_views, unique_ips
                FROM analytics_daily
                WHERE day >= ? AND day <= ?
                ORDER BY day
                """,
                (day_keys[0], day_keys[-1]),
            ).fetchall()
            period = db.execute(
                """
                SELECT COUNT(*) AS page_views,
                       COUNT(DISTINCT ip_address) AS unique_ips
                FROM page_views WHERE occurred_at >= ?
                """,
                (start_iso,),
            ).fetchone()
            locations = db.execute(
                """
                SELECT country, province, city, isp, COUNT(*) AS page_views
                FROM page_views
                WHERE occurred_at >= ?
                GROUP BY country, province, city, isp
                ORDER BY page_views DESC
                LIMIT 10
                """,
                (start_iso,),
            ).fetchall()
        by_day = {row["day"]: row for row in daily_rows}
        daily = [
            {
                "day": day,
                "page_views": by_day.get(day, {"page_views": 0})["page_views"],
                "unique_ips": by_day.get(day, {"unique_ips": 0})["unique_ips"],
            }
            for day in day_keys
        ]
        today = daily[-1]
        return {
            "days": days,
            "from_at": start_iso,
            "to_at": _iso(end),
            "timezone": "Asia/Shanghai",
            "summary": {
                "today_page_views": today["page_views"],
                "today_unique_ips": today["unique_ips"],
                "period_page_views": period["page_views"],
                "period_unique_ips": period["unique_ips"],
            },
            "daily": daily,
            "locations": [
                {
                    **_location_from_row(dict(row)),
                    "page_views": row["page_views"],
                }
                for row in locations
            ],
            "geo_status": self.geo_status,
        }

    def visits(
        self, days: int, limit: int, cursor: str | None
    ) -> dict[str, Any]:
        start, _, _ = self._range(days)
        params: list[Any] = [_iso(start)]
        cursor_clause = ""
        if cursor:
            cursor_at, cursor_id = _cursor_decode(cursor)
            cursor_clause = (
                "AND (p.occurred_at < ? OR "
                "(p.occurred_at = ? AND p.id < ?))"
            )
            params.extend([cursor_at, cursor_at, cursor_id])
        params.append(limit + 1)
        with db_session() as db:
            rows = db.execute(
                f"""
                SELECT p.*, u.username
                FROM page_views p
                LEFT JOIN users u ON u.id = p.user_id
                WHERE p.occurred_at >= ? {cursor_clause}
                ORDER BY p.occurred_at DESC, p.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        return {
            "items": [
                {
                    "id": row["id"],
                    "occurred_at": row["occurred_at"],
                    "ip_address": row["ip_address"],
                    "location": _location_from_row(dict(row)),
                    "path": row["path"],
                    "user_id": row["user_id"],
                    "username": row["username"],
                }
                for row in selected
            ],
            "next_cursor": (
                _cursor_encode(selected[-1]["occurred_at"], selected[-1]["id"])
                if has_more and selected
                else None
            ),
        }

    def ip_users(
        self,
        days: int,
        limit: int,
        cursor: str | None,
        query: str,
    ) -> dict[str, Any]:
        start, _, _ = self._range(days)
        start_iso = _iso(start)
        params: list[Any] = [start_iso]
        search_clause = ""
        if query:
            search_clause = """
                AND (
                    l.ip_address LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM ip_user_links lx
                        JOIN users ux ON ux.id = lx.user_id
                        WHERE lx.ip_address = l.ip_address
                          AND ux.username LIKE ? COLLATE NOCASE
                    )
                )
            """
            wildcard = f"%{query[:100]}%"
            params.extend([wildcard, wildcard])
        cursor_clause = ""
        if cursor:
            cursor_at, cursor_ip = _cursor_decode(cursor)
            cursor_clause = (
                "WHERE latest_at < ? OR (latest_at = ? AND ip_address < ?)"
            )
            params.extend([cursor_at, cursor_at, cursor_ip])
        params.append(limit + 1)
        with db_session() as db:
            ips = db.execute(
                f"""
                WITH grouped AS (
                    SELECT l.ip_address, MAX(l.last_seen_at) AS latest_at
                    FROM ip_user_links l
                    WHERE l.last_seen_at >= ? {search_clause}
                    GROUP BY l.ip_address
                )
                SELECT * FROM grouped
                {cursor_clause}
                ORDER BY latest_at DESC, ip_address DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            has_more = len(ips) > limit
            selected_ips = ips[:limit]
            ip_values = [row["ip_address"] for row in selected_ips]
            if not ip_values:
                return {"items": [], "next_cursor": None}
            placeholders = ",".join("?" for _ in ip_values)
            links = db.execute(
                f"""
                SELECT l.*, u.username
                FROM ip_user_links l
                JOIN users u ON u.id = l.user_id
                WHERE l.ip_address IN ({placeholders})
                ORDER BY l.last_seen_at DESC
                """,
                ip_values,
            ).fetchall()
            count_params = [start_iso, *ip_values]
            page_counts = db.execute(
                f"""
                SELECT ip_address, user_id, COUNT(*) AS event_count
                FROM page_views
                WHERE occurred_at >= ? AND user_id IS NOT NULL
                  AND ip_address IN ({placeholders})
                GROUP BY ip_address, user_id
                """,
                count_params,
            ).fetchall()
            action_counts = db.execute(
                f"""
                SELECT ip_address, user_id,
                    COUNT(*) AS event_count,
                    SUM(
                        CASE WHEN action_key = 'auth.login'
                                  AND outcome = 'success'
                             THEN 1 ELSE 0 END
                    ) AS login_count
                FROM action_events
                WHERE occurred_at >= ? AND user_id IS NOT NULL
                  AND ip_address IN ({placeholders})
                GROUP BY ip_address, user_id
                """,
                count_params,
            ).fetchall()
        links_by_ip: dict[str, list[sqlite3.Row]] = {}
        for row in links:
            links_by_ip.setdefault(row["ip_address"], []).append(row)
        page_count_map = {
            (row["ip_address"], row["user_id"]): row["event_count"]
            for row in page_counts
        }
        action_count_map = {
            (row["ip_address"], row["user_id"]): row["event_count"]
            for row in action_counts
        }
        login_count_map = {
            (row["ip_address"], row["user_id"]): row["login_count"] or 0
            for row in action_counts
        }
        items = []
        for ip_row in selected_ips:
            accounts = links_by_ip.get(ip_row["ip_address"], [])
            first = accounts[0]
            ip_address = ip_row["ip_address"]
            items.append(
                {
                    "ip_address": ip_address,
                    "location": _location_from_row(dict(first)),
                    "first_seen_at": min(row["first_seen_at"] for row in accounts),
                    "last_seen_at": max(row["last_seen_at"] for row in accounts),
                    "login_count": sum(
                        login_count_map.get((ip_address, row["user_id"]), 0)
                        for row in accounts
                    ),
                    "page_view_count": sum(
                        page_count_map.get((ip_address, row["user_id"]), 0)
                        for row in accounts
                    ),
                    "action_count": sum(
                        action_count_map.get((ip_address, row["user_id"]), 0)
                        for row in accounts
                    ),
                    "users": [
                        {
                            "id": row["user_id"],
                            "username": row["username"],
                            "first_login_at": row["first_login_at"],
                            "last_login_at": row["last_login_at"],
                            "last_seen_at": row["last_seen_at"],
                            "login_count": login_count_map.get(
                                (ip_address, row["user_id"]), 0
                            ),
                            "page_view_count": page_count_map.get(
                                (ip_address, row["user_id"]), 0
                            ),
                            "action_count": action_count_map.get(
                                (ip_address, row["user_id"]), 0
                            ),
                        }
                        for row in accounts
                    ],
                }
            )
        return {
            "items": items,
            "next_cursor": (
                _cursor_encode(
                    selected_ips[-1]["latest_at"], selected_ips[-1]["ip_address"]
                )
                if has_more and selected_ips
                else None
            ),
        }

    def actions_overview(self, days: int) -> dict[str, Any]:
        start, _, day_keys = self._range(days)
        start_iso = _iso(start)
        with db_session() as db:
            summary = db.execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success,
                    SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) AS failure,
                    COUNT(DISTINCT user_id) AS active_users
                FROM action_events WHERE occurred_at >= ?
                """,
                (start_iso,),
            ).fetchone()
            daily_rows = db.execute(
                """
                SELECT day,
                    SUM(CASE WHEN outcome = 'success' THEN event_count ELSE 0 END)
                        AS success,
                    SUM(CASE WHEN outcome = 'failure' THEN event_count ELSE 0 END)
                        AS failure
                FROM action_daily_stats
                WHERE day >= ? AND day <= ?
                GROUP BY day ORDER BY day
                """,
                (day_keys[0], day_keys[-1]),
            ).fetchall()
            top_actions = db.execute(
                """
                SELECT action_key, COUNT(*) AS event_count
                FROM action_events
                WHERE occurred_at >= ?
                GROUP BY action_key
                ORDER BY event_count DESC, action_key
                LIMIT 10
                """,
                (start_iso,),
            ).fetchall()
        by_day = {row["day"]: row for row in daily_rows}
        return {
            "days": days,
            "summary": {
                "total": summary["total"] or 0,
                "success": summary["success"] or 0,
                "failure": summary["failure"] or 0,
                "active_users": summary["active_users"] or 0,
            },
            "daily": [
                {
                    "day": day,
                    "success": by_day.get(day, {"success": 0})["success"] or 0,
                    "failure": by_day.get(day, {"failure": 0})["failure"] or 0,
                }
                for day in day_keys
            ],
            "top_actions": [dict(row) for row in top_actions],
        }

    def actions(
        self,
        days: int,
        limit: int,
        cursor: str | None,
        user_id: str | None,
        action: str | None,
        outcome: str | None,
    ) -> dict[str, Any]:
        start, _, _ = self._range(days)
        where = ["a.occurred_at >= ?"]
        params: list[Any] = [_iso(start)]
        if user_id:
            where.append("a.user_id = ?")
            params.append(user_id)
        if action:
            where.append("a.action_key = ?")
            params.append(action)
        if outcome:
            where.append("a.outcome = ?")
            params.append(outcome)
        if cursor:
            cursor_at, cursor_id = _cursor_decode(cursor)
            where.append(
                "(a.occurred_at < ? OR (a.occurred_at = ? AND a.id < ?))"
            )
            params.extend([cursor_at, cursor_at, cursor_id])
        params.append(limit + 1)
        with db_session() as db:
            rows = db.execute(
                f"""
                SELECT a.*, u.username
                FROM action_events a
                LEFT JOIN users u ON u.id = a.user_id
                WHERE {" AND ".join(where)}
                ORDER BY a.occurred_at DESC, a.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = []
        for row in selected:
            try:
                metadata = json.loads(row["metadata_json"])
            except json.JSONDecodeError:
                metadata = {}
            items.append(
                {
                    "id": row["id"],
                    "occurred_at": row["occurred_at"],
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "ip_address": row["ip_address"],
                    "location": _location_from_row(dict(row)),
                    "action_key": row["action_key"],
                    "outcome": row["outcome"],
                    "http_status": row["http_status"],
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "metadata": metadata,
                }
            )
        return {
            "items": items,
            "next_cursor": (
                _cursor_encode(selected[-1]["occurred_at"], selected[-1]["id"])
                if has_more and selected
                else None
            ),
        }


analytics_service = AnalyticsService(settings)


def set_action_metadata(request: Request, **metadata: Any) -> None:
    existing = getattr(request.state, "analytics_metadata", {})
    request.state.analytics_metadata = {**existing, **_safe_metadata(metadata)}


def action_spec_for_request(request: Request) -> ActionSpec | None:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if not route_path:
        return None
    if route_path == "/api/hot-ranks":
        return (
            ActionSpec("hot_ranks.refresh")
            if request.method == "GET"
            and request.query_params.get("refresh", "").lower() == "true"
            else None
        )
    spec = ACTION_ROUTES.get((request.method, route_path))
    if (
        spec
        and spec.key == "douyin.download"
        and request.headers.get("range")
    ):
        return None
    return spec
