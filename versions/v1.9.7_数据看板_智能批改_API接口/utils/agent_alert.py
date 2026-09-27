# -*- coding: utf-8 -*-
"""智能提醒服务（v1.9.5）。

服务层在不超过 3 秒内检测 5 类异常，只取最近 10 次考试，返回 JSON 安全结构：
{alert_type, severity, title, content, suggestion, route, sub, extra, dedup_key}

5 类提醒：
- score_decline      某班某科最近 3 次考试均分持续下降且累计降幅 >5%（红色）
- student_decline    学生最近一次较上次总分下降 >20 分或排名下降 >10 名（红色）
- homework_submission 进行中作业提交率 <60% 且临近截止（黄色）
- progress_delay     本周课程表应上课时数 > 本周已保存教案数（黄色）
- question_bank_low  某知识点已审核题 <5 道（黄色）

提醒状态落 data/agent_alerts.json：
{resolved:{key:时间}, dismissed24:{key:时间}, config:{类型:bool}}
文件缺失自建、损坏回退默认且不覆盖原文件。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import config
from models.models import (
    Exam, Homework, HomeworkSubmission, LessonPlan, Question, Score, Student)
from sqlalchemy import func

ALERTS_PATH = config.DATA_DIR / "agent_alerts.json"

SCORE_DECLINE = "score_decline"
STUDENT_DECLINE = "student_decline"
HOMEWORK_SUBMISSION = "homework_submission"
PROGRESS_DELAY = "progress_delay"
QUESTION_BANK_LOW = "question_bank_low"

ALERT_TYPES = [
    SCORE_DECLINE, STUDENT_DECLINE, HOMEWORK_SUBMISSION,
    PROGRESS_DELAY, QUESTION_BANK_LOW,
]
ALERT_TYPE_LABELS = {
    SCORE_DECLINE: "成绩连续下降",
    STUDENT_DECLINE: "学生成绩骤降",
    HOMEWORK_SUBMISSION: "作业提交率偏低",
    PROGRESS_DELAY: "教学进度落后",
    QUESTION_BANK_LOW: "题库题量不足",
}
SEVERE_TYPES = {SCORE_DECLINE, STUDENT_DECLINE}

RECENT_EXAM_LIMIT = 10
DROP_RATIO = 0.05           # 累计相对降幅阈值
STUDENT_SCORE_DROP = 20.0   # 学生总分下降阈值
STUDENT_RANK_DROP = 10      # 排名下降阈值
SUBMISSION_RATE = 0.60      # 提交率阈值
NEAR_DEADLINE_DAYS = 2      # 临近截止窗口
LOW_QUESTION_COUNT = 5      # 知识点已审核题下限


def default_state() -> dict:
    """提醒状态默认值：5 类开关全开。"""
    return {
        "resolved": {},
        "dismissed24": {},
        "config": {key: True for key in ALERT_TYPES},
    }


def load_state() -> dict:
    """加载提醒状态；缺失自建，损坏回退默认且不覆盖。"""
    path = ALERTS_PATH
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
    state = default_state()
    for bucket in ("resolved", "dismissed24"):
        value = data.get(bucket)
        if isinstance(value, dict):
            state[bucket] = {str(k): str(v) for k, v in value.items()}
    cfg = data.get("config")
    if isinstance(cfg, dict):
        state["config"] = {
            key: bool(cfg.get(key, True)) for key in ALERT_TYPES}
    return state


def save_state(state: dict) -> None:
    """持久化提醒状态，UTF-8、ensure_ascii=False。"""
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_enabled(state: dict, alert_type: str) -> bool:
    """读取某类提醒开关，缺省为开。"""
    return bool(state.get("config", {}).get(alert_type, True))


def check_all_alerts(session) -> list[dict]:
    """跑全部启用的检测，过滤已处理与 24 小时内已显示，返回可见提醒。"""
    state = load_state()
    alerts: list[dict] = []
    checkers = [
        (SCORE_DECLINE, check_score_decline),
        (STUDENT_DECLINE, check_student_decline),
        (HOMEWORK_SUBMISSION, check_homework_submission),
        (PROGRESS_DELAY, check_progress_delay),
        (QUESTION_BANK_LOW, check_question_bank_low),
    ]
    for alert_type, checker in checkers:
        if not is_enabled(state, alert_type):
            continue
        try:
            alerts.extend(checker(session))
        except Exception:
            # 单类检测失败不影响其余提醒。
            continue
    return [a for a in alerts if _is_visible(a["dedup_key"], state)]


def _is_visible(dedup_key: str, state: dict) -> bool:
    """已处理永不再显示；24 小时内已显示的过滤掉。"""
    if dedup_key in state.get("resolved", {}):
        return False
    stamped = state.get("dismissed24", {}).get(dedup_key)
    if stamped and _within_hours(stamped, 24):
        return False
    return True


def _within_hours(stamp: str, hours: int) -> bool:
    """判断时间戳是否在最近 hours 小时内；解析失败按已过期处理。"""
    try:
        ts = datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False
    return datetime.now() - ts < timedelta(hours=hours)


def mark_displayed(alerts: list[dict]) -> None:
    """提醒展示后记时间戳，保证同一提醒 24 小时内只显示一次。"""
    if not alerts:
        return
    state = load_state()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for alert in alerts:
        state["dismissed24"][alert["dedup_key"]] = now
    save_state(state)


def resolve_alert(dedup_key: str) -> None:
    """标记提醒为已处理，之后不再显示。"""
    state = load_state()
    state["resolved"][dedup_key] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    state["dismissed24"].pop(dedup_key, None)
    save_state(state)


def snooze_alert(dedup_key: str) -> None:
    """暂不处理：24 小时内不再显示。"""
    state = load_state()
    state["dismissed24"][dedup_key] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    save_state(state)


# ---------------------------------------------------------------------------
# 检测 1：班级单科成绩连续下降
# ---------------------------------------------------------------------------

def check_score_decline(session) -> list[dict]:
    """某班某科最近 3 次考试均分持续下降且累计相对降幅 >5%。"""
    exams = _recent_exams(session)
    if len(exams) < 3:
        return []
    exam_ids = [e.id for e in exams]
    rows = (session.query(
                Score.exam_id, Student.class_name, Score.subject, Score.score)
            .join(Student, Student.id == Score.student_id)
            .filter(Score.exam_id.in_(exam_ids), Score.score.isnot(None),
                    Student.class_name.isnot(None)).all())
    date_of = {e.id: (e.exam_date or datetime.now().date()) for e in exams}
    # groups[(班级,学科)] = {exam_id: [分数]}
    groups: dict[tuple, dict] = {}
    for exam_id, class_name, subject, score in rows:
        groups.setdefault((class_name, subject), {}).setdefault(
            exam_id, []).append(score)

    alerts = []
    for (class_name, subject), by_exam in groups.items():
        series = []
        for exam_id, scores in by_exam.items():
            series.append((date_of[exam_id], exam_id,
                           round(sum(scores) / len(scores), 2)))
        series.sort(key=lambda x: x[0])
        last3 = series[-3:]
        if len(last3) < 3:
            continue
        avgs = [x[2] for x in last3]
        if not (avgs[0] > avgs[1] > avgs[2]):
            continue
        if avgs[0] <= 0:
            continue
        drop = (avgs[0] - avgs[2]) / avgs[0]
        if drop <= DROP_RATIO:
            continue
        key = f"{SCORE_DECLINE}:{class_name}:{subject}:{last3[-1][1]}"
        alerts.append({
            "alert_type": SCORE_DECLINE,
            "severity": "severe",
            "title": f"{class_name}·{subject}成绩连续三次下降",
            "content": (f"最近三次考试均分 {avgs[0]} → {avgs[1]} → {avgs[2]}，"
                        f"累计下降 {drop * 100:.1f}%。"),
            "suggestion": "分析失分知识点，调整教学节奏并安排专项练习。",
            "route": "📊 学情", "sub": "考试分析",
            "extra": {}, "dedup_key": key,
        })
    return alerts


# ---------------------------------------------------------------------------
# 检测 2：学生个人成绩骤降
# ---------------------------------------------------------------------------

def check_student_decline(session) -> list[dict]:
    """学生最近一次较上次总分下降 >20 分或班内排名下降 >10 名。"""
    exams = _recent_exams(session)
    if len(exams) < 2:
        return []
    exam_ids = [e.id for e in exams]
    rows = (session.query(
                Score.exam_id, Score.student_id, Student.name,
                Student.class_name, Score.subject, Score.score)
            .join(Student, Student.id == Score.student_id)
            .filter(Score.exam_id.in_(exam_ids), Score.score.isnot(None)).all())
    date_of = {e.id: (e.exam_date or datetime.now().date()) for e in exams}
    # totals[student_id] = {exam_id: 总分}；meta 存姓名班级。
    totals: dict[int, dict[int, float]] = {}
    meta: dict[int, tuple] = {}
    # 每场考试每个班的总分列表，用于算班内排名。
    per_exam_class: dict[tuple, list[tuple[int, float]]] = {}
    for exam_id, sid, name, class_name, subject, score in rows:
        totals.setdefault(sid, {})[exam_id] = (
            totals.get(sid, {}).get(exam_id, 0.0) + score)
        meta[sid] = (name, class_name)
    for sid, by_exam in totals.items():
        _, class_name = meta[sid]
        for exam_id, total in by_exam.items():
            per_exam_class.setdefault((exam_id, class_name), []).append(
                (sid, total))
    ranks: dict[tuple[int, int], int] = {}
    for (exam_id, class_name), members in per_exam_class.items():
        members.sort(key=lambda x: x[1], reverse=True)
        last_total, last_rank = None, 0
        for idx, (sid, total) in enumerate(members, start=1):
            if last_total is not None and total == last_total:
                rank = last_rank
            else:
                rank, last_rank, last_total = idx, idx, total
            ranks[(sid, exam_id)] = rank

    alerts = []
    for sid, by_exam in totals.items():
        series = sorted(
            ((date_of[eid], eid, total) for eid, total in by_exam.items()),
            key=lambda x: x[0])
        if len(series) < 2:
            continue
        _, prev_exam, prev_total = series[-2]
        _, last_exam, last_total = series[-1]
        score_drop = prev_total - last_total
        rank_drop = ranks.get((sid, last_exam), 0) - ranks.get(
            (sid, prev_exam), 0)
        if score_drop <= STUDENT_SCORE_DROP and rank_drop <= STUDENT_RANK_DROP:
            continue
        name, class_name = meta[sid]
        reasons = []
        if score_drop > STUDENT_SCORE_DROP:
            reasons.append(f"总分下降 {score_drop:.0f} 分")
        if rank_drop > STUDENT_RANK_DROP:
            reasons.append(f"班内排名下降 {rank_drop} 名")
        key = f"{STUDENT_DECLINE}:{sid}:{last_exam}"
        alerts.append({
            "alert_type": STUDENT_DECLINE,
            "severity": "severe",
            "title": f"学生{name}成绩骤降",
            "content": (f"{name}（{class_name or '未分班'}）最近一次考试"
                        f"总分 {last_total:.0f}，{'，'.join(reasons)}。"),
            "suggestion": "尽快了解情况，进行个别谈话并安排针对性辅导。",
            "route": "📊 学情", "sub": "学生画像",
            "extra": {"profile_student_id": sid},
            "dedup_key": key,
        })
    return alerts


# ---------------------------------------------------------------------------
# 检测 3：作业提交率偏低
# ---------------------------------------------------------------------------

def check_homework_submission(session) -> list[dict]:
    """进行中、有班级、临近截止的作业提交率 <60%。"""
    now = datetime.now()
    window_end = now + timedelta(days=NEAR_DEADLINE_DAYS)
    homeworks = (session.query(Homework)
                 .filter(Homework.is_template.is_(False),
                         Homework.status == "pending",
                         Homework.due_date.isnot(None),
                         Homework.due_date <= window_end,
                         Homework.class_name.isnot(None)).all())
    alerts = []
    for hw in homeworks:
        roster = (session.query(func.count(Student.id))
                  .filter(Student.class_name == hw.class_name).scalar()) or 0
        if roster <= 0:
            continue
        submitted = (session.query(func.count(func.distinct(
                        HomeworkSubmission.student_name)))
                     .filter(HomeworkSubmission.homework_id == hw.id).scalar()) or 0
        rate = submitted / roster
        if rate >= SUBMISSION_RATE:
            continue
        key = f"{HOMEWORK_SUBMISSION}:{hw.id}"
        due = hw.due_date.strftime("%m-%d %H:%M")
        alerts.append({
            "alert_type": HOMEWORK_SUBMISSION,
            "severity": "warning",
            "title": f"作业《{hw.name}》提交率偏低",
            "content": (f"截止 {due}，已交 {submitted}/{roster} 人，"
                        f"提交率 {rate * 100:.0f}%。"),
            "suggestion": "提醒未交学生尽快提交，必要时延长截止时间。",
            "route": "📝 学业测评", "sub": "作业管理",
            "extra": {"hw_open_id": hw.id},
            "dedup_key": key,
        })
    return alerts


# ---------------------------------------------------------------------------
# 检测 4：本周教学进度落后
# ---------------------------------------------------------------------------

def check_progress_delay(session) -> list[dict]:
    """本周课程表应上课时数 > 本周已保存教案数时提醒。"""
    from utils import schedule_service
    from utils import calendar_service as cal_svc
    today = datetime.now().date()
    week_monday, week_sunday = cal_svc.week_range(today)
    planned = len([
        e for e in schedule_service.load_schedule()["entries"]
        if week_monday.weekday() <= e["weekday"] <= week_sunday.weekday()])
    if planned <= 0:
        return []
    saved = (session.query(func.count(LessonPlan.id))
             .filter(LessonPlan.created_at >= week_monday,
                     LessonPlan.created_at < week_sunday).scalar()) or 0
    if saved >= planned:
        return []
    key = f"{PROGRESS_DELAY}:{week_monday.strftime('%Y%m%d')}"
    return [{
        "alert_type": PROGRESS_DELAY,
        "severity": "warning",
        "title": "本周教学进度可能落后",
        "content": f"本周应上 {planned} 节课，目前只保存了 {saved} 份教案。",
        "suggestion": "尽快完成剩余课时的备课，避免临堂无教案。",
        "route": "📚 备课", "sub": "AI 备课",
        "extra": {}, "dedup_key": key,
    }]


# ---------------------------------------------------------------------------
# 检测 5：知识点已审核题不足
# ---------------------------------------------------------------------------

def check_question_bank_low(session) -> list[dict]:
    """某学科存在已审核题少于 5 道的知识点。"""
    questions = (session.query(Question)
                 .filter(Question.status == "approved").all())
    # counts[subject] = {知识点: 题数}
    counts: dict[str, dict[str, int]] = {}
    for q in questions:
        subject = q.subject or "数学"
        try:
            kps = json.loads(q.knowledge_points or "[]")
            if not isinstance(kps, list) or not kps:
                kps = ["未标注"]
        except (json.JSONDecodeError, TypeError):
            kps = ["未标注"]
        bucket = counts.setdefault(subject, {})
        for kp in kps:
            kp = str(kp).strip() or "未标注"
            bucket[kp] = bucket.get(kp, 0) + 1

    alerts = []
    for subject, kp_counts in counts.items():
        low = sorted(
            kp for kp, n in kp_counts.items() if n < LOW_QUESTION_COUNT)
        if not low:
            continue
        key = f"{QUESTION_BANK_LOW}:{subject}:{','.join(low)}"
        labels = "、".join(f"{kp}（{kp_counts[kp]}道）" for kp in low[:6])
        alerts.append({
            "alert_type": QUESTION_BANK_LOW,
            "severity": "warning",
            "title": f"{subject}题库部分知识点题量不足",
            "content": f"以下知识点已审核题少于 {LOW_QUESTION_COUNT} 道：{labels}。",
            "suggestion": "用 AI 出题补充这些知识点，补题默认待审核。",
            "route": "📚 备课", "sub": "题库管理",
            "extra": {}, "dedup_key": key,
        })
    return alerts


def _recent_exams(session) -> list[Exam]:
    """按考试日期升序取最近 10 次考试。"""
    exams = (session.query(Exam)
             .order_by(Exam.exam_date.asc(), Exam.id.asc())
             .limit(RECENT_EXAM_LIMIT).all())
    return exams

