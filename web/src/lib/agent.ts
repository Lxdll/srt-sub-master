import type { LocalHealth, LocalSystem, ModelInfo } from "../types";

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
    throw new Error(body.detail || `本机识别器请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export const agent = {
  health(signal?: AbortSignal) {
    return localFetch<LocalHealth>("/health", { signal });
  },

  system() {
    return localFetch<LocalSystem>("/system");
  },

  pair(serverUrl: string, origin: string, code: string) {
    return localFetch<{ ok: boolean; device_id: string }>("/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server_url: serverUrl, origin, code }),
    });
  },

  models() {
    return localFetch<ModelInfo[]>("/models");
  },

  downloadModel(modelId: string, commandToken: string) {
    return localFetch<{ status: string; progress: number }>(
      `/models/${modelId}/download`,
      {
        method: "POST",
        headers: { "X-Command-Token": commandToken },
      },
    );
  },

  job(taskId: string, commandToken: string) {
    return localFetch<{
      task_id: string;
      status: string;
      progress: number;
      error?: string;
    }>(
      `/jobs/${taskId}?token=${encodeURIComponent(commandToken)}`,
    );
  },
};

function upload(
  url: string,
  form: FormData,
  commandToken: string,
  onProgress: (progress: number) => void,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${AGENT_URL}${url}`);
    xhr.setRequestHeader("X-Command-Token", commandToken);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      const body = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body);
      } else {
        reject(new Error(body.detail || "本机视频传输失败"));
      }
    };
    xhr.onerror = () => reject(new Error("无法连接本机识别器"));
    xhr.send(form);
  });
}

export function uploadJob(
  file: File,
  taskId: string,
  modelId: string,
  commandToken: string,
  onProgress: (progress: number) => void,
) {
  const form = new FormData();
  form.append("file", file);
  form.append("task_id", taskId);
  form.append("model_id", modelId);
  return upload("/jobs", form, commandToken, onProgress);
}

export function relinkVideo(
  file: File,
  taskId: string,
  commandToken: string,
  onProgress: (progress: number) => void,
) {
  const form = new FormData();
  form.append("file", file);
  form.append("task_id", taskId);
  return upload("/assets/relink", form, commandToken, onProgress);
}
