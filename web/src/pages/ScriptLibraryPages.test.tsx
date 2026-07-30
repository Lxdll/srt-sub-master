// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScriptLibraryDetailPage } from "./ScriptLibraryDetailPage";
import { ScriptLibraryPage } from "./ScriptLibraryPage";

const mocks = vi.hoisted(() => ({
  scripts: vi.fn(),
  script: vi.fn(),
  createScript: vi.fn(),
  updateScript: vi.fn(),
  deleteScript: vi.fn(),
  writeText: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: {
    scripts: mocks.scripts,
    script: mocks.script,
    createScript: mocks.createScript,
    updateScript: mocks.updateScript,
    deleteScript: mocks.deleteScript,
  },
}));

const listItem = {
  id: "script-1",
  title: "夏日新品开场",
  excerpt: "用一个夏日问题抓住观众注意力",
  matched_in: ["title", "body"] as Array<"title" | "body">,
  character_count: 16,
  created_by: { id: "user-1", username: "小林" },
  updated_by: { id: "user-2", username: "小陈" },
  created_at: "2026-07-29T08:00:00Z",
  updated_at: "2026-07-30T08:00:00Z",
};

const detail = {
  ...listItem,
  body: "第一段夏日正文\n第二段保持原样",
};

function renderWithClient(node: React.ReactNode, initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Script library pages", () => {
  beforeEach(() => {
    mocks.scripts.mockReset().mockResolvedValue({
      items: [listItem],
      total: 21,
      limit: 20,
      offset: 20,
    });
    mocks.script.mockReset().mockResolvedValue(detail);
    mocks.createScript.mockReset().mockResolvedValue(detail);
    mocks.updateScript.mockReset().mockResolvedValue(detail);
    mocks.deleteScript.mockReset().mockResolvedValue({ ok: true });
    mocks.writeText.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: mocks.writeText },
    });
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(cleanup);

  it("searches with the URL state, highlights results, and exposes pagination", async () => {
    renderWithClient(
      <Routes>
        <Route path="/script-library" element={<ScriptLibraryPage />} />
      </Routes>,
      "/script-library?q=夏日&offset=20",
    );

    expect(
      await screen.findByRole("heading", { name: "夏日新品开场" }),
    ).toBeTruthy();
    expect(mocks.scripts).toHaveBeenCalledWith("夏日", 20, 20);
    expect(document.querySelectorAll("mark").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("标题和正文命中")).toBeTruthy();
    expect(screen.getByText("2 / 2")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: /夏日新品开场/ })
        .getAttribute("href"),
    ).toBe("/script-library/script-1?q=%E5%A4%8F%E6%97%A5&offset=20");
  });

  it("shows a body-match tag when only the script body matches", async () => {
    mocks.scripts.mockResolvedValueOnce({
      items: [
        {
          ...listItem,
          title: "新品开场",
          matched_in: ["body"],
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderWithClient(
      <Routes>
        <Route path="/script-library" element={<ScriptLibraryPage />} />
      </Routes>,
      "/script-library?q=夏日",
    );

    expect(await screen.findByText("正文命中")).toBeTruthy();
    expect(screen.queryByText("标题命中")).toBeNull();
    expect(screen.queryByText("标题和正文命中")).toBeNull();
  });

  it("debounces a new keyword and resets the result offset", async () => {
    renderWithClient(
      <Routes>
        <Route path="/script-library" element={<ScriptLibraryPage />} />
      </Routes>,
      "/script-library?offset=20",
    );
    await screen.findByRole("heading", { name: "夏日新品开场" });
    fireEvent.change(screen.getByLabelText("搜索标题或正文"), {
      target: { value: "问题" },
    });

    await waitFor(
      () => expect(mocks.scripts).toHaveBeenCalledWith("问题", 20, 0),
      { timeout: 1_000 },
    );
  });

  it("copies the raw title and body from the detail page", async () => {
    renderWithClient(
      <Routes>
        <Route
          path="/script-library/:scriptId"
          element={<ScriptLibraryDetailPage />}
        />
      </Routes>,
      "/script-library/script-1?q=夏日&offset=20",
    );
    expect(await screen.findByText("脚本正文")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "复制标题" }));
    await waitFor(() =>
      expect(mocks.writeText).toHaveBeenCalledWith("夏日新品开场"),
    );
    fireEvent.click(screen.getByRole("button", { name: "复制正文" }));
    await waitFor(() =>
      expect(mocks.writeText).toHaveBeenCalledWith(
        "第一段夏日正文\n第二段保持原样",
      ),
    );
    expect(
      screen
        .getByRole("link", { name: "返回脚本库" })
        .getAttribute("href"),
    ).toBe("/script-library?q=%E5%A4%8F%E6%97%A5&offset=20");
  });

  it("edits through the shared form and confirms before deletion", async () => {
    renderWithClient(
      <Routes>
        <Route
          path="/script-library/:scriptId"
          element={<ScriptLibraryDetailPage />}
        />
        <Route path="/script-library" element={<div>脚本列表</div>} />
      </Routes>,
      "/script-library/script-1",
    );
    await screen.findByText("脚本正文");

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    const titleInput = screen.getByDisplayValue("夏日新品开场");
    fireEvent.change(titleInput, { target: { value: "夏日新品新版" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() =>
      expect(mocks.updateScript).toHaveBeenCalledWith("script-1", {
        title: "夏日新品新版",
        body: "第一段夏日正文\n第二段保持原样",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText(/“夏日新品开场”将从共享脚本库中永久删除/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() =>
      expect(mocks.deleteScript).toHaveBeenCalledWith("script-1"),
    );
    expect(await screen.findByText("脚本列表")).toBeTruthy();
  });
});
