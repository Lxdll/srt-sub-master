from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["uploading", "queued", "transcribing", "ready", "failed"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[\w.@+-]+$")
    password: str = Field(min_length=8, max_length=256)
    is_admin: bool = False


class PairDeviceRequest(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=40)
    origin: str
    hardware: dict[str, Any] = Field(default_factory=dict)
    models: list[dict[str, Any]] = Field(default_factory=list)


class CreateTaskRequest(BaseModel):
    device_id: str
    original_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    model_id: str = Field(min_length=1, max_length=120)


class SegmentResult(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str


class TaskResultRequest(BaseModel):
    local_asset_id: str
    sha256: str = Field(min_length=64, max_length=64)
    duration_ms: int = Field(gt=0)
    size_bytes: int = Field(gt=0)
    segments: list[SegmentResult]


class TaskProgressRequest(BaseModel):
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    error: str | None = None


class EditSegmentRequest(BaseModel):
    text: str = Field(max_length=10_000)


class VerifyCommandRequest(BaseModel):
    token: str
    task_id: str | None = None


class AttachAssetRequest(BaseModel):
    local_asset_id: str
    sha256: str
    duration_ms: int
    size_bytes: int
