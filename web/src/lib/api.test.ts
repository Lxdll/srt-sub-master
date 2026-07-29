import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScriptAnalysisResult } from "../types";
import { api, setCsrfToken } from "./api";

function streamingResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    },
  );
}

describe("script analysis streaming API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("publishes semantic SSE items as soon as they arrive", async () => {
    setCsrfToken("csrf-test");
    const highlight = {
      excerpt: "原文亮点",
      reason: "表达清晰",
      leverage: "强化措辞",
    };
    const hook = {
      excerpt: "原文钩子",
      hook_type: "问题",
      position: "开场",
      mechanism: "激发好奇",
      strength: "强" as const,
      suggestion: "更快给出答案",
    };
    const suggestion = {
      area: "节奏",
      issue: "中段偏慢",
      recommendation: "压缩重复表达",
    };
    const finalResult: ScriptAnalysisResult = {
      highlights: [highlight],
      hooks: [hook],
      suggestions: [suggestion],
    };
    const body = [
      `event: highlight\ndata: ${JSON.stringify(highlight)}\n\n`,
      `event: hook\ndata: ${JSON.stringify(hook)}\n\n`,
      `event: suggestion\ndata: ${JSON.stringify(suggestion)}\n\n`,
      `event: result\ndata: ${JSON.stringify(finalResult)}\n\n`,
      'event: done\ndata: {"ok":true}\n\n',
    ].join("");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamingResponse([
          body.slice(0, 17),
          body.slice(17, 83),
          body.slice(83),
        ]),
      ),
    );
    const progress: ScriptAnalysisResult[] = [];

    const result = await api.analyzeScriptStream(
      { text: "测试脚本" },
      (value) => progress.push(value),
    );

    expect(progress[0].highlights).toEqual([highlight]);
    expect(progress[0].hooks).toEqual([]);
    expect(progress.some((value) => value.hooks.length === 1)).toBe(true);
    expect(result).toEqual(finalResult);
    expect(fetch).toHaveBeenCalledWith(
      "/api/script-analysis/analyze/stream",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf-test" }),
      }),
    );
  });

  it("surfaces an SSE error instead of accepting a partial result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamingResponse([
          'event: error\ndata: {"status_code":502,"detail":"模型输出无法解析"}\n\n',
        ]),
      ),
    );

    await expect(
      api.analyzeScriptStream({ text: "测试脚本" }, () => undefined),
    ).rejects.toThrow("模型输出无法解析");
  });
});
