// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { deflateRaw } from "pako";
import { DocxError, extractDocxText } from "./docx";

function uint16(value: number) {
  return [value & 0xff, (value >> 8) & 0xff];
}

function uint32(value: number) {
  return [
    value & 0xff,
    (value >> 8) & 0xff,
    (value >> 16) & 0xff,
    (value >> 24) & 0xff,
  ];
}

function storedZip(name: string, content: string): Uint8Array {
  const encoder = new TextEncoder();
  const fileName = encoder.encode(name);
  const data = encoder.encode(content);
  const local = new Uint8Array([
    ...uint32(0x04034b50),
    ...uint16(20),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint32(0),
    ...uint32(data.length),
    ...uint32(data.length),
    ...uint16(fileName.length),
    ...uint16(0),
    ...fileName,
    ...data,
  ]);
  const central = new Uint8Array([
    ...uint32(0x02014b50),
    ...uint16(20),
    ...uint16(20),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint32(0),
    ...uint32(data.length),
    ...uint32(data.length),
    ...uint16(fileName.length),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint32(0),
    ...uint32(0),
    ...fileName,
  ]);
  const end = new Uint8Array([
    ...uint32(0x06054b50),
    ...uint16(0),
    ...uint16(0),
    ...uint16(1),
    ...uint16(1),
    ...uint32(central.length),
    ...uint32(local.length),
    ...uint16(0),
  ]);
  const zip = new Uint8Array(local.length + central.length + end.length);
  zip.set(local);
  zip.set(central, local.length);
  zip.set(end, local.length + central.length);
  return zip;
}

function deflatedZip(
  name: string,
  content: string,
  declaredUncompressedSize: number,
): Uint8Array {
  const encoder = new TextEncoder();
  const fileName = encoder.encode(name);
  const compressed = deflateRaw(encoder.encode(content));
  const local = new Uint8Array([
    ...uint32(0x04034b50),
    ...uint16(20),
    ...uint16(0),
    ...uint16(8),
    ...uint16(0),
    ...uint16(0),
    ...uint32(0),
    ...uint32(compressed.length),
    ...uint32(declaredUncompressedSize),
    ...uint16(fileName.length),
    ...uint16(0),
    ...fileName,
    ...compressed,
  ]);
  const central = new Uint8Array([
    ...uint32(0x02014b50),
    ...uint16(20),
    ...uint16(20),
    ...uint16(0),
    ...uint16(8),
    ...uint16(0),
    ...uint16(0),
    ...uint32(0),
    ...uint32(compressed.length),
    ...uint32(declaredUncompressedSize),
    ...uint16(fileName.length),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint16(0),
    ...uint32(0),
    ...uint32(0),
    ...fileName,
  ]);
  const end = new Uint8Array([
    ...uint32(0x06054b50),
    ...uint16(0),
    ...uint16(0),
    ...uint16(1),
    ...uint16(1),
    ...uint32(central.length),
    ...uint32(local.length),
    ...uint16(0),
  ]);
  const zip = new Uint8Array(local.length + central.length + end.length);
  zip.set(local);
  zip.set(central, local.length);
  zip.set(end, local.length + central.length);
  return zip;
}

function testFile(content: Uint8Array | string, name: string): File {
  const bytes =
    typeof content === "string" ? new TextEncoder().encode(content) : content;
  const file = new File([bytes], name);
  Object.defineProperty(file, "arrayBuffer", {
    value: async () =>
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
  });
  return file;
}

describe("extractDocxText", () => {
  it("extracts plain paragraph text without rendering Word HTML", async () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
      <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
          <w:p><w:r><w:t>第一段脚本</w:t></w:r></w:p>
          <w:p><w:r><w:t>第二段</w:t><w:tab/><w:t>带制表符</w:t></w:r></w:p>
        </w:body>
      </w:document>`;
    const file = testFile(storedZip("word/document.xml", xml), "脚本.docx");
    await expect(extractDocxText(file)).resolves.toBe(
      "第一段脚本\n第二段\t带制表符",
    );
  });

  it("rejects old doc files and invalid archives with clear errors", async () => {
    await expect(extractDocxText(testFile("old", "脚本.doc"))).rejects.toThrow(
      DocxError,
    );
    await expect(
      extractDocxText(testFile("not-a-zip", "脚本.docx")),
    ).rejects.toThrow("无法读取这个 Word 文件");
  });

  it("stops inflating when the real document exceeds the safe limit", async () => {
    const oversizedXml = "A".repeat(8 * 1024 * 1024 + 1);
    const forged = deflatedZip("word/document.xml", oversizedXml, 1);

    await expect(
      extractDocxText(testFile(forged, "oversized.docx")),
    ).rejects.toThrow("Word 文档内容过大");
  });
});
