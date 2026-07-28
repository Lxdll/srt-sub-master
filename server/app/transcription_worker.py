from __future__ import annotations

import asyncio

from .transcription import run_worker


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
