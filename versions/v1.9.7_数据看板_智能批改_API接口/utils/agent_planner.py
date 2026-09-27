# -*- coding: utf-8 -*-
"""多步任务规划与执行（v1.9.0）。

支持两类复合任务：
- 备课并生成作业：生成教案 → 根据教案生成作业 → 汇总；
- 分析成绩并生成反思：取最近作业 → 薄弱知识点 → 教学反思 → 汇总。

取消是协作式的：只在步骤之间检查标志，正在调用 LLM 时不强行中断。
某一步失败时保留已完成步骤和已生成数据，支持从失败步骤重试。
"""

from __future__ import annotations

from utils.agent_intents import MULTI_STEP

# 模块级取消标志；request_cancel 置 True，执行开始时重置。
_CANCEL_REQUESTED = False


def request_cancel() -> None:
    """请求取消后续步骤（仅在步骤之间生效）。"""
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = True


def _reset_cancel() -> None:
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = False


def _is_cancelled() -> bool:
    return _CANCEL_REQUESTED


def build_plan(parsed_intent: dict) -> list[dict]:
    """按解析意图生成步骤列表；每步 {"step_id","name"}。"""
    params = parsed_intent.get("params", {})
    text = (params.get("topic") or "")
    # 按关键词判定复合任务类型。
    if "反思" in text or ("分析" in text and "作业" in text and "成绩" in text):
        return [
            {"step_id": "pick_homework", "name": "获取最近作业成绩"},
            {"step_id": "weak_points", "name": "分析薄弱知识点"},
            {"step_id": "build_reflection", "name": "生成教学反思"},
            {"step_id": "summary", "name": "汇总结果"},
        ]
    # 默认：备课并生成作业。
    return [
        {"step_id": "gen_lesson", "name": "生成教案"},
        {"step_id": "gen_homework", "name": "根据教案生成作业"},
        {"step_id": "summary", "name": "汇总结果"},
    ]


def run_multi_step(session, instruction: str, parsed_intent: dict) -> dict:
    """agent_service 入口：建计划并从头执行。"""
    plan = build_plan(parsed_intent)
    return execute_plan(session, instruction, plan, parsed_intent=parsed_intent)


def execute_plan(session, instruction: str, plan: list[dict],
                 parsed_intent: dict | None = None,
                 start_index: int = 0,
                 context: dict | None = None) -> dict:
    """按顺序执行计划；start_index 用于从失败步骤重试。

    返回 {"status","summary","steps":[每步结果],"failed_index","plan","context"}
    """
    _reset_cancel()
    context = dict(context or {})
    if parsed_intent is None:
        parsed_intent = {"intent": MULTI_STEP, "params": {"topic": instruction}}
    steps_out = context.get("_steps_out", [])
    failed_index = None

    for i in range(start_index, len(plan)):
        if _is_cancelled():
            return {
                "status": "cancelled",
                "summary": f"已取消，完成前 {i} 步。",
                "steps": steps_out, "failed_index": i,
                "plan": plan, "context": context, "cancelled": True,
            }
        step = plan[i]
        try:
            result = _run_step(session, step["step_id"], parsed_intent, context)
        except Exception as exc:
            failed_index = i
            steps_out.append({
                "step_id": step["step_id"], "name": step["name"],
                "status": "failed", "summary": str(exc)})
            context["_steps_out"] = steps_out
            return {
                "status": "failed",
                "summary": f"第 {i + 1} 步“{step['name']}”失败：{exc}",
                "steps": steps_out, "failed_index": i,
                "plan": plan, "context": context,
            }
        steps_out.append({
            "step_id": step["step_id"], "name": step["name"],
            "status": "success", "summary": result.get("summary", "")})
        context["_steps_out"] = steps_out

    summary = "全部步骤完成：" + "；".join(s["summary"] for s in steps_out if s.get("summary"))
    # 路由到最后产出的主要对象。
    route = context.get("route", "")
    return {
        "status": "success", "summary": summary,
        "steps": steps_out, "failed_index": None,
        "plan": plan, "context": context,
        "route": route, "sub": context.get("sub"),
        "extra": context.get("extra", {}),
    }


def _run_step(session, step_id: str, parsed_intent: dict, context: dict) -> dict:
    """执行单个步骤，结果写入 context 供后续步骤使用。"""
    params = parsed_intent.get("params", {})
    if step_id.startswith("ep_"):
        return _run_enhanced_step(session, step_id, params, context)
    if step_id == "gen_lesson":
        return _step_gen_lesson(session, params, context)
    if step_id == "gen_homework":
        return _step_gen_homework(session, params, context)
    if step_id == "pick_homework":
        return _step_pick_homework(session, params, context)
    if step_id == "weak_points":
        return _step_weak_points(session, params, context)
    if step_id == "build_reflection":
        return _step_build_reflection(session, params, context)
    if step_id == "summary":
        return {"summary": context.get("summary_text", "任务完成")}
    raise ValueError(f"未知步骤：{step_id}")


def _step_gen_lesson(session, params, context) -> dict:
    from utils import agent_service
    result = agent_service._do_prepare(session, params)
    lesson_id = result["extra"].get("pending_load_plan_id")
    context["lesson_id"] = lesson_id
    context["route"] = result["route"]
    context["sub"] = result["sub"]
    return {"summary": result["summary"]}


def _step_gen_homework(session, params, context) -> dict:
    from utils import lesson_homework_link_service
    lesson_id = context.get("lesson_id")
    if not lesson_id:
        raise ValueError("缺少上一步生成的教案，无法生成作业。")
    hw = lesson_homework_link_service.create_homework_from_lesson(session, lesson_id)
    context["homework_id"] = hw.id
    context["route"] = "📝 学业测评"
    context["sub"] = "作业管理"
    context["extra"] = {"hw_open_id": hw.id}
    context["summary_text"] = f"教案与配套作业《{hw.name}》均已生成"
    return {"summary": f"配套作业《{hw.name}》已生成"}


def _step_pick_homework(session, params, context) -> dict:
    from utils import exam_service
    subject = params.get("subject")
    exams = exam_service.list_exams(session)
    if subject:
        exams = [e for e in exams]
    if not exams:
        raise ValueError("没有找到考试数据，无法分析。")
    exam = exams[-1]
    context["exam_id"] = exam.id
    context["exam_label"] = f"{exam.name}（{exam.exam_date}）"
    return {"summary": f"选取考试《{exam.name}》"}


def _step_weak_points(session, params, context) -> dict:
    from utils import exam_service
    exam_id = context.get("exam_id")
    data = exam_service.analyze_exam(session, exam_id)
    subjects = data.get("subjects", [])
    weak = []
    for subject in subjects:
        stats = data["subject_stats"].get(subject, {})
        rate = stats.get("excellent_rate")
        weak.append(f"{subject}优秀率{rate}")
    context["analysis_data"] = True
    if not weak:
        return {"summary": "考试暂无各科成绩"}
    return {"summary": "已分析各科成绩表现"}


def _step_build_reflection(session, params, context) -> dict:
    from utils import reflection_service, llm_client
    from pathlib import Path
    import config
    exam_id = context.get("exam_id")
    data_text = reflection_service.build_reflection_data_text(
        session, "exam", exam_id)
    system_prompt = (Path(config.BASE_DIR) / "prompts" /
                     "reflection_prompt.txt").read_text(encoding="utf-8")
    reply = llm_client.chat(system_prompt, data_text, temperature=0.5)
    sections = reflection_service.parse_sections(reply)
    title = f"教学反思·{context.get('exam_label', exam_id)}"
    reflection_service.save_reflection(
        session, title, "exam", exam_id, None, sections)
    context["route"] = "📊 学情"
    context["sub"] = "教学反思"
    context["summary_text"] = "已基于最近考试生成教学反思"
    return {"summary": "教学反思已生成并保存"}

# ---------------------------------------------------------------------------
# v1.9.5：自主规划（增强）
# ---------------------------------------------------------------------------

FULL_LESSON_PREP = "full_lesson_prep"
EXAM_ANALYSIS_WITH_PLAN = "exam_analysis_with_plan"
REVIEW_PAPER_GENERATION = "review_paper_generation"
STUDENT_INTERVENTION = "student_intervention"

ENHANCED_KINDS = [
    FULL_LESSON_PREP, EXAM_ANALYSIS_WITH_PLAN,
    REVIEW_PAPER_GENERATION, STUDENT_INTERVENTION,
]

PLAN_KIND_LABELS = {
    FULL_LESSON_PREP: "完整备课（教案 + 配套作业）",
    EXAM_ANALYSIS_WITH_PLAN: "考试分析并生成改进计划",
    REVIEW_PAPER_GENERATION: "复习卷生成",
    STUDENT_INTERVENTION: "学生干预（分析 + 专项作业）",
}


def plan_kind_of(text: str, params: dict | None = None) -> str:
    """按指令内容判定自主规划类型。"""
    content = str(text or "")
    params = params or {}
    student_name = params.get("student_name") or ""
    if student_name and any(w in content for w in ("辅导", "专项", "干预", "帮我分析")):
        return STUDENT_INTERVENTION
    if any(w in content for w in ("复习卷", "期末", "复习题", "出一套", "出试卷")):
        return REVIEW_PAPER_GENERATION
    if "分析" in content and any(w in content for w in ("改进", "方案", "建议")):
        return EXAM_ANALYSIS_WITH_PLAN
    if "专项" in content and "分析" in content:
        return STUDENT_INTERVENTION
    if any(w in content for w in ("下周", "备课", "准备", "课")):
        return FULL_LESSON_PREP
    if student_name:
        return STUDENT_INTERVENTION
    return FULL_LESSON_PREP


def build_plan_enhanced(parsed_intent: dict, context: dict | None = None) -> list[dict]:
    """按解析意图动态生成增强计划；每步含 step_id/name/artifact_kind。

    支持四类：full_lesson_prep / exam_analysis_with_plan /
    review_paper_generation / student_intervention。
    """
    parsed_intent = parsed_intent or {}
    context = context or {}
    params = parsed_intent.get("params", {})
    instruction = context.get("instruction") or params.get("topic") or ""
    kind = context.get("plan_kind") or plan_kind_of(instruction, params)

    if kind == FULL_LESSON_PREP:
        return [
            {"step_id": "ep_scope", "name": "确定学科、年级与班级",
             "artifact_kind": "scope"},
            {"step_id": "ep_find_material", "name": "查找相关教学资料",
             "artifact_kind": "material"},
            {"step_id": "gen_lesson", "name": "生成教案",
             "artifact_kind": "lesson_plan"},
            {"step_id": "gen_homework", "name": "根据教案生成配套作业",
             "artifact_kind": "homework"},
            {"step_id": "summary", "name": "汇总结果", "artifact_kind": "none"},
        ]
    if kind == EXAM_ANALYSIS_WITH_PLAN:
        return [
            {"step_id": "ep_analyze_scores", "name": "分析最近一次考试成绩",
             "artifact_kind": "exam"},
            {"step_id": "ep_exam_weak", "name": "识别薄弱知识点",
             "artifact_kind": "knowledge"},
            {"step_id": "ep_make_reflection", "name": "整理教学建议并生成反思",
             "artifact_kind": "reflection"},
            {"step_id": "ep_make_plan", "name": "生成改进计划",
             "artifact_kind": "plan"},
            {"step_id": "summary", "name": "汇总结果", "artifact_kind": "none"},
        ]
    if kind == REVIEW_PAPER_GENERATION:
        return [
            {"step_id": "ep_review_scope", "name": "确定知识点范围",
             "artifact_kind": "scope"},
            {"step_id": "ep_compose_review", "name": "按难度分布出题",
             "artifact_kind": "questions"},
            {"step_id": "ep_finalize_paper", "name": "生成正式复习卷",
             "artifact_kind": "homework"},
            {"step_id": "ep_answer_key", "name": "整理答案与解析",
             "artifact_kind": "answer"},
        ]
    # STUDENT_INTERVENTION
    return [
        {"step_id": "ep_student_analyze", "name": "分析学生近期成绩与错题",
         "artifact_kind": "student"},
        {"step_id": "ep_student_advice", "name": "生成干预建议",
         "artifact_kind": "advice"},
        {"step_id": "ep_special_homework", "name": "生成薄弱点专项作业",
         "artifact_kind": "homework"},
        {"step_id": "summary", "name": "汇总结果", "artifact_kind": "none"},
    ]


# ---------------------------------------------------------------------------
# v1.9.5：增强步骤执行体
# ---------------------------------------------------------------------------

def _run_enhanced_step(session, step_id: str, params: dict,
                       context: dict) -> dict:
    """执行增强计划中的单个 ep_ 步骤；结果写入 context 串给后续步骤。"""
    handlers = {
        "ep_scope": _ep_scope,
        "ep_find_material": _ep_find_material,
        "ep_analyze_scores": _ep_analyze_scores,
        "ep_exam_weak": _ep_exam_weak,
        "ep_make_reflection": _ep_make_reflection,
        "ep_make_plan": _ep_make_plan,
        "ep_review_scope": _ep_review_scope,
        "ep_compose_review": _ep_compose_review,
        "ep_finalize_paper": _ep_finalize_paper,
        "ep_answer_key": _ep_answer_key,
        "ep_student_analyze": _ep_student_analyze,
        "ep_student_advice": _ep_student_advice,
        "ep_special_homework": _ep_special_homework,
    }
    handler = handlers.get(step_id)
    if handler is None:
        raise ValueError(f"未知增强步骤：{step_id}")
    return handler(session, params, context)


def _subject_grade(params: dict, context: dict):
    """取学科与存储年级；complex 预览确认时参数已在解析阶段补过上下文。"""
    from utils.app_config import DEFAULT_SUBJECT, to_storage_grade
    subject = params.get("subject") or context.get("subject") or DEFAULT_SUBJECT
    grade_display = params.get("grade") or context.get("grade") or ""
    grade_store = to_storage_grade(grade_display) if grade_display else None
    return subject, grade_display, grade_store


def _ep_scope(session, params, context) -> dict:
    """确定学科、年级、班级，并补全备课课题。"""
    subject, grade_display, grade_store = _subject_grade(params, context)
    params["subject"] = subject
    class_name = params.get("class_name") or context.get("class_name") or ""
    if not params.get("topic"):
        params["topic"] = (params.get("chapter")
                           or context.get("instruction") or "")
    context["subject"], context["grade"] = subject, grade_store
    context["class_name"] = class_name
    label = f"{subject}" + (f"·{grade_display}" if grade_display else "")
    return {"summary": f"已确定教学范围：{label}"}


def _ep_find_material(session, params, context) -> dict:
    """查找同学科、同年级的已有资料。"""
    from utils import material_service
    subject = context.get("subject") or params.get("subject")
    materials = material_service.list_materials(
        session, subject=subject, grade=context.get("grade"))
    context["material_count"] = len(materials)
    if materials:
        context["material_ids"] = [m.id for m in materials[:5]]
        return {"summary": f"找到 {len(materials)} 份相关资料"}
    return {"summary": "未找到已有资料，将直接生成"}


def _ep_analyze_scores(session, params, context) -> dict:
    """选取最近一次考试并做成绩分析。"""
    from utils import exam_service
    exams = exam_service.list_exams(session)
    if not exams:
        raise ValueError("没有找到考试数据，无法分析。")
    exam = exams[-1]
    data = exam_service.analyze_exam(session, exam.id)
    context["exam_id"] = exam.id
    context["exam_name"] = exam.name
    total_stats = data.get("total_stats", {})
    avg = total_stats.get("average")
    context["summary_text"] = f"《{exam.name}》班均 {avg}"
    return {"summary": f"已分析《{exam.name}》（班均 {avg}）"}


def _ep_exam_weak(session, params, context) -> dict:
    """从逐题作答识别薄弱知识点；普通考试总分不拆分。"""
    from utils import knowledge_graph_service
    subject = context.get("subject") or params.get("subject") or "数学"
    data = knowledge_graph_service.build_mastery(session, subject)
    weak = data.get("weak_top5", [])
    context["weak_points"] = [w["knowledge_point"] for w in weak]
    if weak:
        labels = "、".join(
            f"{w['knowledge_point']}（{w['avg_rate']:.0f}%）" for w in weak[:3])
        return {"summary": f"薄弱点：{labels}"}
    return {"summary": "暂无逐题数据，不拆分知识点"}


def _ep_make_reflection(session, params, context) -> dict:
    """基于考试数据生成并保存教学反思。"""
    from utils import reflection_service, llm_client
    from pathlib import Path
    import config
    exam_id = context.get("exam_id")
    data_text = reflection_service.build_reflection_data_text(
        session, "exam", exam_id)
    system_prompt = (Path(config.BASE_DIR) / "prompts" /
                     "reflection_prompt.txt").read_text(encoding="utf-8")
    reply = llm_client.chat(system_prompt, data_text, temperature=0.5)
    sections = reflection_service.parse_sections(reply)
    title = f"教学反思·{context.get('exam_name', exam_id)}"
    reflection = reflection_service.save_reflection(
        session, title, "exam", exam_id,
        context.get("class_name") or None, sections)
    session.flush()
    context["reflection_id"] = reflection.id
    context["route"] = "📊 学情"
    context["sub"] = "教学反思"
    return {"summary": "教学反思已生成"}


def _ep_make_plan(session, params, context) -> dict:
    """根据反思生成改进措施并保存改进计划（不绑定验证考试）。"""
    from utils import reflection_service
    reflection_id = context.get("reflection_id")
    if not reflection_id:
        raise ValueError("缺少上一步生成的反思，无法制定改进计划。")
    reflection = session.get(
        __import__("models.models", fromlist=["TeachingReflection"])
        .TeachingReflection, reflection_id)
    raw_content = reflection_service.load_reflection_content(reflection)
    text = reflection_service.sections_to_text(raw_content)
    measures = reflection_service.generate_improvement_plan(
        text, context.get("subject"))
    reflection_service.save_plan(session, reflection_id, measures, None)
    session.flush()
    context["summary_text"] = f"已生成 {len(measures)} 条改进措施"
    return {"summary": f"改进计划已生成（{len(measures)} 条措施）"}


def _ep_review_scope(session, params, context) -> dict:
    """确定复习卷的学科、年级和知识点范围。"""
    subject, grade_display, grade_store = _subject_grade(params, context)
    kps = [kp for kp in (params.get("knowledge_points") or []) if kp]
    context["subject"], context["grade"] = subject, grade_store
    context["review_kps"] = kps
    context["class_name"] = params.get("class_name") or ""
    scope = subject + (f"·{grade_display}" if grade_display else "")
    return {"summary": f"复习范围：{scope}"}


def _ep_compose_review(session, params, context) -> dict:
    """建隐藏草稿，按基础/中等/拓展分布出题。"""
    from utils import homework_service as hw_svc
    subject = context["subject"]
    grade_store = context.get("grade")
    draft = hw_svc.create_homework(
        session, f"__review_draft__{__import__('uuid').uuid4().hex[:8]}",
        homework_type="review", is_template=True, subject=subject,
        grade=grade_store, class_name=context.get("class_name") or None)
    session.flush()
    slots = [
        {"question_type": "choice", "difficulty": 1, "count": 4},
        {"question_type": "choice", "difficulty": 2, "count": 2},
        {"question_type": "fill", "difficulty": 1, "count": 2},
        {"question_type": "fill", "difficulty": 2, "count": 1},
        {"question_type": "solution", "difficulty": 2, "count": 1},
        {"question_type": "solution", "difficulty": 3, "count": 1},
    ]
    stats = hw_svc.auto_compose(
        session, draft.id, {"slots": slots},
        knowledge_points=context.get("review_kps") or None)
    context["draft_id"] = draft.id
    context["review_stats"] = stats
    return {"summary": f"已出 {stats.get('total_questions', 0)} 道题"}


def _ep_finalize_paper(session, params, context) -> dict:
    """有题则把草稿转正式复习卷，无题删除并失败。"""
    from utils import homework_service as hw_svc
    draft = session.get(
        __import__("models.models", fromlist=["Homework"]).Homework,
        context["draft_id"])
    stats = context.get("review_stats", {})
    if stats.get("total_questions", 0) <= 0:
        hw_svc.delete_homework(session, draft.id)
        session.flush()
        raise ValueError("没有生成任何题目，复习卷未创建。")
    grade_label = ""
    if draft.grade:
        from utils.app_config import to_display_grade
        grade_label = to_display_grade(draft.grade)
    draft.is_template = False
    draft.name = f"{context['subject']}{grade_label}复习卷"
    session.flush()
    context["homework_id"] = draft.id
    context["route"] = "📝 学业测评"
    context["sub"] = "作业管理"
    context["extra"] = {"hw_open_id": draft.id}
    context["summary_text"] = f"复习卷《{draft.name}》已生成"
    return {"summary": f"正式复习卷《{draft.name}》已生成"}


def _ep_answer_key(session, params, context) -> dict:
    """答案与解析随题目一起保存，这里只做汇总说明。"""
    return {"summary": "答案与解析已随卷整理"}


def _ep_student_analyze(session, params, context) -> dict:
    """定位学生并汇总近期成绩与错题。"""
    from utils import student_service, exam_service
    name = params.get("student_name") or ""
    if not name:
        raise ValueError("需要给出学生姓名。")
    students = student_service.list_students(session, keyword=name)
    if not students:
        raise ValueError(f"没有找到学生：{name}")
    student = students[0]
    history = exam_service.student_scores_over_time(session, student.id)
    context["student_id"] = student.id
    context["student_name"] = student.name
    context["class_name"] = student.class_name or ""
    context["subject"] = params.get("subject") or "数学"
    if history:
        context["last_total"] = history[-1].get("total")
    return {"summary": f"已分析 {student.name} 的近期表现"}


def _ep_student_advice(session, params, context) -> dict:
    """生成个人干预建议。"""
    from utils import agent_advisor
    plan = agent_advisor.generate_intervention_plan(
        session, context["student_id"])
    context["intervention"] = plan
    return {"summary": "干预建议已生成"}


def _ep_special_homework(session, params, context) -> dict:
    """根据学生薄弱点生成专项作业。"""
    from utils import homework_service as hw_svc, knowledge_graph_service
    from utils.app_config import to_storage_grade
    sid = context["student_id"]
    subject = context.get("subject") or "数学"
    mastery = knowledge_graph_service.build_mastery(
        session, subject, student_id=sid)
    weak = [w["knowledge_point"] for w in mastery.get("weak_top5", [])
            if w["knowledge_point"] != "未标注"][:3]
    student = session.get(
        __import__("models.models", fromlist=["Student"]).Student, sid)
    hw = hw_svc.create_homework(
        session, f"{student.name}薄弱点专项练习",
        homework_type="after_class", subject=subject,
        grade=to_storage_grade(params.get("grade")) if params.get("grade") else None,
        class_name=student.class_name)
    session.flush()
    slots = [
        {"question_type": "choice", "difficulty": 1, "count": 3},
        {"question_type": "fill", "difficulty": 2, "count": 2},
        {"question_type": "solution", "difficulty": 2, "count": 1},
    ]
    stats = hw_svc.auto_compose(
        session, hw.id, {"slots": slots},
        knowledge_points=weak or None)
    if stats.get("total_questions", 0) <= 0:
        hw_svc.delete_homework(session, hw.id)
        session.flush()
        raise ValueError("没有生成专项练习题。")
    context["homework_id"] = hw.id
    context["route"] = "📝 学业测评"
    context["sub"] = "作业管理"
    context["extra"] = {"hw_open_id": hw.id}
    context["summary_text"] = f"专项作业《{hw.name}》已生成"
    return {"summary": f"专项作业已生成（{stats['total_questions']} 题）"}

