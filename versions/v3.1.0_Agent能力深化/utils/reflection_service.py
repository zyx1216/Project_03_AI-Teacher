# -*- coding: utf-8 -*-
"""
教学反思服务层（v1.9.3）。

职责：
- 聚合“成绩数据 + 作业错题”文本，作为 user 消息注入给主模型；
- 四段式反思（成功之处/不足之处/学生反馈/改进措施）的解析、保存、读取、删除；
- 导出 Word。

所有数据库函数收外部 session，便于用内存库单测；本模块不直接调用 LLM，
逐人/逐次调用由页面负责，保证离线可测。
"""

from __future__ import annotations

import json
from datetime import date, datetime

from models.models import (
    Exam, Homework, HomeworkAnswer, HomeworkQuestion, Question,
    ReflectionPlan, Student, TeachingReflection)
from utils import exam_service, homework_stats as hstat, llm_client

# 四段标题（AI 输出用 “## 标题” 开头，解析时按这个顺序）
SECTIONS = ["成功之处", "不足之处", "学生反馈", "改进措施"]


# ---------------------------------------------------------------------------
# 数据聚合
# ---------------------------------------------------------------------------

def exams_in_scope(session, scope_type: str, start_exam_id: int,
                   end_exam_id: int | None = None) -> list[Exam]:
    """按范围取考试：exam 只取一场；range 取起止考试日期之间（含两端）的全部考试。"""
    start = exam_service.get_exam(session, start_exam_id)
    if start is None:
        return []
    if scope_type != "range" or not end_exam_id:
        return [start]
    end = exam_service.get_exam(session, end_exam_id)
    if end is None:
        return [start]
    d_from, d_to = sorted([start.exam_date, end.exam_date])
    return [e for e in exam_service.list_exams(session)
            if d_from <= e.exam_date <= d_to]


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _exam_metrics_lines(session, exam: Exam, class_name: str | None,
                        thresholds: dict | None = None) -> list[str]:
    """一场考试的指标文本行（复用考试分析口径）。"""
    data = exam_service.analyze_exam(
        session, exam.id, class_name=class_name, thresholds=thresholds)
    if not data or not data["rows"]:
        return [f"- 《{exam.name}》（{exam.exam_date}）：暂无成绩数据。"]
    lines = [f"- 《{exam.name}》（{exam.exam_date}）参考 {len(data['rows'])} 人："]
    for subject in data["subjects"]:
        stt = data["subject_stats"][subject]
        lines.append(
            f"    {subject}（满分{data['full_scores'][subject]:g}）："
            f"均分{stt['mean']}，最高{stt['max']:g}，"
            f"最低{stt['min']:g}，及格率{_pct(stt['pass_rate'])}，"
            f"优秀率{_pct(stt['excellent_rate'])}")
    total = data["total_stats"]
    lines.append(
        f"    总分（满分{data['total_full']:g}）：均分{total['mean']}，"
        f"及格率{_pct(total['pass_rate'])}，优秀率{_pct(total['excellent_rate'])}")
    # 进退步人数（只在有上次考试时才有）
    if data.get("deltas"):
        up = sum(1 for d in data["deltas"].values()
                 if d.get("score_delta") is not None and d["score_delta"] > 0)
        down = sum(1 for d in data["deltas"].values()
                   if d.get("score_delta") is not None and d["score_delta"] < 0)
        lines.append(f"    较上一次考试：进步 {up} 人，退步 {down} 人。")
    return lines


def collect_homework_errors(session, date_from: date | None, date_to: date | None,
                            class_name: str | None) -> dict:
    """
    聚合一段时间内作业的逐题作答，返回：
    {questions:[{content,knowledge_points,judged,wrong,rate}], error_types:{类型:次数}, total_wrong}
    只统计已判对错（is_correct 非空）的作答。
    """
    q = (session.query(HomeworkAnswer, Homework, Question, Student)
         .join(Homework, HomeworkAnswer.homework_id == Homework.id)
         .join(Question, HomeworkAnswer.question_id == Question.id)
         .join(Student, HomeworkAnswer.student_id == Student.id)
         .filter(Homework.is_template.is_(False))
         .filter(HomeworkAnswer.is_correct.isnot(None)))
    if date_from is not None:
        q = q.filter(Homework.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to is not None:
        q = q.filter(Homework.created_at <= datetime.combine(date_to, datetime.max.time()))
    if class_name:
        q = q.filter(Student.class_name == class_name)

    bucket: dict[int, dict] = {}
    error_types: dict[str, int] = {}
    total_wrong = 0
    for ans, _hw, question, _stu in q.all():
        g = bucket.setdefault(question.id, {
            "content": question.content, "knowledge_points": _kp_list(question),
            "judged": 0, "wrong": 0})
        g["judged"] += 1
        if not ans.is_correct:
            g["wrong"] += 1
            total_wrong += 1
            if ans.error_type:
                error_types[ans.error_type] = error_types.get(ans.error_type, 0) + 1

    questions = []
    for g in bucket.values():
        g["rate"] = round(g["wrong"] / g["judged"], 4) if g["judged"] else None
        questions.append(g)
    # 高频错题：错误人数多的在前
    questions.sort(key=lambda g: (g["wrong"], g["rate"] or 0), reverse=True)
    return {"questions": questions, "error_types": error_types,
            "total_wrong": total_wrong}


def _kp_list(question: Question) -> list[str]:
    try:
        data = json.loads(question.knowledge_points) if question.knowledge_points else []
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def build_reflection_data_text(session, scope_type: str, start_exam_id: int,
                               end_exam_id: int | None = None,
                               class_name: str | None = None,
                               thresholds: dict | None = None) -> str:
    """组装发给 AI 的数据文本（成绩指标 + 作业错题）。"""
    exams = exams_in_scope(session, scope_type, start_exam_id, end_exam_id)
    if not exams:
        return "没有找到考试数据。"

    scope_label = (f"{exams[0].name} 至 {exams[-1].name}"
                   if scope_type == "range" and len(exams) > 1 else exams[0].name)
    lines = [f"反思范围：{scope_label}",
             f"班级：{class_name or '全部班级'}",
             "",
             "【一、考试成绩数据】"]
    for exam in exams:
        lines.extend(_exam_metrics_lines(session, exam, class_name, thresholds))

    # 作业错题时间窗：单次考上一场之后到本场；时间段就用两端考试日期
    if scope_type == "range" and len(exams) > 1:
        d_from, d_to = exams[0].exam_date, exams[-1].exam_date
    else:
        prev = exam_service._previous_exam(session, exams[0])
        d_from = prev.exam_date if prev else None
        d_to = exams[0].exam_date

    errors = collect_homework_errors(session, d_from, d_to, class_name)
    lines.extend(["", "【二、作业错题数据】"])
    if errors["total_wrong"] == 0:
        lines.append("这段时间没有逐题批改的作业错题数据（可能只录了总分），请主要依据成绩数据分析。")
    else:
        if errors["error_types"]:
            et = "，".join(f"{k}{v} 次" for k, v in
                          sorted(errors["error_types"].items(), key=lambda x: -x[1]))
            lines.append(f"错误类型分布：{et}。")
        lines.append(f"高频错题 TOP5（共 {errors['total_wrong']} 个错误作答）：")
        for i, g in enumerate(errors["questions"][:5], start=1):
            kps = "、".join(g["knowledge_points"]) or "未标注知识点"
            preview = g["content"].replace("\n", " ")[:60]
            lines.append(f"{i}. {preview}……｜知识点：{kps}"
                         f"｜错误 {g['wrong']}/{g['judged']} 人，错误率{_pct(g['rate'])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 反思内容解析与留档
# ---------------------------------------------------------------------------

def parse_sections(text: str) -> dict:
    """
    把 AI 输出按 “## 标题” 解析成 {四段标题: 正文}。
    解析不出来时整篇归到“成功之处”，保证内容不丢。
    """
    result = {name: "" for name in SECTIONS}
    current = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        matched = None
        if line.startswith("#"):
            for name in SECTIONS:
                if name in line:
                    matched = name
                    break
        if matched:
            current = matched
            continue
        if current and line:
            result[current] = (result[current] + "\n" + line).strip()
    if not any(result.values()):
        result[SECTIONS[0]] = (text or "").strip()
    return result


def sections_to_text(sections: dict) -> str:
    """四段字典转成带标题的纯文本（AI 原文风格），供编辑框和导出共用。"""
    return "\n\n".join(f"## {name}\n{(sections.get(name) or '').strip()}"
                       for name in SECTIONS).strip()


def save_reflection(session, title: str, scope_type: str, start_exam_id: int,
                    class_name: str | None, content: str | dict,
                    end_exam_id: int | None = None,
                    reflection_id: int | None = None) -> TeachingReflection:
    """新建或更新一条反思。content 可传四段字典或纯文本（自动解析）。"""
    if isinstance(content, dict):
        sections = {name: str(content.get(name, "")) for name in SECTIONS}
        raw = sections_to_text(sections)
    else:
        raw = (content or "").strip()
        sections = parse_sections(raw)
    stored = json.dumps({"raw": raw, "sections": sections}, ensure_ascii=False)

    if reflection_id is not None:
        row = session.get(TeachingReflection, reflection_id)
        if row is None:
            raise ValueError(f"反思不存在：id={reflection_id}")
        row.title, row.content = title, stored
        row.updated_at = datetime.now()
        return row

    row = TeachingReflection(
        title=title, scope_type=scope_type, start_exam_id=start_exam_id,
        end_exam_id=end_exam_id if scope_type == "range" else None,
        class_name=class_name, content=stored)
    session.add(row)
    session.flush()
    return row


def load_reflection_content(reflection: TeachingReflection) -> dict:
    """读取留档反思，返回 {"raw": 全文, "sections": 四段字典}，兼容旧数据。"""
    try:
        data = json.loads(reflection.content) if reflection.content else {}
        sections = data.get("sections") or parse_sections(data.get("raw", ""))
        return {"raw": data.get("raw", reflection.content or ""),
                "sections": {name: sections.get(name, "") for name in SECTIONS}}
    except (ValueError, TypeError):
        return {"raw": reflection.content or "",
                "sections": parse_sections(reflection.content or "")}


def list_reflections(session, class_name: str | None = None) -> list[TeachingReflection]:
    q = session.query(TeachingReflection)
    if class_name:
        q = q.filter(TeachingReflection.class_name == class_name)
    return q.order_by(TeachingReflection.id.desc()).all()




def export_word(reflection: TeachingReflection) -> bytes:
    """把反思导出成含四个小节标题的 Word。"""
    import io
    from docx import Document

    data = load_reflection_content(reflection)
    doc = Document()
    doc.add_heading(reflection.title, level=0)
    meta = "　".join(x for x in [reflection.class_name,
                                 reflection.created_at.strftime("%Y-%m-%d")
                                 if reflection.created_at else ""] if x)
    if meta:
        doc.add_paragraph(meta)
    for name in SECTIONS:
        doc.add_heading(name, level=1)
        doc.add_paragraph(data["sections"].get(name) or "—")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

# ---------------------------------------------------------------------------
# v1.9.3：改进计划
# ---------------------------------------------------------------------------

PLAN_METHODS = ["课堂调整", "作业优化", "个别辅导", "其他"]
PLAN_STATUSES = {"pending": "待验证", "verified": "已验证", "expired": "已过期"}


def _json_array(text: str):
    """从模型文本中解析 JSON 数组。"""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _normalize_measures(measures) -> list[dict]:
    """校验并归一改进措施。"""
    if not isinstance(measures, list):
        raise ValueError("改进措施必须是列表。")
    result = []
    for item in measures:
        if not isinstance(item, dict):
            continue
        measure = str(item.get("measure") or "").strip()
        if not measure:
            continue
        method = str(item.get("method") or "课堂调整").strip()
        method = method if method in PLAN_METHODS else "其他"
        expected = str(
            item.get("expected_effect") or item.get("expected") or
            "提升相关学习表现").strip()
        result.append({
            "measure": measure,
            "method": method,
            "expected_effect": expected,
        })
    if not result:
        raise ValueError("至少保留一条有效改进措施。")
    return result[:5]


def _check_verify_exam(session, reflection: TeachingReflection,
                       verify_exam_id: int | None) -> Exam | None:
    """校验验证考试存在且晚于反思创建时间。"""
    if verify_exam_id is None:
        return None
    exam = exam_service.get_exam(session, int(verify_exam_id))
    if exam is None:
        raise ValueError(f"验证考试不存在：id={verify_exam_id}")
    reflection_day = (reflection.created_at or datetime.now()).date()
    if exam.exam_date <= reflection_day:
        raise ValueError("验证考试日期必须晚于反思创建日期。")
    return exam


def generate_improvement_plan(reflection_content: str,
                              subject: str | None = None) -> list[dict]:
    """让 AI 根据反思内容生成 3-5 条可执行改进措施。"""
    system_prompt = (
        "你是资深教学研究员，擅长根据教学反思提出具体可执行的改进措施。"
        "只输出 JSON 数组，不要输出其他文字。")
    user_text = (
        f"学科：{subject or '未指定'}\n"
        f"教学反思：\n{reflection_content}\n\n"
        "请输出3到5条措施，每条包含 measure、method、expected_effect。"
        "method 只能是：课堂调整、作业优化、个别辅导、其他。")
    raw = llm_client.chat_content(system_prompt, user_text, temperature=0.4)
    try:
        return _normalize_measures(_json_array(raw))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("AI 返回的改进措施格式不正确，请重试或手动填写。") from exc


def save_plan(session, reflection_id, measures: list[dict],
              verify_exam_id: int | None) -> ReflectionPlan:
    """保存一条改进计划，并同步反思的 has_plan 标记。"""
    reflection = session.get(TeachingReflection, int(reflection_id))
    if reflection is None:
        raise ValueError(f"反思不存在：id={reflection_id}")
    if get_plan_by_reflection(session, reflection.id) is not None:
        raise ValueError("这条反思已经存在改进计划。")
    normalized = _normalize_measures(measures)
    _check_verify_exam(session, reflection, verify_exam_id)

    plan = ReflectionPlan(
        reflection_id=reflection.id,
        content=json.dumps(normalized, ensure_ascii=False),
        verify_exam_id=verify_exam_id,
        status="pending",
        created_at=datetime.now())
    session.add(plan)
    reflection.has_plan = 1
    session.flush()
    return plan


def plan_content(plan: ReflectionPlan) -> list[dict]:
    """读取计划措施 JSON。"""
    try:
        data = json.loads(plan.content)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def get_plan_by_reflection(session, reflection_id):
    """按反思 ID 获取改进计划。"""
    return (session.query(ReflectionPlan)
            .filter(ReflectionPlan.reflection_id == int(reflection_id))
            .order_by(ReflectionPlan.id.desc()).first())


def update_plan(session, plan_id, measures: list[dict],
                verify_exam_id: int | None) -> None:
    """更新待验证计划。"""
    plan = session.get(ReflectionPlan, int(plan_id))
    if plan is None:
        raise ValueError(f"改进计划不存在：id={plan_id}")
    if plan.status != "pending":
        raise ValueError("只有待验证计划可以编辑。")
    reflection = session.get(TeachingReflection, plan.reflection_id)
    _check_verify_exam(session, reflection, verify_exam_id)
    plan.content = json.dumps(_normalize_measures(measures), ensure_ascii=False)
    plan.verify_exam_id = verify_exam_id
    session.flush()


def delete_plan(session, plan_id) -> None:
    """删除计划，并把反思标记恢复为无计划。"""
    plan = session.get(ReflectionPlan, int(plan_id))
    if plan is None:
        raise ValueError(f"改进计划不存在：id={plan_id}")
    reflection = session.get(TeachingReflection, plan.reflection_id)
    session.delete(plan)
    if reflection is not None:
        reflection.has_plan = 0
    session.flush()


def delete_reflection(session, reflection_id: int) -> None:
    """删除反思及其改进计划。"""
    row = session.get(TeachingReflection, reflection_id)
    if row is None:
        raise ValueError(f"反思不存在：id={reflection_id}")
    session.query(ReflectionPlan).filter(
        ReflectionPlan.reflection_id == row.id).delete()
    session.delete(row)


def _answer_rate_value(answer, link):
    """计算逐题作答得分率。"""
    if answer.earned_score is not None and link is not None and link.score:
        return min(1.0, max(0.0, float(answer.earned_score) / float(link.score)))
    if answer.is_correct is not None:
        return 1.0 if answer.is_correct else 0.0
    return None


def _knowledge_rate_on_day(session, exam: Exam, class_name: str | None) -> dict:
    """统计考试日期当天、逐题批改作业中的知识点正确率。"""
    homeworks = session.query(Homework).filter(
        Homework.status == "completed",
        Homework.is_template.is_(False))
    if class_name:
        homeworks = homeworks.filter(Homework.class_name == class_name)
    homeworks = [hw for hw in homeworks.all()
                 if hw.completed_at and hw.completed_at.date() == exam.exam_date]
    if not homeworks:
        return {}

    buckets = {}
    for hw in homeworks:
        links = {link.question_id: link for link in session.query(HomeworkQuestion).filter(
            HomeworkQuestion.homework_id == hw.id).all()}
        for answer in session.query(HomeworkAnswer).filter(
                HomeworkAnswer.homework_id == hw.id).all():
            if class_name:
                student = session.get(Student, answer.student_id)
                if student is None or student.class_name != class_name:
                    continue
            question = session.get(Question, answer.question_id)
            link = links.get(answer.question_id)
            rate = _answer_rate_value(answer, link)
            if rate is None or question is None:
                continue
            kps = question_service_kps(question) or ["未标注"]
            for kp in kps:
                item = buckets.setdefault(kp, [0.0, 0])
                item[0] += rate / len(kps)
                item[1] += 1 / len(kps)
    return {kp: round(value / weight * 100, 1)
            for kp, (value, weight) in buckets.items() if weight}


def question_service_kps(question):
    """延迟导入题目服务，避免循环依赖。"""
    from utils import question_service
    return question_service.knowledge_points_list(question)


def _rate(value, full) -> float | None:
    """计算百分制得分率。"""
    if value is None or not full:
        return None
    return round(float(value) / float(full) * 100, 1)


def _compare_exam_data(before: dict, after: dict) -> dict:
    """比较两次考试的总分、分科和及格/优秀率。"""
    before_total_rate = _rate(
        before["total_stats"]["mean"], before["total_full"])
    after_total_rate = _rate(
        after["total_stats"]["mean"], after["total_full"])
    subject_rates = {}
    for subject in sorted(set(before["subjects"]) & set(after["subjects"])):
        old_rate = _rate(before["subject_stats"][subject]["mean"],
                         before["full_scores"][subject])
        new_rate = _rate(after["subject_stats"][subject]["mean"],
                         after["full_scores"][subject])
        if old_rate is not None and new_rate is not None:
            subject_rates[subject] = {
                "before": old_rate,
                "after": new_rate,
                "delta": round(new_rate - old_rate, 1),
            }

    before_rows = {row["student_id"]: row for row in before["rows"]}
    student_deltas = []
    for row in after["rows"]:
        old = before_rows.get(row["student_id"])
        if old and old["total"] is not None and row["total"] is not None:
            student_deltas.append({
                "student_id": row["student_id"],
                "name": row["name"],
                "before": old["total"],
                "after": row["total"],
                "delta": round(row["total"] - old["total"], 2),
            })

    return {
        "total_before": before_total_rate,
        "total_after": after_total_rate,
        "total_delta": (round(after_total_rate - before_total_rate, 1)
                        if before_total_rate is not None and after_total_rate is not None
                        else None),
        "pass_rate_delta": round(
            (after["total_stats"]["pass_rate"] - before["total_stats"]["pass_rate"]) * 100, 1),
        "excellent_rate_delta": round(
            (after["total_stats"]["excellent_rate"] - before["total_stats"]["excellent_rate"]) * 100, 1),
        "subject_rates": subject_rates,
        "student_deltas": student_deltas,
    }


def _effect_from_delta(delta: float | None) -> tuple[str, float]:
    """按总得分率变化判定整体效果。"""
    if delta is None:
        return "数据不足", 0.0
    if delta >= 5:
        return "有效", 1.0
    if delta >= 0:
        return "部分有效", 0.5
    return "效果不明显", 0.2


def _build_verify_report(session, plan: ReflectionPlan) -> dict:
    """生成数值验证报告；AI 仅补充中文解释。"""
    reflection = session.get(TeachingReflection, plan.reflection_id)
    base_exam_id = reflection.end_exam_id or reflection.start_exam_id
    if not base_exam_id or not plan.verify_exam_id:
        raise ValueError("基准考试或验证考试缺失，无法自动验证。")
    if base_exam_id == plan.verify_exam_id:
        raise ValueError("验证考试不能和基准考试相同。")

    before = exam_service.analyze_exam(
        session, base_exam_id, class_name=reflection.class_name)
    after = exam_service.analyze_exam(
        session, plan.verify_exam_id, class_name=reflection.class_name)
    if not before.get("rows") or not after.get("rows"):
        raise ValueError("基准考试或验证考试暂无成绩，无法验证。")

    comparison = _compare_exam_data(before, after)
    overall_effect, attainment = _effect_from_delta(comparison["total_delta"])
    old_kps = _knowledge_rate_on_day(
        session, before["exam"], reflection.class_name)
    new_kps = _knowledge_rate_on_day(
        session, after["exam"], reflection.class_name)
    knowledge_effects = []
    for kp in sorted(set(old_kps) & set(new_kps)):
        knowledge_effects.append({
            "knowledge_point": kp,
            "before": old_kps[kp],
            "after": new_kps[kp],
            "delta": round(new_kps[kp] - old_kps[kp], 1),
        })

    measures = plan_content(plan)
    measure_effects = [{
        **item,
        "attainment": attainment,
        "result": overall_effect,
    } for item in measures]
    data_support = [
        f"总分得分率：{comparison['total_before']}% → {comparison['total_after']}%",
        f"及格率变化：{comparison['pass_rate_delta']} 个百分点",
        f"优秀率变化：{comparison['excellent_rate_delta']} 个百分点",
    ]
    if not knowledge_effects:
        data_support.append("无逐题数据，不评估知识点变化。")

    suggestions = []
    try:
        ai_text = llm_client.chat_content(
            "你是教学评估专家。请根据验证数据给出简短中文建议。",
            json.dumps({
                "measures": measures,
                "comparison": comparison,
                "knowledge_effects": knowledge_effects,
            }, ensure_ascii=False, default=str),
            temperature=0.3)
        suggestions = [line.strip("- ").strip()
                       for line in ai_text.splitlines() if line.strip()][:5]
    except Exception:
        pass
    if not suggestions:
        suggestions = (["继续坚持有效措施，并在后续作业中复测。"]
                       if overall_effect != "效果不明显"
                       else ["调整措施，增加课堂反馈和个别辅导。"])

    return {
        "overall_effect": overall_effect,
        "overall_rate": attainment,
        "overall_delta": comparison["total_delta"],
        "measure_effects": measure_effects,
        "knowledge_effects": knowledge_effects,
        "comparison": comparison,
        "data_support": data_support,
        "suggestions": suggestions,
    }


def verify_plan(session, plan_id) -> dict:
    """执行自动验证并保存结果。"""
    plan = session.get(ReflectionPlan, int(plan_id))
    if plan is None:
        raise ValueError(f"改进计划不存在：id={plan_id}")
    report = _build_verify_report(session, plan)
    plan.status = "verified"
    plan.verified_at = datetime.now()
    plan.verify_result = json.dumps(report, ensure_ascii=False, default=str)
    session.flush()
    return report


def load_verify_result(plan: ReflectionPlan) -> dict:
    """读取验证结果。"""
    try:
        data = json.loads(plan.verify_result) if plan.verify_result else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def mark_plan_verified_manually(session, plan_id) -> dict:
    """手动标记计划已验证。"""
    plan = session.get(ReflectionPlan, int(plan_id))
    if plan is None:
        raise ValueError(f"改进计划不存在：id={plan_id}")
    report = {
        "overall_effect": "手动确认",
        "overall_rate": 1.0,
        "overall_delta": None,
        "measure_effects": [{**item, "attainment": 1.0, "result": "手动确认"}
                            for item in plan_content(plan)],
        "knowledge_effects": [],
        "data_support": ["由老师手动确认完成。"],
        "suggestions": ["继续保留有效做法。"],
    }
    plan.status = "verified"
    plan.verified_at = datetime.now()
    plan.verify_result = json.dumps(report, ensure_ascii=False)
    session.flush()
    return report


def check_and_verify_pending_plans(session, exam_id: int) -> list[int]:
    """成绩写入后，自动验证绑定该考试的待验证/过期计划。"""
    verified_ids = []
    plans = session.query(ReflectionPlan).filter(
        ReflectionPlan.verify_exam_id == int(exam_id),
        ReflectionPlan.status.in_(["pending", "expired"])).all()
    for plan in plans:
        try:
            report = _build_verify_report(session, plan)
            plan.status = "verified"
            plan.verified_at = datetime.now()
            plan.verify_result = json.dumps(
                report,
                ensure_ascii=False, default=str)
            verified_ids.append(plan.id)
        except Exception:
            continue
    session.flush()
    return verified_ids


def refresh_expired_plans(session) -> int:
    """把验证考试已过期、仍未验证的计划标记为 expired。"""
    today = date.today()
    count = 0
    plans = session.query(ReflectionPlan).filter(
        ReflectionPlan.status == "pending").all()
    for plan in plans:
        exam = session.get(Exam, plan.verify_exam_id) if plan.verify_exam_id else None
        if exam is not None and exam.exam_date < today:
            plan.status = "expired"
            count += 1
    session.flush()
    return count


def get_improvement_history(session, subject=None, start_date=None,
                            end_date=None) -> list[dict]:
    """获取已验证闭环历史。"""
    q = session.query(ReflectionPlan).filter(
        ReflectionPlan.status == "verified")
    plans = q.order_by(ReflectionPlan.verified_at.desc()).all()
    result = []
    for plan in plans:
        reflection = session.get(TeachingReflection, plan.reflection_id)
        if reflection is None:
            continue
        base_exam = session.get(
            Exam, reflection.end_exam_id or reflection.start_exam_id)
        verify_exam = session.get(Exam, plan.verify_exam_id)
        if subject:
            from models.models import Score
            subject_rows = session.query(Score.subject).filter(
                Score.exam_id.in_(
                    [x.id for x in (base_exam, verify_exam) if x])).all()
            if subject not in {row[0] for row in subject_rows}:
                continue
        if start_date and reflection.created_at.date() < start_date:
            continue
        if end_date and reflection.created_at.date() > end_date:
            continue
        report = load_verify_result(plan)
        result.append({
            "plan_id": plan.id,
            "reflection_id": reflection.id,
            "reflection_title": reflection.title,
            "reflection_created_at": reflection.created_at,
            "base_exam": base_exam.name if base_exam else "—",
            "verify_exam": verify_exam.name if verify_exam else "—",
            "core_problem": load_reflection_content(reflection)["sections"].get(
                "不足之处", "")[:60],
            "measure_count": len(plan_content(plan)),
            "overall_effect": report.get("overall_effect", "—"),
            "report": report,
        })
    return result


def export_improvement_report(session, plans: list) -> bytes:
    """导出教学改进年度报告 Word。"""
    import io
    from docx import Document

    doc = Document()
    doc.add_heading("教学改进年度报告", level=0)
    for index, item in enumerate(plans, start=1):
        doc.add_heading(f"{index}. {item['reflection_title']}", level=1)
        doc.add_paragraph(f"反思时间：{item['reflection_created_at']:%Y-%m-%d}")
        doc.add_paragraph(f"基准考试：{item['base_exam']}")
        doc.add_paragraph(f"验证考试：{item['verify_exam']}")
        doc.add_paragraph(f"整体效果：{item['overall_effect']}")
        report = item.get("report") or {}
        for measure in report.get("measure_effects", []):
            doc.add_paragraph(
                f"• {measure.get('measure')}（{measure.get('result')}）",
                style=None)
        for suggestion in report.get("suggestions", []):
            doc.add_paragraph(f"建议：{suggestion}")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
