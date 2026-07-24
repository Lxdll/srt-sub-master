import type {
  AuthResponse,
  Device,
  Task,
  TaskDetail,
  User,
} from "../types";
import type { components } from "../generated/api";

type ApiSchemas = components["schemas"];

let csrfToken = "";

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

  createUser(username: string, password: string) {
    return request<User>("/api/admin/users", {
      method: "POST",
      csrf: true,
      body: JSON.stringify({ username, password, is_admin: false }),
    });
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
};
