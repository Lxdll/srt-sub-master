import type { DouyinParseResult, LocalHealth, ModelInfo } from "../types";

export const AGENT_URL = "http://127.0.0.1:43921";

type LocalRequestInit = RequestInit & {
  targetAddressSpace?: "loopback";
};

async function localFetch<T>(
  path: string,
  options: LocalRequestInit = {},
): Promise<T> {
  const response = await fetch(`${AGENT_URL}${path}`, {
    ...options,
    targetAddressSpace: "loopback",
  } as RequestInit);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `本机组件请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export const douyinAgent = {
  health(signal?: AbortSignal) {
    return localFetch<LocalHealth & { douyin?: boolean }>("/health", { signal });
  },

  pair(code: string) {
    const origin = window.location.origin;
    return localFetch<{ ok: boolean; device_id: string }>("/pair", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        code,
        origin,
        server_url: origin,
      }),
    });
  },

  parse(text: string, commandToken: string) {
    return localFetch<DouyinParseResult>("/douyin/parse", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Command-Token": commandToken,
      },
      body: JSON.stringify({ text }),
    });
  },

  models() {
    return localFetch<ModelInfo[]>("/models");
  },

  downloadModel(modelId: string, commandToken: string) {
    return localFetch<{
      status: "queued" | "downloading" | "ready" | "failed";
      progress: number;
      error?: string;
    }>(`/models/${encodeURIComponent(modelId)}/download`, {
      method: "POST",
      headers: {"X-Command-Token": commandToken},
    });
  },

  downloadUrl(ticket: string, quality: string) {
    return `${AGENT_URL}/douyin/download/${encodeURIComponent(ticket)}?quality=${encodeURIComponent(quality)}`;
  },

  previewUrl(ticket: string, quality: string, commandToken: string) {
    const query = new URLSearchParams({
      quality,
      command_token: commandToken,
    });
    return `${AGENT_URL}/douyin/preview/${encodeURIComponent(ticket)}?${query}`;
  },

  assetUrl(assetId: string, taskId: string, commandToken: string) {
    const query = new URLSearchParams({
      task_id: taskId,
      token: commandToken,
    });
    return `${AGENT_URL}/assets/${encodeURIComponent(assetId)}?${query}`;
  },
};
