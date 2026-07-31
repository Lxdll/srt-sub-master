// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { User } from "../types";
import { ToolsPage } from "./ToolsPage";

const mocks = vi.hoisted(() => ({
  user: null as User | null,
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/auth", () => ({
  useAuth: () => ({ user: mocks.user }),
}));

function renderPage(state?: { accessDenied: boolean }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/tools", state }]}>
      <ToolsPage />
    </MemoryRouter>,
  );
}

describe("ToolsPage", () => {
  beforeEach(() => {
    mocks.user = {
      id: "user-1",
      username: "tester",
      is_admin: false,
      permissions: [],
    };
  });

  afterEach(cleanup);

  it("shows a friendly empty state when the account has no tools", () => {
    renderPage();
    expect(screen.getByText("工具箱还在等待解锁")).toBeTruthy();
    expect(screen.queryByText("抖音下载")).toBeNull();
  });

  it("requires both permissions for the transcribe workflow", () => {
    mocks.user!.permissions = ["douyin_download"];
    renderPage();
    expect(screen.getByText("抖音下载")).toBeTruthy();
    expect(screen.queryByText("抖音转文案")).toBeNull();

    cleanup();
    mocks.user!.permissions = ["douyin_download", "subtitle_workspace"];
    renderPage();
    expect(screen.getByText("抖音转文案")).toBeTruthy();
    expect(screen.getByText("字幕校对")).toBeTruthy();
  });

  it("explains an unauthorized redirect without hiding allowed tools", () => {
    mocks.user!.permissions = ["script_analysis"];
    renderPage({ accessDenied: true });
    expect(screen.getByText("这个工具尚未向你的账号开放")).toBeTruthy();
    expect(screen.getByText("脚本拆解")).toBeTruthy();
  });

  it("shows the shared script library only with its dedicated permission", () => {
    renderPage();
    expect(screen.queryByText("共享脚本库")).toBeNull();

    cleanup();
    mocks.user!.permissions = ["script_library"];
    renderPage();
    expect(screen.getByText("共享脚本库")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /开始使用/ }).getAttribute("href"),
    ).toBe("/script-library");
  });

  it("shows script fission only with its independent permission", () => {
    mocks.user!.permissions = ["script_fission"];
    renderPage();
    expect(screen.getByText("脚本裂变")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /开始使用/ }).getAttribute("href"),
    ).toBe("/script-fission");
    expect(screen.queryByText("脚本拆解")).toBeNull();
  });
});
