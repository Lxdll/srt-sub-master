// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DouyinTranscribePage } from "./DouyinTranscribePage";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: {
    createDouyinTranscription: mocks.create,
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
    mocks.navigate.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("hides local transcription and creates a server transcription", async () => {
    render(<DouyinTranscribePage />);
    expect(screen.queryByText(/本机转写/)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "用服务器转成文案" }),
    );

    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        "https://www.douyin.com/video/7372484719365098803",
        { backend: "server" },
      ),
    );
    expect(mocks.navigate).toHaveBeenCalledWith("/tasks/task-1");
  });

  it("keeps the user on the page when task creation fails", async () => {
    mocks.create.mockRejectedValue(new Error("服务器转写队列已满，请稍后再试。"));
    render(<DouyinTranscribePage />);
    fireEvent.click(
      screen.getByRole("button", { name: "用服务器转成文案" }),
    );

    expect(
      await screen.findByText("服务器转写队列已满，请稍后再试。"),
    ).toBeTruthy();
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

});
