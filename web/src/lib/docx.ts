import { inflateRaw } from "pako";

const MAX_UNCOMPRESSED_XML_BYTES = 8 * 1024 * 1024;
const WORD_NAMESPACE =
  "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

export class DocxError extends Error {}

interface ZipEntry {
  compression: number;
  compressedSize: number;
  uncompressedSize: number;
  localOffset: number;
}

function findEndOfCentralDirectory(view: DataView): number {
  const minimum = Math.max(0, view.byteLength - 65_557);
  for (let offset = view.byteLength - 22; offset >= minimum; offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) return offset;
  }
  throw new DocxError("无法读取这个 Word 文件，请确认文件未损坏。");
}

function findDocumentEntry(bytes: Uint8Array): ZipEntry | null {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const eocd = findEndOfCentralDirectory(view);
  const entryCount = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  const decoder = new TextDecoder();

  for (let index = 0; index < entryCount; index += 1) {
    if (
      offset + 46 > view.byteLength ||
      view.getUint32(offset, true) !== 0x02014b50
    ) {
      throw new DocxError("Word 文件结构无效，请重新另存为 .docx 后再试。");
    }
    const compression = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const uncompressedSize = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const nameStart = offset + 46;
    const name = decoder.decode(bytes.subarray(nameStart, nameStart + nameLength));
    if (name === "word/document.xml") {
      return {
        compression,
        compressedSize,
        uncompressedSize,
        localOffset,
      };
    }
    offset = nameStart + nameLength + extraLength + commentLength;
  }
  return null;
}

function readEntry(bytes: Uint8Array, entry: ZipEntry): Uint8Array {
  if (entry.uncompressedSize > MAX_UNCOMPRESSED_XML_BYTES) {
    throw new DocxError("Word 文档内容过大，请精简后再试。");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (
    entry.localOffset + 30 > view.byteLength ||
    view.getUint32(entry.localOffset, true) !== 0x04034b50
  ) {
    throw new DocxError("Word 文件结构无效，请重新另存为 .docx 后再试。");
  }
  const nameLength = view.getUint16(entry.localOffset + 26, true);
  const extraLength = view.getUint16(entry.localOffset + 28, true);
  const dataStart = entry.localOffset + 30 + nameLength + extraLength;
  const dataEnd = dataStart + entry.compressedSize;
  if (dataEnd > bytes.byteLength) {
    throw new DocxError("Word 文件内容不完整，请重新选择文件。");
  }
  const compressed = bytes.subarray(dataStart, dataEnd);
  if (entry.compression === 0) return compressed;
  if (entry.compression === 8) {
    try {
      return inflateRaw(compressed);
    } catch {
      throw new DocxError("无法解压这个 Word 文件，文件可能已损坏或加密。");
    }
  }
  throw new DocxError("暂不支持这个 Word 文件的压缩格式。");
}

function paragraphText(paragraph: Element): string {
  let output = "";
  const visit = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      output += node.nodeValue ?? "";
      return;
    }
    if (node instanceof Element && node.namespaceURI === WORD_NAMESPACE) {
      if (node.localName === "tab") output += "\t";
      if (node.localName === "br" || node.localName === "cr") output += "\n";
    }
    node.childNodes.forEach(visit);
  };
  paragraph.childNodes.forEach(visit);
  return output.trimEnd();
}

export async function extractDocxText(file: File): Promise<string> {
  const lowerName = file.name.toLowerCase();
  if (lowerName.endsWith(".doc") && !lowerName.endsWith(".docx")) {
    throw new DocxError("暂不支持旧版 .doc，请在 Word 中另存为 .docx 后上传。");
  }
  if (!lowerName.endsWith(".docx")) {
    throw new DocxError("请选择 .docx 格式的 Word 文档。");
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  const entry = findDocumentEntry(bytes);
  if (!entry) {
    throw new DocxError(
      "未找到可读取的正文，文件可能已加密或不是有效的 .docx 文档。",
    );
  }
  const xmlBytes = readEntry(bytes, entry);
  const xml = new TextDecoder("utf-8", { fatal: false }).decode(xmlBytes);
  const document = new DOMParser().parseFromString(xml, "application/xml");
  if (document.querySelector("parsererror")) {
    throw new DocxError("Word 正文解析失败，请重新另存文件后再试。");
  }
  const paragraphs = Array.from(
    document.getElementsByTagNameNS(WORD_NAMESPACE, "p"),
  )
    .map(paragraphText)
    .filter((paragraph) => paragraph.trim());
  const text = paragraphs.join("\n").trim();
  if (!text) throw new DocxError("这个 Word 文档没有可分析的文字内容。");
  return text;
}
