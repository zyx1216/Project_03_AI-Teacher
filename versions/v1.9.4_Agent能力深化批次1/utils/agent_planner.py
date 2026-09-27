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
