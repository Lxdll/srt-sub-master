import os
from pathlib import Path
import sys


bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
bundled_bin = bundle_root / "agent" / "bin"
if bundled_bin.is_dir():
    os.environ["PATH"] = f"{bundled_bin}{os.pathsep}{os.environ.get('PATH', '')}"

from agent.app.main import run  # noqa: E402


if __name__ == "__main__":
    run()
