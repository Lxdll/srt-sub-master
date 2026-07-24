// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { formatTime } from "./SegmentEditor";
import { SegmentEditor } from "./SegmentEditor";

const mocks = vi.hoisted(() => ({
  editSegment: vi.fn().mockResolvedValue({ ok: true }),
}));

vi.mock("../lib/api", () => ({
  api: { editSegment: mocks.editSegment },
}));

describe("formatTime", () => {
  it("formats subtitle milliseconds", () => {
    expect(formatTime(0)).toBe("00:00.0");
    expect(formatTime(65_430)).toBe("01:05.4");
  });

  it("saves edited text after the debounce window", async () => {
    render(
      <SegmentEditor
        taskId="task-1"
        segment={{
          id: "segment-1",
          ordinal: 0,
          start_ms: 0,
          end_ms: 1000,
          original_text: "原文",
          edited_text: "原文",
          updated_at: "2026-07-24T00:00:00Z",
        }}
        active={false}
        onSeek={() => undefined}
      />,
    );

    fireEvent.change(screen.getByLabelText("第 1 条字幕"), {
      target: { value: "修改后的字幕" },
    });
    expect(screen.getByText("保存中")).toBeTruthy();
    await waitFor(
      () =>
        expect(mocks.editSegment).toHaveBeenCalledWith(
          "task-1",
          "segment-1",
          "修改后的字幕",
        ),
      { timeout: 1000 },
    );
    expect(screen.getByText("已保存")).toBeTruthy();
  });
});
