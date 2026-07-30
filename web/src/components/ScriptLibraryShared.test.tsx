// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  HighlightedText,
  ScriptEditorDialog,
} from "./ScriptLibraryShared";

const mocks = vi.hoisted(() => ({
  extractDocxText: vi.fn(),
}));

vi.mock("../lib/docx", () => ({
  DocxError: class DocxError extends Error {},
  extractDocxText: mocks.extractDocxText,
}));

describe("ScriptLibraryShared", () => {
  beforeEach(() => {
    mocks.extractDocxText.mockReset().mockResolvedValue("Word 中的脚本正文");
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("highlights every literal keyword match without treating text as HTML", () => {
    const { container } = render(
      <p>
        <HighlightedText text={"夏日<script>夏日"} query="夏日" />
      </p>,
    );
    expect(container.querySelectorAll("mark")).toHaveLength(2);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>")).toBeTruthy();
  });

  it("imports docx text locally and uses the filename as the default title", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ScriptEditorDialog onClose={vi.fn()} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "导入 Word" }));
    const file = new File(["docx"], "夏日新品.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    fireEvent.change(screen.getByLabelText("选择 Word 文档"), {
      target: { files: [file] },
    });

    expect(await screen.findByDisplayValue("夏日新品")).toBeTruthy();
    expect(screen.getByDisplayValue("Word 中的脚本正文")).toBeTruthy();
    expect(mocks.extractDocxText).toHaveBeenCalledWith(file);
  });

  it("trims the title but preserves the original body formatting when saving", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ScriptEditorDialog onClose={vi.fn()} onSave={onSave} />);
    fireEvent.change(screen.getByPlaceholderText("例如：夏日新品短视频脚本"), {
      target: { value: "  测试标题  " },
    });
    fireEvent.change(screen.getByPlaceholderText("在这里粘贴或输入完整脚本…"), {
      target: { value: "\n  第一行\n第二行  \n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存到脚本库" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        "测试标题",
        "\n  第一行\n第二行  \n",
      ),
    );
  });
});
