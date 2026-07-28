import type { PermissionKey, User } from "../types";

export const FEATURE_LABELS: Record<PermissionKey, string> = {
  subtitle_workspace: "字幕校对",
  douyin_download: "抖音下载",
  prohibited_word_check: "违禁词检测",
};

export const FEATURE_PERMISSIONS = Object.keys(
  FEATURE_LABELS,
) as PermissionKey[];

export function hasPermission(
  user: User | null | undefined,
  permission: PermissionKey,
) {
  return Boolean(user?.is_admin || user?.permissions.includes(permission));
}

export function defaultPath(user: User | null | undefined) {
  if (hasPermission(user, "douyin_download")) return "/douyin";
  if (hasPermission(user, "prohibited_word_check")) return "/prohibited-words";
  if (hasPermission(user, "subtitle_workspace")) return "/subtitle";
  return "/no-access";
}
