// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ContentCreativeQuizOverview, ContentCreativeQuizSession } from "../types";
import { ContentCreativeQuizPage } from "./ContentCreativeQuizPage";

const mocks = vi.hoisted(() => ({
  overview: vi.fn(),
  createSession: vi.fn(),
  answer: vi.fn(),
  session: vi.fn(),
  submit: vi.fn(),
}));

vi.mock("../components/AppShell", () => ({
  AppShell: ({ children }: PropsWithChildren) => <>{children}</>,
}));

vi.mock("../lib/api", () => ({
  api: {
    contentCreativeQuizOverview: mocks.overview,
    createContentCreativeQuizSession: mocks.createSession,
    answerContentCreativeQuestion: mocks.answer,
    contentCreativeQuizSession: mocks.session,
    submitContentCreativeQuizSession: mocks.submit,
  },
}));

const activeSession: ContentCreativeQuizSession = {
  id: "session-1",
  mode: "random",
  status: "active",
  filters: { sources: [], question_types: [], question_count: 1 },
  duration_seconds: null,
  deadline_at: null,
  started_at: "2026-08-18T01:00:00Z",
  completed_at: null,
  elapsed_seconds: 0,
  question_count: 1,
  answered_count: 0,
  score_correct: null,
  score_total: null,
  breakdown: null,
  questions: [
    {
      id: "content-creative-0001",
      serial: 1,
      source: "2026年Q1季度-真题",
      question_type: "single",
      prompt: "微电影工具的定位是什么？",
      options: [
        { key: "A", text: "视频拍摄工具" },
        { key: "B", text: "视频智能剪辑工具" },
      ],
      selected_options: [],
      answered_at: null,
      is_correct: null,
      correct_options: null,
      note: null,
    },
  ],
};

const completedSession: ContentCreativeQuizSession = {
  ...activeSession,
  status: "completed",
  completed_at: "2026-08-18T01:00:30Z",
  elapsed_seconds: 30,
  answered_count: 1,
  score_correct: 1,
  score_total: 1,
  breakdown: {
    single: { total: 1, correct: 1 },
    multiple: { total: 0, correct: 0 },
    judgment: { total: 0, correct: 0 },
  },
  questions: [
    {
      ...activeSession.questions[0],
      selected_options: ["B"],
      answered_at: "2026-08-18T01:00:30Z",
      is_correct: true,
      correct_options: ["B"],
      note: "微电影是一款视频智能剪辑工具。",
    },
  ],
};

const overview: ContentCreativeQuizOverview = {
  question_count: 628,
  by_type: { single: 352, multiple: 181, judgment: 95 },
  sources: [
    { source: "2026年Q1季度-真题", count: 332 },
    { source: "第三套创意认证真题", count: 118 },
  ],
  progress: { attempts: 10, correct: 8, correct_rate: 0.8, mistakes: 2 },
  active_session: null,
  recent_sessions: [],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContentCreativeQuizPage />
    </QueryClientProvider>,
  );
}

describe("ContentCreativeQuizPage", () => {
  beforeEach(() => {
    mocks.overview.mockReset().mockResolvedValue(overview);
    mocks.createSession.mockReset().mockResolvedValue(activeSession);
    mocks.answer.mockReset().mockResolvedValue(completedSession);
    mocks.session.mockReset().mockResolvedValue(activeSession);
    mocks.submit.mockReset().mockResolvedValue(completedSession);
  });

  afterEach(cleanup);

  it("configures a random practice and reveals feedback after confirmation", async () => {
    renderPage();
    expect(await screen.findByText("628")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /随机练习/ }));
    expect(screen.getByRole("dialog", { name: "随机练习" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "开始" }));

    expect(await screen.findByText("微电影工具的定位是什么？")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /B 视频智能剪辑工具/ }));
    fireEvent.click(screen.getByRole("button", { name: "确认答案" }));

    await waitFor(() =>
      expect(mocks.answer).toHaveBeenCalledWith(
        "session-1",
        "content-creative-0001",
        ["B"],
      ),
    );
    expect(await screen.findByText("回答正确")).toBeTruthy();
    expect(screen.getByText("微电影是一款视频智能剪辑工具。")).toBeTruthy();
  });
});
