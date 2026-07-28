// @vitest-environment jsdom

import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren, ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProhibitedWordsPage } from "./ProhibitedWordsPage";

const mocks = vi.hoisted(() => ({
  customWords: vi.fn(),
  addWord: vi.fn(),
  deleteWord: vi.fn(),
  check: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: {
    customProhibitedWords: mocks.customWords,
    addCustomProhibitedWord: mocks.addWord,
    deleteCustomProhibitedWord: mocks.deleteWord,
    checkProhibitedWords: mocks.check,
  },
}));

function renderPage(element: ReactElement = <ProhibitedWordsPage />) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {element}
    </QueryClientProvider>,
  );
}

const result = {
  matches: [
    {
      term: "加微信",
      category: "引流导流",
      reason: "可能引导用户转移到站外",
      sources: ["ai", "custom"] as const,
      occurrences: [
        { start: 0, end: 3 },
        { start: 10, end: 13 },
      ],
    },
  ],
  match_count: 2,
  unique_term_count: 1,
};

describe("ProhibitedWordsPage", () => {
  beforeEach(() => {
    mocks.customWords.mockReset().mockResolvedValue([
      {
        id: "word-1",
        term: "加微信",
        created_at: "2026-07-26T08:00:00Z",
      },
    ]);
    mocks.addWord.mockReset().mockResolvedValue({
      id: "word-2",
      term: "稳赚不赔",
      created_at: "2026-07-26T08:01:00Z",
    });
    mocks.deleteWord.mockReset().mockResolvedValue({ ok: true });
    mocks.check.mockReset().mockResolvedValue(result);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("detects text and renders verified matches with highlighted source text", async () => {
    renderPage();
    await screen.findByText("加微信");

    fireEvent.change(screen.getByLabelText("待检测文字"), {
      target: { value: "加微信即可联系我们，加微信。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始检测" }));

    await waitFor(() =>
      expect(mocks.check).toHaveBeenCalledWith("加微信即可联系我们，加微信。"),
    );
    expect(await screen.findByText("AI 识别")).toBeTruthy();
    expect(
      document.querySelector(".prohibited-result-totals")?.textContent,
    ).toContain("1 个风险词");
    expect(screen.getAllByText("个人词库")).toHaveLength(2);
    expect(document.querySelectorAll("mark")).toHaveLength(2);
    expect(document.querySelector("mark")?.textContent).toBe("加微信");
  });

  it("clears stale results after the input changes", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("待检测文字"), {
      target: { value: "加微信" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始检测" }));
    await screen.findByText("AI 识别");

    fireEvent.change(screen.getByLabelText("待检测文字"), {
      target: { value: "新的文案" },
    });
    expect(document.querySelector(".prohibited-result-totals")).toBeNull();
    expect(screen.getByText("等待检测")).toBeTruthy();
  });

  it("adds and deletes personal prohibited words", async () => {
    renderPage();
    await screen.findByText("加微信");

    fireEvent.change(screen.getByLabelText("添加自定义违禁词"), {
      target: { value: "稳赚不赔" },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加违禁词" }));
    await waitFor(() =>
      expect(mocks.addWord).toHaveBeenCalledWith("稳赚不赔"),
    );

    fireEvent.click(screen.getByRole("button", { name: "删除 加微信" }));
    await waitFor(() => expect(mocks.deleteWord).toHaveBeenCalledWith("word-1"));
  });

  it("shows model failures instead of reporting the text as safe", async () => {
    mocks.check.mockRejectedValue(new Error("违禁词检测模型尚未配置"));
    renderPage();
    fireEvent.change(screen.getByLabelText("待检测文字"), {
      target: { value: "待检测文案" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始检测" }));

    expect(
      await screen.findByText("违禁词检测模型尚未配置"),
    ).toBeTruthy();
    expect(screen.queryByText("未发现可定位的违禁词")).toBeNull();
  });
});
