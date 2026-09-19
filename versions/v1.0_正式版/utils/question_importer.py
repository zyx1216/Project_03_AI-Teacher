# -*- coding: utf-8 -*-
"""
题目外部导入层。

支持三种来源，统一产出题目字典，再交给 question_service 校验入库：
- Excel：按列映射 题干/题型/答案/解析/知识点/难度（表头模糊识别）；
- Word：按题目编号（1. / 1、 / (1) 等）自动切分；
- 粘贴文本：按空行分段，或按编号切分。

铁律不变：缺答案的题不入库，只在预览里标红提醒补充。
所有导入题默认进入"待审核"。
"""

from __future__ import annotations

import io
import re

import pandas as pd

from utils import question_service as qs

# Excel 列名别名
COLUMN_ALIASES = {
    "content": ["题干", "题目", "题面", "内容", "question", "content"],
    "question_type": ["题型", "类型", "type"],
    "answer": ["答案", "解答", "answer"],
    "analysis": ["解析", "详解", "分析", "analysis"],
    "knowledge_points": ["知识点", "考点", "knowledge", "kp"],
    "difficulty": ["难度", "difficulty", "level"],
    "error_points": ["易错点", "易错", "error"],
}

# 题目编号：1. / 1、 / 1） / (1) / （1） / 第1题
_NUMBER_RE = re.compile(
    r"^\s*(?:第?\s*)?(?:[（(]?\s*\d+\s*[）).、]|\d+[.、])\s*"
)


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or "").lower())


def _build_alias_lookup():
    lookup = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            lookup[_norm(a)] = field
    return lookup


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def detect_question_columns(df: pd.DataFrame) -> dict:
    """识别题目表的列，返回 {字段: 原列名}；题干和答案缺失时给问题提示。"""
    lookup = _build_alias_lookup()
    mapping = {f: None for f in COLUMN_ALIASES}
    for col in df.columns:
        field = lookup.get(_norm(col))
        if field and mapping[field] is None:
            mapping[field] = col
    problems = []
    if mapping["content"] is None:
        problems.append("没有识别到题干列（需含“题干”或“题目”列）")
    if mapping["answer"] is None:
        problems.append("没有识别到答案列（需含“答案”列）")
    return {"mapping": mapping, "problems": problems}


def records_from_excel(df: pd.DataFrame, mapping: dict) -> list[dict]:
    """把题目 Excel 转成原始题目字典列表（未校验，保留 problems 供预览标红）。"""
    records = []
    for row_no, (_, row) in enumerate(df.iterrows(), start=2):
        def cell(field):
            col = mapping.get(field)
            if col is None:
                return ""
            val = row[col]
            if pd.isna(val):
                return ""
            return str(val).strip()

        content = cell("content")
        answer = cell("answer")
        problems = []
        if not content:
            problems.append("缺题干")
        if not answer:
            problems.append("缺答案")
        records.append({
            "row_no": row_no,
            "content": content,
            "question_type": cell("question_type"),
            "answer": answer,
            "analysis": cell("analysis"),
            "knowledge_points": cell("knowledge_points"),
            "difficulty": cell("difficulty") or 2,
            "error_points": cell("error_points"),
            "problems": problems,
        })
    # 整行全空的剔除
    records = [r for r in records if r["content"] or r["answer"]
               or r["analysis"] or r["knowledge_points"]]
    return records


# ---------------------------------------------------------------------------
# Word / 粘贴文本
# ---------------------------------------------------------------------------

def _split_numbered(text: str) -> list[str]:
    """按行首编号切分文本；切不出编号时按空行退一段一块。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks, current = [], []
    found_number = False
    for line in lines:
        if _NUMBER_RE.match(line):
            found_number = True
            if current:
                blocks.append("\n".join(current).strip())
            current = [_NUMBER_RE.sub("", line, count=1)]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    if not found_number:
        # 没有编号：空行分段
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [b for b in blocks if b]


_BLOCK_FIELD_RE = {
    "answer": re.compile(r"(?:答案|解)\s*[:：]?\s*(.*)"),
    "analysis": re.compile(r"(?:解析|详解|分析)\s*[:：]?\s*(.*)"),
    "error_points": re.compile(r"(?:易错点?|注意)\s*[:：]?\s*(.*)"),
    "question_type": re.compile(r"(?:题型|类型)\s*[:：]?\s*(.*)"),
    "knowledge_points": re.compile(r"(?:知识点?|考点)\s*[:：]?\s*(.*)"),
    "difficulty": re.compile(r"(?:难度)\s*[:：]?\s*(.*)"),
}


def _parse_block(block: str, index: int) -> dict:
    """
    解析一个题目块：识别“答案：”“解析：”等标记行。
    没有结构化标记时，整块当题干（这种多半缺答案，会在预览标红）。
    """
    fields = {"content": "", "answer": "", "analysis": "", "error_points": "",
              "question_type": "", "knowledge_points": "", "difficulty": 2}
    content_lines = []
    for line in block.split("\n"):
        matched = False
        for field, pat in _BLOCK_FIELD_RE.items():
            m = pat.match(line.strip())
            if m:
                fields[field] = m.group(1).strip()
                matched = True
                break
        if not matched:
            content_lines.append(line)
    fields["content"] = "\n".join(content_lines).strip()

    problems = []
    if not fields["content"]:
        problems.append("缺题干")
    if not fields["answer"]:
        problems.append("缺答案")
    fields["row_no"] = index + 1
    fields["problems"] = problems
    return fields


def records_from_text(text: str) -> list[dict]:
    """粘贴文本 -> 题目字典列表。"""
    blocks = _split_numbered(text or "")
    return [_parse_block(b, i) for i, b in enumerate(blocks)]


def records_from_docx(file_bytes_or_path) -> list[dict]:
    """Word 文档 -> 题目字典列表（按编号/空行切分）。"""
    from docx import Document
    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        doc = Document(io.BytesIO(file_bytes_or_path))
    else:
        doc = Document(file_bytes_or_path)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    return records_from_text(full_text)


# ---------------------------------------------------------------------------
# 统一入库
# ---------------------------------------------------------------------------

def import_records(session, records: list[dict]) -> dict:
    """
    把预览确认后的记录校验入库。
    - 缺题干或缺答案的跳过（统计到 rejected）；
    - 通过的归一化后保存，默认来源 imported、状态 pending。
    返回 {imported, rejected}。
    """
    imported = rejected = 0
    for rec in records:
        if rec.get("problems"):
            rejected += 1
            continue
        item = {
            "content": rec["content"],
            "question_type": rec.get("question_type") or "solution",
            "answer": rec["answer"],
            "analysis": rec.get("analysis") or "",
            "knowledge_points": rec.get("knowledge_points") or "",
            "difficulty": rec.get("difficulty") or 2,
            "error_points": rec.get("error_points") or "",
        }
        normalized = qs.validate_question(item)
        if normalized is None:
            rejected += 1
            continue
        qs.create_question(session, normalized, source="imported", status="pending")
        imported += 1
    session.flush()
    return {"imported": imported, "rejected": rejected}