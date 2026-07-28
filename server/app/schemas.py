from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal[
    "uploading",
    "queued",
    "downloading",
    "transcribing",
    "ready",
    "failed",
]
PermissionKey = Literal[
    "subtitle_workspace",
    "douyin_download",
    "prohibited_word_check",
    "script_analysis",
]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[\w.@+-]+$")
    password: str = Field(min_length=8, max_length=256)
    is_admin: bool = False
    permissions: list[PermissionKey] = Field(default_factory=list)


class UpdateUserPermissionsRequest(BaseModel):
    permissions: list[PermissionKey]


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


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
    downloaded_bytes: int | None = Field(default=None, ge=0)
    download_total_bytes: int | None = Field(default=None, ge=0)
    download_speed_bps: float | None = Field(default=None, ge=0)
    download_eta_seconds: int | None = Field(default=None, ge=0)


class EditSegmentRequest(BaseModel):
    text: str = Field(max_length=10_000)


class VerifyCommandRequest(BaseModel):
    token: str
    task_id: str | None = None


class ClaimLocalDouyinTaskRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class AttachAssetRequest(BaseModel):
    local_asset_id: str
    sha256: str
    duration_ms: int
    size_bytes: int


class DouyinParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)


class DouyinTranscriptionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    backend: Literal["server", "local_agent"] = "server"
    device_id: str | None = None
    model_id: Literal["small", "large-v3", "large-v3-turbo"] | None = None


class DouyinTranscriptionResponse(BaseModel):
    task_id: str


class DouyinQualityResponse(BaseModel):
    id: str
    label: str
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    estimated_bytes: int | None = None


class DouyinParseResponse(BaseModel):
    ticket: str
    aweme_id: str
    title: str
    author: str
    cover_url: str | None = None
    duration_ms: int | None = None
    qualities: list[DouyinQualityResponse]
    recommended_quality: str
    expires_at: str


class CustomProhibitedWordRequest(BaseModel):
    term: str = Field(min_length=1, max_length=100)


class CustomProhibitedWordResponse(BaseModel):
    id: str
    term: str
    created_at: str


class ProhibitedWordsCheckRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ProhibitedWordOccurrence(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ProhibitedWordMatch(BaseModel):
    term: str
    category: str
    reason: str
    sources: list[Literal["ai", "custom"]]
    occurrences: list[ProhibitedWordOccurrence]


class ProhibitedWordsCheckResponse(BaseModel):
    matches: list[ProhibitedWordMatch]
    match_count: int = Field(ge=0)
    unique_term_count: int = Field(ge=0)


class ScriptAnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30_000)
    platform: str | None = Field(default=None, max_length=80)
    audience: str | None = Field(default=None, max_length=300)
    target_duration_seconds: int | None = Field(default=None, ge=1, le=7_200)
    goal: str | None = Field(default=None, max_length=500)


class ScriptAnalysisOverview(BaseModel):
    title: str
    synopsis: str
    core_message: str
    target_audience: str
    tone: str
    estimated_duration: str


class ScriptAnalysisBreakdownItem(BaseModel):
    section: int = Field(ge=1)
    label: str
    excerpt: str
    purpose: str
    visuals: list[str]
    assets: list[str]
    on_screen_text: list[str]
    audio: list[str]
    production_notes: str


class ScriptAnalysisRequirementItem(BaseModel):
    name: str
    purpose: str
    priority: Literal["必需", "建议"]


class ScriptAnalysisRequirementGroup(BaseModel):
    category: str
    items: list[ScriptAnalysisRequirementItem]


class ScriptAnalysisHighlight(BaseModel):
    excerpt: str
    reason: str
    leverage: str


class ScriptAnalysisHook(BaseModel):
    excerpt: str
    hook_type: str
    position: str
    mechanism: str
    strength: Literal["强", "中", "弱"]
    suggestion: str


class ScriptAnalysisSuggestion(BaseModel):
    area: str
    issue: str
    recommendation: str


class ScriptAnalysisResponse(BaseModel):
    overview: ScriptAnalysisOverview
    breakdown: list[ScriptAnalysisBreakdownItem]
    requirements: list[ScriptAnalysisRequirementGroup]
    highlights: list[ScriptAnalysisHighlight]
    hooks: list[ScriptAnalysisHook]
    suggestions: list[ScriptAnalysisSuggestion]
