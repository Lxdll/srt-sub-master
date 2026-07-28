// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DouyinTranscribePage } from "./DouyinTranscribePage";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  devices: vi.fn(),
  health: vi.fn(),
  pairCode: vi.fn(),
  pair: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: {
    createDouyinTranscription: mocks.create,
    devices: mocks.devices,
    pairCode: mocks.pairCode,
  },
}));

vi.mock("../lib/douyin-agent", () => ({
  douyinAgent: {
    health: mocks.health,
    pair: mocks.pair,
  },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...original,
    useNavigate: () => mocks.navigate,
    useLocation: () => ({
      state: {
        text: "https://www.douyin.com/video/7372484719365098803",
      },
    }),
  };
});

describe("DouyinTranscribePage", () => {
  beforeEach(() => {
    mocks.create.mockReset().mockResolvedValue({ task_id: "task-1" });
    mocks.health.mockReset().mockResolvedValue({
      status: "ok",
      paired: true,
      device_id: "device-1",
      version: "0.1.0",
      douyin: true,
    });
    mocks.devices.mockReset().mockResolvedValue([
      {
        id: "device-1",
        name: "测试 Mac",
        platform: "Darwin",
        online: true,
        last_seen_at: new Date().toISOString(),
        hardware: {},
        models: [
          {
            id: "large-v3-turbo",
            label: "Large V3 Turbo",
            description: "均衡",
            approximate_bytes: 1,
            installed: true,
            recommended: true,
          },
        ],
      },
    ]);
    mocks.pairCode.mockReset();
    mocks.pair.mockReset();
    mocks.navigate.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("creates a local Agent transcription by default and opens the editor", async () => {
    render(<DouyinTranscribePage />);
    await screen.findByText("测试 Mac已连接");
    fireEvent.click(
      screen.getByRole("button", { name: "在本机转成文案" }),
    );

    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        "https://www.douyin.com/video/7372484719365098803",
        {
          backend: "local_agent",
          device_id: "device-1",
          model_id: "large-v3-turbo",
        },
      ),
    );
    expect(mocks.navigate).toHaveBeenCalledWith("/tasks/task-1");
  });

  it("keeps the user on the page when task creation fails", async () => {
    mocks.create.mockRejectedValue(new Error("服务器转写队列已满，请稍后再试。"));
    render(<DouyinTranscribePage />);
    fireEvent.click(
      await screen.findByRole("button", { name: /^服务器转写/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "用服务器转成文案" }),
    );

    expect(
      await screen.findByText("服务器转写队列已满，请稍后再试。"),
    ).toBeTruthy();
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("shows an explicit offline message and does not silently use the server", async () => {
    mocks.health.mockRejectedValue(new Error("offline"));
    mocks.devices.mockResolvedValue([]);
    render(<DouyinTranscribePage />);
    await screen.findByText("未检测到当前账号的在线 Agent");
    fireEvent.click(
      screen.getByRole("button", { name: "在本机转成文案" }),
    );

    expect(
      await screen.findByText(
        "本机 Agent 离线或未与当前账号配对，请先启动并连接。",
      ),
    ).toBeTruthy();
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
