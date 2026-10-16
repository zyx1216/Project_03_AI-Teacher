# -*- coding: utf-8 -*-
"""AI 自然语言助手服务。

职责：
- 用 LLM 把老师的话解析成标准意图；
- 按意图调用现有服务层执行；
- v1.9.4 起支持上下文记忆和基于最近结果的多轮修正。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import config
from models.models import Homework, LessonPlan
from utils import agent_context, llm_client
from utils.agent_intents import (
    normalize_intent, storage_grade,
    COMPOSE_PAPER, PREPARE_LESSON, ANALYZE_STUDENT, QUERY, MULTI_STEP,
    CORRECTION, RAG_QUERY,
    is_correction_instruction, parse_correction,
)
from utils.app_config import DEFAULT_SUBJECT, to_display_grade

AGENT_HISTORY_PATH = config.DATA_DIR / "agent_history.json"
HISTORY_LIMIT = 20


class AgentClarificationNeeded(Exception):
    """信息不足，需要老师主动澄清；不允许系统臆造目标。"""

    def __init__(self, clarification: dict):
        self.clarification = clarification
        super().__init__(clarification.get("question", "需要补充信息。"))

_PARSE_SYSTEM = """你是教学助手的指令解析器。把老师的中文指令解析成 JSON，不要执行、不要编造结果。
固定输出结构：
{"intent": "compose_paper|prepare_lesson|analyze_student|query|multi_step",
 "params": {"subject":"学科","grade":"年级(用界面口径,如 高一/初二/三年级)",
   "class_name":"班级名称","chapter":"章节","knowledge_points":["知识点"],
   "question_type":"choice|fill|judge|solution","count":0,"difficulty":0,
   "student_name":"学生姓名","time_range":"时间范围","topic":"课题"}}
规则：
- intent 只能取上述 5 个；无法判断就用 query。
- question_type 不确定就留空字符串；difficulty 1基础/2中等/3拓展，不限为0。
- 年级小学用“X年级”，初中用初一/初二/初三，高中用高一/高二/高三。
- 只输出 JSON 对象本身，不要代码围栏和解释。"""


def parse_raw_instruction(text: str) -> dict:
    """调用 LLM 获取原始结构化意图，不做归一化。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("指令内容为空。")
    raw = llm_client.chat_content(
        _PARSE_SYSTEM, f"老师指令：{text}", temperature=0.0)
    from utils.lesson_service import extract_json
    data = extract_json(raw)
    if data is None:
        raise ValueError("模型没有返回可识别的结构化结果。")
    if not isinstance(data, dict):
        raise ValueError("解析结果格式不正确。")
    return data


def resolve_instruction_text(text: str, session=None) -> tuple[str, dict]:
    """意图解析前做指代消解；目标无法确定时主动澄清。"""
    from utils import reference_resolution_service as reference_svc
    result = reference_svc.resolve_reference(
        text, agent_context.load_context(), session=session)
    if result.get("needs_clarification"):
        raise AgentClarificationNeeded(result["clarification"])
    return result.get("text") or text, result.get("resolved") or {}


def parse_instruction(text: str, session=None) -> dict:
    """解析、补上下文并归一化为标准意图。"""
    resolved_text, _resolved = resolve_instruction_text(text, session)
    raw = parse_raw_instruction(resolved_text)
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    raw["params"] = agent_context.fill_intent_params(params)
    parsed = normalize_intent(raw)
    missing = reference_resolution_needs_clarification(parsed)
    if missing is not None:
        raise AgentClarificationNeeded(missing)
    return parsed


def reference_resolution_needs_clarification(parsed: dict):
    from utils import reference_resolution_service as reference_svc
    return reference_svc.needs_missing_params(parsed)


def run_instruction(session, text: str, *, last_result: dict | None = None) -> dict:
    """解析并执行一条指令；修正指令基于 last_result。"""
    content = str(text or "").strip()
    if not content:
        raise ValueError("指令内容为空。")

    # 重置上下文是本地操作，不进入业务服务。
    if _is_reset_context(content):
        agent_context.clear_context()
        return _simple_result("已重置教学上下文。")

    # “记住我现在教……”只更新上下文，不触发业务。
    if _is_context_only(content):
        patch = agent_context.extract_context_from_instruction(content)
        if not patch:
            raise ValueError("没有识别出要记住的学科、年级、班级或章节。")
        context = agent_context.update_context(**patch)
        label = agent_context.context_label(context)
        return _simple_result(f"已记住：{label}")

    tool_result = try_tool_by_text(session, content)
    if tool_result is not None:
        result = {"status": "success",
                  "summary": f"工具查询完成：{tool_result.get('student')}",
                  "route": "", "sub": "", "extra": {},
                  "tool_result": tool_result}
        _append_history(_history_item(content, result), allow_duplicate=True)
        return result

    if is_correction_instruction(content, last_result):
        correction = parse_correction(content, last_result)
        result = _execute_correction(session, correction, last_result)
        result["parent_history_id"] = last_result.get("parent_history_id") or ""
        _append_history(_history_item(content, result, correction=correction),
                        allow_duplicate=True)
        return result

    parsed = parse_instruction(content, session)
    _apply_auto_preferences(session, parsed)
    result = _execute_parsed(session, parsed)
    if result.get("status") in ("success", "empty"):
        context_params = dict(parsed.get("params") or {})
        context_params.update(result.get("context_hints") or {})
        agent_context.remember_execution(parsed["intent"], context_params)
        result["artifact"] = _build_artifact(session, parsed, result)
    _append_history(_history_item(content, result, parsed=parsed))
    return result


def _apply_auto_preferences(session, parsed: dict) -> None:
    """只把允许列表里的偏好补进用户没明确给出的参数。"""
    from utils import agent_memory_service as memory_svc
    prefs = memory_svc.auto_applied_preferences(session)
    params = parsed.setdefault("params", {})

    if not params.get("difficulty") and prefs.get("default_difficulty"):
        value = str(prefs["default_difficulty"])
        number = {"基础": "1", "简单": "1", "中等": "2", "拓展": "3",
                  "难": "3"}.get(value, value)
        if number in ("1", "2", "3"):
            params["difficulty"] = int(number)

    if not params.get("count") and prefs.get("default_question_count"):
        match = __import__("re").search(r"\d+", str(prefs["default_question_count"]))
        if match:
            params["count"] = int(match.group())

    if not params.get("question_type") and prefs.get("common_question_types"):
        first = __import__("re").split(r"[，,、;；]",
                                       str(prefs["common_question_types"]))[0].strip()
        from utils.agent_intents import TYPE_TO_SLOT
        if first in TYPE_TO_SLOT:
            params["question_type"] = TYPE_TO_SLOT[first]


def try_tool_by_text(session, text: str):
    """规则识别参数明确的工具请求；失败返回 None。"""
    from utils import agent_tools
    content = str(text or "").strip()
    match = __import__("re").search(
        r"(?:查询|查一下|查)([\u4e00-\u9fa5]{2,5})(?:的)?(?:最近)?成绩", content)
    if match:
        return agent_tools.execute_tool(
            session, "query_student_score",
            {"student_name": match.group(1)}, confirmed=True)
    return None


def _execute_parsed(session, parsed: dict) -> dict:
    """按意图分发到现有业务服务。"""
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
    if intent == RAG_QUERY:
        return _do_rag_query(session, params)
    from utils import agent_planner
    instruction = params.get("topic") or ""
    return agent_planner.run_multi_step(session, instruction, parsed)


# ---------------------------------------------------------------------------
# 业务执行
# ---------------------------------------------------------------------------

def _do_compose(session, params: dict) -> dict:
    """出题指令：隐藏草稿 -> auto_compose -> 成功转正式，失败删草稿。"""
    from utils import homework_service as hw_svc
    subject = params.get("subject") or DEFAULT_SUBJECT
    grade_display = params.get("grade") or ""
    grade_store = storage_grade(params)
    class_name = params.get("class_name") or None

    qtype = params.get("question_type") or "choice"
    count = params.get("count") or 5
    difficulty = params.get("difficulty") or 1
    slots = [{"question_type": qtype, "difficulty": difficulty,
              "count": int(count)}]
    name = f"{subject}{to_display_grade(grade_store) or grade_display or ''}智能组卷"
    if class_name:
        name = f"{class_name}{name}"
    draft_name = f"__smart_compose_draft__{uuid.uuid4().hex[:8]}"
    draft = hw_svc.create_homework(
        session, draft_name, homework_type="exam", is_template=True,
        subject=subject, grade=grade_store or None, class_name=class_name)
    session.flush()
    try:
        stats = hw_svc.auto_compose(
            session, draft.id, {"slots": slots},
            knowledge_points=params.get("knowledge_points") or None,
            ai_context={"grade": grade_store or None,
                        "chapters": [params["chapter"]] if params.get("chapter") else []})
    except Exception:
        hw_svc.delete_homework(session, draft.id)
        session.flush()
        raise

    if stats.get("total_questions", 0) <= 0:
        hw_svc.delete_homework(session, draft.id)
        session.flush()
        return {
            "status": "empty",
            "summary": "没有生成任何题目（题库无可用题且 AI 补缺失败），未创建试卷。",
            "route": "", "sub": "", "extra": {},
        }
    draft.is_template = False
    draft.name = name
    session.flush()
    summary = (
        f"已生成正式试卷《{name}》：共 {stats['total_questions']} 题，"
        f"题库抽题 {stats.get('rule_picked', 0)} 道，"
        f"AI 补题 {stats.get('ai_generated', 0)} 道。")
    return {
        "status": "success", "summary": summary,
        "route": "📝 学业测评", "sub": "作业管理",
        "extra": {"hw_open_id": draft.id},
    }


def _do_prepare(session, params: dict) -> dict:
    """备课指令：生成、解析并保存教案。"""
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
    lesson = lesson_svc.save_plan(
        session, topic, plan, grade=grade_store or None,
        chapter=params.get("chapter") or None, source="AI 助手",
        subject=subject)
    session.flush()
    return {
        "status": "success",
        "summary": f"已备好教案《{topic}》（{subject}·{grade_display or '未指定年级'}）。",
        "route": "📚 备课", "sub": "AI 备课",
        "extra": {"pending_load_plan_id": lesson.id},
    }


def _do_analyze_student(session, params: dict) -> dict:
    """学生分析：返回最近成绩摘要，并生成 analysis artifact。"""
    from utils import student_service, exam_service
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
        "context_hints": {
            "student_name": stu.name,
            "class_name": stu.class_name or params.get("class_name") or "",
        },
    }


def _do_query(session, params: dict) -> dict:
    """查询题库数量和临期作业。"""
    from utils import question_service
    subject = params.get("subject")
    questions = question_service.list_questions(session, subject=subject)
    scope = subject or "全部学科"
    parts = [f"{scope}题库共 {len(questions)} 道题"]
    upcoming = (session.query(Homework)
                .filter(Homework.is_template.is_(False),
                        Homework.status == "pending",
                        Homework.due_date.isnot(None),
                        Homework.due_date >= datetime.now())
                .order_by(Homework.due_date.asc()).limit(5).all())
    if upcoming:
        items = "、".join(
            f"{h.name}（{h.due_date.strftime('%m-%d')}）" for h in upcoming)
        parts.append(f"临期作业：{items}")
    else:
        parts.append("近期没有设置截止时间的作业")
    return {"status": "success", "summary": "；".join(parts) + "。",
            "route": "", "sub": "", "extra": {}}


# ---------------------------------------------------------------------------
# 多轮修正
# ---------------------------------------------------------------------------

def _execute_correction(session, correction: dict, last_result: dict) -> dict:
    """按 artifact 类型执行修正。"""
    artifact_type = correction.get("artifact_type")
    if artifact_type == "homework":
        return _correct_homework(session, correction, last_result)
    if artifact_type == "lesson_plan":
        return _correct_lesson(session, correction, last_result)
    if artifact_type == "analysis":
        return _correct_analysis(correction, last_result)
    raise ValueError("当前结果暂不支持直接修正，请重新输入完整指令。")


def _correct_homework(session, correction: dict, last_result: dict) -> dict:
    """修正试卷：克隆新题并替换关联，不修改原题。"""
    from utils import homework_service as hw_svc
    artifact = last_result["artifact"]
    hw = session.get(Homework, artifact["homework_id"])
    if hw is None:
        raise ValueError("原作业不存在，无法修正。")
    questions = list(artifact.get("questions") or [])
    undo_stack = list(artifact.get("undo_stack") or [])
    action = correction["action"]
    context = {"subject": hw.subject, "grade": hw.grade}

    if action in ("revise", "replace"):
        for target in correction["targets"]:
            if not 1 <= target <= len(questions):
                continue
            old = questions[target - 1]
            modified = _modify_with_fallback(old, correction, context)
            new = _create_modified_question(session, modified, hw)
            hw_svc.replace_homework_question(
                session, hw.id, old["id"], new.id)
            undo_stack.append({
                "action": action, "target": target,
                "old_question_id": old["id"],
                "new_question_id": new.id,
            })
    elif action == "add":
        qtype = correction.get("question_type") or "choice"
        count = correction.get("count") or 1
        before = {q["id"] for q in questions}
        stats = hw_svc.auto_compose(
            session, hw.id,
            {"slots": [{"question_type": qtype, "difficulty": 2,
                        "count": count}]},
            ai_context={"grade": hw.grade,
                        "chapters": [hw.chapter] if hw.chapter else []})
        added_ids = [q.id for _link, q in hw_svc.homework_questions(session, hw.id)
                     if q.id not in before]
        undo_stack.append({"action": "add", "added_ids": added_ids})
        if stats.get("total_questions", 0) <= len(questions):
            raise ValueError("没有可追加的题目，请调整知识点或章节。")
    elif action == "remove":
        for target in correction["targets"]:
            if 1 <= target <= len(questions):
                old = questions[target - 1]
                score = _question_score(session, hw.id, old["id"])
                hw_svc.remove_question(session, hw.id, old["id"])
                undo_stack.append({
                    "action": "remove", "question": old, "score": score,
                })
    session.flush()
    result = {
        "status": "success", "summary": f"已修正作业《{hw.name}》。",
        "route": "📝 学业测评", "sub": "作业管理",
        "extra": {"hw_open_id": hw.id},
    }
    result["artifact"] = _homework_artifact(session, hw, undo_stack)
    result["correction_count"] = int(last_result.get("correction_count") or 0) + 1
    return result


def _modify_with_fallback(old: dict, correction: dict, context: dict) -> dict:
    """调用 LLM 修改题目；模型失败时用确定性规则处理难度调整。"""
    from utils import question_service
    try:
        return question_service.modify_question(
            old, correction["instruction"], context)
    except Exception:
        if "难" in correction["instruction"]:
            modified = dict(old)
            if any(word in correction["instruction"] for word in ("简单", "降低", "容易")):
                modified["difficulty"] = max(1, int(old.get("difficulty") or 2) - 1)
            else:
                modified["difficulty"] = min(3, int(old.get("difficulty") or 2) + 1)
            return modified
        raise


def _create_modified_question(session, data: dict, hw: Homework):
    """把修正后的题目创建为待审核新题。"""
    from utils import question_service
    checked = question_service.validate_question(data)
    if checked is None:
        raise ValueError("修正后的题目缺少题干或答案，未保存。")
    checked["knowledge_points"] = data.get("knowledge_points") or "[]"
    # 作业 grade 是存储口径，题目 grade 要界面口径。
    q = question_service.create_question(
        session, checked, source="AI 修正", status="pending",
        subject=hw.subject, grade=to_display_grade(hw.grade) or None)
    session.flush()
    return q


def _correct_lesson(session, correction: dict, last_result: dict) -> dict:
    """修正教案并保留撤销快照。"""
    from utils import lesson_service
    artifact = last_result["artifact"]
    lesson = session.get(LessonPlan, artifact["plan_id"])
    if lesson is None:
        raise ValueError("原教案不存在，无法修正。")
    old_plan = lesson_service.load_plan(lesson)
    new_plan = lesson_service.modify_lesson_plan(
        old_plan, correction["instruction"])
    lesson_service.save_plan(
        session, lesson.title, new_plan, grade=lesson.grade,
        chapter=lesson.chapter, source=lesson.textbook_source,
        plan_id=lesson.id, subject=lesson_service.plan_subject(lesson))
    session.flush()
    undo_stack = list(artifact.get("undo_stack") or [])
    undo_stack.append({"action": "lesson", "old_plan": old_plan})
    result = {
        "status": "success",
        "summary": f"已修正教案《{lesson.title}》。",
        "route": "📚 备课", "sub": "AI 备课",
        "extra": {"pending_load_plan_id": lesson.id},
    }
    result["artifact"] = {
        "artifact_type": "lesson_plan", "plan_id": lesson.id,
        "undo_stack": undo_stack[-5:],
    }
    result["correction_count"] = int(last_result.get("correction_count") or 0) + 1
    return result


def _correct_analysis(correction: dict, last_result: dict) -> dict:
    """分析修正只做参数和路由调整。"""
    artifact = dict(last_result.get("artifact") or {})
    params = dict(artifact.get("params") or {})
    instruction = correction["instruction"]
    subject = _detect_subject(instruction)
    if subject:
        params["subject"] = subject
    if "趋势" in instruction:
        result = {
            "status": "success",
            "summary": f"已改为查看{subject or ''}趋势。",
            "route": "📊 学情", "sub": "趋势分析",
            "extra": {"trend_subject": subject} if subject else {},
        }
    elif "上次" in instruction or "上一次" in instruction:
        params["compare_previous"] = True
        result = {
            "status": "success", "summary": "已加入上一次考试对比。",
            "route": "📊 学情", "sub": "考试分析", "extra": {},
        }
    else:
        raise ValueError("当前分析不支持这个筛选条件，请重新输入完整指令。")
    undo_stack = list(artifact.get("undo_stack") or [])
    undo_stack.append({"action": "analysis", "params": artifact.get("params") or {},
                       "summary": last_result.get("summary")})
    artifact.update({"params": params, "undo_stack": undo_stack[-5:]})
    result["artifact"] = artifact
    result["correction_count"] = int(last_result.get("correction_count") or 0) + 1
    return result


def undo_last_correction(session, last_result: dict) -> dict:
    """撤销最近一次修正。"""
    artifact = (last_result or {}).get("artifact") or {}
    stack = list(artifact.get("undo_stack") or [])
    if not stack:
        raise ValueError("没有可撤销的修正。")
    snapshot = stack.pop()
    kind = artifact.get("artifact_type")
    if kind == "homework":
        result = _undo_homework_snapshot(session, artifact, snapshot, stack)
    elif kind == "lesson_plan":
        result = _undo_lesson_snapshot(session, artifact, snapshot, stack)
    else:
        result = _undo_analysis_snapshot(last_result, snapshot, stack)
    result["correction_count"] = max(
        0, int(last_result.get("correction_count") or 1) - 1)
    return result


def _undo_homework_snapshot(session, artifact, snapshot, stack):
    """撤销作业修正并恢复关联。"""
    from utils import homework_service as hw_svc
    hw = session.get(Homework, artifact["homework_id"])
    action = snapshot["action"]
    if action == "add":
        for qid in snapshot.get("added_ids") or []:
            hw_svc.remove_question(session, hw.id, qid)
    elif action == "remove":
        old = snapshot["question"]
        hw_svc.add_questions(session, hw.id, [old["id"]],
                             default_score=snapshot.get("score"))
    else:
        hw_svc.replace_homework_question(
            session, hw.id, snapshot["new_question_id"],
            snapshot["old_question_id"])
    session.flush()
    result = {
        "status": "success", "summary": f"已撤销作业《{hw.name}》的修正。",
        "route": "📝 学业测评", "sub": "作业管理",
        "extra": {"hw_open_id": hw.id},
    }
    result["artifact"] = _homework_artifact(session, hw, stack)
    return result


def _undo_lesson_snapshot(session, artifact, snapshot, stack):
    """撤销教案修正。"""
    from utils import lesson_service
    lesson = session.get(LessonPlan, artifact["plan_id"])
    old_plan = snapshot["old_plan"]
    lesson_service.save_plan(
        session, lesson.title, old_plan, grade=lesson.grade,
        chapter=lesson.chapter, source=lesson.textbook_source,
        plan_id=lesson.id, subject=lesson_service.plan_subject(lesson))
    result = {
        "status": "success", "summary": f"已撤销教案《{lesson.title}》的修正。",
        "route": "📚 备课", "sub": "AI 备课",
        "extra": {"pending_load_plan_id": lesson.id},
    }
    artifact = dict(artifact)
    artifact["undo_stack"] = stack
    result["artifact"] = artifact
    return result


def _undo_analysis_snapshot(last_result, snapshot, stack):
    """恢复分析参数和摘要。"""
    artifact = dict(last_result.get("artifact") or {})
    artifact["params"] = snapshot.get("params") or {}
    artifact["undo_stack"] = stack
    result = {
        "status": "success",
        "summary": f"已恢复为：{snapshot.get('summary') or '上一次分析'}",
        "route": last_result.get("route") or "📊 学情",
        "sub": last_result.get("sub") or "学生画像",
        "extra": dict(last_result.get("extra") or {}),
    }
    result["artifact"] = artifact
    return result


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------

def _build_artifact(session, parsed: dict, result: dict) -> dict | None:
    """给最近结果构造可修正对象引用。"""
    intent = parsed["intent"]
    if intent == COMPOSE_PAPER and result.get("extra", {}).get("hw_open_id"):
        return _homework_artifact(
            session, result["extra"]["hw_open_id"], [])
    if intent == PREPARE_LESSON and result.get("extra", {}).get(
            "pending_load_plan_id"):
        return {
            "artifact_type": "lesson_plan",
            "plan_id": result["extra"]["pending_load_plan_id"],
            "undo_stack": [],
        }
    if intent == ANALYZE_STUDENT:
        return {
            "artifact_type": "analysis",
            "params": {
                "student_name": parsed["params"].get("student_name"),
                "subject": parsed["params"].get("subject"),
                "student_id": result.get("extra", {}).get("profile_student_id"),
            },
            "undo_stack": [],
        }
    return None


def _homework_artifact(session, homework_or_id, undo_stack=None) -> dict:
    """构造作业 artifact；题目只存修正所需的轻量字段。"""
    hw = (session.get(Homework, homework_or_id)
          if isinstance(homework_or_id, int) else homework_or_id)
    from utils import homework_service
    questions = []
    for link, q in homework_service.homework_questions(session, hw.id):
        questions.append({
            "id": q.id,
            "content": q.content,
            "question_type": q.question_type,
            "difficulty": int(q.difficulty or 2),
            "knowledge_points": q.knowledge_points or "[]",
            "answer": q.answer,
            "analysis": q.analysis or "",
            "score": link.score,
        })
    return {
        "artifact_type": "homework",
        "homework_id": hw.id,
        "questions": questions,
        "undo_stack": (undo_stack or [])[-5:],
    }


def _question_score(session, hw_id: int, qid: int):
    """读取某题原分值。"""
    from models.models import HomeworkQuestion
    row = (session.query(HomeworkQuestion)
           .filter(HomeworkQuestion.homework_id == hw_id,
                   HomeworkQuestion.question_id == qid).first())
    return row.score if row is not None else None


# ---------------------------------------------------------------------------
# 历史记录
# ---------------------------------------------------------------------------

def list_agent_history() -> list[dict]:
    """加载历史；文件缺失自建，损坏回退空列表且不覆盖。"""
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


def _append_history(item: dict, allow_duplicate: bool = False) -> None:
    """追加历史；修正历史允许连续重复。"""
    rows = list_agent_history()
    if not allow_duplicate and rows and rows[0].get("instruction", "").strip() == item.get(
            "instruction", "").strip():
        return
    rows.insert(0, item)
    AGENT_HISTORY_PATH.write_text(
        json.dumps(rows[:HISTORY_LIMIT], ensure_ascii=False, indent=2),
        encoding="utf-8")


def _history_item(text: str, result: dict, parsed: dict | None = None,
                   correction: dict | None = None) -> dict:
    """构造统一历史记录。"""
    parsed = parsed or {}
    artifact = result.get("artifact") or {}
    return {
        "history_id": uuid.uuid4().hex[:12],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instruction": text.strip(),
        "intent": parsed.get("intent") or (correction or {}).get("artifact_type", "correction"),
        "params": parsed.get("params") or {},
        "summary": result.get("summary", ""),
        "entry_kind": "correction" if correction else "normal",
        "parent_history_id": (result.get("parent_history_id") or ""),
        "artifact_type": artifact.get("artifact_type", ""),
        "correction_count": result.get("correction_count", 0),
    }


def reexecute_agent_history(session, history_id: str,
                            last_result: dict | None = None) -> dict:
    """按历史 ID 重新执行。"""
    for item in list_agent_history():
        if item.get("history_id") == history_id:
            if item.get("entry_kind") == "correction" and not last_result:
                raise ValueError("请先重新执行原指令，再执行这条修正。")
            return run_instruction(
                session, item["instruction"], last_result=last_result)
    raise ValueError(f"找不到历史记录：{history_id}")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _simple_result(summary: str) -> dict:
    """构造无需跳转的普通结果。"""
    return {"status": "success", "summary": summary,
            "route": "", "sub": "", "extra": {}}


def _is_reset_context(text: str) -> bool:
    """识别重置上下文指令。"""
    return ("重置上下文" in text or "清空上下文" in text or
            "忘记上下文" in text)


def _is_context_only(text: str) -> bool:
    """识别仅保存上下文的指令。"""
    return (text.startswith("记住") or "我现在教" in text or
            "当前上下文" in text)


def _detect_subject(text: str) -> str:
    """从修正文本中识别学科。"""
    from utils.app_config import SUBJECT_NAMES
    for subject in SUBJECT_NAMES:
        if subject in text:
            return subject
    return ""




# ---------------------------------------------------------------------------
# v1.9.5：自主规划预览 + 提醒/建议口语路由
# ---------------------------------------------------------------------------

def build_complex_preview(session, text: str) -> dict:
    """解析 complex 指令并生成增强计划；不执行、不调业务服务、不落库。

    返回 {needs_confirmation, instruction, parsed, plan, context}。
    """
    from utils import agent_planner
    instruction = str(text or "").strip()
    parsed = parse_instruction(instruction, session)
    params = parsed.get("params", {})
    context = {
        "instruction": instruction,
        "plan_kind": agent_planner.plan_kind_of(instruction, params),
    }
    plan = agent_planner.build_plan_enhanced(parsed, context)
    return {
        "needs_confirmation": True,
        "instruction": instruction,
        "parsed": parsed,
        "plan": plan,
        "context": context,
    }


def execute_complex_preview(session, preview: dict,
                            start_index: int = 0) -> dict:
    """确认后执行增强计划；start_index 用于跳过或从失败步骤重试。"""
    from utils import agent_planner
    return agent_planner.execute_plan(
        session, preview["instruction"], preview["plan"],
        parsed_intent=preview["parsed"], start_index=start_index,
        context=dict(preview.get("context") or {}))


def run_quick_info(session, text: str) -> dict | None:
    """识别提醒/建议类口语并直接返回结果；不是这类口径返回 None。

    - “有什么需要注意的”→ 智能提醒清单；
    - “给我教学建议”→ 本周建议；
    - “这个班怎么分层”→ 分层教学建议；
    - “快考试了怎么复习”→ 最近考试复习计划。
    """
    content = str(text or "").strip()
    if not content:
        return None

    if any(word in content for word in
           ("需要注意", "注意什么", "哪些提醒", "有什么异常", "要注意的")):
        return _alerts_summary(session)

    if any(word in content for word in ("怎么分层", "分层教学", "如何分层")):
        return _layered_summary(session)

    if any(word in content for word in ("怎么复习", "复习计划", "如何复习")):
        return _review_summary(session)

    if any(word in content for word in
           ("教学建议", "给我建议", "本周建议", "教学意见")):
        return _weekly_advice_summary(session)
    return None


def _alerts_summary(session) -> dict:
    """把智能提醒整理成中文清单。"""
    from utils import agent_alert
    alerts = agent_alert.check_all_alerts(session)
    if not alerts:
        return _simple_result("暂无异常提醒，各班级表现平稳。")
    lines = "；".join(a["title"] for a in alerts)
    return {"status": "success", "summary": f"需要注意：{lines}。",
            "route": "", "sub": "", "extra": {}, "alerts": alerts}


def _weekly_advice_summary(session) -> dict:
    """本周教学建议。"""
    from utils import agent_advisor, agent_context
    ctx = agent_context.load_context()
    entry = agent_advisor.generate_weekly_suggestions(session, ctx)
    return {"status": "success", "summary": entry.get("text", ""),
            "route": "", "sub": "", "extra": {}}


def _layered_summary(session) -> dict:
    """分层教学建议；班级从上下文取。"""
    from utils import agent_advisor, agent_context
    ctx = agent_context.load_context()
    class_name = ctx.get("class_name") or ""
    subject = ctx.get("subject") or "数学"
    if not class_name:
        return _simple_result("请先在上下文中设置班级，再生成分层教学建议。")
    data = agent_advisor.generate_layered_teaching_suggestions(
        session, class_name, subject)
    return {"status": "success", "summary": data.get("text", ""),
            "route": "", "sub": "", "extra": {}}


def _review_summary(session) -> dict:
    """最近一场考试的复习计划。"""
    from utils import exam_service, agent_advisor
    exams = exam_service.list_exams(session)
    if not exams:
        return _simple_result("还没有考试记录，无法生成复习计划。")
    data = agent_advisor.generate_review_plan(session, exams[-1].id)
    return {"status": "success", "summary": data.get("text", ""),
            "route": "", "sub": "", "extra": {}}



# ---------------------------------------------------------------------------
# v1.9.6：RAG 课本问答
# ---------------------------------------------------------------------------

def _do_rag_query(session, params: dict) -> dict:
    """按学科选资料，走 RAG 问答；有资料线索则收窄范围。"""
    from utils import rag_service
    subject = params.get("subject") or DEFAULT_SUBJECT
    topic = (params.get("topic") or params.get("chapter") or "").strip()
    query = topic or params.get("knowledge_points") and "、".join(
        params["knowledge_points"])
    if not query:
        raise ValueError("请说明要从课本里查找什么内容。")

    materials = rag_service.material_service.list_materials(
        session, subject=subject)
    if not materials:
        return {
            "status": "empty",
            "summary": f"{subject}还没有可检索的资料，请先在资料管理上传。",
            "route": "📚 备课", "sub": "资料管理", "extra": {}}

    # 有明确课题/章节时优先选名称或章节命中的资料，否则用全部本学科资料。
    hint = params.get("chapter") or topic
    narrowed = [m for m in materials
                if hint and (hint in (m.name or "")
                             or hint in (m.chapter_info or ""))]
    chosen = narrowed or materials
    textbook_ids = [m.id for m in chosen]

    for tb_id in textbook_ids:
        rag_service.ensure_index(session, tb_id)
    data = rag_service.rag_answer(session, query, textbook_ids)
    sources = data.get("sources") or []
    src_text = ""
    if sources:
        labels = "、".join(
            s.get("chapter") or s.get("textbook_name") for s in sources[:3])
        src_text = f"来源：{labels}；"
    summary = f"【{data['confidence']}置信度】{src_text}{data['answer']}"
    return {
        "status": "success", "summary": summary,
        "route": "📚 备课", "sub": "📚 RAG知识库",
        "extra": {}, "rag": data,
    }


