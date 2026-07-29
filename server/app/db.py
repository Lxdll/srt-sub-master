from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import sqlite3
from typing import Iterator

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, permission_key)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pair_codes (
    code_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    origin TEXT NOT NULL,
    hardware_json TEXT NOT NULL DEFAULT '{}',
    models_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
    backend TEXT NOT NULL DEFAULT 'local_agent',
    original_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    duration_ms INTEGER,
    sha256 TEXT,
    model_id TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_created
ON tasks(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS server_transcription_jobs (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    aweme_id TEXT NOT NULL,
    media_filename TEXT,
    media_expires_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_at TEXT,
    fc_task_id TEXT,
    oss_media_key TEXT,
    oss_result_key TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_server_transcription_jobs_created
ON server_transcription_jobs(created_at);

CREATE TABLE IF NOT EXISTS local_douyin_jobs (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    source_urls_json TEXT NOT NULL DEFAULT '[]',
    aweme_id TEXT NOT NULL,
    expected_size_bytes INTEGER NOT NULL DEFAULT 0,
    expected_duration_ms INTEGER,
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    download_total_bytes INTEGER NOT NULL DEFAULT 0,
    download_speed_bps REAL NOT NULL DEFAULT 0,
    download_eta_seconds INTEGER,
    claim_token_hash TEXT,
    claim_receipt_hash TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_local_douyin_jobs_created
ON local_douyin_jobs(created_at);

CREATE TABLE IF NOT EXISTS fc_callback_receipts (
    nonce TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service TEXT PRIMARY KEY,
    current_task_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    original_text TEXT NOT NULL,
    edited_text TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, ordinal)
);

CREATE TABLE IF NOT EXISTS device_assets (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    local_asset_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(task_id, device_id)
);

CREATE TABLE IF NOT EXISTS pending_commands (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    command TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS user_prohibited_words (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, normalized_term)
);

CREATE INDEX IF NOT EXISTS idx_user_prohibited_words_created
ON user_prohibited_words(user_id, created_at);

CREATE TABLE IF NOT EXISTS hot_rank_snapshots (
    platform TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    items_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def initialize_database() -> None:
    with connect() as connection:
        permissions_table_existed = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'user_permissions'
            """
        ).fetchone()
        connection.executescript(SCHEMA)
        task_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "backend" not in task_columns:
            connection.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN backend TEXT NOT NULL DEFAULT 'local_agent'"
            )
            connection.execute(
                "UPDATE tasks SET backend = 'imported' "
                "WHERE model_id = 'imported-srt'"
            )
            server_backend = (
                "fc" if settings.transcription_backend == "fc" else "server_local"
            )
            connection.execute(
                """
                UPDATE tasks SET backend = ?
                WHERE id IN (SELECT task_id FROM server_transcription_jobs)
                """,
                (server_backend,),
            )
        job_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(server_transcription_jobs)"
            ).fetchall()
        }
        for name, definition in (
            ("fc_task_id", "TEXT"),
            ("oss_media_key", "TEXT"),
            ("oss_result_key", "TEXT"),
            ("completed_at", "TEXT"),
        ):
            if name not in job_columns:
                connection.execute(
                    f"ALTER TABLE server_transcription_jobs "
                    f"ADD COLUMN {name} {definition}"
                )
        local_job_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(local_douyin_jobs)"
            ).fetchall()
        }
        for name, definition in (
            ("source_urls_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("downloaded_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("download_total_bytes", "INTEGER NOT NULL DEFAULT 0"),
            ("download_speed_bps", "REAL NOT NULL DEFAULT 0"),
            ("download_eta_seconds", "INTEGER"),
        ):
            if name not in local_job_columns:
                connection.execute(
                    f"ALTER TABLE local_douyin_jobs ADD COLUMN {name} {definition}"
                )
        if not permissions_table_existed:
            for permission_key in ("subtitle_workspace", "douyin_download"):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_permissions(
                        user_id, permission_key, created_at
                    )
                    SELECT id, ?, ? FROM users WHERE is_admin = 0
                    """,
                    (permission_key, utc_now()),
                )


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
