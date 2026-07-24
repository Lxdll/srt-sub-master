from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import shutil
import threading
from typing import Any, Callable

from huggingface_hub import snapshot_download
from tqdm.auto import tqdm

from .config import settings
from .system_info import hardware_info


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    label: str
    description: str
    approximate_bytes: int
    mac_repo: str
    windows_repo: str


MODELS = (
    ModelDefinition(
        id="large-v3",
        label="Large V3 · 高精度",
        description="准确率优先，适合 16GB 以上内存。",
        approximate_bytes=3_100_000_000,
        mac_repo="mlx-community/whisper-large-v3-mlx",
        windows_repo="Systran/faster-whisper-large-v3",
    ),
    ModelDefinition(
        id="large-v3-turbo",
        label="Large V3 Turbo · 均衡",
        description="速度更快，准确率略低于 Large V3。",
        approximate_bytes=1_700_000_000,
        mac_repo="mlx-community/whisper-large-v3-turbo",
        windows_repo="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    ),
    ModelDefinition(
        id="small",
        label="Small · 低配置",
        description="占用更小，适合内存有限的电脑。",
        approximate_bytes=500_000_000,
        mac_repo="mlx-community/whisper-small-mlx",
        windows_repo="Systran/faster-whisper-small",
    ),
)


download_states: dict[str, dict[str, Any]] = {}
download_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-download")
download_lock = threading.Lock()


def definition(model_id: str) -> ModelDefinition:
    for item in MODELS:
        if item.id == model_id:
            return item
    raise KeyError(model_id)


def repo_for(model: ModelDefinition) -> str:
    return model.mac_repo if platform.system() == "Darwin" else model.windows_repo


def _model_cache_root(repo_id: str) -> Path:
    return settings.model_cache_dir / f"models--{repo_id.replace('/', '--')}" / "snapshots"


def _complete_snapshot(repo_id: str) -> Path | None:
    root = _model_cache_root(repo_id)
    if not root.exists():
        return None
    for snapshot in sorted(root.iterdir(), reverse=True):
        if not snapshot.is_dir():
            continue
        if platform.system() == "Darwin":
            candidates = (snapshot / "weights.npz", snapshot / "weights.safetensors")
        else:
            candidates = (snapshot / "model.bin",)
        if any(candidate.exists() and candidate.stat().st_size > 10_000_000 for candidate in candidates):
            return snapshot
    return None


def _legacy_mac_model(model_id: str) -> Path | None:
    if platform.system() != "Darwin" or model_id != "large-v3":
        return None
    root = (
        Path.home()
        / "Desktop"
        / "视频转文字工具"
        / "模型缓存"
        / "hub"
        / "models--mlx-community--whisper-large-v3-mlx"
        / "snapshots"
    )
    if not root.exists():
        return None
    for snapshot in root.iterdir():
        weights = snapshot / "weights.npz"
        if weights.exists() and weights.stat().st_size > 1_000_000_000:
            return snapshot
    return None


def model_path(model_id: str) -> Path | None:
    legacy = _legacy_mac_model(model_id)
    if legacy:
        return legacy
    return _complete_snapshot(repo_for(definition(model_id)))


def recommended_model() -> str:
    memory = hardware_info().get("memory_bytes") or 0
    if memory >= 16 * 1024**3:
        return "large-v3"
    if memory >= 8 * 1024**3:
        return "large-v3-turbo"
    return "small"


def catalog() -> list[dict[str, Any]]:
    recommendation = recommended_model()
    return [
        {
            "id": item.id,
            "label": item.label,
            "description": item.description,
            "approximate_bytes": item.approximate_bytes,
            "installed": model_path(item.id) is not None,
            "recommended": item.id == recommendation,
            "download": download_states.get(item.id),
        }
        for item in MODELS
    ]


class DownloadTqdm(tqdm):
    callback: Callable[[float], None] | None = None

    def update(self, n: int | float = 1) -> bool | None:
        result = super().update(n)
        if self.callback and self.total:
            self.callback(min(99.0, self.n / self.total * 100))
        return result


def _download(model_id: str) -> None:
    model = definition(model_id)
    repo_id = repo_for(model)

    def progress(value: float) -> None:
        download_states[model_id] = {"status": "downloading", "progress": round(value, 1)}

    try:
        download_states[model_id] = {"status": "downloading", "progress": 0}
        settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
        DownloadTqdm.callback = progress
        kwargs: dict[str, Any] = {
            "repo_id": repo_id,
            "cache_dir": settings.model_cache_dir,
            "resume_download": True,
        }
        try:
            snapshot_download(tqdm_class=DownloadTqdm, **kwargs)
        except TypeError:
            snapshot_download(**kwargs)
        download_states[model_id] = {"status": "ready", "progress": 100}
    except Exception as exc:
        download_states[model_id] = {
            "status": "failed",
            "progress": 0,
            "error": str(exc),
        }
    finally:
        DownloadTqdm.callback = None


def start_download(model_id: str) -> dict[str, Any]:
    model = definition(model_id)
    if model_path(model_id):
        return {"status": "ready", "progress": 100}
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(settings.model_cache_dir).free
    required = int(model.approximate_bytes * 1.15) + 512 * 1024 * 1024
    if free < required:
        raise OSError("磁盘空间不足，无法下载该模型。")
    with download_lock:
        state = download_states.get(model_id)
        if state and state["status"] == "downloading":
            return state
        download_states[model_id] = {"status": "queued", "progress": 0}
        download_executor.submit(_download, model_id)
    return download_states[model_id]
