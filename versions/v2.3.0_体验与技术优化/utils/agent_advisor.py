# -*- coding: utf-8 -*-
"""教学建议 Agent（v1.9.5）。

口径：服务层先做确定性数据聚合，再由 LLM 组织成中文建议；
AI 未配置或调用失败时用规则模板兜底，不阻断。数据不足时明确提示，不编造。

提供四类建议：
- generate_weekly_suggestions   本周教学建议（薄弱点/错误率/提交率/层次分布）
- generate_layered_teaching_suggestions  班级 A/B/C 分层教学建议
- generate_review_plan          考试复习计划
- generate_intervention_plan    学生个人干预计划

缓存：本周首次进首页自动生成一次，落 data/agent_suggestions.json（含周标识），
之后读缓存。文件缺失自建、损坏回退默认且不覆盖原文件。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import config
from models.models import (
    Exam, Homework, HomeworkAnswer, HomeworkSubmission, Score, Student)
from sqlalchemy import func
from utils import llm_client

SUGGESTIONS_PATH = config.DATA_DIR / "agent_suggestions.json"
HISTORY_LIMIT = 8
INSUFFICIENT_TEXT = "需要更多成绩数据：先录入一场考试或一次逐题批改作业。"

_LAYER_METHODS = ("课堂调整", "作业优化", "个别辅导", "其他")


# ---------------------------------------------------------------------------
# JSON 持久化
# ---------------------------------------------------------------------------

def default_state() -> dict:
    """建议缓存默认结构。"""
    return {"current": None, "weeks": []}


def load_state() -> dict:
    """加载建议缓存；缺失自建，损坏回退默认且不覆盖。"""
    path = SUGGESTIONS_PATH
    try:
        if not path.exists():
            state = default_state()
            save_state(state)
            return state
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_state()
    except (json.JSONDecodeError, OSError):
        return default_state()
    return {
        "current": data.get("current") if isinstance(data.get("current"), dict) else None,
        "weeks": data.get("weeks") if isinstance(data.get("weeks"), list) else [],
    }


def save_state(state: dict) -> None:
    """持久化建议缓存，UTF-8、ensure_ascii=False。"""
    SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUGGESTIONS_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def week_id(day: datetime | None = None) -> str:
    """返回 ISO 周标识，如 2026-W39。"""
    day = day or datetime.now()
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def get_cached_weekly() -> dict | None:
    """读取本周已缓存的周建议；不是本周或没有缓存返回 None。"""
    state = load_state()
    current = state.get("current")
    if current and current.get("week_id") == week_id():
        return current
    return None


def _store_weekly(entry: dict) -> None:
    """写入本周建议缓存，并保留最近 HISTORY_LIMIT 周。"""
    state = load_state()
    state["current"] = entry
    weeks = [w for w in state.get("weeks", [])
             if w.get("week_id") != entry.get("week_id")]
    weeks.insert(0, entry)
    state["weeks"] = weeks[:HISTORY_LIMIT]
    save_state(state)


# ---------------------------------------------------------------------------
# 确定性数据聚合
# ---------------------------------------------------------------------------

def weekly_facts(session, context: dict | None = None) -> dict:
    """聚合本周建议所需事实：薄弱点、错误率、提交率、学生层次、关注名单。"""
    context = context or {}
    subject = context.get("subject") or "数学"
    class_name = context.get("class_name") or None

    weak = _weak_points(session, subject, class_name)
    error_rate = _recent_error_rate(session, subject, class_name)
    submission_rate = _recent_submission_rate(session, class_name)
    layers, latest_exam = _latest_exam_layers(session, class_name, subject)
    watch_students = _watch_students(session, class_name, subject)

    return {
        "subject": subject,
        "class_name": class_name,
        "weak_points": weak,
        "error_rate": error_rate,
        "submission_rate": submission_rate,
        "layers": layers,
        "latest_exam": latest_exam,
        "watch_students": watch_students,
    }


def has_enough_data(facts: dict) -> bool:
    """判断是否有足够数据生成建议。"""
    return bool(facts.get("weak_points")
                or facts.get("error_rate") is not None
                or facts.get("layers"))


def _weak_points(session, subject: str, class_name: str | None) -> list[dict]:
    """复用知识图谱服务取 Top5 薄弱知识点。"""
    try:
        from utils import knowledge_graph_service
        data = knowledge_graph_service.build_mastery(
            session, subject,
            class_names=[class_name] if class_name else None)
        return [{"knowledge_point": w["knowledge_point"],
                 "avg_rate": w["avg_rate"]}
                for w in data.get("weak_top5", [])]
    except Exception:
        return []


def _recent_error_rate(session, subject: str,
                       class_name: str | None, days: int = 14) -> float | None:
    """最近 days 天逐题作答的整体错误率。"""
    since = datetime.now() - timedelta(days=days)
    q = (session.query(HomeworkAnswer)
         .filter(HomeworkAnswer.created_at >= since,
                 HomeworkAnswer.is_correct.isnot(None)))
    if class_name:
        q = (q.join(Student, Student.id == HomeworkAnswer.student_id)
             .filter(Student.class_name == class_name))
    rows = q.all()
    if not rows:
        return None
    wrong = sum(1 for r in rows if r.is_correct is False)
    return round(wrong / len(rows) * 100, 1)


def _recent_submission_rate(session, class_name: str | None,
                            days: int = 7) -> float | None:
    """最近 days 天在线提交作业的平均提交率（按提交人数/班级名册）。"""
    since = datetime.now() - timedelta(days=days)
    homeworks = (session.query(Homework)
                 .filter(Homework.is_template.is_(False),
                         Homework.created_at >= since,
                         Homework.class_name.isnot(None)).all())
    if class_name:
        homeworks = [h for h in homeworks if h.class_name == class_name]
    rates = []
    for hw in homeworks:
        roster = (session.query(func.count(Student.id))
                  .filter(Student.class_name == hw.class_name).scalar()) or 0
        if roster <= 0:
            continue
        submitted = (session.query(func.count(func.distinct(
                        HomeworkSubmission.student_name)))
                     .filter(HomeworkSubmission.homework_id == hw.id).scalar()) or 0
        rates.append(submitted / roster)
    if not rates:
        return None
    return round(sum(rates) / len(rates) * 100, 1)


def _latest_exam_layers(session, class_name: str | None, subject: str):
    """取最近一场考试的 A/B/C 层次分布。"""
    exams = (session.query(Exam)
             .order_by(Exam.exam_date.desc(), Exam.id.desc())
             .limit(5).all())
    for exam in exams:
        rows = _exam_totals(session, exam.id, class_name)
        if not rows:
            continue
        values = [r["total"] for r in rows if r["total"] is not None]
        if not values:
            continue
        avg = sum(values) / len(values)
        # 以相对班均的比例分层：A>=105%，B 85%~105%，C<85%。
        layers = {"A": 0, "B": 0, "C": 0}
        for total in values:
            ratio = total / avg if avg else 1
            if ratio >= 1.05:
                layers["A"] += 1
            elif ratio >= 0.85:
                layers["B"] += 1
            else:
                layers["C"] += 1
        return layers, {"exam_id": exam.id, "name": exam.name,
                        "average": round(avg, 1)}
    return None, None


def _exam_totals(session, exam_id: int, class_name: str | None) -> list[dict]:
    """一场考试每个学生的总分。"""
    q = (session.query(Score.student_id, Student.name, Student.class_name,
                       func.sum(Score.score))
         .join(Student, Student.id == Score.student_id)
         .filter(Score.exam_id == exam_id, Score.score.isnot(None)))
    if class_name:
        q = q.filter(Student.class_name == class_name)
    return [{"student_id": sid, "name": name,
             "class_name": cn, "total": total}
            for sid, name, cn, total in q.group_by(
                Score.student_id, Student.name, Student.class_name).all()]


def _watch_students(session, class_name: str | None, subject: str,
                    n: int = 5) -> list[str]:
    """最近一场考试总分排在最后或近两周错题最多的学生名单。"""
    exams = (session.query(Exam)
             .order_by(Exam.exam_date.desc(), Exam.id.desc()).limit(3).all())
    names: list[str] = []
    for exam in exams:
        rows = _exam_totals(session, exam.id, class_name)
        rows = [r for r in rows if r["total"] is not None]
        if rows:
            rows.sort(key=lambda r: r["total"])
            names = [r["name"] for r in rows[:n]]
            break
    if not names:
        since = datetime.now() - timedelta(days=14)
        q = (session.query(Student.name, func.count(HomeworkAnswer.id))
             .join(Student, Student.id == HomeworkAnswer.student_id)
             .filter(HomeworkAnswer.created_at >= since,
                     HomeworkAnswer.is_correct.is_(False)))
        if class_name:
            q = q.filter(Student.class_name ==class_name)
        names = [name for name, _cnt in q.group_by(Student.name)
                 .order_by(func.count(HomeworkAnswer.id).desc()).limit(n).all()]
    return names


# ---------------------------------------------------------------------------
# 1. 本周教学建议
# ---------------------------------------------------------------------------

def generate_weekly_suggestions(session, context: dict | None = None,
                                *, force: bool = False) -> dict:
    """生成本周教学建议；默认读本周缓存，force=True 强制重新生成。"""
    if not force:
        cached = get_cached_weekly()
        if cached:
            return cached
    context = context or {}
    facts = weekly_facts(session, context)
    if not has_enough_data(facts):
        entry = {
            "week_id": week_id(),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "context": context,
            "facts": facts,
            "insufficient": True,
            "text": INSUFFICIENT_TEXT,
            "focus_points": [],
            "measures": [],
        }
        _store_weekly(entry)
        return entry

    text, focus, measures = _organize_weekly(facts)
    entry = {
        "week_id": week_id(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "context": context,
        "facts": facts,
        "insufficient": False,
        "text": text,
        "focus_points": focus,
        "measures": measures,
    }
    _store_weekly(entry)
    return entry


def _organize_weekly(facts: dict) -> tuple[str, list[str], list[dict]]:
    """用 LLM 把事实组织成中文建议；失败走模板兜底。"""
    weak_labels = [f"{w['knowledge_point']}（掌握率约{w['avg_rate']:.0f}%）"
                   for w in facts["weak_points"][:5]]
    prompt_facts = json.dumps({
        "学科": facts["subject"],
        "薄弱知识点": weak_labels,
        "近两周错误率": facts["error_rate"],
        "提交率": facts["submission_rate"],
        "层次分布": facts["layers"],
        "关注学生": facts["watch_students"],
    }, ensure_ascii=False)
    system = (
        "你是有经验的中小学教研组长。根据给定的教学数据写本周教学建议，"
        "只基于数据，不要编造。输出 JSON："
        '{"text":"300字内整体建议","focus_points":["教学重点1"]*3-5,'
        '"measures":[{"measure":"具体措施","method":"课堂调整|作业优化|个别辅导|其他",'
        '"expected_effect":"预期效果"}]}')
    text = None
    focus: list[str] = []
    measures: list[dict] = []
    if llm_client.is_content_configured():
        try:
            raw = llm_client.chat_content(system, prompt_facts, temperature=0.4)
            from utils.lesson_service import extract_json
            data = extract_json(raw)
            if isinstance(data, dict):
                text = str(data.get("text") or "").strip()
                focus = [str(x).strip() for x in data.get("focus_points", [])
                         if str(x).strip()]
                measures = _clean_measures(data.get("measures"))
        except Exception:
            text = None
    if not text:
        text, focus, measures = _weekly_template(facts)
    return text, focus, measures


def _weekly_template(facts: dict) -> tuple[str, list[str], list[dict]]:
    """AI 不可用时的确定性兜底建议。"""
    focus = [w["knowledge_point"] for w in facts["weak_points"][:3]] \
        or ["巩固本周核心知识点"]
    parts = [f"本周教学重点：{'、'.join(focus)}。"]
    if facts["weak_points"]:
        parts.append("薄弱点 "
                     + "、".join(f"{w['knowledge_point']}（{w['avg_rate']:.0f}%）"
                                 for w in facts["weak_points"][:3])
                     + " 需要安排专项讲解和练习。")
    if facts["error_rate"] is not None:
        parts.append(f"近两周整体错误率 {facts['error_rate']}%，注意审题和计算规范。")
    if facts["watch_students"]:
        parts.append("重点关注 " + "、".join(facts["watch_students"]) + "，及时个别辅导。")
    measures = [
        {"measure": f"课堂上增加{focus[0]}的例题与变式",
         "method": "课堂调整", "expected_effect": "提升薄弱点掌握率"},
        {"measure": "错题二次订正并面批",
         "method": "作业优化", "expected_effect": "降低重复错误率"},
    ]
    return "".join(parts), focus, measures


def _clean_measures(raw) -> list[dict]:
    """归一化措施，method 限定固定取值。"""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        measure = str(item.get("measure") or "").strip()
        if not measure:
            continue
        method = str(item.get("method") or "课堂调整").strip()
        if method not in _LAYER_METHODS:
            method = "课堂调整"
        out.append({
            "measure": measure, "method": method,
            "expected_effect": str(item.get("expected_effect") or "").strip(),
        })
    return out


# ---------------------------------------------------------------------------
# 2. 分层教学建议
# ---------------------------------------------------------------------------

def generate_layered_teaching_suggestions(session, class_name: str,
                                          subject: str = "数学") -> dict:
    """按最近成绩把班级分 A/B/C 三层，给目标、活动、作业和关注点。"""
    layers, exam = _latest_exam_layers(session, class_name, subject)
    if not layers:
        return {"insufficient": True, "text": INSUFFICIENT_TEXT,
                "class_name": class_name, "subject": subject}
    plans = {
        "A": {"goal": "拓展提升，培养综合与迁移能力",
              "activity": "增加开放性、压轴题探究",
              "homework": "以拓展题、综合题为主",
              "focus": "防止基础题粗心失分"},
        "B": {"goal": "夯实基础并稳步提高",
              "activity": "典型例题精讲 + 变式训练",
              "homework": "基础与中等题搭配",
              "focus": "突破中档题的思路卡点"},
        "C": {"goal": "补牢最基础的概念和计算",
              "activity": "小步快跑、多重复、多鼓励",
              "homework": "以基础题为主、减量保质",
              "focus": "建立信心，盯住作业落实"},
    }
    text = (
        f"依据《{exam['name']}》（班均 {exam['average']}）分层："
        f"A 层 {layers['A']} 人、B 层 {layers['B']} 人、C 层 {layers['C']} 人。"
        "A 层重在拓展，B 层重在中档突破，C 层重在基础落实。")
    return {"insufficient": False, "text": text, "class_name": class_name,
            "subject": subject, "layers": layers, "plans": plans}


# ---------------------------------------------------------------------------
# 3. 复习计划
# ---------------------------------------------------------------------------

def generate_review_plan(session, exam_id: int, days: int = 5) -> dict:
    """根据考试范围生成复习天数安排、每日重点、配套题与易错点。"""
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ValueError(f"考试不存在：id={exam_id}")
    subjects = sorted({s[0] for s in session.query(Score.subject)
                       .filter(Score.exam_id == exam_id).all()})
    daily = []
    for d in range(1, days + 1):
        topic = subjects[(d - 1) % len(subjects)] if subjects else "综合"
        daily.append({"day": f"第{d}天", "focus": f"{topic}专项复习",
                      "task": "回顾错题 + 完成配套练习"})
    weak = _weak_points(session, subjects[0] if subjects else "数学", None)
    error_points = [w["knowledge_point"] for w in weak[:3]]
    text = (f"《{exam.name}》按 {days} 天安排复习：先分科专项突破，"
            "再做整套模拟，最后回顾错题。")
    return {"insufficient": False, "text": text, "exam_id": exam_id,
            "daily": daily, "error_points": error_points}


# ---------------------------------------------------------------------------
# 4. 学生干预计划
# ---------------------------------------------------------------------------

def generate_intervention_plan(session, student_id: int) -> dict:
    """对单个学生给问题诊断、干预措施、家长沟通和跟踪计划。"""
    student = session.get(Student, student_id)
    if student is None:
        raise ValueError(f"学生不存在：id={student_id}")
    recent = (session.query(Exam.name, Score.score)
              .join(Score, Score.exam_id == Exam.id)
              .filter(Score.student_id == student_id, Score.score.isnot(None))
              .order_by(Exam.exam_date.desc()).limit(3).all())
    wrong = (session.query(func.count(HomeworkAnswer.id))
             .filter(HomeworkAnswer.student_id == student_id,
                     HomeworkAnswer.is_correct.is_(False)).scalar()) or 0
    diagnosis = []
    if recent:
        scores = "、".join(f"{name} {score:.0f}" for name, score in recent)
        diagnosis.append(f"最近成绩：{scores}")
    diagnosis.append(f"累计错题 {wrong} 道")
    measures = [
        {"measure": "每周固定 1-2 次针对性辅导",
         "method": "个别辅导", "expected_effect": "补齐薄弱环节"},
        {"measure": "错题本每周检查一次",
         "method": "作业优化", "expected_effect": "减少重复错误"},
    ]
    text = (f"{student.name}（{student.class_name or '未分班'}）："
            + "；".join(diagnosis) + "。建议小步辅导、持续跟踪。")
    return {"insufficient": False, "text": text,
            "student_id": student_id, "student_name": student.name,
            "measures": measures,
            "family": "客观反馈近期表现，约定家庭督促方式",
            "tracking": "每两周对比一次成绩与错题变化"}


# ---------------------------------------------------------------------------
# 保存建议到教学反思（新建反思 + 自动生成改进计划）
# ---------------------------------------------------------------------------

def save_weekly_to_reflection(session, entry: dict) -> dict:
    """把本周建议保存为一条新教学反思，并据措施生成改进计划。"""
    from utils import reflection_service
    if entry.get("insufficient"):
        raise ValueError("数据不足，暂不能把建议保存为教学反思。")
    context = entry.get("context") or {}
    subject = context.get("subject") or "数学"
    title = f"AI教学建议·{entry.get('week_id') or week_id()}"
    content = entry.get("text") or ""
    reflection = reflection_service.save_reflection(
        session, title, "exam", None, context.get("class_name"), content)
    session.flush()
    measures = entry.get("measures") or []
    if measures:
        reflection_service.save_plan(
            session, reflection.id, _clean_measures(measures), None)
        session.flush()
    return {"reflection_id": reflection.id, "title": title}


# ---------------------------------------------------------------------------
# v2.0.0 分层作业落库
# ---------------------------------------------------------------------------

def _tier_names(rows) -> dict[str, list[dict]]:
    """按最近考试总分排名把学生分 A/B/C 三层。

    口径：A 前 20%、B 中间 60%、C 后 20%；并列按 student_id 稳定截断。
    """
    ordered = sorted(rows, key=lambda r: (-r["total"], r["student_id"]))
    n = len(ordered)
    a_count = max(1, round(n * 0.2)) if n else 0
    c_count = max(1, round(n * 0.2)) if n else 0
    # 人数过少时保证三层不重叠：A、C 各取，其余为 B
    if a_count + c_count > n:
        a_count = 1 if n >= 1 else 0
        c_count = 1 if n >= 2 else 0
    return {
        "A": ordered[:a_count],
        "B": ordered[a_count:n - c_count],
        "C": ordered[n - c_count:],
    }


def _tier_spec(difficulty: int, per_layer: int) -> dict:
    """按层难度组卷：选择/填空各 2 道、解答 1 道，per_layer 控制总题量。

    per_layer 不足时只保留解答题，保证每层至少有题（最小结构）。
    """
    if per_layer <= 2:
        counts = {"choice": 0, "fill": 0, "solution": max(1, per_layer)}
    elif per_layer <= 4:
        counts = {"choice": 1, "fill": 1,
                  "solution": max(1, per_layer - 2)}
    else:
        counts = {"choice": 2, "fill": 2,
                  "solution": max(1, per_layer - 4)}
    slots = []
    for qtype, count in counts.items():
        for _ in range(count):
            slots.append({"question_type": qtype,
                          "difficulty": difficulty, "count": 1})
    return {"slots": slots}


def generate_tiered_homework(session, class_name: str, subject: str,
                             weak_points=None, exam_id=None,
                             questions_per_layer=5) -> dict:
    """按 A/B/C 三层各生成一份作业并自动组题，返回作业 ID 与分层名单。

    复用 homework_service.create_homework + auto_compose，不新增分层字段。
    没有可用考试成绩时返回明确错误，不臆造分层。
    """
    # 选一场该班有总分数据的最近考试作为分层依据
    rows = None
    if exam_id is not None:
        candidate = _exam_totals(session, exam_id, class_name)
        if candidate and any(r["total"] is not None for r in candidate):
            rows = [r for r in candidate if r["total"] is not None]
    if rows is None:
        exams = (session.query(Exam)
                 .order_by(Exam.exam_date.desc(), Exam.id.desc())
                 .limit(10).all())
        for exam in exams:
            candidate = _exam_totals(session, exam.id, class_name)
            candidate = [r for r in candidate if r["total"] is not None]
            if candidate:
                exam_id = exam.id
                rows = candidate
                break
    if not rows:
        raise ValueError("该班暂无可用于分层的考试成绩。")

    tiers = _tier_names(rows)
    # 函数内导入避免循环依赖
    from utils import homework_service

    difficulty_of = {"A": 3, "B": 2, "C": 1}
    base_exam = session.get(Exam, exam_id)
    grade = base_exam.grade if base_exam else None
    homework_ids, name_lists = {}, {}
    for tier in ("A", "B", "C"):
        members = tiers[tier]
        if not members:
            continue
        name_lists[tier] = [m["name"] for m in members]
        title = f"{class_name}·{tier}层作业"
        homework = homework_service.create_homework(
            session, title, homework_type="after_class",
            class_name=class_name, subject=subject, grade=grade)
        spec = _tier_spec(difficulty_of[tier], questions_per_layer)
        homework_service.auto_compose(
            session, homework.id, spec,
            knowledge_points=weak_points or None)
        homework_ids[tier] = homework.id
    session.commit()
    return {
        "exam_id": exam_id,
        "tiers": name_lists,
        "homework_ids": homework_ids,
    }

