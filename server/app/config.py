from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    public_url: str
    allowed_origins: tuple[str, ...]
    session_secret: str
    cookie_secure: bool
    session_days: int
    admin_username: str
    admin_password: str
    web_dist: Path
    douyin_enabled: bool
    douyin_access: str
    douyin_cookie: str
    douyin_cookie_file: Path | None
    bhwa_api_base: str
    transcription_enabled: bool
    transcription_model_path: Path
    transcription_vad_model_path: Path
    transcription_whisper_path: Path
    transcription_ffmpeg_path: str
    transcription_ffprobe_path: str
    transcription_threads: int
    transcription_max_duration_seconds: int
    transcription_max_source_bytes: int
    transcription_media_retention_hours: int
    transcription_media_quota_bytes: int
    transcription_user_queue_limit: int
    transcription_global_queue_limit: int
    transcription_backend: str
    fc_endpoint: str
    fc_function_name: str
    fc_qualifier: str
    fc_callback_secret: str
    fc_stale_job_seconds: int
    fc_queue_max_age_seconds: int
    oss_region: str
    oss_endpoint: str
    oss_bucket: str
    oss_prefix: str
    oss_media_url_ttl_seconds: int
    moderation_api_base: str
    moderation_api_key: str
    moderation_model: str
    moderation_timeout_seconds: float


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = Path(
        os.getenv("SRT_DATA_DIR", project_root / "data" / "server")
    ).expanduser()
    allowed = tuple(
        item.strip().rstrip("/")
        for item in os.getenv(
            "SRT_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if item.strip()
    )
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "srt-sub.sqlite3",
        public_url=os.getenv("SRT_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
        allowed_origins=allowed,
        session_secret=os.getenv(
            "SRT_SESSION_SECRET", "dev-only-change-before-deployment"
        ),
        cookie_secure=_bool_env("SRT_COOKIE_SECURE", False),
        session_days=int(os.getenv("SRT_SESSION_DAYS", "14")),
        admin_username=os.getenv("SRT_ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("SRT_ADMIN_PASSWORD", "change-me-now"),
        web_dist=Path(os.getenv("SRT_WEB_DIST", project_root / "web" / "dist")),
        douyin_enabled=_bool_env("SRT_DOUYIN_ENABLED", True),
        douyin_access=os.getenv("SRT_DOUYIN_ACCESS", "authenticated").strip().lower(),
        douyin_cookie=os.getenv("SRT_DOUYIN_COOKIE", "").strip(),
        douyin_cookie_file=(
            Path(os.environ["SRT_DOUYIN_COOKIE_FILE"]).expanduser()
            if os.getenv("SRT_DOUYIN_COOKIE_FILE")
            else None
        ),
        bhwa_api_base=os.getenv(
            "SRT_BHWA_API_BASE", "https://downloader-api.bhwa233.com"
        ).rstrip("/"),
        transcription_enabled=_bool_env("SRT_TRANSCRIPTION_ENABLED", True),
        transcription_model_path=Path(
            os.getenv(
                "SRT_TRANSCRIPTION_MODEL_PATH",
                "/opt/whisper/models/ggml-small-q5_1.bin",
            )
        ),
        transcription_vad_model_path=Path(
            os.getenv(
                "SRT_TRANSCRIPTION_VAD_MODEL_PATH",
                "/opt/whisper/models/ggml-silero-v6.2.0.bin",
            )
        ),
        transcription_whisper_path=Path(
            os.getenv(
                "SRT_TRANSCRIPTION_WHISPER_PATH",
                "/opt/whisper/bin/whisper-cli",
            )
        ),
        transcription_ffmpeg_path=os.getenv(
            "SRT_TRANSCRIPTION_FFMPEG_PATH", "ffmpeg"
        ),
        transcription_ffprobe_path=os.getenv(
            "SRT_TRANSCRIPTION_FFPROBE_PATH", "ffprobe"
        ),
        transcription_threads=max(
            1, int(os.getenv("SRT_TRANSCRIPTION_THREADS", "2"))
        ),
        transcription_max_duration_seconds=max(
            1, int(os.getenv("SRT_TRANSCRIPTION_MAX_DURATION_SECONDS", "1800"))
        ),
        transcription_max_source_bytes=max(
            1, int(os.getenv("SRT_TRANSCRIPTION_MAX_SOURCE_BYTES", "524288000"))
        ),
        transcription_media_retention_hours=max(
            1, int(os.getenv("SRT_TRANSCRIPTION_MEDIA_RETENTION_HOURS", "168"))
        ),
        transcription_media_quota_bytes=max(
            1,
            int(
                os.getenv(
                    "SRT_TRANSCRIPTION_MEDIA_QUOTA_BYTES", "10737418240"
                )
            ),
        ),
        transcription_user_queue_limit=max(
            1, int(os.getenv("SRT_TRANSCRIPTION_USER_QUEUE_LIMIT", "3"))
        ),
        transcription_global_queue_limit=max(
            1, int(os.getenv("SRT_TRANSCRIPTION_GLOBAL_QUEUE_LIMIT", "20"))
        ),
        transcription_backend=os.getenv(
            "SRT_TRANSCRIPTION_BACKEND", "local"
        ).strip().lower(),
        fc_endpoint=os.getenv("SRT_FC_ENDPOINT", "").strip(),
        fc_function_name=os.getenv("SRT_FC_FUNCTION_NAME", "").strip(),
        fc_qualifier=os.getenv("SRT_FC_QUALIFIER", "LATEST").strip() or "LATEST",
        fc_callback_secret=os.getenv("SRT_FC_CALLBACK_SECRET", "").strip(),
        fc_stale_job_seconds=max(
            3600, int(os.getenv("SRT_FC_STALE_JOB_SECONDS", "3900"))
        ),
        fc_queue_max_age_seconds=max(
            3600, int(os.getenv("SRT_FC_QUEUE_MAX_AGE_SECONDS", "86400"))
        ),
        oss_region=os.getenv("SRT_OSS_REGION", "").strip(),
        oss_endpoint=os.getenv("SRT_OSS_ENDPOINT", "").strip().rstrip("/"),
        oss_bucket=os.getenv("SRT_OSS_BUCKET", "").strip(),
        oss_prefix=os.getenv(
            "SRT_OSS_PREFIX", "douyin-transcriptions"
        ).strip().strip("/"),
        oss_media_url_ttl_seconds=max(
            60, int(os.getenv("SRT_OSS_MEDIA_URL_TTL_SECONDS", "600"))
        ),
        moderation_api_base=os.getenv("SRT_MODERATION_API_BASE", "").strip().rstrip("/"),
        moderation_api_key=os.getenv("SRT_MODERATION_API_KEY", "").strip(),
        moderation_model=os.getenv("SRT_MODERATION_MODEL", "").strip(),
        moderation_timeout_seconds=float(
            os.getenv("SRT_MODERATION_TIMEOUT_SECONDS", "30")
        ),
    )


settings = load_settings()
