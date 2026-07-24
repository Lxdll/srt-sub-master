from __future__ import annotations

import ctypes
import os
from pathlib import Path
import platform
import socket
import subprocess
from typing import Any


def memory_bytes() -> int:
    try:
        if platform.system() == "Darwin":
            return int(
                subprocess.check_output(
                    ["/usr/sbin/sysctl", "-n", "hw.memsize"], text=True
                ).strip()
            )
        if platform.system() == "Windows":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullTotalPhys)
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def nvidia_available() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return completed.returncode == 0 and bool(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def hardware_info() -> dict[str, Any]:
    total_memory = memory_bytes()
    return {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "memory_bytes": total_memory,
        "memory_gb": round(total_memory / 1024**3, 1) if total_memory else None,
        "nvidia_gpu": nvidia_available(),
    }


def data_disk_free(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return os.statvfs(path).f_bavail * os.statvfs(path).f_frsize if hasattr(os, "statvfs") else 0

