import type { PermissionKey, User } from "../types";

export const FEATURE_LABELS: Record<PermissionKey, string> = {
  subtitle_workspace: "字幕校对",
  douyin_download: "抖音下载",
  prohibited_word_check: "违禁词检测",
  script_analysis: "脚本拆解",
  script_fission: "脚本裂变",
  script_library: "共享脚本库",
};

export const FEATURE_PERMISSIONS = Object.keys(
  FEATURE_LABELS,
) as PermissionKey[];

export type ToolKey =
  | "douyin_transcribe"
  | "douyin_download"
  | "subtitle_workspace"
  | "prohibited_word_check"
  | "script_analysis"
  | "script_fission"
  | "script_library";

export interface ToolDefinition {
  key: ToolKey;
  title: string;
  description: string;
  input: string;
  output: string;
  path: string;
  group: "video" | "copy";
  permissions: PermissionKey[];
  featured?: boolean;
}

export const TOOLS: ToolDefinition[] = [
  {
    key: "douyin_transcribe",
    title: "抖音转文案",
    description: "从分享链接开始，自动下载视频并生成可编辑字幕。",
    input: "抖音分享链接",
    output: "逐句字幕与 SRT",
    path: "/douyin-transcribe",
    group: "video",
    permissions: ["douyin_download", "subtitle_workspace"],
    featured: true,
  },
  {
    key: "douyin_download",
    title: "抖音下载",
    description: "解析抖音分享内容，选择清晰度并保存无水印视频。",
    input: "抖音分享链接",
    output: "无水印视频",
    path: "/douyin",
    group: "video",
    permissions: ["douyin_download"],
  },
  {
    key: "subtitle_workspace",
    title: "字幕校对",
    description: "导入 SRT，配合视频逐句校时、修改并重新导出。",
    input: "SRT 字幕文件",
    output: "校对后的字幕",
    path: "/subtitle",
    group: "video",
    permissions: ["subtitle_workspace"],
  },
  {
    key: "prohibited_word_check",
    title: "违禁词检测",
    description: "快速标记文案中的风险词，并管理自己的检测词库。",
    input: "待检测文案",
    output: "风险标记结果",
    path: "/prohibited-words",
    group: "copy",
    permissions: ["prohibited_word_check"],
  },
  {
    key: "script_analysis",
    title: "脚本拆解",
    description: "识别亮点、钩子和节奏问题，提炼可复用的表达结构。",
    input: "视频脚本文案",
    output: "拆解与优化建议",
    path: "/script-analysis",
    group: "copy",
    permissions: ["script_analysis"],
  },
  {
    key: "script_fission",
    title: "脚本裂变",
    description: "基于一个好脚本，规划三个方向并生成三篇差异化新脚本。",
    input: "文字或共享脚本",
    output: "3 篇可编辑脚本",
    path: "/script-fission",
    group: "copy",
    permissions: ["script_fission"],
    featured: true,
  },
  {
    key: "script_library",
    title: "共享脚本库",
    description: "集中保存团队脚本，按标题或正文快速搜索和复用。",
    input: "文字或 Word 文档",
    output: "可搜索的共享脚本",
    path: "/script-library",
    group: "copy",
    permissions: ["script_library"],
  },
];

export function hasPermission(
  user: User | null | undefined,
  permission: PermissionKey,
) {
  return Boolean(user?.is_admin || user?.permissions.includes(permission));
}

export function canUseTool(
  user: User | null | undefined,
  tool: ToolDefinition,
) {
  return tool.permissions.every((permission) => hasPermission(user, permission));
}
