from __future__ import annotations

import pytest

from fc_worker.app import WorkerError, _source_allowed, _validate_payload


def test_fc_worker_allows_only_expected_public_media_hosts():
    assert _source_allowed(
        "https://v5-se.douyinvod.com/video/test.mp4",
        set(),
    )
    assert _source_allowed(
        "https://download.example.com/video/test.mp4",
        {"download.example.com"},
    )
    assert not _source_allowed("http://v5-se.douyinvod.com/test.mp4", set())
    assert not _source_allowed("https://127.0.0.1/test.mp4", {"127.0.0.1"})
    assert not _source_allowed(
        "https://metadata.internal/test.mp4",
        {"metadata.internal"},
    )


def test_fc_worker_validates_task_identity_and_limits():
    task_id, attempt = _validate_payload(
        {
            "task_id": "b2e16f90-aac5-4372-9a65-c7ba22bbce10",
            "attempt": 2,
            "max_source_bytes": 500,
            "max_duration_seconds": 1800,
        }
    )
    assert task_id.endswith("ce10")
    assert attempt == 2
    with pytest.raises(WorkerError):
        _validate_payload(
            {
                "task_id": "../../etc/passwd",
                "attempt": 1,
                "max_source_bytes": 500,
                "max_duration_seconds": 1800,
            }
        )
