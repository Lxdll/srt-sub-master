import type { components } from "./generated/api";

export type TaskStatus =
  components["schemas"]["TaskProgressRequest"]["status"];

export type PermissionKey =
  | "subtitle_workspace"
  | "douyin_download"
  | "prohibited_word_check"
  | "script_analysis"
  | "script_library";

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  permissions: PermissionKey[];
}

export interface AdminUser extends User {
  created_at: string;
}

export type AnalyticsDays = 7 | 30 | 90;

export interface AnalyticsLocation {
  country: string | null;
  province: string | null;
  city: string | null;
  isp: string | null;
  label: string;
}

export interface AnalyticsOverview {
  days: AnalyticsDays;
  from_at: string;
  to_at: string;
  timezone: "Asia/Shanghai";
  summary: {
    today_page_views: number;
    today_unique_ips: number;
    period_page_views: number;
    period_unique_ips: number;
  };
  daily: Array<{ day: string; page_views: number; unique_ips: number }>;
  locations: Array<AnalyticsLocation & { page_views: number }>;
  geo_status: { ipv4: boolean; ipv6: boolean };
}

export interface AnalyticsVisit {
  id: string;
  occurred_at: string;
  ip_address: string;
  location: AnalyticsLocation;
  path: string;
  user_id: string | null;
  username: string | null;
}

export interface IpUserLink {
  ip_address: string;
  location: AnalyticsLocation;
  first_seen_at: string;
  last_seen_at: string;
  login_count: number;
  page_view_count: number;
  action_count: number;
  users: Array<{
    id: string;
    username: string;
    first_login_at: string | null;
    last_login_at: string | null;
    last_seen_at: string;
    login_count: number;
    page_view_count: number;
    action_count: number;
  }>;
}

export interface ActionOverview {
  days: AnalyticsDays;
  summary: {
    total: number;
    success: number;
    failure: number;
    active_users: number;
  };
  daily: Array<{ day: string; success: number; failure: number }>;
  top_actions: Array<{ action_key: string; event_count: number }>;
}

export interface ActionEvent {
  id: string;
  occurred_at: string;
  user_id: string | null;
  username: string | null;
  ip_address: string;
  location: AnalyticsLocation;
  action_key: string;
  outcome: "success" | "failure";
  http_status: number;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

export interface AuthResponse {
  user: User;
  csrf_token: string;
}

export type HotRankPlatformKey = "rednote" | "douyin" | "bilibili";
export type HotRankStatus = "fresh" | "stale" | "unavailable";
export type HotRankSource = "60s" | "uapi" | null;

export interface HotRankItem {
  rank: number;
  title: string;
  url: string;
  hot_value?: string | null;
  badge?: string | null;
}

export interface HotRankPlatform {
  platform: HotRankPlatformKey;
  display_name: string;
  status: HotRankStatus;
  source: HotRankSource;
  updated_at: string | null;
  items: HotRankItem[];
}

export interface HotRanksResponse {
  generated_at: string;
  platforms: HotRankPlatform[];
}

export interface Device {
  id: string;
  name: string;
  platform: string;
  online: boolean;
  last_seen_at: string | null;
  hardware: Record<string, unknown>;
  models: ModelInfo[];
}

export interface ModelInfo {
  id: string;
  label: string;
  description: string;
  approximate_bytes: number;
  installed: boolean;
  recommended: boolean;
  download?: {
    status: "queued" | "downloading" | "ready" | "failed";
    progress: number;
    error?: string;
  } | null;
}

export interface LocalHealth {
  status: string;
  paired: boolean;
  device_id?: string;
  version: string;
}

export interface LocalSystem {
  hardware: {
    hostname: string;
    platform: string;
    architecture: string;
    memory_gb: number | null;
    nvidia_gpu: boolean;
  };
  models: ModelInfo[];
  device_id?: string;
  server_url?: string;
}

export interface Task {
  id: string;
  device_id: string | null;
  backend: "local_agent" | "server_local" | "fc" | "imported";
  original_name: string;
  size_bytes: number;
  duration_ms: number | null;
  sha256: string | null;
  model_id: string;
  status: TaskStatus;
  progress: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  source_type?: "douyin";
  media_available?: boolean;
  media_expires_at?: string | null;
  queue_position?: number | null;
  downloaded_bytes?: number;
  download_total_bytes?: number;
  download_speed_bps?: number;
  download_eta_seconds?: number | null;
}

export interface Segment {
  id: string;
  ordinal: number;
  start_ms: number;
  end_ms: number;
  original_text: string;
  edited_text: string;
  updated_at: string;
}

export interface DeviceAsset {
  id: string;
  device_id: string;
  device_name: string;
  local_asset_id: string;
}

export interface TaskDetail extends Task {
  segments: Segment[];
  device_assets: DeviceAsset[];
}

export type DouyinParseResult =
  components["schemas"]["DouyinParseResponse"];

export type CustomProhibitedWord =
  components["schemas"]["CustomProhibitedWordResponse"];

export type ProhibitedWordsCheckResult =
  components["schemas"]["ProhibitedWordsCheckResponse"];

export type ScriptAnalysisResult =
  components["schemas"]["ScriptAnalysisResponse"];

export type ScriptLibraryUser =
  components["schemas"]["ScriptAuthorResponse"];

export type ScriptLibraryListItem =
  components["schemas"]["ScriptListItemResponse"];

export type ScriptLibraryDetail =
  components["schemas"]["ScriptDetailResponse"];

export type ScriptLibraryListResponse =
  components["schemas"]["ScriptListResponse"];
