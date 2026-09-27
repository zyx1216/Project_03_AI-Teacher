"""全局搜索服务（v1.8.1）：纯逻辑，不依赖 Streamlit。

按关键词搜索题目、教案、学生、作业四类，各取前 5 条。
LIKE 查询的通配符做转义，防止输入 %、_ 破坏匹配。
"""
from __future__ import annotations

from models.models import Homework, LessonPlan, Question, Student

_DRAFT_PREFIX = "__smart_compose_draft__"


def _like_value(query: str) -> str:
    """转义 SQL LIKE 通配符，再包成模糊匹配串。"""
    escaped = (query.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_"))
    return f"%{escaped}%"


def search_all(session, query: str, limit: int = 5) -> dict:
    """搜索四类对象，返回 {questions, plans, students, homeworks}。"""
    like = _like_value(query.strip())

    questions = (session.query(Question)
                 .filter((Question.content.like(like, escape="\\")) |
                         (Question.knowledge_points.like(like, escape="\\")))
                 .limit(limit).all())

    plans = (session.query(LessonPlan)
             .filter((LessonPlan.title.like(like, escape="\\")) |
                     (LessonPlan.chapter.like(like, escape="\\")))
             .limit(limit).all())

    students = (session.query(Student)
                .filter(Student.name.like(like, escape="\\"))
                .limit(limit).all())

    homeworks = (session.query(Homework)
                 .filter(Homework.name.like(like, escape="\\"))
                 .filter(Homework.is_template.is_(False))
                 .filter(~Homework.name.like(_DRAFT_PREFIX + "%", escape="\\"))
                 .limit(limit).all())

    return {
        "questions": questions,
        "plans": plans,
        "students": students,
        "homeworks": homeworks,
    }
