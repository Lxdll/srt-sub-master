// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DouyinPage } from "./DouyinPage";

const mocks = vi.hoisted(() => ({
  parseDouyin: vi.fn(),
  commandToken: vi.fn(),
  health: vi.fn(),
  localParse: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...original,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("../lib/auth", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      username: "tester",
      is_admin: true,
      permissions: [],
    },
  }),
}));

vi.mock("../lib/api", () => ({
  api: {
    parseDouyin: mocks.parseDouyin,
    commandToken: mocks.commandToken,
    douyinDownloadUrl: (ticket: string, quality: string) =>
      `/api/douyin/download/${ticket}?quality=${quality}`,
    douyinPreviewUrl: (ticket: string, quality: string) =>
      `/api/douyin/preview/${ticket}?quality=${quality}`,
  },
}));

vi.mock("../lib/douyin-agent", () => ({
  AGENT_URL: "http://127.0.0.1:43921",
  douyinAgent: {
    health: mocks.health,
    parse: mocks.localParse,
    downloadUrl: (ticket: string, quality: string) =>
      `http://127.0.0.1:43921/douyin/download/${ticket}?quality=${quality}`,
    previewUrl: (ticket: string, quality: string, token: string) =>
      `http://127.0.0.1:43921/douyin/preview/${ticket}?quality=${quality}&command_token=${token}`,
  },
}));

const parsed = {
  ticket: "ticket-1",
  aweme_id: "7372484719365098803",
  title: "测试视频",
  author: "测试作者",
  cover_url: null,
  duration_ms: 12_000,
  qualities: [
    {
      id: "1080p",
      label: "1080P",
      width: 1080,
      height: 1920,
      bitrate: 2_000_000,
      estimated_bytes: 3_000_000,
    },
  ],
  recommended_quality: "1080p",
  expires_at: "2026-07-24T08:00:00Z",
};

describe("DouyinPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete window.showDirectoryPicker;
    delete window.showSaveFilePicker;
  });

  beforeEach(() => {
    mocks.parseDouyin.mockReset().mockResolvedValue(parsed);
    mocks.commandToken.mockReset().mockResolvedValue({ token: "command" });
    mocks.health.mockReset().mockRejectedValue(new Error("not installed"));
    mocks.localParse.mockReset();
    mocks.navigate.mockReset();
  });

  it("parses a share link through cloud and renders the result", async () => {
    render(<DouyinPage />);
    fireEvent.change(screen.getByLabelText("分享文案或视频链接"), {
      target: {
        value:
          "复制打开抖音 https://www.douyin.com/video/7372484719365098803",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "解析视频" }));

    await waitFor(() => expect(mocks.parseDouyin).toHaveBeenCalledOnce());
    expect(await screen.findByText("测试视频")).toBeTruthy();
    expect(screen.getByText("@测试作者")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "保存到指定目录" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "浏览器下载" })).toBeTruthy();
    expect(document.querySelector("video")?.getAttribute("src")).toBe(
      "/api/douyin/preview/ticket-1?quality=1080p",
    );
    expect(screen.queryByRole("button", { name: "本机" })).toBeNull();
  });

  it("falls back to cloud when local parsing fails in auto mode", async () => {
    mocks.health.mockResolvedValue({
      status: "ok",
      paired: true,
      device_id: "device-1",
      version: "0.1.0",
      douyin: true,
    });
    mocks.localParse.mockRejectedValue(new Error("anonymous session rejected"));
    render(<DouyinPage />);

    await screen.findByText("本机可用，失败时自动转云端");
    fireEvent.change(screen.getByLabelText("分享文案或视频链接"), {
      target: { value: "https://v.douyin.com/example/" },
    });
    fireEvent.click(screen.getByRole("button", { name: "解析视频" }));

    await waitFor(() => expect(mocks.localParse).toHaveBeenCalledOnce());
    expect(mocks.parseDouyin).toHaveBeenCalledOnce();
    expect(await screen.findByText("云端解析")).toBeTruthy();
  });

  it("downloads with the browser and reports success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3]), {
        status: 200,
        headers: {
          "Content-Type": "video/mp4",
          "Content-Length": "3",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:video"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<DouyinPage />);
    fireEvent.change(screen.getByLabelText("分享文案或视频链接"), {
      target: { value: "https://v.douyin.com/example/" },
    });
    fireEvent.click(screen.getByRole("button", { name: "解析视频" }));
    await screen.findByText("测试视频");
    fireEvent.click(screen.getByRole("button", { name: "浏览器下载" }));

    expect(
      await screen.findByText("视频下载成功，已交给浏览器保存。"),
    ).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/douyin/download/ticket-1?quality=1080p",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("reports a browser download failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("网络已断开")));

    render(<DouyinPage />);
    fireEvent.change(screen.getByLabelText("分享文案或视频链接"), {
      target: { value: "https://v.douyin.com/example/" },
    });
    fireEvent.click(screen.getByRole("button", { name: "解析视频" }));
    await screen.findByText("测试视频");
    fireEvent.click(screen.getByRole("button", { name: "浏览器下载" }));

    expect(
      await screen.findByText("视频下载失败：网络已断开"),
    ).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("streams the recommended video into a chosen folder", async () => {
    const writable = {
      write: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
      abort: vi.fn().mockResolvedValue(undefined),
    };
    const getFileHandle = vi.fn().mockResolvedValue({
      createWritable: vi.fn().mockResolvedValue(writable),
    });
    window.showDirectoryPicker = vi.fn().mockResolvedValue({ getFileHandle });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: { "Content-Length": "3" },
        }),
      ),
    );

    render(<DouyinPage />);
    fireEvent.change(screen.getByLabelText("分享文案或视频链接"), {
      target: { value: "https://v.douyin.com/example/" },
    });
    fireEvent.click(screen.getByRole("button", { name: "解析视频" }));
    await screen.findByText("测试视频");
    fireEvent.click(screen.getByRole("button", { name: "保存到指定目录" }));

    expect(
      await screen.findByText("视频下载成功，已保存到你指定的目录。"),
    ).toBeTruthy();
    expect(getFileHandle).toHaveBeenCalledWith(
      "测试作者_测试视频_7372484719365098803_1080P.mp4",
      { create: true },
    );
    expect(writable.write).toHaveBeenCalledOnce();
    expect(writable.close).toHaveBeenCalledOnce();
  });
});
