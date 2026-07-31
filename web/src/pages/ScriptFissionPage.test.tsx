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
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { User } from "../types";
import { ScriptFissionPage } from "./ScriptFissionPage";

const mocks = vi.hoisted(() => ({
  user: {
    id: "user-1",
    username: "tester",
    is_admin: false,
    permissions: ["script_fission", "script_library"],
  } as User,
  plan: vi.fn(),
  generate: vi.fn(),
  scripts: vi.fn(),
  script: vi.fn(),
  createScript: vi.fn(),
  writeText: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/auth", () => ({
  useAuth: () => ({ user: mocks.user }),
}));

vi.mock("../lib/api", () => ({
  api: {
    planScriptFission: mocks.plan,
    generateScriptFission: mocks.generate,
    scripts: mocks.scripts,
    script: mocks.script,
    createScript: mocks.createScript,
  },
}));

const directions = [
  {
    id: "direction-1",
    name: "反常识挑战",
    angle: "从反常识结论切入",
    hook_strategy: "先抛出冲突结论",
    structure_strategy: "误区、原因、方法、行动",
  },
  {
    id: "direction-2",
    name: "陪伴式共情",
    angle: "从失败感受切入",
    hook_strategy: "说出观众内心",
    structure_strategy: "共情、减压、微行动、收束",
  },
  {
    id: "direction-3",
    name: "结果倒推",
    angle: "从结果倒推第一步",
    hook_strategy: "先展示结果",
    structure_strategy: "结果、倒推、动作、互动",
  },
];

const libraryScript = {
  id: "script-1",
  title: "五分钟行动法",
  body: "别再把目标定得太大，先从每天五分钟开始。",
  character_count: 22,
  created_by: { id: "user-1", username: "小林" },
  updated_by: { id: "user-1", username: "小林" },
  created_at: "2026-07-30T08:00:00Z",
  updated_at: "2026-07-30T08:00:00Z",
};

function renderPage(initialEntry = "/script-fission") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ScriptFissionPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ScriptFissionPage", () => {
  beforeEach(() => {
    mocks.user.permissions = ["script_fission", "script_library"];
    mocks.plan.mockReset().mockResolvedValue({ directions });
    mocks.generate
      .mockReset()
      .mockImplementation(
        async (payload: { direction_id: string }) => ({
          direction_id: payload.direction_id,
          title: `${payload.direction_id} 标题`,
          body: `${payload.direction_id} 完整正文`,
        }),
      );
    mocks.scripts.mockReset().mockResolvedValue({
      items: [],
      total: 0,
      limit: 10,
      offset: 0,
    });
    mocks.script.mockReset().mockResolvedValue(libraryScript);
    mocks.createScript.mockReset().mockImplementation(
      async (title: string, body: string) => ({
        ...libraryScript,
        id: "saved-script",
        title,
        body,
        character_count: body.length,
      }),
    );
    mocks.writeText.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: mocks.writeText },
    });
  });

  afterEach(cleanup);

  it("plans once, generates three variants in parallel, and supports edit copy save", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("来源脚本"), {
      target: { value: "原始脚本正文" },
    });
    fireEvent.change(screen.getByLabelText("补充创作要求"), {
      target: { value: "面向职场新人" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "生成 3 个裂变脚本" }),
    );

    const firstTitle = await screen.findByLabelText("版本 1 标题");
    expect(mocks.plan).toHaveBeenCalledWith(
      { text: "原始脚本正文", requirements: "面向职场新人" },
      expect.any(AbortSignal),
    );
    expect(mocks.generate).toHaveBeenCalledTimes(3);
    expect(
      mocks.generate.mock.calls.map(([payload]) => payload.direction_id).sort(),
    ).toEqual(["direction-1", "direction-2", "direction-3"]);

    fireEvent.change(firstTitle, { target: { value: "编辑后的标题" } });
    fireEvent.change(screen.getByLabelText("版本 1 正文"), {
      target: { value: "编辑后的完整正文" },
    });
    fireEvent.click(
      screen.getAllByRole("button", { name: "复制脚本" })[0],
    );
    await waitFor(() =>
      expect(mocks.writeText).toHaveBeenCalledWith(
        "编辑后的标题\n\n编辑后的完整正文",
      ),
    );

    fireEvent.click(
      screen.getAllByRole("button", { name: "保存到脚本库" })[0],
    );
    await waitFor(() =>
      expect(mocks.createScript).toHaveBeenCalledWith(
        "编辑后的标题",
        "编辑后的完整正文",
      ),
    );
    expect(
      (
        await screen.findByRole("link", { name: "已保存，查看脚本" })
      ).getAttribute("href"),
    ).toBe("/script-library/saved-script");

    fireEvent.change(firstTitle, { target: { value: "再次编辑" } });
    expect(
      screen.getAllByRole("button", { name: "另存为新脚本" })[0],
    ).toBeTruthy();
  });

  it("keeps successful variants when one fails and retries only that direction", async () => {
    let directionTwoAttempts = 0;
    mocks.generate.mockImplementation(
      async (payload: { direction_id: string }) => {
        if (payload.direction_id === "direction-2") {
          directionTwoAttempts += 1;
          if (directionTwoAttempts === 1) throw new Error("模型暂时繁忙");
        }
        return {
          direction_id: payload.direction_id,
          title: `${payload.direction_id} 标题`,
          body: `${payload.direction_id} 正文`,
        };
      },
    );

    renderPage();
    fireEvent.change(screen.getByLabelText("来源脚本"), {
      target: { value: "原始脚本" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "生成 3 个裂变脚本" }),
    );

    expect(await screen.findByText("模型暂时繁忙")).toBeTruthy();
    expect(screen.getByLabelText("版本 1 标题")).toBeTruthy();
    expect(screen.getByLabelText("版本 3 标题")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "单独重试" }));
    expect(await screen.findByLabelText("版本 2 标题")).toBeTruthy();
    expect(directionTwoAttempts).toBe(2);
  });

  it("preselects a shared script from the URL and sends only its id", async () => {
    renderPage("/script-fission?scriptId=script-1");
    expect(await screen.findByText("五分钟行动法")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "生成 3 个裂变脚本" }),
    );
    await screen.findByLabelText("版本 1 标题");
    expect(mocks.plan).toHaveBeenCalledWith(
      { source_script_id: "script-1" },
      expect.any(AbortSignal),
    );
  });

  it("degrades to paste-only mode without script library permission", async () => {
    mocks.user.permissions = ["script_fission"];
    renderPage();
    expect(
      (screen.getByRole("button", {
        name: "共享脚本库",
      }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      screen.getByText(/当前账号可使用粘贴输入/),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText("来源脚本"), {
      target: { value: "原始脚本" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "生成 3 个裂变脚本" }),
    );
    await screen.findByLabelText("版本 1 标题");
    expect(
      screen.queryByRole("button", { name: "保存到脚本库" }),
    ).toBeNull();
  });

  it("cancels an in-flight planning request", async () => {
    mocks.plan.mockImplementation(
      (_payload: unknown, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText("来源脚本"), {
      target: { value: "原始脚本" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "生成 3 个裂变脚本" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "取消生成" }));
    expect(await screen.findByText("本次裂变已取消。")).toBeTruthy();
  });
});
