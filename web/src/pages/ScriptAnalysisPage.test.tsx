// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScriptAnalysisPage } from "./ScriptAnalysisPage";

const mocks = vi.hoisted(() => ({
  analyze: vi.fn(),
  extractDocxText: vi.fn(),
  writeText: vi.fn(),
  readText: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: {
    analyzeScript: mocks.analyze,
  },
}));

vi.mock("../lib/docx", () => ({
  DocxError: class DocxError extends Error {},
  extractDocxText: mocks.extractDocxText,
}));

const result = {
  overview: {
    title: "从五分钟开始",
    synopsis: "用反问引出降低行动门槛的方法。",
    core_message: "小目标更容易形成持续行动。",
    target_audience: "希望建立习惯的人",
    tone: "直接、鼓励",
    estimated_duration: "约 25 秒",
  },
  breakdown: [
    {
      section: 1,
      label: "反问开场",
      excerpt: "你知道为什么大多数人坚持不下来吗？",
      purpose: "制造共鸣",
      visuals: ["人物直视镜头"],
      assets: ["近景机位"],
      on_screen_text: ["为什么坚持不下来？"],
      audio: ["开场停顿"],
      production_notes: "第一秒直接进入问题。",
    },
  ],
  requirements: [
    {
      category: "画面",
      items: [
        { name: "人物近景", purpose: "建立交流感", priority: "必需" as const },
      ],
    },
  ],
  highlights: [
    {
      excerpt: "你知道为什么大多数人坚持不下来吗？",
      reason: "问题具有普遍共鸣。",
      leverage: "第一帧同步展示大字。",
    },
  ],
  hooks: [
    {
      excerpt: "你知道为什么大多数人坚持不下来吗？",
      hook_type: "问题",
      position: "开场",
      mechanism: "激发观众寻找答案。",
      strength: "强" as const,
      suggestion: "压缩停顿后立即给出答案。",
    },
  ],
  suggestions: [
    {
      area: "行动引导",
      issue: "结尾缺少互动。",
      recommendation: "邀请观众留言自己的五分钟目标。",
    },
  ],
};

describe("ScriptAnalysisPage", () => {
  beforeEach(() => {
    mocks.analyze.mockReset().mockResolvedValue(result);
    mocks.extractDocxText.mockReset().mockResolvedValue("从 Word 读取的脚本");
    mocks.writeText.mockReset().mockResolvedValue(undefined);
    mocks.readText.mockReset().mockResolvedValue("剪贴板脚本");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: mocks.writeText,
        readText: mocks.readText,
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("submits script context, renders all result groups, and copies the report", async () => {
    render(<ScriptAnalysisPage />);
    fireEvent.change(screen.getByLabelText("视频脚本"), {
      target: { value: "你知道为什么大多数人坚持不下来吗？" },
    });
    fireEvent.click(screen.getByText("补充分析背景"));
    fireEvent.change(screen.getByLabelText("发布平台"), {
      target: { value: "抖音" },
    });
    fireEvent.change(screen.getByLabelText("目标时长（秒）"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByLabelText("目标受众"), {
      target: { value: "习惯养成新手" },
    });
    fireEvent.change(screen.getByLabelText("内容目标"), {
      target: { value: "提高收藏" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始 AI 拆解" }));

    await waitFor(() =>
      expect(mocks.analyze).toHaveBeenCalledWith(
        {
          text: "你知道为什么大多数人坚持不下来吗？",
          platform: "抖音",
          audience: "习惯养成新手",
          target_duration_seconds: 30,
          goal: "提高收藏",
        },
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("从五分钟开始")).toBeTruthy();
    expect(screen.getByText("制作拆解")).toBeTruthy();
    expect(screen.getByText("所需内容清单")).toBeTruthy();
    expect(screen.getByText("脚本亮点")).toBeTruthy();
    expect(screen.getByText("脚本钩子")).toBeTruthy();
    expect(screen.getByText("整体优化建议")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "复制完整报告" }));
    await waitFor(() =>
      expect(mocks.writeText).toHaveBeenCalledWith(
        expect.stringContaining("# 从五分钟开始｜脚本拆解"),
      ),
    );
  });

  it("clears stale results after the input or context changes", async () => {
    render(<ScriptAnalysisPage />);
    const textarea = screen.getByLabelText("视频脚本");
    fireEvent.change(textarea, { target: { value: "第一版脚本" } });
    fireEvent.click(screen.getByRole("button", { name: "开始 AI 拆解" }));
    expect(await screen.findByText("从五分钟开始")).toBeTruthy();

    fireEvent.change(textarea, { target: { value: "第二版脚本" } });
    expect(screen.queryByText("从五分钟开始")).toBeNull();
    expect(screen.getByText("制作思路会在这里展开")).toBeTruthy();
  });

  it("reads a docx locally and asks before replacing existing text", async () => {
    render(<ScriptAnalysisPage />);
    fireEvent.change(screen.getByLabelText("视频脚本"), {
      target: { value: "现有脚本" },
    });
    const file = new File(["docx"], "脚本.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    fireEvent.change(screen.getByLabelText("选择 Word 文档"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(
        (screen.getByLabelText("视频脚本") as HTMLTextAreaElement).value,
      ).toBe("从 Word 读取的脚本"),
    );
    expect(window.confirm).toHaveBeenCalled();
    expect(mocks.extractDocxText).toHaveBeenCalledWith(file);
    expect(screen.getByText("脚本.docx")).toBeTruthy();
  });

  it("cancels an in-flight analysis and reports the cancellation", async () => {
    mocks.analyze.mockImplementation(
      (_payload: unknown, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    render(<ScriptAnalysisPage />);
    fireEvent.change(screen.getByLabelText("视频脚本"), {
      target: { value: "等待分析的脚本" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始 AI 拆解" }));
    fireEvent.click(await screen.findByRole("button", { name: "取消分析" }));

    expect(await screen.findByText("已取消本次脚本分析。")).toBeTruthy();
  });

  it("rejects oversized Word files before reading them", async () => {
    render(<ScriptAnalysisPage />);
    const file = new File(["small"], "过大脚本.docx");
    Object.defineProperty(file, "size", { value: 10 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByLabelText("选择 Word 文档"), {
      target: { files: [file] },
    });

    expect(
      await screen.findByText("Word 文件不能超过 10MB，请压缩或拆分后再试。"),
    ).toBeTruthy();
    expect(mocks.extractDocxText).not.toHaveBeenCalled();
  });
});
