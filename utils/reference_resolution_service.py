# -*- coding: utf-8 -*-
"""指代消解和主动澄清。"""

from __future__ import annotations

import re

from models.models import Exam, Homework, LessonPlan, Student


def _clarify(question: str, options: list[str], reference_type: str) -> dict:
    return {
        "needs_clarification": True,
        "clarification": {
            "question": question,
            "options": options[:4],
            "reference_type": reference_type,
        },
        "resolved": {},
    }


def _result(text: str, resolved: dict) -> dict:
    return {"text": text, "resolved": resolved,
            "needs_clarification": False, "clarification": None}


def _recent_students(session, limit=4) -> list[Student]:
    return session.query(Student).order_by(Student.id.desc()).limit(limit).all()


def _recent_exams(session, limit=4) -> list[Exam]:
    return session.query(Exam).order_by(Exam.exam_date.desc(),
                                        Exam.id.desc()).limit(limit).all()


def _recent_artifacts(session, limit=4) -> list[Homework]:
    return session.query(Homework).filter(Homework.is_template.is_(False)).order_by(
        Homework.created_at.desc(), Homework.id.desc()).limit(limit).all()


def _recent_plans(session, limit=4) -> list[LessonPlan]:
    return session.query(LessonPlan).order_by(LessonPlan.created_at.desc(),
                                              LessonPlan.id.desc()).limit(limit).all()


def resolve_reference(user_input, context, recent_history=None, session=None) -> dict:
    """把“上次/这次/那个”等指代替换成明确文本。

    可传入 session 查询数据库；不传时只按 context/recent_history 解析。
    """
    text = str(user_input or "").strip()
    context = context or {}
    recent_history = recent_history or []
    resolved = {}

    if re.search(r"(上次|上一套|那套).{0,4}(卷子|试卷|作业)", text):
        target = context.get("last_homework") or context.get("last_action")
        if session is not None:
            items = _recent_artifacts(session)
            if items:
                target = items[0].name
                resolved["homework_id"] = items[0].id
        if target:
            clear = str(target)
            resolved.setdefault("reference", "homework")
            return _result(re.sub(r"(上次那套卷子|那套卷子|上一套卷|上次的作业)", clear, text),
                           resolved)
        if session is not None:
            options = [x.name for x in _recent_artifacts(session)]
            if options:
                return _clarify("你指的是哪一套卷子？", options, "homework")
        return _clarify("你指的是哪一套卷子？", [], "homework")

    if re.search(r"(这次|这场|上次).{0,2}考试", text):
        target = context.get("exam_name")
        if session is not None:
            items = _recent_exams(session)
            if items:
                target = items[0].name
                resolved["exam_id"] = items[0].id
        if target:
            resolved["reference"] = "exam"
            return _result(re.sub(r"(这次考试|这场考试|上次考试)", str(target), text),
                           resolved)
        if session is not None:
            options = [x.name for x in _recent_exams(session)]
            if options:
                return _clarify("你指的是哪一场考试？", options, "exam")
        return _clarify("你指的是哪一场考试？", [], "exam")

    if re.search(r"(那个|这位|这名).{0,2}学生|他|她", text):
        target = context.get("student_name")
        if session is not None and not target:
            students = _recent_students(session)
            if students:
                options = [f"{s.name}（{s.class_name or '未分班'}）" for s in students]
                return _clarify("你指的是哪位学生？", options, "student")
        if target:
            resolved["reference"] = "student"
            return _result(re.sub(r"(那个学生|这位学生|这名学生)", str(target), text),
                           resolved)
        return _clarify("你指的是哪位学生？", [], "student")

    if re.search(r"(这个|该).{0,4}(知识点|章节)", text):
        target = context.get("knowledge_point") or context.get("current_chapter")
        if target:
            resolved["reference"] = "knowledge"
            return _result(re.sub(r"(这个知识点|该知识点|这个章节)", str(target), text),
                           resolved)
        return _clarify("你指的是哪个知识点或章节？", [], "knowledge")

    if re.search(r"(刚才|上次|那份).{0,2}教案", text):
        target = context.get("last_lesson_plan")
        if session is not None:
            items = _recent_plans(session)
            if items:
                target = items[0].title
                resolved["lesson_plan_id"] = items[0].id
        if target:
            resolved["reference"] = "lesson_plan"
            return _result(re.sub(r"(刚才的教案|上次的教案|那份教案)", str(target), text),
                           resolved)
        if session is not None:
            options = [x.title for x in _recent_plans(session)]
            if options:
                return _clarify("你指的是哪份教案？", options, "lesson_plan")
        return _clarify("你指的是哪份教案？", [], "lesson_plan")

    return _result(text, resolved)


def needs_missing_params(parsed: dict) -> dict | None:
    """检查常见任务缺失参数，返回澄清信息。"""
    intent = parsed.get("intent")
    params = parsed.get("params") or {}
    if intent == "prepare_lesson" and not (params.get("topic") or params.get("chapter")):
        return {"question": "这节课要备什么课题？", "options": [],
                "reference_type": "topic"}
    if intent == "analyze_student" and not params.get("student_name"):
        return {"question": "要分析哪位学生？", "options": [],
                "reference_type": "student"}
    return None


def high_risk_confirmation(operation: str, details: dict) -> dict:
    """构造高风险操作摘要，供页面二次确认。"""
    return {
        "needs_confirmation": True,
        "title": "请再次确认高风险操作",
        "operation": operation,
        "summary": "；".join(f"{k}：{v}" for k, v in details.items()),
        "remember_key": "confirm_high_risk",
    }
