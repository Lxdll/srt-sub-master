---
name: local-video-to-srt
description: Transcribe a local video or audio file into an SRT subtitle file without uploading media. Use when a user asks any AI assistant to create subtitles, transcribe speech locally, or prepare an SRT for later correction.
---

# Local video to SRT

Keep the input media, model, and generated SRT on the user's computer.

## Workflow

1. Run the environment check:

   ```bash
   python3 scripts/local_video_to_srt.py doctor --json
   ```

2. If `ready` is false, report the missing dependency. Install Python packages from the platform-specific requirements file only after the user approves installation.

3. List model choices when the user has not selected one:

   ```bash
   python3 scripts/local_video_to_srt.py models --json
   ```

4. Transcribe the local file:

   ```bash
   python3 scripts/local_video_to_srt.py transcribe "/absolute/input.mp4" \
     --output "/absolute/output.srt" \
     --model large-v3-turbo \
     --language zh \
     --json
   ```

5. Return the absolute SRT path and the segment count. Do not upload the source media or model files.

## Model selection

- `large-v3`: highest accuracy; prefer with at least 16 GB memory.
- `large-v3-turbo`: balanced default.
- `small`: lower memory use and faster setup.

Use `--model-path` when the user already has a local model directory. Otherwise the selected engine may retrieve the model from its original Hugging Face repository during transcription.

## Contract

Machine-readable commands print one JSON object to stdout. Treat a nonzero exit code or `"status": "error"` as failure. The portable command contract is also described in `skill.json`.
