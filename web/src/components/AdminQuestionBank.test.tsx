// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AdminContentCreativeQuestion } from "../types";
import { AdminQuestionBank } from "./AdminQuestionBank";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
  create: vi.fn(),
  status: vi.fn(),
  versions: vi.fn(),
  restore: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: {
    adminContentCreativeQuestions: mocks.list,
    updateAdminContentCreativeQuestion: mocks.update,
    createAdminContentCreativeQuestion: mocks.create,
    setAdminContentCreativeQuestionStatus: mocks.status,
    adminContentCreativeQuestionVersions: mocks.versions,
    restoreAdminContentCreativeQuestion: mocks.restore,
  },
}));

const question: AdminContentCreativeQuestion = {
  id: "content-creative-0001",
  serial: 1,
  source: "2026年Q1季度-真题",
  question_type: "single",
  prompt: "原题目",
  options: [
    { key: "A", text: "错误答案" },
    { key: "B", text: "正确答案" },
  ],
  correct_options: ["B"],
  note: "原解析",
  is_active: true,
  needs_review: false,
  review_notes: [],
  content_version: 1,
  grading_version: 1,
  created_at: "2026-08-18T01:00:00Z",
  updated_at: "2026-08-18T01:00:00Z",
  updated_by_username: null,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminQuestionBank />
    </QueryClientProvider>,
  );
}

describe("AdminQuestionBank", () => {
  beforeEach(() => {
    mocks.list.mockReset().mockResolvedValue({
      items: [question],
      total: 1,
      offset: 0,
      limit: 50,
      summary: {
        active: 628,
        inactive: 0,
        needs_review: 1,
        by_type: { single: 352, multiple: 181, judgment: 95 },
        sources: [question.source],
      },
    });
    mocks.update.mockReset().mockResolvedValue({ ...question, prompt: "修正后的题目", content_version: 2 });
    mocks.create.mockReset();
    mocks.status.mockReset();
    mocks.versions.mockReset().mockResolvedValue([
      { version_number: 2, action: "update", admin_username: "admin", created_at: "2026-08-18T02:00:00Z", snapshot: { ...question, prompt: "修正后的题目", content_version: 2 } },
      { version_number: 1, action: "import", admin_username: null, created_at: "2026-08-18T01:00:00Z", snapshot: question },
    ]);
    mocks.restore.mockReset().mockResolvedValue({ ...question, content_version: 3 });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("edits question text without changing the grading version", async () => {
    renderPanel();
    expect(await screen.findByText("原题目")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("题目描述"), { target: { value: "修正后的题目" } });
    fireEvent.click(screen.getByRole("button", { name: "保存题目" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(
      question.id,
      expect.objectContaining({ prompt: "修正后的题目", expected_version: 1 }),
    ));
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it("shows version differences and restores an older snapshot", async () => {
    mocks.list.mockResolvedValue({
      items: [{ ...question, prompt: "修正后的题目", content_version: 2 }],
      total: 1,
      offset: 0,
      limit: 50,
      summary: {
        active: 628,
        inactive: 0,
        needs_review: 1,
        by_type: { single: 352, multiple: 181, judgment: 95 },
        sources: [question.source],
      },
    });
    renderPanel();
    await screen.findByText("修正后的题目");
    fireEvent.click(screen.getByRole("button", { name: "历史" }));
    expect(await screen.findByText(/变更：题目/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(mocks.restore).toHaveBeenCalledWith(question.id, 1, 2));
  });
});
