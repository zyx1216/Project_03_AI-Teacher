# -*- coding: utf-8 -*-
"""AI 自然语言助手服务（v1.9.0）。

职责：
- parse_instruction：用 LLM 把老师的话解析成 agent_intents 标准意图；
- run_instruction：按意图真正调用现有服务层执行（不是只给建议）；
- 历史记录落 data/agent_history.json，最多保留 20 条。

LLM 只做解析；实际执行结果以统一动作结构返回：
{"status","summary","route","sub","extra"}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import config
from utils import llm_client
from utils.agent_intents import (
    INTENTS, INTENT_HINTS, normalize_intent, storage_grade,
    COMPOSE_PAPER, PREPARE_LESSON, ANALYZE_STUDENT, QUERY, MULTI_STEP,
    SLOT_TYPES,
)
from utils.app_config import DEFAULT_SUBJECT, to_display_grade

AGENT_HISTORY_PATH = config.DATA_DIR / "agent_history.json"
HISTORY_LIMIT = 20

_PARSE_SYSTEM = """你是教学助手的指令解析器。把老师的中文指令解析成 JSON，不要执行、不要编造结果。
固定输出结构：
{"intent": "compose_paper|prepare_lesson|analyze_student|query|multi_step",
 "params": {"subject":"学科","grade":"年级(用界面口径,如 高一/初二/三年级)",
   "chapter":"章节","knowledge_points":["知识点"],
   "question_type":"choice|fill|judge|solution","count":0,"difficulty":0,
   "student_name":"学生姓名","time_range":"时间范围","topic":"课题"}}
规则：
- intent 只能取上述 5 个；无法判断就用 query。
- question_type 不确定就留空字符串；difficulty 1基础/2中等/3拓展，不限为0。
- 年级小学用“X年级”，初中用初一/初二/初三，高中用高一/高二/高三。
- 只输出 JSON 对象本身，不要代码围栏和解释。"""


def parse_instruction(text: str) -> dict:
    """用 LLM 解析指令为标准意图；解析失败抛 ValueError（中文原因）。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("指令内容为空。")
    raw = llm_client.chat_content(_PARSE_SYSTEM, f"老师指令：{text}",
                                  temperature=0.0)
    from utils.lesson_service import extract_json
    data = extract_json(raw)
    if data is None:
        raise ValueError("模型没有返回可识别的结构化结果。")
    return normalize_intent(data)


def run_instruction(session, text: str) -> dict:
    """解析并真正执行一条指令，返回统一动作结构；同时写历史。"""
    parsed = parse_instruction(text)
    result = _execute_parsed(session, parsed)
    try:
        _append_history({
            "history_id": uuid.uuid4().hex[:12],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "instruction": text.strip(),
            "intent": parsed["intent"],
            "params": parsed["params"],
            "summary": result.get("summary", ""),
        })
    except Exception:
        # 历史写入失败不影响主流程。
        pass
    return result


def _execute_parsed(session, parsed: dict) -> dict:
    intent = parsed["intent"]
    params = parsed["params"]
    if intent == COMPOSE_PAPER:
        return _do_compose(session, params)
    if intent == PREPARE_LESSON:
        return _do_prepare(session, params)
    if intent == ANALYZE_STUDENT:
        return _do_analyze_student(session, params)
    if intent == QUERY:
        return _do_query(session, params)
    # multi_step 交给 agent_planner
    from utils import agent_planner
    instruction = params.get("topic") or ""
    return agent_planner.run_multi_step(session, instruction, parsed)


# ---------------------------------------------------------------------------
# 各意图执行
# ---------------------------------------------------------------------------

def _do_compose(session, params: dict) -> dict:
    """出题指令：建隐藏草稿 → auto_compose → 总题数>0 转正式，否则删草稿。"""
    from utils import homework_service as hw_svc
    subject = params.get("subject") or DEFAULT_SUBJECT
    grade_display = params.get("grade") or ""
    grade_store = storage_grade(params)

    qtype = params.get("question_type") or "choice"
    count = params.get("count") or 5
    difficulty = params.get("difficulty") or 1

    slots = [{"question_type": qtype, "difficulty": difficulty, "count": int(count)}]
    spec = {"slots": slots}
    name = f"{subject}{to_display_grade(grade_store) or grade_display or ''}智能组卷"
    draft_name = f"__smart_compose_draft__{uuid.uuid4().hex[:8]}"
    draft = hw_svc.create_homework(
        session, draft_name, homework_type="exam", is_template=True,
        subject=subject, grade=grade_store or None)
    session.flush()
    try:
        stats = hw_svc.auto_compose(
            session, draft.id, spec,
            knowledge_points=params.get("knowledge_points") or None,
            ai_context={"grade": grade_store or None,
                        "chapters": [params["chapter"]] if params.get("chapter") else []})
    except Exception:
        hw_svc.delete_homework(session, draft.id)
        session.flush()
        raise

    total = stats.get("total_questions", 0)
    if total <= 0:
        hw_svc.delete_homework(session, draft.id)
        session.flush()
        return {
            "status": "empty",
            "summary": "没有生成任何题目（题库无可用题且 AI 补缺失败），未创建试卷。",
            "route": "🤖 智能组卷", "sub": None, "extra": {},
        }
    draft.is_template = False
    draft.name = name
    session.flush()
    summary = (f"已生成正式试卷《{name}》：共 {total} 题，"
               f"题库抽题 {stats.get('rule_picked', 0)} 道，"
               f"AI 补题 {stats.get('ai_generated', 0)} 道，"
               f"未满足 {stats.get('shortage_count', 0)} 个槽位。")
    return {
        "status": "success", "summary": summary,
        "route": "📝 学业测评", "sub": "作业管理",
        "extra": {"hw_open_id": draft.id},
    }


def _do_prepare(session, params: dict) -> dict:
    """备课指令：调 LLM 生成教案并保存，返回教案 ID、标题、摘要。"""
    from utils import lesson_service as lesson_svc
    subject = params.get("subject") or DEFAULT_SUBJECT
    topic = params.get("topic") or params.get("chapter") or ""
    if not topic:
        raise ValueError("备课缺少课题，请补充“备什么课”。")
    grade_display = params.get("grade") or ""
    grade_store = storage_grade(params)
    system_prompt = (Path(config.BASE_DIR) / "prompts" /
                     "lesson_plan_prompt.txt").read_text(encoding="utf-8")
    user_text = (
        f"学科：{subject}\n课题：{topic}\n"
        f"年级：{grade_display or '未指定'}\n"
        f"章节：{params.get('chapter') or '未指定'}\n课时数：1（每课时45分钟）\n"
        "请按你固定的教案结构输出 JSON。")
    raw = llm_client.chat_content(system_prompt, user_text, temperature=0.7)
    plan = lesson_svc.parse_lesson_plan(raw)
    if plan is None:
        raise ValueError("模型返回的教案无法解析，请重试或更换课题。")
    plan["subject"] = subject
    title = topic
    lesson = lesson_svc.save_plan(
        session, title, plan, grade=grade_store or None,
        chapter=params.get("chapter") or None, source="AI 助手", subject=subject)
    session.flush()
    summary = f"已备好教案《{title}》（{subject}·{grade_display or '未指定年级'}）。"
    return {
        "status": "success", "summary": summary,
        "route": "📚 备课", "sub": "AI 备课",
        "extra": {"pending_load_plan_id": lesson.id},
    }


def _do_analyze_student(session, params: dict) -> dict:
    """学生分析指令：查学生最近成绩并给事实摘要。"""
    from utils import student_service
    name = params.get("student_name") or ""
    if not name:
        raise ValueError("分析学生需要给出学生姓名。")
    students = student_service.list_students(session, keyword=name)
    if not students:
        return {
            "status": "empty",
            "summary": f"没有找到名为“{name}”的学生。",
            "route": "📊 学情", "sub": "学生管理", "extra": {},
        }
    stu = students[0]
    from utils import exam_service
    history = exam_service.student_scores_over_time(session, stu.id)
    recent = history[-3:] if history else []
    if recent:
        parts = [f"{h['exam_name']} 总分 {h.get('total')}" for h in recent]
        summary = f"{stu.name} 最近成绩：" + "；".join(parts) + "。"
    else:
        summary = f"{stu.name} 暂无考试成绩记录。"
    return {
        "status": "success", "summary": summary,
        "route": "📊 学情", "sub": "学生画像",
        "extra": {"profile_student_id": stu.id},
    }


def _do_query(session, params: dict) -> dict:
    """查询指令：题库数量、临期作业等事实摘要。"""
    from utils import question_service, homework_service
    from models.models import Homework
    from datetime import datetime
    subject = params.get("subject")
    parts = []
    questions = question_service.list_questions(session, subject=subject)
    scope = f"{subject}" if subject else "全部学科"
    parts.append(f"{scope}题库共 {len(questions)} 道题")
    now = datetime.now()
    upcoming = (session.query(Homework)
                .filter(Homework.is_template.is_(False),
                        Homework.status == "pending",
                        Homework.due_date.isnot(None),
                        Homework.due_date >= now)
                .order_by(Homework.due_date.asc()).limit(5).all())
    if upcoming:
        items = "、".join(
            f"{h.name}（{h.due_date.strftime('%m-%d')}）" for h in upcoming)
        parts.append(f"临期作业：{items}")
    else:
        parts.append("近期没有设置截止时间的作业")
    return {
        "status": "success", "summary": "；".join(parts) + "。",
        "route": "", "sub": "", "extra": {},
    }


# ---------------------------------------------------------------------------
# 历史记录
# ---------------------------------------------------------------------------

def list_agent_history() -> list[dict]:
    """加载 AI 助手历史；文件缺失自建，损坏回退空列表且不覆盖。"""
    path = AGENT_HISTORY_PATH
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[]", encoding="utf-8")
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_history(item: dict) -> None:
    rows = list_agent_history()
    rows.insert(0, item)
    rows = rows[:HISTORY_LIMIT]
    AGENT_HISTORY_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def reexecute_agent_history(session, history_id: str) -> dict:
    """按历史 id 找到原指令并重新执行。"""
    for item in list_agent_history():
        if item.get("history_id") == history_id:
            return run_instruction(session, item["instruction"])
    raise ValueError(f"找不到历史记录：{history_id}")
