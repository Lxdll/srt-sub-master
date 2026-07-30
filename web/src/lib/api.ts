import type {
  ActionEvent,
  ActionOverview,
  AdminUser,
  AnalyticsDays,
  AnalyticsOverview,
  AnalyticsVisit,
  AuthResponse,
  CursorPage,
  Device,
  PermissionKey,
  Task,
  TaskDetail,
  User,
  ScriptAnalysisResult,
  HotRanksResponse,
  IpUserLink,
  ScriptLibraryDetail,
  ScriptLibraryListResponse,
} from "../types";
import type { components } from "../generated/api";

type ApiSchemas = components["schemas"];

let csrfToken = "";

type ScriptAnalysisPayload = {
  text: string;
  platform?: string;
  audience?: string;
  target_duration_seconds?: number;
  goal?: string;
};

export function setCsrfToken(token: string) {
  csrfToken = token;
}

async function request<T>(
  path: string,
  options: RequestInit & { csrf?: boolean } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.csrf) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  recordPageView(eventId: string, path: string) {
    return request<{ status: "accepted" | "duplicate" }>(
      "/api/analytics/page-view",
      {
        method: "POST",
        body: JSON.stringify({ event_id: eventId, path }),
        keepalive: true,
      },
    );
  },

  async login(username: string, password: string) {
    const result = await request<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setCsrfToken(result.csrf_token);
    return result;
  },

  async me() {
    const result = await request<AuthResponse>("/api/auth/me");
    setCsrfToken(result.csrf_token);
    return result;
  },

  logout() {
    return request<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
      csrf: true,
    });
  },

  createUser(
    username: string,
    password: string,
    permissions: PermissionKey[],
  ) {
    return request<User>("/api/admin/users", {
      method: "POST",
      csrf: true,
      body: JSON.stringify({
        username,
        password,
        is_admin: false,
        permissions,
      }),
    });
  },

  adminUsers() {
    return request<AdminUser[]>("/api/admin/users");
  },

  analyticsOverview(days: AnalyticsDays) {
    return request<AnalyticsOverview>(
      `/api/admin/analytics/overview?days=${days}`,
    );
  },

  analyticsVisits(days: AnalyticsDays, cursor?: string) {
    const params = new URLSearchParams({ days: String(days), limit: "50" });
    if (cursor) params.set("cursor", cursor);
    return request<CursorPage<AnalyticsVisit>>(
      `/api/admin/analytics/visits?${params.toString()}`,
    );
  },

  analyticsIpUsers(
    days: AnalyticsDays,
    query = "",
    cursor?: string,
  ) {
    const params = new URLSearchParams({ days: String(days), limit: "50" });
    if (query) params.set("query", query);
    if (cursor) params.set("cursor", cursor);
    return request<CursorPage<IpUserLink>>(
      `/api/admin/analytics/ip-users?${params.toString()}`,
    );
  },

  analyticsActionsOverview(days: AnalyticsDays) {
    return request<ActionOverview>(
      `/api/admin/analytics/actions/overview?days=${days}`,
    );
  },

  analyticsActions(
    days: AnalyticsDays,
    filters: {
      user_id?: string;
      action?: string;
      outcome?: "success" | "failure";
      cursor?: string;
    } = {},
  ) {
    const params = new URLSearchParams({ days: String(days), limit: "50" });
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value);
    }
    return request<CursorPage<ActionEvent>>(
      `/api/admin/analytics/actions?${params.toString()}`,
    );
  },

  updateUserPermissions(userId: string, permissions: PermissionKey[]) {
    return request<AdminUser>(
      `/api/admin/users/${encodeURIComponent(userId)}/permissions`,
      {
        method: "PATCH",
        csrf: true,
        body: JSON.stringify({ permissions }),
      },
    );
  },

  resetUserPassword(userId: string, password: string) {
    return request<{ ok: boolean }>(
      `/api/admin/users/${encodeURIComponent(userId)}/password`,
      {
        method: "PATCH",
        csrf: true,
        body: JSON.stringify({ password }),
      },
    );
  },

  changePassword(currentPassword: string, newPassword: string) {
    return request<{ ok: boolean }>("/api/auth/password", {
      method: "PATCH",
      csrf: true,
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
  },

  hotRanks(refresh = false) {
    const query = refresh ? "?refresh=true" : "";
    return request<HotRanksResponse>(`/api/hot-ranks${query}`);
  },

  pairCode() {
    return request<{ code: string; expires_at: string }>(
      "/api/devices/pair-code",
      { method: "POST", csrf: true },
    );
  },

  devices() {
    return request<Device[]>("/api/devices");
  },

  commandToken(deviceId: string, taskId?: string) {
    const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
    return request<{ token: string }>(
      `/api/devices/${deviceId}/command-token${query}`,
      { method: "POST", csrf: true },
    );
  },

  tasks() {
    return request<Task[]>("/api/tasks");
  },

  customProhibitedWords() {
    return request<ApiSchemas["CustomProhibitedWordResponse"][]>(
      "/api/prohibited-words/custom",
      { csrf: true },
    );
  },

  addCustomProhibitedWord(term: string) {
    return request<ApiSchemas["CustomProhibitedWordResponse"]>(
      "/api/prohibited-words/custom",
      {
        method: "POST",
        csrf: true,
        body: JSON.stringify({ term }),
      },
    );
  },

  deleteCustomProhibitedWord(wordId: string) {
    return request<{ ok: boolean }>(
      `/api/prohibited-words/custom/${encodeURIComponent(wordId)}`,
      {
        method: "DELETE",
        csrf: true,
      },
    );
  },

  checkProhibitedWords(text: string) {
    return request<ApiSchemas["ProhibitedWordsCheckResponse"]>(
      "/api/prohibited-words/check",
      {
        method: "POST",
        csrf: true,
        body: JSON.stringify({ text }),
      },
    );
  },

  analyzeScript(
    payload: ScriptAnalysisPayload,
    signal?: AbortSignal,
  ) {
    return request<ScriptAnalysisResult>("/api/script-analysis/analyze", {
      method: "POST",
      csrf: true,
      signal,
      body: JSON.stringify(payload),
    });
  },

  async analyzeScriptStream(
    payload: ScriptAnalysisPayload,
    onProgress: (result: ScriptAnalysisResult) => void,
    signal?: AbortSignal,
  ): Promise<ScriptAnalysisResult> {
    const response = await fetch("/api/script-analysis/analyze/stream", {
      method: "POST",
      credentials: "include",
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `请求失败（${response.status}）`);
    }
    if (!response.body) {
      throw new Error("浏览器无法读取脚本拆解的流式响应");
    }

    let result: ScriptAnalysisResult = {
      highlights: [],
      hooks: [],
      suggestions: [],
    };
    let buffer = "";
    let completed = false;
    const decoder = new TextDecoder();
    const reader = response.body.getReader();

    const publish = () => {
      onProgress({
        highlights: [...result.highlights],
        hooks: [...result.hooks],
        suggestions: [...result.suggestions],
      });
    };

    const consumeEvent = (block: string) => {
      let eventName = "";
      const dataLines: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (!eventName || !dataLines.length) return;

      let data: unknown;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        throw new Error("脚本拆解的流式响应格式无效");
      }

      if (eventName === "highlight") {
        result.highlights.push(
          data as ScriptAnalysisResult["highlights"][number],
        );
        publish();
      } else if (eventName === "hook") {
        result.hooks.push(data as ScriptAnalysisResult["hooks"][number]);
        publish();
      } else if (eventName === "suggestion") {
        result.suggestions.push(
          data as ScriptAnalysisResult["suggestions"][number],
        );
        publish();
      } else if (eventName === "result") {
        result = data as ScriptAnalysisResult;
        publish();
      } else if (eventName === "done") {
        completed = true;
      } else if (eventName === "error") {
        const detail =
          typeof data === "object" &&
          data !== null &&
          "detail" in data &&
          typeof data.detail === "string"
            ? data.detail
            : "脚本分析失败，请稍后重试。";
        throw new Error(detail);
      }
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });

        let boundary = buffer.match(/\r?\n\r?\n/);
        while (boundary?.index !== undefined) {
          const block = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          consumeEvent(block);
          boundary = buffer.match(/\r?\n\r?\n/);
        }
        if (done) break;
      }
      if (buffer.trim()) consumeEvent(buffer);
    } finally {
      reader.releaseLock();
    }

    if (!completed) {
      throw new Error("脚本拆解连接意外中断，请重试。");
    }
    return result;
  },

  parseDouyin(text: string) {
    return request<ApiSchemas["DouyinParseResponse"]>("/api/douyin/parse", {
      method: "POST",
      csrf: true,
      body: JSON.stringify({ text }),
    });
  },

  createDouyinTranscription(
    text: string,
    options: {
      backend: "server" | "local_agent";
      device_id?: string;
      model_id?: string;
    } = { backend: "server" },
  ) {
    return request<{ task_id: string }>("/api/douyin/transcriptions", {
      method: "POST",
      csrf: true,
      body: JSON.stringify({ text, ...options }),
    });
  },

  douyinDownloadUrl(ticket: string, quality: string) {
    return `/api/douyin/download/${encodeURIComponent(ticket)}?quality=${encodeURIComponent(quality)}`;
  },

  douyinPreviewUrl(ticket: string, quality: string) {
    return `/api/douyin/preview/${encodeURIComponent(ticket)}?quality=${encodeURIComponent(quality)}`;
  },

  taskMediaUrl(taskId: string) {
    return `/api/tasks/${encodeURIComponent(taskId)}/media`;
  },

  importSrt(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: string }>("/api/tasks/import-srt", {
      method: "POST",
      csrf: true,
      body: form,
    });
  },

  task(taskId: string) {
    return request<TaskDetail>(`/api/tasks/${taskId}`);
  },

  createTask(payload: ApiSchemas["CreateTaskRequest"]) {
    return request<{ id: string; command_token: string }>("/api/tasks", {
      method: "POST",
      csrf: true,
      body: JSON.stringify(payload),
    });
  },

  editSegment(taskId: string, segmentId: string, text: string) {
    return request<{ ok: boolean }>(
      `/api/tasks/${taskId}/segments/${segmentId}`,
      {
        method: "PATCH",
        csrf: true,
        body: JSON.stringify({ text }),
      },
    );
  },

  retryTask(taskId: string) {
    return request<{ ok: boolean }>(`/api/tasks/${taskId}/retry`, {
      method: "POST",
      csrf: true,
    });
  },

  relinkToken(taskId: string, deviceId: string) {
    return request<{ command_token: string }>(
      `/api/tasks/${taskId}/relink?device_id=${encodeURIComponent(deviceId)}`,
      { method: "POST", csrf: true },
    );
  },

  deleteTask(taskId: string) {
    return request<{ ok: boolean }>(`/api/tasks/${taskId}`, {
      method: "DELETE",
      csrf: true,
    });
  },

  scripts(query = "", limit = 20, offset = 0) {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (query.trim()) params.set("q", query.trim());
    return request<ScriptLibraryListResponse>(
      `/api/scripts?${params.toString()}`,
    );
  },

  script(scriptId: string) {
    return request<ScriptLibraryDetail>(
      `/api/scripts/${encodeURIComponent(scriptId)}`,
    );
  },

  createScript(title: string, body: string) {
    return request<ScriptLibraryDetail>("/api/scripts", {
      method: "POST",
      csrf: true,
      body: JSON.stringify({ title, body }),
    });
  },

  updateScript(
    scriptId: string,
    payload: Partial<Pick<ScriptLibraryDetail, "title" | "body">>,
  ) {
    return request<ScriptLibraryDetail>(
      `/api/scripts/${encodeURIComponent(scriptId)}`,
      {
        method: "PATCH",
        csrf: true,
        body: JSON.stringify(payload),
      },
    );
  },

  deleteScript(scriptId: string) {
    return request<{ ok: boolean }>(
      `/api/scripts/${encodeURIComponent(scriptId)}`,
      {
        method: "DELETE",
        csrf: true,
      },
    );
  },
};
