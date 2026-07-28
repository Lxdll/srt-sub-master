import type { components } from "./generated/api";

export type TaskStatus =
  components["schemas"]["TaskProgressRequest"]["status"];

export type PermissionKey =
  | "subtitle_workspace"
  | "douyin_download"
  | "prohibited_word_check";

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  permissions: PermissionKey[];
}

export interface AdminUser extends User {
  created_at: string;
}

export interface AuthResponse {
  user: User;
  csrf_token: string;
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
