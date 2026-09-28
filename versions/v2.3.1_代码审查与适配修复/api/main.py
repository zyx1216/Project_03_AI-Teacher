# -*- coding: utf-8 -*-
"""AI 教学辅助 REST API（v1.9.8）。

路由直接调用现有 service 层，复用 utils.db 的数据库连接，不重复业务逻辑。
除 /api/health 外，所有接口都要在请求头 X-API-Key 中带有效密钥。
交互式文档：/docs（Swagger）、/redoc（ReDoc）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from utils import api_key_service
from utils import db
from utils import (
    agent_service, exam_service, student_service)
from models.models import Exam, Score

app = FastAPI(title="AI 教学辅助API", version="1.9.8")


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------

def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """校验 X-API-Key；失败返回 401。"""
    if not api_key_service.verify_key(x_api_key or ""):
        raise HTTPException(status_code=401, detail="无效或缺失的 API Key。")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class StudentIn(BaseModel):
    """新增学生入参。"""
    name: str = Field(min_length=1)
    class_name: str = Field(min_length=1)
    gender: str = "未知"


class ScoreIn(BaseModel):
    """录入成绩入参。"""
    student_name: str = Field(min_length=1)
    class_name: str = ""
    exam_name: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    score: float


class QuestionIn(BaseModel):
    """AI 出题入参。"""
    subject: str = "数学"
    grade: str = ""
    question_type: str = "choice"
    difficulty: int = 1
    knowledge_point: str = ""
    count: int = 5


class LessonIn(BaseModel):
    """AI 备课入参。"""
    subject: str = "数学"
    grade: str = ""
    chapter: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 健康检查（无需认证）
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["系统"])
def health_check():
    """健康检查。"""
    return {"status": "ok", "service": "AI教学辅助API"}


# ---------------------------------------------------------------------------
# 学生
# ---------------------------------------------------------------------------

@app.get("/api/students", tags=["学生"], dependencies=[Depends(require_key)])
def list_students(class_name: Optional[str] = None):
    """获取学生列表。"""
    with db.SessionLocal() as session:
        rows = student_service.list_students(
            session, class_name=class_name)
        return [{"id": s.id, "name": s.name,
                 "class_name": s.class_name,
                 "gender": s.gender or "未知"} for s in rows]


@app.post("/api/students", tags=["学生"], dependencies=[Depends(require_key)])
def create_student(student: StudentIn):
    """新增学生；已存在则返回已有学生。"""
    with db.SessionLocal() as session:
        existing, created = student_service.get_or_create_student(
            session, student.name, student.class_name)
        if created and student.gender not in ("", "未知"):
            existing.gender = student.gender
        data = {"id": existing.id, "name": existing.name,
                "class_name": existing.class_name, "created": created}
        session.commit()
    return data


# ---------------------------------------------------------------------------
# 成绩
# ---------------------------------------------------------------------------

@app.get("/api/scores", tags=["成绩"], dependencies=[Depends(require_key)])
def list_scores(exam_name: Optional[str] = None,
                subject: Optional[str] = None):
    """获取成绩列表，可按考试名和学科过滤。"""
    with db.SessionLocal() as session:
        q = session.query(Score, Exam).join(Exam, Score.exam_id == Exam.id)
        if exam_name:
            q = q.filter(Exam.name == exam_name)
        if subject:
            q = q.filter(Score.subject == subject)
        return [{"exam_name": exam.name, "exam_id": exam.id,
                 "student_id": score.student_id,
                 "subject": score.subject, "score": score.score}
                for score, exam in q.all()]


@app.post("/api/scores", tags=["成绩"], dependencies=[Depends(require_key)])
def add_score(payload: ScoreIn):
    """录入（或更新）一条成绩；考试不存在时自动按名字创建。"""
    with db.SessionLocal() as session:
        exam = _find_or_create_exam(session, payload.exam_name)
        result = exam_service.import_scores(session, exam.id, [{
            "name": payload.student_name,
            "class_name": payload.class_name or None,
            "scores": {payload.subject: payload.score}}])
        session.commit()
        exam_id = exam.id
    return {"exam_id": exam_id, **result}


def _find_or_create_exam(session, name):
    """按名字找考试，找不到就建一场。"""
    exam = session.query(Exam).filter(Exam.name == name).first()
    if exam is None:
        exam = exam_service.create_exam(session, name)
    return exam


# ---------------------------------------------------------------------------
# 考试分析
# ---------------------------------------------------------------------------

@app.get("/api/exams/analysis", tags=["分析"],
         dependencies=[Depends(require_key)])
def exam_analysis(exam_name: str, subject: Optional[str] = None):
    """获取一场考试的分析结果。"""
    with db.SessionLocal() as session:
        exam = session.query(Exam).filter(Exam.name == exam_name).first()
        if exam is None:
            raise HTTPException(status_code=404, detail="考试不存在。")
        if subject:
            return exam_service.analyze_subject(session, exam.id, subject)
        return exam_service.analyze_exam(session, exam.id)


# ---------------------------------------------------------------------------
# AI 出题 / 备课
# ---------------------------------------------------------------------------

@app.post("/api/questions/generate", tags=["AI"],
          dependencies=[Depends(require_key)])
def generate_questions(q: QuestionIn):
    """AI 生成并保存一份正式试卷。"""
    params = {
        "subject": q.subject, "grade": q.grade,
        "question_type": q.question_type, "difficulty": q.difficulty,
        "count": q.count,
        "knowledge_points": [q.knowledge_point] if q.knowledge_point else []}
    with db.SessionLocal() as session:
        result = agent_service._do_compose(session, params)
        session.commit()
    return result


@app.post("/api/lesson/generate", tags=["AI"],
          dependencies=[Depends(require_key)])
def generate_lesson(lesson: LessonIn):
    """AI 生成并保存一份教案。"""
    params = {"subject": lesson.subject, "grade": lesson.grade,
              "topic": lesson.chapter, "chapter": lesson.chapter}
    with db.SessionLocal() as session:
        result = agent_service._do_prepare(session, params)
        session.commit()
    return result
