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
    downloads_dir: Path


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
        downloads_dir=Path(
            os.getenv("SRT_DOWNLOADS_DIR", project_root / "installer" / "artifacts")
        ),
    )


settings = load_settings()
