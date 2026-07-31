from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    "script_fission",
    "script_library",
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
    highlights: list[ScriptAnalysisHighlight]
    hooks: list[ScriptAnalysisHook]
    suggestions: list[ScriptAnalysisSuggestion]


class ScriptFissionSourceRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=30_000)
    source_script_id: str | None = Field(default=None, min_length=1, max_length=64)
    requirements: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def require_one_source(self) -> "ScriptFissionSourceRequest":
        if (self.text is None) == (self.source_script_id is None):
            raise ValueError("粘贴脚本和共享脚本来源必须且只能提供一个")
        return self


class ScriptFissionDirection(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    angle: str = Field(min_length=1, max_length=500)
    hook_strategy: str = Field(min_length=1, max_length=500)
    structure_strategy: str = Field(min_length=1, max_length=800)


class ScriptFissionPlanRequest(ScriptFissionSourceRequest):
    pass


class ScriptFissionPlanResponse(BaseModel):
    directions: list[ScriptFissionDirection] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def require_unique_directions(self) -> "ScriptFissionPlanResponse":
        ids = [item.id.casefold() for item in self.directions]
        names = [item.name.casefold() for item in self.directions]
        if len(set(ids)) != 3 or len(set(names)) != 3:
            raise ValueError("三个裂变方向必须互不重复")
        return self


class ScriptFissionGenerateRequest(ScriptFissionSourceRequest):
    directions: list[ScriptFissionDirection] = Field(min_length=3, max_length=3)
    direction_id: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_plan(self) -> "ScriptFissionGenerateRequest":
        ids = [item.id.casefold() for item in self.directions]
        names = [item.name.casefold() for item in self.directions]
        angles = [item.angle.casefold() for item in self.directions]
        if len(set(ids)) != 3 or len(set(names)) != 3 or len(set(angles)) != 3:
            raise ValueError("三个裂变方向必须互不重复")
        if self.direction_id not in [item.id for item in self.directions]:
            raise ValueError("目标裂变方向不存在")
        return self


class ScriptFissionGenerateResponse(BaseModel):
    direction_id: str
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=30_000)


class ScriptCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=30_000)


class ScriptUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=30_000)

    @model_validator(mode="after")
    def require_change(self) -> "ScriptUpdateRequest":
        if self.title is None and self.body is None:
            raise ValueError("至少需要提供一个要修改的字段")
        return self


class ScriptAuthorResponse(BaseModel):
    id: str
    username: str


class ScriptListItemResponse(BaseModel):
    id: str
    title: str
    excerpt: str
    matched_in: list[Literal["title", "body"]]
    character_count: int = Field(ge=0)
    created_by: ScriptAuthorResponse
    updated_by: ScriptAuthorResponse
    created_at: str
    updated_at: str


class ScriptListResponse(BaseModel):
    items: list[ScriptListItemResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ScriptDetailResponse(BaseModel):
    id: str
    title: str
    body: str
    character_count: int = Field(ge=0)
    created_by: ScriptAuthorResponse
    updated_by: ScriptAuthorResponse
    created_at: str
    updated_at: str


class HotRankItemResponse(BaseModel):
    rank: int = Field(ge=1, le=10)
    title: str
    url: str
    hot_value: str | None = None
    badge: str | None = None


class HotRankPlatformResponse(BaseModel):
    platform: Literal["rednote", "douyin", "bilibili"]
    display_name: str
    status: Literal["fresh", "stale", "unavailable"]
    source: Literal["60s", "uapi"] | None
    updated_at: str | None
    items: list[HotRankItemResponse]


class HotRanksResponse(BaseModel):
    generated_at: str
    platforms: list[HotRankPlatformResponse]


class PageViewRequest(BaseModel):
    event_id: UUID
    path: str = Field(min_length=1, max_length=256, pattern=r"^/")


class AnalyticsLocationResponse(BaseModel):
    country: str | None = None
    province: str | None = None
    city: str | None = None
    isp: str | None = None
    label: str


class AnalyticsDailyResponse(BaseModel):
    day: str
    page_views: int = Field(ge=0)
    unique_ips: int = Field(ge=0)


class AnalyticsSummaryResponse(BaseModel):
    today_page_views: int = Field(ge=0)
    today_unique_ips: int = Field(ge=0)
    period_page_views: int = Field(ge=0)
    period_unique_ips: int = Field(ge=0)


class AnalyticsLocationCountResponse(AnalyticsLocationResponse):
    page_views: int = Field(ge=0)


class GeoStatusResponse(BaseModel):
    ipv4: bool
    ipv6: bool


class AnalyticsOverviewResponse(BaseModel):
    days: Literal[7, 30, 90]
    from_at: str
    to_at: str
    timezone: Literal["Asia/Shanghai"]
    summary: AnalyticsSummaryResponse
    daily: list[AnalyticsDailyResponse]
    locations: list[AnalyticsLocationCountResponse]
    geo_status: GeoStatusResponse


class VisitResponse(BaseModel):
    id: str
    occurred_at: str
    ip_address: str
    location: AnalyticsLocationResponse
    path: str
    user_id: str | None = None
    username: str | None = None


class VisitListResponse(BaseModel):
    items: list[VisitResponse]
    next_cursor: str | None = None


class IpUserAccountResponse(BaseModel):
    id: str
    username: str
    first_login_at: str | None = None
    last_login_at: str | None = None
    last_seen_at: str
    login_count: int = Field(ge=0)
    page_view_count: int = Field(ge=0)
    action_count: int = Field(ge=0)


class IpUserLinkResponse(BaseModel):
    ip_address: str
    location: AnalyticsLocationResponse
    first_seen_at: str
    last_seen_at: str
    login_count: int = Field(ge=0)
    page_view_count: int = Field(ge=0)
    action_count: int = Field(ge=0)
    users: list[IpUserAccountResponse]


class IpUserListResponse(BaseModel):
    items: list[IpUserLinkResponse]
    next_cursor: str | None = None


class ActionSummaryResponse(BaseModel):
    total: int = Field(ge=0)
    success: int = Field(ge=0)
    failure: int = Field(ge=0)
    active_users: int = Field(ge=0)


class ActionDailyResponse(BaseModel):
    day: str
    success: int = Field(ge=0)
    failure: int = Field(ge=0)


class ActionCountResponse(BaseModel):
    action_key: str
    event_count: int = Field(ge=0)


class ActionOverviewResponse(BaseModel):
    days: Literal[7, 30, 90]
    summary: ActionSummaryResponse
    daily: list[ActionDailyResponse]
    top_actions: list[ActionCountResponse]


class ActionEventResponse(BaseModel):
    id: str
    occurred_at: str
    user_id: str | None = None
    username: str | None = None
    ip_address: str
    location: AnalyticsLocationResponse
    action_key: str
    outcome: Literal["success", "failure"]
    http_status: int
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict[str, Any]


class ActionEventListResponse(BaseModel):
    items: list[ActionEventResponse]
    next_cursor: str | None = None
