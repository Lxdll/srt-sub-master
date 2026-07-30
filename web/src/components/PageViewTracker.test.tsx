// @vitest-environment jsdom

import { cleanup, render, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PageViewTracker } from "./PageViewTracker";

const mocks = vi.hoisted(() => ({
  recordPageView: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: { recordPageView: mocks.recordPageView },
}));

describe("PageViewTracker", () => {
  beforeEach(() => {
    mocks.recordPageView.mockReset().mockResolvedValue({ status: "accepted" });
  });

  afterEach(cleanup);

  it("reports one pathname event under React StrictMode", async () => {
    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/login"]}>
          <PageViewTracker />
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => expect(mocks.recordPageView).toHaveBeenCalledTimes(1));
    expect(mocks.recordPageView.mock.calls[0][1]).toBe("/login");
    expect(mocks.recordPageView.mock.calls[0][0]).toMatch(
      /^[0-9a-f-]{36}$/i,
    );
  });
});
