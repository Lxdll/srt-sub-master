from __future__ import annotations

import pytest

from fc_worker.app import WorkerError, _source_allowed, _transcribe, _validate_payload


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


def test_fc_worker_forces_chinese_language(monkeypatch, tmp_path):
    command: list[str] = []

    class Process:
        def __init__(self):
            self.stdout = []

        def wait(self):
            return 0

    def popen(received, **_kwargs):
        command.extend(received)
        output_index = received.index("--output-file") + 1
        tmp_path.joinpath("transcript.srt").write_text("", encoding="utf-8")
        assert received[output_index] == str(tmp_path / "transcript")
        return Process()

    monkeypatch.setattr("fc_worker.app.subprocess.Popen", popen)
    settings = type(
        "Settings",
        (),
        {
            "whisper_path": "whisper-cli",
            "model_path": "model.bin",
            "threads": 4,
            "vad_model_path": "vad.bin",
        },
    )()

    _transcribe(
        settings,
        "b2e16f90-aac5-4372-9a65-c7ba22bbce10",
        1,
        tmp_path / "audio.wav",
        tmp_path / "transcript",
    )

    language_index = command.index("--language")
    assert command[language_index + 1] == "zh"
