import { describe, expect, it } from "vitest";
import {
  downloadProgressText,
  formatBytes,
  formatEta,
} from "./download-progress";

describe("download progress formatting", () => {
  it("shows downloaded size, total, speed and eta", () => {
    expect(
      downloadProgressText({
        downloaded_bytes: 29 * 1024 * 1024,
        download_total_bytes: 106 * 1024 * 1024,
        download_speed_bps: 2.5 * 1024 * 1024,
        download_eta_seconds: 31,
      }),
    ).toBe("29.0 MB / 106.0 MB · 2.5 MB/s · 预计剩余 31 秒");
  });

  it("formats large values and longer estimates", () => {
    expect(formatBytes(2 * 1024 * 1024 * 1024)).toBe("2.00 GB");
    expect(formatEta(3660)).toBe("1 小时 1 分钟");
  });
});
