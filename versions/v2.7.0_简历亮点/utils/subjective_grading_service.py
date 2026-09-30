# -*- coding: utf-8 -*-
"""主观题 AI 辅助批改服务（v2.1.0）。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from models.models import GradingLog, Homework, HomeworkSubmission, Question


def _parse_json_object(text: str) -> dict:
    """从模型回复中提取 JSON 对象。"""
    match = re.search(r"\{.*\}", str(text or ""), re.S)
    if not match:
        raise ValueError("AI 批改结果不是有效 JSON。")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("AI 批改结果结构不正确。")
    return data


def grade_subjective_question(question, student_answer,
                              max_score, rubric="") -> dict:
    """AI 批改一道主观题，返回实际得分、百分率、评语和漏掉的得分点。"""
    from utils import llm_client

    max_score = float(max_score or 100)
    if max_score <= 0:
        raise ValueError("题目满分必须大于 0。")
    answer = str(student_answer or "").strip()
    if not answer:
        return {
            "score": 0.0,
            "max_score": max_score,
            "percent": 0.0,
            "feedback": "未作答。",
            "key_points_missed": [],
        }

    system = (
        "你是严谨的阅卷老师。根据题目、参考答案、评分标准和学生作答评分。"
        "只输出 JSON：{\"score\":0到满分之间的数字,"
        "\"feedback\":\"中文评语\","
        "\"key_points_missed\":[\"未覆盖得分点\"]}。"
        "不要输出 JSON 以外的内容。")
    user = (
        f"题目：{getattr(question, 'content', '')}\n"
        f"参考答案：{getattr(question, 'answer', '')}\n"
        f"评分标准：{rubric or '未单独设置'}\n"
        f"满分：{max_score:g}\n学生作答：{answer}")
    try:
        data = _parse_json_object(llm_client.chat_content(
            system, user, temperature=0.1))
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        raise ValueError("AI 批改结果无法解析，请重新批改或人工评分。")

    score = max(0.0, min(score, max_score))
    missed = data.get("key_points_missed") or []
    if isinstance(missed, str):
        missed = [missed]
    return {
        "score": round(score, 1),
        "max_score": max_score,
        "percent": round(score / max_score * 100, 1),
        "feedback": str(data.get("feedback", "")).strip(),
        "key_points_missed": [str(x).strip() for x in missed
                              if str(x).strip()],
    }


def _question_max_score(session, homework: Homework,
                        question: Question) -> float:
    """取主观题在作业中的满分；没配置则等额分摊。"""
    from models.models import HomeworkQuestion

    link = (session.query(HomeworkQuestion)
            .filter(HomeworkQuestion.homework_id == homework.id,
                    HomeworkQuestion.question_id == question.id).first())
    if link is not None and link.score is not None:
        return float(link.score)
    total_links = (session.query(HomeworkQuestion)
                   .filter(HomeworkQuestion.homework_id == homework.id).count())
    base = homework.total_score if homework.total_score else 100
    return round(float(base) / max(total_links, 1), 1)


def batch_grade_subjective(session, homework_id, question_id,
                           rubric="") -> dict:
    """批量批改某作业某道主观题的所有在线提交。"""
    homework = session.get(Homework, int(homework_id))
    question = session.get(Question, int(question_id))
    if homework is None or question is None:
        raise ValueError("作业或题目不存在。")
    if question.question_type != "solution":
        raise ValueError("只有解答题按主观题批量批改。")

    max_score = _question_max_score(session, homework, question)
    submissions = (session.query(HomeworkSubmission)
                   .filter(HomeworkSubmission.homework_id == homework.id)
                   .order_by(HomeworkSubmission.id.asc()).all())
    results = []
    for row in submissions:
        try:
            answers = json.loads(row.answers_json or "{}")
        except json.JSONDecodeError:
            answers = {}
        order_no = _order_no(session, homework.id, question.id)
        student_answer = answers.get(str(order_no), "") if isinstance(
            answers, dict) else ""
        try:
            graded = grade_subjective_question(
                question, student_answer, max_score, rubric)
        except ValueError as exc:
            graded = {
                "score": None, "max_score": max_score,
                "percent": None, "feedback": str(exc),
                "key_points_missed": [],
            }
        results.append({
            "submission_id": row.id,
            "student_name": row.student_name,
            "student_answer": str(student_answer or ""),
            **graded,
        })
    return {
        "homework_id": homework.id,
        "question_id": question.id,
        "question_content": question.content,
        "max_score": max_score,
        "results": results,
    }


def _order_no(session, homework_id: int, question_id: int) -> int | None:
    """读取题目在作业中的序号。"""
    from models.models import HomeworkQuestion

    link = (session.query(HomeworkQuestion)
            .filter(HomeworkQuestion.homework_id == homework_id,
                    HomeworkQuestion.question_id == question_id).first())
    return link.order if link is not None else None


def save_batch_log(session, homework_id, question_id,
                   payload: dict) -> GradingLog:
    """教师确认后给一批主观题批改留痕。"""
    log = GradingLog(
        homework_id=int(homework_id), student_id=None, image_count=0,
        total_score=None,
        ai_comment=json.dumps(
            {"question_id": int(question_id), **payload},
            ensure_ascii=False),
        mode="all", status="confirmed",
        created_at=datetime.now(), confirmed_at=datetime.now())
    session.add(log)
    session.flush()
    return log


# ---------------------------------------------------------------------------
# v2.5.0：主观题批改评语模板（内置 4 条预设 + 自定义，JSON 存储）
# ---------------------------------------------------------------------------

BUILTIN_COMMENT_TEMPLATES = [
    {"template_id": "builtin_excellent", "name": "优秀",
     "text": "思路清晰，步骤完整，继续保持！", "builtin": True},
    {"template_id": "builtin_good", "name": "良好",
     "text": "基本正确，注意细节优化。", "builtin": True},
    {"template_id": "builtin_fair", "name": "一般",
     "text": "思路有待加强，建议复习相关知识点。", "builtin": True},
    {"template_id": "builtin_weak", "name": "需努力",
     "text": "基础薄弱，建议从基础题开始练习。", "builtin": True},
]


def _templates_path():
    import config
    return config.DATA_DIR / "grading_comment_templates.json"


def load_comment_templates() -> list[dict]:
    """读取评语模板；文件缺失自建、损坏回退内置且不覆盖原文件。"""
    path = _templates_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return [dict(item) for item in BUILTIN_COMMENT_TEMPLATES]
    if not path.exists():
        try:
            path.write_text(json.dumps(
                {"templates": [dict(i) for i in BUILTIN_COMMENT_TEMPLATES]},
                ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return [dict(item) for item in BUILTIN_COMMENT_TEMPLATES]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        custom = raw.get("templates") if isinstance(raw, dict) else raw
        if not isinstance(custom, list):
            raise TypeError("模板结构非法")
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        # 损坏：回退内置，但不覆盖用户原文件
        return [dict(item) for item in BUILTIN_COMMENT_TEMPLATES]
    builtin_ids = {i["template_id"] for i in BUILTIN_COMMENT_TEMPLATES}
    kept = [item for item in custom
            if isinstance(item, dict) and item.get("template_id") not in builtin_ids]
    return [dict(i) for i in BUILTIN_COMMENT_TEMPLATES] + kept


def save_comment_template(name: str, text: str) -> list[dict]:
    """新增/更新一条自定义评语模板（同名覆盖）。"""
    name = str(name or "").strip()
    text = str(text or "").strip()
    if not name:
        raise ValueError("请填写模板名称。")
    if not text:
        raise ValueError("请填写评语内容。")
    import uuid as _uuid
    path = _templates_path()
    items = load_comment_templates()
    custom = [i for i in items if not i.get("builtin")]
    hit = next((i for i in custom if str(i.get("name")) == name), None)
    if hit is not None:
        hit["text"] = text
    else:
        custom.append({"template_id": "custom_" + _uuid.uuid4().hex,
                       "name": name, "text": text, "builtin": False})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"templates": custom},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return load_comment_templates()


def delete_comment_template(template_id: str) -> list[dict]:
    """删除一条自定义评语模板（内置不可删）。"""
    items = load_comment_templates()
    if str(template_id).startswith("builtin_"):
        raise ValueError("内置模板不可删除。")
    custom = [i for i in items
              if not i.get("builtin") and i.get("template_id") != template_id]
    path = _templates_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"templates": custom},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return load_comment_templates()
