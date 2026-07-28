from __future__ import annotations

import re
from typing import Any


TIMESTAMP = re.compile(
    r"^(?P<start>\d{1,3}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,3}:\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$"
)


class SrtError(ValueError):
    pass


def _milliseconds(value: str) -> int:
    hours, minutes, rest = value.replace(".", ",").split(":")
    seconds, milliseconds = rest.split(",")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(milliseconds)
    )


def parse_srt(content: str) -> list[dict[str, Any]]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise SrtError("SRT 文件是空的")
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\n{2,}", normalized):
        lines = [line.strip("\ufeff") for line in block.split("\n")]
        if not lines:
            continue
        timestamp_index = next(
            (index for index, line in enumerate(lines) if TIMESTAMP.match(line.strip())),
            None,
        )
        if timestamp_index is None:
            raise SrtError(f"无法识别时间轴：{lines[0][:80]}")
        match = TIMESTAMP.match(lines[timestamp_index].strip())
        if not match:
            raise SrtError("SRT 时间轴格式不正确")
        start_ms = _milliseconds(match.group("start"))
        end_ms = _milliseconds(match.group("end"))
        text = "\n".join(lines[timestamp_index + 1 :]).strip()
        if end_ms <= start_ms:
            raise SrtError("字幕结束时间必须晚于开始时间")
        if not text:
            continue
        segments.append(
            {"start_ms": start_ms, "end_ms": end_ms, "text": text}
        )
    if not segments:
        raise SrtError("SRT 中没有可用字幕")
    return segments
