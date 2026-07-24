from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pytest
from fastapi.testclient import TestClient


TEST_ROOT = Path(tempfile.mkdtemp(prefix="srt-sub-agent-tests-"))
os.environ["SRT_AGENT_DATA_DIR"] = str(TEST_ROOT)
os.environ["SRT_AGENT_ALLOWED_ORIGINS"] = "http://localhost:5173"

from agent.app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
