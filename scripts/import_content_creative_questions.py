from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
EXPECTED_HEADERS = [
    "序号",
    "题目来源",
    "题型",
    "题目内容",
    "选项A",
    "选项B",
    "选项C",
    "选项D",
    "选项E",
    "选项F",
    "选项G",
    "选项H",
    "正确答案",
    "备注",
]
TYPE_MAP = {"单选": "single", "多选": "multiple", "判断": "judgment"}
RATIO_FIXES = {
    12: ["1:1", "9:16", "4:3", "3:4"],
    576: ["1:1", "4:3", "3:4", "9:16"],
}


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"无效单元格地址：{reference}")
    value = 0
    for character in letters.group(0):
        value = value * 26 + ord(character) - 64
    return value - 1


def _read_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.findall(".//x:t", NS))
            for item in shared_root.findall("x:si", NS)
        ]
        sheet_root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows: list[list[str]] = []
    for row_node in sheet_root.findall(".//x:sheetData/x:row", NS):
        values = [""] * len(EXPECTED_HEADERS)
        for cell in row_node.findall("x:c", NS):
            index = _column_index(cell.attrib["r"])
            if index >= len(values):
                continue
            value_node = cell.find("x:v", NS)
            if value_node is None:
                continue
            raw = value_node.text or ""
            values[index] = shared[int(raw)] if cell.attrib.get("t") == "s" else raw
        rows.append(values)
    return rows


def import_questions(source: Path) -> dict[str, object]:
    rows = _read_rows(source)
    if not rows or rows[0] != EXPECTED_HEADERS:
        raise ValueError(f"题库表头不符合预期：{rows[0] if rows else '空工作簿'}")

    questions: list[dict[str, object]] = []
    for row in rows[1:]:
        serial = int(row[0])
        source_name = row[1].strip()
        raw_type = row[2].strip()
        prompt = row[3].strip()
        if raw_type not in TYPE_MAP:
            raise ValueError(f"第 {serial} 题题型无效：{raw_type}")

        option_values = [value.strip() for value in row[4:12]]
        if serial in RATIO_FIXES:
            option_values[:4] = RATIO_FIXES[serial]
        options = [
            {"key": chr(65 + index), "text": value}
            for index, value in enumerate(option_values)
            if value and value != "21"
        ]
        if [item["key"] for item in options] != [
            chr(65 + index) for index in range(len(options))
        ]:
            raise ValueError(f"第 {serial} 题选项不连续")

        raw_answer = row[12].strip()
        if raw_type == "判断":
            if len(options) != 2:
                raise ValueError(f"第 {serial} 题判断选项数量错误")
            options = [
                {"key": "A", "text": "正确"},
                {"key": "B", "text": "错误"},
            ]
            answer_map = {"正确": "A", "对": "A", "错误": "B", "错": "B"}
            if raw_answer not in answer_map:
                raise ValueError(f"第 {serial} 题判断答案无法匹配：{raw_answer}")
            correct_options = [answer_map[raw_answer]]
        else:
            correct_options = list(raw_answer.replace(" ", "").upper())

        option_keys = {item["key"] for item in options}
        if not correct_options or any(key not in option_keys for key in correct_options):
            raise ValueError(f"第 {serial} 题答案超出选项范围：{raw_answer}")
        if raw_type == "单选" and len(correct_options) != 1:
            raise ValueError(f"第 {serial} 题单选答案数量错误")
        review_notes: list[str] = []
        if raw_type == "多选" and len(correct_options) < 2:
            review_notes.append("源文件标记为多选，但正确答案少于两个选项")

        note = row[13].strip()
        questions.append(
            {
                "id": f"content-creative-{serial:04d}",
                "serial": serial,
                "source": source_name,
                "type": TYPE_MAP[raw_type],
                "prompt": prompt,
                "options": options,
                "correct_options": correct_options,
                "note": None if not note or note == "21" else note,
                "needs_review": bool(review_notes),
                "review_notes": review_notes,
            }
        )

    counts = {
        question_type: sum(item["type"] == question_type for item in questions)
        for question_type in TYPE_MAP.values()
    }
    if len(questions) != 628 or counts != {
        "single": 352,
        "multiple": 181,
        "judgment": 95,
    }:
        raise ValueError(f"题库数量校验失败：总数 {len(questions)}，分类 {counts}")
    if len({item["id"] for item in questions}) != len(questions):
        raise ValueError("题目 ID 不唯一")

    return {
        "schema_version": 1,
        "title": "巨量认证内容创意初级题库",
        "question_count": len(questions),
        "type_counts": counts,
        "questions": questions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导入巨量认证内容创意初级题库")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = import_questions(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Imported {payload['question_count']} questions to {args.output} "
        f"({payload['type_counts']})"
    )


if __name__ == "__main__":
    main()
