from __future__ import annotations

from functools import lru_cache

from opencc import OpenCC


@lru_cache(maxsize=1)
def _traditional_to_simplified() -> OpenCC:
    return OpenCC("t2s")


def to_simplified_chinese(text: str) -> str:
    """Normalize recognized Chinese text to Simplified Chinese."""

    return _traditional_to_simplified().convert(text)
