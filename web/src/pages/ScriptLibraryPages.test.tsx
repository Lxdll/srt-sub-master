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
import type { User } from "../types";

const mocks = vi.hoisted(() => ({
  scripts: vi.fn(),
  script: vi.fn(),
  createScript: vi.fn(),
  updateScript: vi.fn(),
  deleteScript: vi.fn(),
  writeText: vi.fn(),
  user: {
    id: "user-1",
    username: "tester",
    is_admin: false,
    permissions: ["script_library"],
  } as User,
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

vi.mock("../lib/auth", () => ({
  useAuth: () => ({ user: mocks.user }),
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
    mocks.user.permissions = ["script_library"];
    mocks.scripts.mockReset().mockResolvedValue({
      items: [listItem],
      total: 1,
      limit: 24,
      offset: 0,
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

  it("searches with the URL state and highlights virtualized results", async () => {
    renderWithClient(
      <Routes>
        <Route path="/script-library" element={<ScriptLibraryPage />} />
      </Routes>,
      "/script-library?q=夏日",
    );

    expect(
      await screen.findByRole("heading", { name: "夏日新品开场" }),
    ).toBeTruthy();
    expect(mocks.scripts).toHaveBeenCalledWith("夏日", 24, 0);
    expect(document.querySelectorAll("mark").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("标题和正文命中")).toBeTruthy();
    expect(screen.getByText("已加载 1 / 1")).toBeTruthy();
    expect(screen.getByLabelText("脚本搜索结果")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: /夏日新品开场/ })
        .getAttribute("href"),
    ).toBe("/script-library/script-1?q=%E5%A4%8F%E6%97%A5");
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

  it("debounces a new keyword and starts loading from the beginning", async () => {
    renderWithClient(
      <Routes>
        <Route path="/script-library" element={<ScriptLibraryPage />} />
      </Routes>,
      "/script-library",
    );
    await screen.findByRole("heading", { name: "夏日新品开场" });
    fireEvent.change(screen.getByLabelText("搜索标题或正文"), {
      target: { value: "问题" },
    });

    await waitFor(
      () => expect(mocks.scripts).toHaveBeenCalledWith("问题", 24, 0),
      { timeout: 1_000 },
    );
  });

  it("renders only visible rows and loads the next page near the end", async () => {
    const firstPage = Array.from({ length: 24 }, (_, index) => ({
      ...listItem,
      id: `script-${index + 1}`,
      title: `脚本 ${index + 1}`,
    }));
    const finalItem = {
      ...listItem,
      id: "script-25",
      title: "脚本 25",
    };
    mocks.scripts.mockImplementation(
      async (_query: string, _limit: number, offset: number) =>
        offset === 0
          ? {
              items: firstPage,
              total: 25,
              limit: 24,
              offset: 0,
            }
          : {
              items: [finalItem],
              total: 25,
              limit: 24,
              offset: 24,
            },
    );

    renderWithClient(
      <Routes>
        <Route path="/script-library" element={<ScriptLibraryPage />} />
      </Routes>,
      "/script-library",
    );

    await screen.findByRole("heading", { name: "脚本 1" });
    expect(document.querySelectorAll(".script-library-card").length).toBeLessThan(
      firstPage.length,
    );

    const viewport = screen.getByLabelText("脚本搜索结果");
    viewport.scrollTop = 4_200;
    fireEvent.scroll(viewport);

    await waitFor(() =>
      expect(mocks.scripts).toHaveBeenCalledWith("", 24, 24),
    );
    expect(
      await screen.findByRole("heading", { name: "脚本 25" }),
    ).toBeTruthy();
  });

  it("copies the raw title and body from the detail page", async () => {
    mocks.user.permissions = ["script_library", "script_fission"];
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
    expect(
      screen
        .getByRole("link", { name: "基于此脚本裂变" })
        .getAttribute("href"),
    ).toBe("/script-fission?scriptId=script-1");
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
