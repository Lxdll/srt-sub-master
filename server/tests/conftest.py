from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pytest
from fastapi.testclient import TestClient


TEST_ROOT = Path(tempfile.mkdtemp(prefix="srt-sub-server-tests-"))
os.environ["SRT_DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["SRT_WEB_DIST"] = str(TEST_ROOT / "web")
os.environ["SRT_PUBLIC_URL"] = "https://subtitles.test"
os.environ["SRT_ALLOWED_ORIGINS"] = "https://subtitles.test"
os.environ["SRT_SESSION_SECRET"] = "test-secret-that-is-long-and-random-enough"
os.environ["SRT_COOKIE_SECURE"] = "false"
os.environ["SRT_ADMIN_USERNAME"] = "admin"
os.environ["SRT_ADMIN_PASSWORD"] = "admin-password-123"
os.environ["SRT_TRANSCRIPTION_BACKEND"] = "local"
os.environ["SRT_FC_CALLBACK_SECRET"] = "test-fc-callback-secret-32-characters"

from server.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app, base_url="https://subtitles.test") as test_client:
        yield test_client


def login(test_client: TestClient, username: str, password: str) -> str:
    response = test_client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]
