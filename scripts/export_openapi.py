from __future__ import annotations

import json
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from server.app.main import app  # noqa: E402


output = project_root / "web" / "openapi.json"
output.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"OpenAPI written to {output}")
