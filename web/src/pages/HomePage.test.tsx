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
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const mocks = vi.hoisted(() => ({
  hotRanks: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: { hotRanks: mocks.hotRanks },
}));

const response = {
  generated_at: "2026-07-29T08:30:00Z",
  platforms: [
    {
      platform: "rednote" as const,
      display_name: "小红书",
      status: "fresh" as const,
      source: "60s" as const,
      updated_at: "2026-07-29T08:30:00Z",
      items: Array.from({ length: 10 }, (_, index) => ({
        rank: index + 1,
        title: `小红书热点 ${index + 1}`,
        url: `https://www.xiaohongshu.com/explore/${index + 1}`,
        hot_value: String(1000 - index),
      })),
    },
    {
      platform: "douyin" as const,
      display_name: "抖音",
      status: "fresh" as const,
      source: "uapi" as const,
      updated_at: "2026-07-29T08:29:00Z",
      items: [
        {
          rank: 1,
          title: "抖音热点",
          url: "https://www.douyin.com/hot/1",
        },
      ],
    },
    {
      platform: "bilibili" as const,
      display_name: "B站热门",
      status: "stale" as const,
      source: "60s" as const,
      updated_at: "2026-07-29T07:00:00Z",
      items: [
        {
          rank: 1,
          title: "B站热点",
          url: "https://www.bilibili.com/video/BV1",
        },
      ],
    },
  ],
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <HomePage />
    </QueryClientProvider>,
  );
}

describe("HomePage", () => {
  beforeEach(() => {
    mocks.hotRanks.mockReset().mockResolvedValue(response);
  });

  afterEach(cleanup);

  it("renders all platforms, ten ranked items and source states", async () => {
    renderPage();

    expect(await screen.findByText("小红书热点 1")).toBeTruthy();
    expect(screen.getByText("小红书热点 10")).toBeTruthy();
    expect(screen.getByText("备用源")).toBeTruthy();
    expect(screen.getByText("缓存榜单")).toBeTruthy();
    const link = screen.getByRole("link", {
      name: /第 1 名：小红书热点 1/,
    });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("requests a forced refresh and keeps the result in the page", async () => {
    renderPage();
    await screen.findByText("小红书热点 1");

    fireEvent.click(screen.getByRole("button", { name: "刷新热榜" }));

    await waitFor(() => expect(mocks.hotRanks).toHaveBeenCalledWith(true));
    expect(screen.getByText("小红书热点 1")).toBeTruthy();
  });
});
