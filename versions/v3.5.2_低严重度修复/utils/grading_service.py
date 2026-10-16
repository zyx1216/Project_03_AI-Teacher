# -*- coding: utf-8 -*-
"""作业图片智能批改服务（v1.9.7）。

口径：本地 RapidOCR 识别图片文字 → 文本 LLM 把识别文字结构化成“题号→学生答案”
→ 客观题对照标准答案自动判分，主观题调文本 LLM 按评分标准打分写评语。
不使用多模态视觉模型。所有 LLM 调用沿用现有超时与异常类型。
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from models.models import GradingLog, Homework, Question
from utils import llm_client, ocr_service
from utils import homework_score_service as score_svc
from utils import homework_service as hw_svc

OBJECTIVE_TYPES = {"choice", "fill", "judge"}

_RECOG_SYSTEM = (
    "你是作业答案识别助手。下面是学生作业照片的 OCR 文字，可能有识别噪声。"
    "请只输出一个 JSON 对象，键是题目序号（整数或字符串数字），"
    "值是该题学生作答的原文。无法辨认的题不要输出。不要输出 JSON 以外的内容。")

_SUBJECTIVE_SYSTEM = (
    "你是严谨的阅卷老师。根据题目、标准答案、评分标准和学生作答评分。"
    "只输出 JSON：{\"score\": 0到满分之间的数字, \"comment\": \"中文评语\", "
 "\"key_points\": \"得分点说明\"}。不要输出 JSON 以外的内容。")

_OVERALL_SYSTEM = (
    "你是教学助手。根据学生本次作业逐题批改结果，写一句中文整体评语，"
    "指出主要问题和改进方向，不超过80字。只输出评语本身。")


# ---------------------------------------------------------------------------
# 识别
# ---------------------------------------------------------------------------

def recognize_answers(image_bytes_list, homework) -> dict:
    """逐张 OCR → LLM 结构化成 {题号字符串: 学生答案}。"""
    ocr_texts = []
    for image_bytes in image_bytes_list:
        ocr_texts.append(ocr_service.ocr_image(image_bytes))
    raw_text = "\n\n".join(ocr_texts)
    reply = llm_client.chat_content(
        _RECOG_SYSTEM, f"作业：{homework.name}\nOCR文字：\n{raw_text}",
        temperature=0.0)
    return _parse_json_object(reply)


def _parse_json_object(text):
    """从模型回复里提取 JSON 对象；失败抛 ValueError。"""
    match = re.search(r"\{.*\}", str(text), re.S)
    if not match:
        raise ValueError("识别结果无法解析，请重新批改。")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("识别结果格式不正确。")
    return {str(k).strip(): str(v).strip() for k, v in data.items()
            if str(v).strip()}


# ---------------------------------------------------------------------------
# 批改
# ---------------------------------------------------------------------------

def grade_homework_image(image_bytes_list, homework_id: int,
                         student_id: int, mode: str = "all") -> dict:
    """识别并批改一份作业图片，返回逐题结果与总分（不落库）。"""
    if not image_bytes_list:
        raise ValueError("请先上传作业图片。")
    from utils.db import SessionLocal
    with SessionLocal() as session:
        hw = session.get(Homework, int(homework_id))
        if hw is None:
            raise ValueError("作业不存在。")
        pairs = hw_svc.homework_questions(session, int(homework_id))
        homework_name = hw.name
        recognized = recognize_answers(image_bytes_list, hw)

        items = []
        for order_no, (link, question) in enumerate(pairs, start=1):
            full_score = _full_score(link, hw, len(pairs))
            student_answer = _match_recognized(recognized, order_no)
            item = {
                "order_no": order_no,
                "question_id": question.id,
                "question_type": question.question_type,
                "student_answer": student_answer,
                "standard_answer": question.answer or "",
                "score": full_score,
                "earned_score": None,
                "is_correct": None,
                "comment": "",
                # v2.7.0：识别不确定/无作答时标注，提示人工确认
                "need_confirm": is_uncertain_answer(student_answer),
            }
            is_objective = question.question_type in OBJECTIVE_TYPES
            if is_objective:
                _grade_objective(item)
            elif mode == "all":
                _grade_subjective(item, question, full_score)
            items.append(item)

    total = round(sum(i["earned_score"] or 0 for i in items), 1)
    result = {
        "homework_id": int(homework_id),
        "student_id": int(student_id),
        "mode": mode,
        "image_count": len(image_bytes_list),
        "items": items,
        "total_score": total,
        "ai_comment": _overall_comment(items, total, homework_name),
    }
    return result


def _full_score(link, homework, question_count):
    """单题满分：关联有分值用分值，否则按作业总分等额均摊。"""
    if link.score is not None:
        return float(link.score)
    base = homework.total_score or 100
    return round(float(base) / max(question_count, 1), 1)


def _match_recognized(recognized, order_no):
    """按序号取学生答案；兼容“第2题/2.”等键。"""
    keys = [str(order_no), f"第{order_no}题", f"{order_no}.", f"{order_no}、"]
    for key in keys:
        if key in recognized:
            return recognized[key]
    for k, v in recognized.items():
        digits = re.sub(r"\D", "", k)
        if digits == str(order_no):
            return v
    return ""


# ---------------------------------------------------------------------------
# 客观题
# ---------------------------------------------------------------------------

def _grade_objective(item):
    """对照标准答案自动判定客观题。"""
    qtype = item["question_type"]
    student = item["student_answer"]
    standard = item["standard_answer"]
    if not student:
        item["earned_score"] = 0
        item["is_correct"] = False
        item["comment"] = "未识别到作答。"
        return
    correct = _is_objective_correct(qtype, student, standard)
    item["is_correct"] = correct
    item["earned_score"] = item["score"] if correct else 0
    item["comment"] = "回答正确。" if correct else (
        f"回答错误，标准答案：{standard}")


def _is_objective_correct(qtype, student, standard):
    """客观题对错判定。"""
    if qtype == "choice":
        s = re.search(r"[A-D]", student.upper())
        t = re.search(r"[A-D]", standard.upper())
        return bool(s and t and s.group(0) == t.group(0))
    if qtype == "judge":
        return _judge_value(student) == _judge_value(standard)
    # 填空题：去空格后，标准答案任一写法命中即算对。
    s_norm = re.sub(r"\s+", "", student)
    options = re.split(r"[；;、/\n]", standard)
    return any(s_norm == re.sub(r"\s+", "", opt) for opt in options if opt)


def _judge_value(text):
    """把判断说法归一为 True/False。"""
    t = str(text).strip()
    if t in ("错", "错误", "×", "✗", "F", "f", "false", "False", "B"):
        return False
    if t in ("对", "正确", "√", "T", "t", "true", "True", "A"):
        return True
    return None


# ---------------------------------------------------------------------------
# 主观题
# ---------------------------------------------------------------------------

def _grade_subjective(item, question, full_score):
    """LLM 给主观题评分与评语。"""
    user_text = (
        f"题目：{question.content}\n标准答案：{question.answer}\n"
        f"满分：{full_score}\n学生作答：{item['student_answer'] or '未作答'}")
    reply = llm_client.chat_content(
        _SUBJECTIVE_SYSTEM, user_text, temperature=0.2)
    try:
        data = _parse_score_json(reply)
        score = max(0, min(float(data.get("score", 0)), full_score))
    except (ValueError, TypeError):
        score = 0
    item["earned_score"] = round(score, 1)
    item["is_correct"] = score >= full_score * 0.6
    item["comment"] = str(data.get("comment", "")).strip()


def _parse_score_json(text):
    match = re.search(r"\{.*\}", str(text), re.S)
    if not match:
        raise ValueError("评分结果无法解析。")
    return json.loads(match.group(0))


def _overall_comment(items, total, homework_name):
    """AI 整体评语；调用失败用确定性模板兜底。"""
    correct_n = sum(1 for i in items if i.get("is_correct"))
    try:
        user_text = (
            f"作业：{homework_name}，总分得分：{total}\n"
            f"逐题情况：" + "；".join(
                f"第{i['order_no']}题{i['earned_score']}/{i['score']}"
                f"（{i['comment']}）" for i in items))
        return str(llm_client.chat_content(
            _OVERALL_SYSTEM, user_text, temperature=0.4)).strip()
    except Exception:
        return f"本次共答对 {correct_n}/{len(items)} 题，得分 {total}，请结合错题复习。"


# ---------------------------------------------------------------------------
# 确认落库
# ---------------------------------------------------------------------------

def confirm_grading(session, result: dict) -> dict:
    """把批改结果写入作业作答/总分，并留一条 confirmed 的批改记录。"""
    homework_id = int(result["homework_id"])
    student_id = int(result["student_id"])

    log = GradingLog(
        homework_id=homework_id, student_id=student_id,
        image_count=int(result.get("image_count", 0)),
        total_score=result.get("total_score"),
        ai_comment=result.get("ai_comment"),
        mode=result.get("mode", "all"), status="confirmed",
        created_at=datetime.now(), confirmed_at=datetime.now())
    session.add(log)

    entries = [{
        "student_id": student_id,
        "question_id": i["question_id"],
        "order_no": i["order_no"],
        "is_correct": i.get("is_correct"),
        "earned_score": i.get("earned_score"),
        "error_type": None,
    } for i in result.get("items", [])]
    score_svc.save_answers(session, homework_id, entries)
    score_svc.save_total_score(
        session, homework_id, student_id, result.get("total_score"))
    session.flush()
    return {"grading_log_id": log.id,
            "total_score": result.get("total_score")}

# ---------------------------------------------------------------------------
# v2.1.0：在线提交作业的客观题批量重批
# ---------------------------------------------------------------------------


def grade_objective_question(question, student_answer) -> dict:
    """批改单道客观题，返回对错、按本题百分制折算分和标准答案。"""
    qtype = getattr(question, "question_type", "")
    standard = str(getattr(question, "answer", "") or "")
    student = str(student_answer or "").strip()
    if qtype not in OBJECTIVE_TYPES:
        raise ValueError("只有选择、填空、判断题能按客观题批改。")

    correct = _is_objective_correct(qtype, student, standard)
    return {
        "correct": bool(correct),
        "score": 100.0 if correct else 0.0,
        "correct_answer": standard,
    }


def grade_homework_objective(session, homework_id, *, force=False) -> dict:
    """对某作业全部在线提交重算客观题百分制得分。"""
    from models.models import HomeworkSubmission

    hw = session.get(Homework, int(homework_id))
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")

    pairs = hw_svc.homework_questions(session, hw.id)
    objective_pairs = [
        (link.order, question) for link, question in pairs
        if question.question_type in OBJECTIVE_TYPES
    ]
    if not objective_pairs:
        return {"homework_id": hw.id, "updated": 0, "skipped": 0,
                "objective_count": 0}

    submissions = (session.query(HomeworkSubmission)
                   .filter(HomeworkSubmission.homework_id == hw.id).all())
    updated = skipped = 0
    for row in submissions:
        # 默认保护老师已经写过评语的记录；强制重批也只重算客观题分。
        if not force and (row.feedback or "").strip():
            skipped += 1
            continue
        try:
            answers = json.loads(row.answers_json or "{}")
        except json.JSONDecodeError:
            answers = {}
        if not isinstance(answers, dict):
            answers = {}

        correct = 0
        for order, question in objective_pairs:
            result = grade_objective_question(
                question, answers.get(str(order)))
            correct += 1 if result["correct"] else 0
        row.score = round(correct / len(objective_pairs) * 100, 2)
        updated += 1

    session.flush()
    return {
        "homework_id": hw.id,
        "updated": updated,
        "skipped": skipped,
        "objective_count": len(objective_pairs),
    }


# ---------------------------------------------------------------------------
# v2.7.0：识别结果的不确定性判定（图片批改强化）
# ---------------------------------------------------------------------------

def is_uncertain_answer(student_answer) -> bool:
    """识别结果是否需人工确认：空、过短（<2 字符）或含乱码/问号占位。"""
    text = str(student_answer or "").strip()
    if len(text) < 2:
        return True
    if text in {"？", "?", "无法识别", "未知"}:
        return True
    # OCR 常见乱码特征（连续问号/替换符）
    if "�" in text or "????" in text:
        return True
    return False
