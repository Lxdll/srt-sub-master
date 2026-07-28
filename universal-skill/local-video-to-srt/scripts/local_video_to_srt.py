#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Any, Iterable


MODELS = {
    "large-v3": {
        "label": "Large V3",
        "memory_gb": 16,
        "mac_repo": "mlx-community/whisper-large-v3-mlx",
        "windows_repo": "Systran/faster-whisper-large-v3",
    },
    "large-v3-turbo": {
        "label": "Large V3 Turbo",
        "memory_gb": 8,
        "mac_repo": "mlx-community/whisper-large-v3-turbo",
        "windows_repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    },
    "small": {
        "label": "Small",
        "memory_gb": 4,
        "mac_repo": "mlx-community/whisper-small-mlx",
        "windows_repo": "Systran/faster-whisper-small",
    },
}


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def engine_name(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    return "mlx-whisper" if platform.system() == "Darwin" else "faster-whisper"


def engine_module(engine: str) -> str:
    return "mlx_whisper" if engine == "mlx-whisper" else "faster_whisper"


def model_reference(model_id: str, engine: str, local_path: str | None) -> str:
    if local_path:
        path = Path(local_path).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"模型目录不存在：{path}")
        return str(path)
    model = MODELS[model_id]
    return str(model["mac_repo"] if engine == "mlx-whisper" else model["windows_repo"])


def doctor_payload(engine: str) -> dict[str, Any]:
    module = engine_module(engine)
    python_supported = (3, 11) <= sys.version_info[:2] <= (3, 12)
    checks = {
        "python": {
            "ok": python_supported,
            "version": platform.python_version(),
            "required": "3.11 or 3.12",
        },
        "ffmpeg": {"ok": shutil.which("ffmpeg") is not None, "path": shutil.which("ffmpeg")},
        "ffprobe": {
            "ok": shutil.which("ffprobe") is not None,
            "path": shutil.which("ffprobe"),
        },
        "engine": {
            "ok": importlib.util.find_spec(module) is not None,
            "name": engine,
            "module": module,
        },
    }
    return {
        "status": "ok",
        "ready": all(item["ok"] for item in checks.values()),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "checks": checks,
    }


def srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def write_srt(segments: Iterable[dict[str, Any]], output: Path) -> int:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start_ms = max(0, round(float(segment["start"]) * 1000))
        end_ms = max(start_ms + 1, round(float(segment["end"]) * 1000))
        blocks.append(
            f"{index}\n{srt_timestamp(start_ms)} --> {srt_timestamp(end_ms)}\n{text}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
    return len(blocks)


def transcribe_mlx(
    source: Path, model: str, language: str
) -> list[dict[str, Any]]:
    import mlx_whisper

    result = mlx_whisper.transcribe(
        str(source),
        path_or_hf_repo=model,
        language=language,
        task="transcribe",
        word_timestamps=True,
        temperature=0.0,
        verbose=False,
    )
    return list(result.get("segments", []))


def transcribe_faster(
    source: Path, model: str, language: str
) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel

    whisper = WhisperModel(model, device="auto", compute_type="default")
    segments, _ = whisper.transcribe(
        str(source), language=language, beam_size=5, vad_filter=True
    )
    return [
        {"start": segment.start, "end": segment.end, "text": segment.text}
        for segment in segments
    ]


def command_doctor(args: argparse.Namespace) -> int:
    payload = doctor_payload(engine_name(args.engine))
    emit(payload, args.json)
    return 0 if payload["ready"] else 2


def command_models(args: argparse.Namespace) -> int:
    engine = engine_name(args.engine)
    platform_key = "mac_repo" if engine == "mlx-whisper" else "windows_repo"
    emit(
        {
            "status": "ok",
            "engine": engine,
            "models": [
                {
                    "id": model_id,
                    "label": details["label"],
                    "minimum_memory_gb": details["memory_gb"],
                    "source": f"https://huggingface.co/{details[platform_key]}",
                }
                for model_id, details in MODELS.items()
            ],
        },
        args.json,
    )
    return 0


def command_transcribe(args: argparse.Namespace) -> int:
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"输入文件不存在：{source}")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else source.with_suffix(".srt")
    )
    engine = engine_name(args.engine)
    health = doctor_payload(engine)
    if not health["ready"]:
        missing = [
            name for name, check in health["checks"].items() if not check["ok"]
        ]
        raise RuntimeError(f"本机环境未就绪：{', '.join(missing)}")
    model = model_reference(args.model, engine, args.model_path)
    segments = (
        transcribe_mlx(source, model, args.language)
        if engine == "mlx-whisper"
        else transcribe_faster(source, model, args.language)
    )
    count = write_srt(segments, output)
    emit(
        {
            "status": "ok",
            "input": str(source),
            "output": str(output),
            "engine": engine,
            "model": args.model,
            "segments": count,
        },
        args.json,
    )
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="在本机把视频或音频转成 SRT，不上传媒体文件。"
    )
    subcommands = result.add_subparsers(dest="command", required=True)

    doctor = subcommands.add_parser("doctor", help="检查本机依赖")
    doctor.add_argument(
        "--engine", choices=("auto", "mlx-whisper", "faster-whisper"), default="auto"
    )
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    models = subcommands.add_parser("models", help="列出模型")
    models.add_argument(
        "--engine", choices=("auto", "mlx-whisper", "faster-whisper"), default="auto"
    )
    models.add_argument("--json", action="store_true")
    models.set_defaults(handler=command_models)

    transcribe = subcommands.add_parser("transcribe", help="生成 SRT")
    transcribe.add_argument("input")
    transcribe.add_argument("--output")
    transcribe.add_argument("--model", choices=tuple(MODELS), default="large-v3-turbo")
    transcribe.add_argument("--model-path")
    transcribe.add_argument("--language", default="zh")
    transcribe.add_argument(
        "--engine", choices=("auto", "mlx-whisper", "faster-whisper"), default="auto"
    )
    transcribe.add_argument("--json", action="store_true")
    transcribe.set_defaults(handler=command_transcribe)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.handler(args))
    except Exception as exc:
        emit({"status": "error", "error": str(exc)}, getattr(args, "json", False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
