from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx
import oss2
from fastapi import FastAPI, HTTPException, Request

from server.app.chinese import to_simplified_chinese
from server.app.srt import SrtError, parse_srt

MEDIA_HOST_SUFFIXES = (
    ".douyinvod.com",
    ".bytecdn.cn",
    ".douyin.com",
    ".snssdk.com",
)
TASK_ID_PATTERN = re.compile(r"^[0-9a-f-]{36}$")
PROGRESS_PATTERN = re.compile(r"progress\s*=\s*(\d{1,3})%", re.IGNORECASE)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)


class WorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerSettings:
    oss_region: str
    oss_endpoint: str
    oss_bucket: str
    callback_url: str
    callback_secret: str
    whisper_path: str
    model_path: str
    vad_model_path: str
    ffmpeg_path: str
    ffprobe_path: str
    threads: int

    @classmethod
    def load(cls) -> WorkerSettings:
        result = cls(
            oss_region=os.getenv("SRT_OSS_REGION", "").strip(),
            oss_endpoint=os.getenv("SRT_OSS_INTERNAL_ENDPOINT", "").strip().rstrip(
                "/"
            ),
            oss_bucket=os.getenv("SRT_OSS_BUCKET", "").strip(),
            callback_url=os.getenv("SRT_FC_CALLBACK_URL", "").strip(),
            callback_secret=os.getenv("SRT_FC_CALLBACK_SECRET", "").strip(),
            whisper_path=os.getenv(
                "SRT_TRANSCRIPTION_WHISPER_PATH", "/opt/whisper/bin/whisper-cli"
            ),
            model_path=os.getenv(
                "SRT_TRANSCRIPTION_MODEL_PATH",
                "/opt/whisper/models/ggml-small-q5_1.bin",
            ),
            vad_model_path=os.getenv(
                "SRT_TRANSCRIPTION_VAD_MODEL_PATH",
                "/opt/whisper/models/ggml-silero-v6.2.0.bin",
            ),
            ffmpeg_path=os.getenv("SRT_TRANSCRIPTION_FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.getenv("SRT_TRANSCRIPTION_FFPROBE_PATH", "ffprobe"),
            threads=max(1, int(os.getenv("SRT_TRANSCRIPTION_THREADS", "4"))),
        )
        missing = [
            name
            for name, value in (
                ("SRT_OSS_REGION", result.oss_region),
                ("SRT_OSS_INTERNAL_ENDPOINT", result.oss_endpoint),
                ("SRT_OSS_BUCKET", result.oss_bucket),
                ("SRT_FC_CALLBACK_URL", result.callback_url),
                ("SRT_FC_CALLBACK_SECRET", result.callback_secret),
            )
            if not value
        ]
        if missing:
            raise WorkerError(f"函数配置缺失：{', '.join(missing)}")
        return result


def _credentials() -> tuple[str, str, str | None]:
    access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    security_token = os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN", "").strip() or None
    if not access_key_id or not access_key_secret:
        raise WorkerError("函数 RAM 角色凭据不可用。")
    return access_key_id, access_key_secret, security_token


def _bucket(settings: WorkerSettings):
    access_key_id, access_key_secret, security_token = _credentials()
    if security_token:
        auth = oss2.StsAuth(
            access_key_id,
            access_key_secret,
            security_token,
            auth_version="v4",
        )
    else:
        auth = oss2.AuthV4(access_key_id, access_key_secret)
    return oss2.Bucket(
        auth,
        settings.oss_endpoint,
        settings.oss_bucket,
        region=settings.oss_region,
    )


def _hostname_is_public(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    if (
        host in {"localhost", "localhost.localdomain"}
        or host.endswith((".local", ".internal", ".localhost"))
    ):
        return False
    try:
        return not (
            ipaddress.ip_address(host).is_private
            or ipaddress.ip_address(host).is_loopback
            or ipaddress.ip_address(host).is_link_local
        )
    except ValueError:
        return "." in host


def _source_allowed(url: str, extra_allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if not _hostname_is_public(host):
        return False
    return host in extra_allowed_hosts or any(
        host.endswith(suffix) for suffix in MEDIA_HOST_SUFFIXES
    )


def _callback(
    settings: WorkerSettings,
    *,
    task_id: str,
    attempt: int,
    event: str,
    **fields: Any,
) -> None:
    payload = {
        "task_id": task_id,
        "attempt": attempt,
        "event": event,
        **fields,
    }
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    last_error: Exception | None = None
    for _ in range(3):
        timestamp = str(int(time.time()))
        nonce = str(uuid4())
        signed = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
        signature = hmac.new(
            settings.callback_secret.encode(),
            signed,
            hashlib.sha256,
        ).hexdigest()
        try:
            response = httpx.post(
                settings.callback_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-SRT-Timestamp": timestamp,
                    "X-SRT-Nonce": nonce,
                    "X-SRT-Signature": signature,
                },
                timeout=30,
            )
            response.raise_for_status()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise WorkerError("无法回写转写任务状态。") from last_error


def _upload_part(bucket, upload_id: str, key: str, number: int, data: bytes):
    result = bucket.upload_part(
        key,
        upload_id,
        number,
        BytesIO(data),
    )
    return oss2.models.PartInfo(number, result.etag)


def _multipart_upload(
    bucket,
    key: str,
    chunks: Iterable[bytes],
    max_bytes: int,
    total_bytes: int,
    progress,
) -> tuple[int, str]:
    upload = bucket.init_multipart_upload(key)
    parts = []
    buffer = bytearray()
    received = 0
    digest = hashlib.sha256()
    last_progress = -1
    try:
        for chunk in chunks:
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise WorkerError("视频文件超过 500MB，下载已停止。")
            digest.update(chunk)
            buffer.extend(chunk)
            if total_bytes:
                value = 3 + min(17, int(received / total_bytes * 17))
                if value != last_progress:
                    progress(value)
                    last_progress = value
            if len(buffer) >= 8 * 1024 * 1024:
                parts.append(
                    _upload_part(
                        bucket,
                        upload.upload_id,
                        key,
                        len(parts) + 1,
                        bytes(buffer),
                    )
                )
                buffer.clear()
        if received == 0:
            raise WorkerError("视频下载结果为空，请稍后重试。")
        if buffer:
            parts.append(
                _upload_part(
                    bucket,
                    upload.upload_id,
                    key,
                    len(parts) + 1,
                    bytes(buffer),
                )
            )
        bucket.complete_multipart_upload(key, upload.upload_id, parts)
    except Exception:
        bucket.abort_multipart_upload(key, upload.upload_id)
        raise
    return received, digest.hexdigest()


def _download_to_oss(
    settings: WorkerSettings,
    bucket,
    payload: dict[str, Any],
    media_key: str,
    progress,
) -> tuple[int, str]:
    source_urls = payload.get("source_urls")
    if (
        not isinstance(source_urls, list)
        or not source_urls
        or not all(isinstance(item, str) for item in source_urls)
    ):
        raise WorkerError("没有可用的视频源。")
    raw_extra = payload.get("extra_allowed_hosts") or []
    extra_allowed_hosts = {
        value.lower().rstrip(".")
        for value in raw_extra
        if isinstance(value, str)
        and _hostname_is_public(value.lower().rstrip("."))
    }
    max_bytes = int(payload["max_source_bytes"])
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
    }
    with httpx.Client(timeout=120, follow_redirects=False) as client:
        for source_url in source_urls:
            current = source_url
            for _ in range(4):
                if not _source_allowed(current, extra_allowed_hosts):
                    break
                with client.stream("GET", current, headers=headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            break
                        current = urljoin(current, location)
                        continue
                    if response.status_code not in {200, 206}:
                        break
                    total = int(response.headers.get("content-length") or 0)
                    if total > max_bytes:
                        raise WorkerError("视频文件超过 500MB，暂不支持转写。")
                    return _multipart_upload(
                        bucket,
                        media_key,
                        response.iter_bytes(256 * 1024),
                        max_bytes,
                        total,
                        progress,
                    )
    raise WorkerError("视频源已经失效，请重新提交任务。")


def _run(command: list[str], timeout: int) -> str:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerError("媒体处理超时。") from exc
    if completed.returncode != 0:
        raise WorkerError("媒体处理失败。")
    return completed.stdout.decode("utf-8", errors="replace")


def _duration_ms(
    settings: WorkerSettings,
    media_url: str,
    max_duration_seconds: int,
) -> int:
    output = _run(
        [
            settings.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            media_url,
        ],
        120,
    )
    try:
        duration_ms = max(1, round(float(output.strip()) * 1000))
    except ValueError as exc:
        raise WorkerError("视频时长格式无效。") from exc
    if duration_ms > max_duration_seconds * 1000:
        raise WorkerError("视频超过 30 分钟，暂不支持转写。")
    return duration_ms


def _extract_audio(
    settings: WorkerSettings,
    media_url: str,
    audio_path: Path,
) -> None:
    _run(
        [
            settings.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            media_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ],
        600,
    )
    if not audio_path.is_file():
        raise WorkerError("无法提取视频音频。")


def _transcribe(
    settings: WorkerSettings,
    task_id: str,
    attempt: int,
    audio_path: Path,
    output_base: Path,
) -> Path:
    command = [
        settings.whisper_path,
        "--model",
        settings.model_path,
        "--file",
        str(audio_path),
        "--threads",
        str(settings.threads),
        "--language",
        "zh",
        "--no-gpu",
        "--vad",
        "--vad-model",
        settings.vad_model_path,
        "--output-srt",
        "--output-file",
        str(output_base),
        "--print-progress",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    last_reported = -5
    for raw_line in process.stdout:
        line = raw_line.decode("utf-8", errors="replace")
        match = PROGRESS_PATTERN.search(line)
        if not match:
            continue
        whisper_progress = min(100, int(match.group(1)))
        if whisper_progress - last_reported < 5 and whisper_progress < 100:
            continue
        last_reported = whisper_progress
        _callback(
            settings,
            task_id=task_id,
            attempt=attempt,
            event="progress",
            status="transcribing",
            progress=25 + whisper_progress * 0.7,
        )
    code = process.wait()
    srt_path = output_base.with_suffix(".srt")
    if code != 0 or not srt_path.is_file():
        raise WorkerError("语音识别失败。")
    return srt_path


def _validate_payload(payload: dict[str, Any]) -> tuple[str, int]:
    task_id = payload.get("task_id")
    attempt = payload.get("attempt")
    if (
        not isinstance(task_id, str)
        or not TASK_ID_PATTERN.fullmatch(task_id)
        or not isinstance(attempt, int)
        or attempt < 1
    ):
        raise WorkerError("任务参数无效。")
    for field in ("max_source_bytes", "max_duration_seconds"):
        if not isinstance(payload.get(field), int) or payload[field] <= 0:
            raise WorkerError("任务限制参数无效。")
    return task_id, attempt


def process(payload: dict[str, Any]) -> dict[str, Any]:
    settings = WorkerSettings.load()
    task_id, attempt = _validate_payload(payload)
    prefix = str(payload.get("oss_prefix") or "douyin-transcriptions").strip("/")
    media_key = f"{prefix}/media/{task_id}/video.mp4"
    result_key = f"{prefix}/results/{task_id}/{attempt}/result.json"
    srt_key = f"{prefix}/results/{task_id}/{attempt}/transcript.srt"
    root = Path("/tmp") / f"{task_id}-{attempt}"
    root.mkdir(parents=True, exist_ok=True)
    audio_path = root / "audio.wav"
    output_base = root / "transcript"
    bucket = _bucket(settings)
    media_uploaded = False

    try:
        _callback(
            settings,
            task_id=task_id,
            attempt=attempt,
            event="progress",
            status="downloading",
            progress=3,
        )

        def download_progress(value: int) -> None:
            _callback(
                settings,
                task_id=task_id,
                attempt=attempt,
                event="progress",
                status="downloading",
                progress=value,
            )

        media_bytes, sha256 = _download_to_oss(
            settings,
            bucket,
            payload,
            media_key,
            download_progress,
        )
        media_uploaded = True
        media_url = bucket.sign_url("GET", media_key, 3600, slash_safe=True)
        duration_ms = _duration_ms(
            settings,
            media_url,
            int(payload["max_duration_seconds"]),
        )
        _callback(
            settings,
            task_id=task_id,
            attempt=attempt,
            event="progress",
            status="transcribing",
            progress=22,
        )
        _extract_audio(settings, media_url, audio_path)
        _callback(
            settings,
            task_id=task_id,
            attempt=attempt,
            event="progress",
            status="transcribing",
            progress=25,
        )
        srt_path = _transcribe(
            settings,
            task_id,
            attempt,
            audio_path,
            output_base,
        )
        try:
            segments = parse_srt(srt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, SrtError) as exc:
            raise WorkerError("识别结果无法转换为字幕。") from exc
        for segment in segments:
            segment["text"] = to_simplified_chinese(segment["text"])
        if not segments:
            raise WorkerError("视频中没有识别到可用的说话内容。")

        result = {
            "task_id": task_id,
            "attempt": attempt,
            "media_bytes": media_bytes,
            "duration_ms": duration_ms,
            "sha256": sha256,
            "segments": segments,
        }
        bucket.put_object(
            result_key,
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            headers={"Content-Type": "application/json"},
        )
        bucket.put_object(
            srt_key,
            srt_path.read_bytes(),
            headers={"Content-Type": "application/x-subrip"},
        )
        _callback(
            settings,
            task_id=task_id,
            attempt=attempt,
            event="completed",
            media_key=media_key,
            result_key=result_key,
            srt_key=srt_key,
        )
        return {"ok": True, "task_id": task_id, "attempt": attempt}
    except Exception as exc:
        error = (
            str(exc)
            if isinstance(exc, WorkerError)
            else "云端转写发生异常，请重试。"
        )
        if media_uploaded:
            try:
                bucket.delete_object(media_key)
            except Exception:
                pass
        try:
            _callback(
                settings,
                task_id=task_id,
                attempt=attempt,
                event="failed",
                error=error,
            )
        except WorkerError:
            pass
        if isinstance(exc, WorkerError):
            raise
        raise WorkerError(error) from exc
    finally:
        audio_path.unlink(missing_ok=True)
        output_base.with_suffix(".srt").unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass


app = FastAPI(title="srt-sub FC worker", docs_url=None, redoc_url=None)


@app.get("/")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/")
@app.post("/invoke")
async def invoke(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise WorkerError("请求体必须是 JSON 对象。")
        return process(payload)
    except WorkerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
