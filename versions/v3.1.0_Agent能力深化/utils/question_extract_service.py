# -*- coding: utf-8 -*-
"""资料/批改题目提取 + 难度判定（v2.5.1）。

- 从资料正文确定性切分题目，AI 可选做结构化补全；
- 难度判定不使用得分率，改为 AI 多维度加权合成。
所有函数不直接操作数据库连接之外的东西；调用方负责 session 与落库。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import config

# 难度权重（合计 1.0）：AI 预估 50% / 知识点复杂度 20% / 步骤数 15% /
# 易错点 10% / 教师手动调整 5%
DIFFICULTY_WEIGHTS = {
    "ai_estimate": 0.50,
    "knowledge_complexity": 0.20,
    "step_count": 0.15,
    "error_prone_points": 0.10,
    "teacher_adjust": 0.05,
}

# 各维度 → 难度分（0=易、1=中、2=难）
_COMPLEXITY_SCORE = {"概念理解": 0, "简单应用": 1, "综合应用": 2, "创新应用": 2}
_STEP_SCORE = {1: 0, 2: 1, 3: 1, 4: 2}
_ERROR_SCORE = {0: 0, 1: 0, 2: 1}  # >=2 易错点视为中；再按阈值细分
_LABEL_BY_SCORE = {0: "易", 1: "中", 2: "难"}
_SCORE_BY_LABEL = {"易": 0, "中": 1, "难": 2}


def _material_text_path(material_id: int) -> Path:
    return Path(config.UPLOAD_DIR) / "text" / f"{int(material_id)}.txt"


def parse_question_structure(text: str) -> dict:
    """解析单道题的确定性结构：题干、选项、答案、解析。

    尽量从纯文本里提取；提取不到的字段留空字符串，不抛异常。
    """
    raw = str(text or "").strip()
    if not raw:
        return {"content": "", "question_type": "solution", "options": [],
                "answer": "", "analysis": "", "knowledge_points": []}
    answer = ""
    analysis = ""
    # 答案 / 解析 常见标注
    m = re.search(r"(?:答案|参考答案|【答案】)\s*[:：]?\s*(.+)", raw)
    if m:
        answer = m.group(1).strip().split("\n")[0]
    m2 = re.search(r"(?:解析|解答|【解析】)\s*[:：]?\s*(.+)", raw, re.S)
    if m2:
        analysis = m2.group(1).strip()
    options = re.findall(r"(?:^|\n)\s*([A-DＡ-Ｄ])[．.、)）]\s*(.+)", raw)
    content = raw
    for cut in ("答案", "参考答案", "解析", "解答"):
        idx = content.find(cut)
        if idx > 0:
            content = content[:idx]
    content = content.strip()
    if options:
        qtype = "choice"
    elif re.search(r"(?:判断|对错|正确|错误)", raw):
        qtype = "judge"
    elif re.search(r"_{2,}|（\s*）|\(\s*\)", raw):
        qtype = "fill"
    else:
        qtype = "solution"
    return {
        "content": content,
        "question_type": qtype,
        "options": [f"{k}.{v.strip()}" for k, v in options],
        "answer": answer,
        "analysis": analysis,
        "knowledge_points": [],
    }


def _split_blocks(text: str) -> list[str]:
    """按题号把整段文本切成单题块（复用导入器的确定性切分思路）。"""
    lines = str(text or "").split("\n")
    blocks, current = [], []
    num_re = re.compile(r"^\s*(?:第\s*)?(\d{1,3})\s*[.、．)）]\s*")
    for line in lines:
        if num_re.match(line) and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b.strip()]


def _ai_structure_block(block: str, chat_func) -> dict:
    """用 AI 把单题块结构化；失败返回 None，由调用方回落确定性结果。"""
    if chat_func is None:
        return None
    system = (
        "你是中小学题目解析助手。把给定文本整理成 JSON："
        '{"content":"题干","question_type":"choice|fill|judge|solution",'
        '"answer":"答案","analysis":"解析","knowledge_points":["知识点"]}。'
        "只输出 JSON，缺信息给空字符串，不要编造答案。")
    try:
        raw = chat_func(system, f"题目文本：\\n{block}")
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", str(raw).strip(),
                                 flags=re.M))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 —— AI 失败回落到确定性结果
        return None


def extract_questions_from_material(material_id: int, chat_func=None) -> list[dict]:
    """从资料正文提取题目。

    AI 可用时逐题结构化；不可用或失败时退化为确定性解析（调用方可提示未做 AI 结构化）。
    """
    path = _material_text_path(material_id)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    results = []
    for block in _split_blocks(text):
        parsed = _ai_structure_block(block, chat_func) or parse_question_structure(block)
        parsed.setdefault("options", [])
        parsed.setdefault("knowledge_points", [])
        if not str(parsed.get("content") or "").strip():
            continue
        results.append(parsed)
    return results


def estimate_difficulty(question: dict, chat_func=None,
                        teacher_label: str | None = None) -> dict:
    """AI 多维度预估难度（不使用得分率）。

    返回 {"difficulty": "易/中/难", "evidence": {...}}；
    AI 不可用时各维度用确定性启发式，仍给出结果并标注来源。
    """
    content = str((question or {}).get("content") or "")
    kps = question.get("knowledge_points") or []
    error_points = str(question.get("error_points") or "")

    # 维度 1：AI 预估（50%）
    ai_label = None
    if chat_func is not None:
        try:
            system = (
                "你是题目难度评估专家。只输出 JSON："
                "{'difficulty':'易|中|难',"
                "'knowledge_complexity':'概念理解|简单应用|综合应用|创新应用',"
                "'step_count':1,'error_prone_points':0}。"
                "标准：易=单一知识点直接套用1-2步；"
                "中=1-2知识点简单变形2-3步；难=多知识点综合，4步以上。")
            raw = chat_func(system, f"题目：{content}")
            data = json.loads(re.sub(r"^```(?:json)?|```$", "", str(raw).strip(),
                                     flags=re.M))
            ai_label = str(data.get("difficulty") or "").strip()
            complexity = str(data.get("knowledge_complexity") or "").strip()
            step_count = int(data.get("step_count") or 0)
            err_cnt = int(data.get("error_prone_points") or 0)
        except Exception:  # noqa: BLE001
            ai_label = None
    if ai_label not in _SCORE_BY_LABEL:
        # 确定性兜底：按知识点数与题干长度粗估
        ai_label = ("易" if len(kps) <= 1 and len(content) <= 40
                    else ("难" if len(kps) >= 3 else "中"))
    complexity = locals().get("complexity") or (
        "概念理解" if len(kps) <= 1 else ("综合应用" if len(kps) >= 3 else "简单应用"))
    step_count = locals().get("step_count") or (
        1 if len(kps) <= 1 else (3 if len(kps) == 2 else 4))
    err_cnt = locals().get("err_cnt") or len(
        [x for x in re.split(r"[，,、;；\n]", error_points) if x.strip()])

    # 各维度难度分（0/1/2）
    scores = {
        "ai_estimate": _SCORE_BY_LABEL[ai_label],
        "knowledge_complexity": _COMPLEXITY_SCORE.get(complexity, 1),
        "step_count": _STEP_SCORE.get(min(max(step_count, 1), 4), 1),
        "error_prone_points": 2 if err_cnt >= 3 else _ERROR_SCORE.get(err_cnt, 0),
        "teacher_adjust": _SCORE_BY_LABEL.get(teacher_label, 1),
    }
    weighted = sum(scores[k] * DIFFICULTY_WEIGHTS[k] for k in DIFFICULTY_WEIGHTS)
    # 权重分 0~2 → 门槛：<0.67 易、<1.34 中、否则难
    label = "易" if weighted < 0.67 else ("中" if weighted < 1.34 else "难")
    return {
        "difficulty": label,
        "evidence": {
            "knowledge_complexity": complexity,
            "step_count": step_count,
            "error_prone_points": err_cnt,
            "ai_estimate": ai_label,
            "weighted_score": round(weighted, 3),
        },
    }


# 兼容指令里的短名
estimate_question_difficulty = estimate_difficulty
