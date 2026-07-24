from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
from typing import Any


def default_data_dir() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "SRTSubAgent"
    if platform.system() == "Windows":
        return Path(os.getenv("LOCALAPPDATA", Path.home())) / "SRTSubAgent"
    return Path.home() / ".local" / "share" / "SRTSubAgent"


@dataclass(frozen=True)
class AgentSettings:
    data_dir: Path
    assets_dir: Path
    model_cache_dir: Path
    state_path: Path
    database_path: Path
    port: int
    development_origins: tuple[str, ...]


def load_settings() -> AgentSettings:
    data_dir = Path(
        os.getenv("SRT_AGENT_DATA_DIR") or default_data_dir()
    ).expanduser()
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv(
            "SRT_AGENT_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )
    return AgentSettings(
        data_dir=data_dir,
        assets_dir=data_dir / "assets",
        model_cache_dir=data_dir / "models",
        state_path=data_dir / "agent-state.json",
        database_path=data_dir / "agent.sqlite3",
        port=int(os.getenv("SRT_AGENT_PORT", "43921")),
        development_origins=origins,
    )


settings = load_settings()


def load_state() -> dict[str, Any]:
    if not settings.state_path.exists():
        return {}
    try:
        return json.loads(settings.state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    temporary = settings.state_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, settings.state_path)
    try:
        settings.state_path.chmod(0o600)
    except OSError:
        pass

