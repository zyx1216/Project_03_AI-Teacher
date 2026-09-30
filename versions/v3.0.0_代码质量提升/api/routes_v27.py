# -*- coding: utf-8 -*-
"""v2.7.0 增量 API 路由：资料 / 组卷 / 批改 / 分析 / 学生 / RAG / Agent。

不修改现有 api/main.py 的端点与 X-API-Key 认证；本模块提供：
- POST /api/auth/token：用标准库 HMAC 签发短期 token（可选认证方式）
- 其余业务端点：统一调用现有 service 层，不重复业务逻辑
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from utils import api_key_service, db

router = APIRouter(prefix="/api", tags=["v2.7.0"])

# ---------------------------------------------------------------------------
# 可选 token 认证（stdlib HMAC，不引入 PyJWT）
# ---------------------------------------------------------------------------

_TOKEN_TTL = 3600  # 1 小时
_RATE_LIMIT = 60   # 每 key 每分钟
_rate_buckets: dict[str, list[float]] = {}


def _secret() -> bytes:
    """签名密钥：取已存 API Key 的哈希做派生（不落新密钥）。"""
    state = api_key_service.load_keys()
    seed = json.dumps(state.get("keys") or state, ensure_ascii=False,
                      sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest().encode("utf-8")


def create_token(subject: str = "api_user") -> dict:
    """签发短期 token：base64(payload).hmac_sig。"""
    payload = {"sub": subject, "exp": int(time.time()) + _TOKEN_TTL}
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_secret(), raw, hashlib.sha256).hexdigest()
    return {"token": raw.decode("ascii") + "." + sig,
            "expires_in": _TOKEN_TTL, "token_type": "bearer"}


def verify_token(token: str) -> bool:
    """校验 token 签名与有效期。"""
    token = str(token or "").strip()
    if "." not in token:
        return False
    raw, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except (ValueError, TypeError):
        return False
    return int(payload.get("exp") or 0) > int(time.time())


def _rate_ok(key: str) -> bool:
    """内存限流：每 key 每分钟至多 _RATE_LIMIT 次。"""
    now = time.time()
    bucket = [t for t in _rate_buckets.get(key, []) if now - t < 60]
    if len(bucket) >= _RATE_LIMIT:
        _rate_buckets[key] = bucket
        return False
    bucket.append(now)
    _rate_buckets[key] = bucket
    return True


def require_key_or_token(
        x_api_key: Optional[str] = Header(default=None),
        authorization: Optional[str] = Header(default=None)) -> str:
    """接受 X-API-Key 或 Authorization: Bearer <token>；并做限流。"""
    ident = None
    if x_api_key and api_key_service.verify_key(x_api_key):
        ident = "key:" + hashlib.sha256(x_api_key.encode()).hexdigest()[:12]
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        if verify_token(token):
            ident = "token:" + token[-12:]
    if ident is None:
        raise HTTPException(status_code=401, detail="无效或缺失的认证信息。")
    if not _rate_ok(ident):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
    return ident


def _log(action: str, target: str, detail: dict) -> None:
    """把 API 访问写入 operation_logs（失败不影响主流程）。"""
    try:
        from utils import logger_service
        with db.SessionLocal() as session:
            logger_service.log_operation(session, action, "API", target, detail)
            session.commit()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class TokenIn(BaseModel):
    subject: str = "api_user"


class MaterialIn(BaseModel):
    name: str = Field(min_length=1)
    subject: str = "数学"
    grade: str = ""
    material_type: str = "textbook"


class ComposeIn(BaseModel):
    name: str = Field(min_length=1)
    subject: str = "数学"
    grade: str = ""
    total_score: Optional[float] = None


class ObjectiveIn(BaseModel):
    homework_id: int
    force: bool = False


class SubjectiveIn(BaseModel):
    homework_id: int
    question_id: int
    rubric: str = ""


class ImportStudentsIn(BaseModel):
    students: list[dict]


class RagIn(BaseModel):
    query: str = Field(min_length=1)
    textbook_ids: list[int] = Field(default_factory=list)


class AgentIn(BaseModel):
    instruction: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.post("/auth/token", summary="获取访问令牌（HMAC，可选认证）")
def get_token(payload: TokenIn):
    return create_token(payload.subject)


@router.get("/materials", summary="资料列表")
def list_materials(subject: Optional[str] = None, _id: str = Depends(require_key_or_token)):
    from utils import material_service
    with db.SessionLocal() as session:
        items = material_service.list_materials(session, subject=subject)
        return {"items": [{"id": m.id, "name": m.name, "subject": m.subject,
                           "grade": m.grade,
                           "type": getattr(m, "type", None) or "textbook"}
                          for m in items]}


@router.get("/materials/{material_id}", summary="资料详情")
def get_material(material_id: int, _id: str = Depends(require_key_or_token)):
    from utils import rag_service
    with db.SessionLocal() as session:
        chunks = rag_service.load_chunks_for(session, material_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="资料不存在或没有正文。")
    return {"material_id": material_id, "chunk_count": len(chunks),
            "chapters": sorted({c.get("chapter") or "" for c in chunks} - {""})}


@router.post("/exam/compose", summary="创建草稿试卷")
def compose_exam(payload: ComposeIn, _id: str = Depends(require_key_or_token)):
    from utils import homework_service
    with db.SessionLocal() as session:
        hw = homework_service.create_homework(
            session, payload.name[:100], homework_type="exam",
            subject=payload.subject, grade=payload.grade or None,
            total_score=payload.total_score)
        session.commit()
    _log("API组卷", payload.name, {"homework_id": hw.id})
    return {"homework_id": hw.id, "name": hw.name, "status": hw.status}


@router.get("/exam/{exam_id}", summary="试卷详情")
def get_exam(exam_id: int, _id: str = Depends(require_key_or_token)):
    from models.models import Homework
    with db.SessionLocal() as session:
        hw = session.get(Homework, exam_id)
        if hw is None:
            raise HTTPException(status_code=404, detail="试卷不存在。")
        return {"id": hw.id, "name": hw.name, "subject": hw.subject,
                "total_score": hw.total_score, "status": hw.status}


@router.post("/grading/objective", summary="客观题批量重批")
def grade_objective(payload: ObjectiveIn, _id: str = Depends(require_key_or_token)):
    from utils import grading_service
    with db.SessionLocal() as session:
        result = grading_service.grade_homework_objective(
            session, payload.homework_id, force=payload.force)
        session.commit()
    return result


@router.post("/grading/subjective", summary="主观题 AI 批改（需教师确认）")
def grade_subjective(payload: SubjectiveIn, _id: str = Depends(require_key_or_token)):
    from utils import subjective_grading_service
    with db.SessionLocal() as session:
        return subjective_grading_service.batch_grade_subjective(
            session, payload.homework_id, payload.question_id,
            rubric=payload.rubric)


@router.get("/analysis/exam/{exam_id}", summary="考试分析")
def analysis_exam(exam_id: int, _id: str = Depends(require_key_or_token)):
    from utils import exam_service
    with db.SessionLocal() as session:
        data = exam_service.analyze_exam(session, exam_id)
    if not data:
        raise HTTPException(status_code=404, detail="考试不存在。")
    return {"exam_id": exam_id, "exam_name": data["exam"].name,
            "subjects": data["subjects"],
            "average": data["total_stats"].get("mean"),
            "pass_rate": data["total_stats"].get("pass_rate"),
            "excellent_rate": data["total_stats"].get("excellent_rate")}


@router.get("/analysis/trends", summary="趋势分析")
def analysis_trends(class_name: Optional[str] = None,
                    _id: str = Depends(require_key_or_token)):
    from utils import exam_service
    with db.SessionLocal() as session:
        return {"trend": exam_service.class_trend(session, class_name=class_name)}


@router.get("/students/{student_id}", summary="学生画像")
def student_profile(student_id: int, _id: str = Depends(require_key_or_token)):
    from models.models import Student
    from utils import exam_service
    with db.SessionLocal() as session:
        stu = session.get(Student, student_id)
        if stu is None:
            raise HTTPException(status_code=404, detail="学生不存在。")
        history = exam_service.student_scores_over_time(session, student_id) or []
        return {"id": stu.id, "name": stu.name, "class_name": stu.class_name,
                "exam_count": len(history)}


@router.post("/students/import", summary="批量导入学生")
def import_students(payload: ImportStudentsIn, _id: str = Depends(require_key_or_token)):
    from utils import student_service
    created = 0
    with db.SessionLocal() as session:
        for item in payload.students or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            student_service.get_or_create_student(
                session, name, item.get("class_name") or "未分班")
            created += 1
        session.commit()
    _log("API导入学生", f"{created} 人", {"count": created})
    return {"imported": created}


@router.post("/rag/query", summary="RAG 智能问答")
def rag_query(payload: RagIn, _id: str = Depends(require_key_or_token)):
    from utils import rag_service
    with db.SessionLocal() as session:
        try:
            return rag_service.rag_answer(session, payload.query,
                                          payload.textbook_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/chat", summary="Agent 对话")
def agent_chat(payload: AgentIn, _id: str = Depends(require_key_or_token)):
    from utils import agent_service
    with db.SessionLocal() as session:
        result = agent_service.run_instruction(session, payload.instruction)
        session.commit()
    return {"status": result.get("status"), "summary": result.get("summary")}
