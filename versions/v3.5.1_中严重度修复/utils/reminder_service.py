# -*- coding: utf-8 -*-
"""智能提醒服务（v3.3.0）。

在 agent_alert 的异常检测之外，按教学数据实时计算三类提醒：
- homework 作业提醒：临近截止时列出未提交学生，可生成催交文案；
- teaching 教学提醒：教学进度标记为落后的章节；
- student  学生预警：连续3次考试下降、连续2次及以上未交作业。

开关和已处理签名存 reminder_settings 表：每个类型一行，
handled_json 存已处理提醒签名数组。所有函数收外部 session。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func

from models.models import (
    Homework, HomeworkSubmission, ReminderSettings, Score, Student,
    TeachingProgress,
)

REMINDER_TYPES = ("homework", "teaching", "student")
TYPE_LABELS = {"homework": "作业提醒", "teaching": "教学提醒", "student": "学生预警"}

NEAR_DEADLINE_DAYS = 2     # 截止前多少天开始催
NO_SUBMIT_LIMIT = 2        # 连续未交多少次触发学生预警


# ---------------------------------------------------------------------------
# 设置与已处理状态
# ---------------------------------------------------------------------------

def _get_setting(session, reminder_type: str) -> ReminderSettings:
    row = (session.query(ReminderSettings)
           .filter(ReminderSettings.user_id == "teacher",
                   ReminderSettings.reminder_type == reminder_type).first())
    if row is None:
        row = ReminderSettings(user_id="teacher",
                               reminder_type=reminder_type)
        session.add(row)
        session.flush()
    return row


def save_setting(session, reminder_type: str, *, enabled: bool | None = None,
                 frequency: str | None = None) -> ReminderSettings:
    """保存某类提醒的开关和频率；不传的字段保持原值。"""
    row = _get_setting(session, reminder_type)
    if enabled is not None:
        row.enabled = bool(enabled)
    if frequency:
        row.frequency = str(frequency)
    session.flush()
    return row


def is_enabled(session, reminder_type: str) -> bool:
    return bool(_get_setting(session, reminder_type).enabled)


def _handled_signatures(session, reminder_type: str) -> set[str]:
    raw = _get_setting(session, reminder_type).handled_json
    try:
        data = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return set()
    return {str(x) for x in data} if isinstance(data, list) else set()


def mark_handled(session, signature: str) -> None:
    """把提醒签名记入对应类型的已处理列表。"""
    reminder_type = signature.split(":", 1)[0]
    if reminder_type not in REMINDER_TYPES:
        return
    row = _get_setting(session, reminder_type)
    sigs = sorted(_handled_signatures(session, reminder_type) | {signature})
    row.handled_json = json.dumps(sigs, ensure_ascii=False)
    session.flush()


# ---------------------------------------------------------------------------
# 三类提醒检测
# ---------------------------------------------------------------------------

def list_reminders(session) -> list[dict]:
    """汇总启用且未处理的全部提醒，按类型分组返回。"""
    result: list[dict] = []
    if is_enabled(session, "homework"):
        result.extend(_homework_reminders(session))
    if is_enabled(session, "teaching"):
        result.extend(_teaching_reminders(session))
    if is_enabled(session, "student"):
        result.extend(_student_reminders(session))
    return result


def _homework_reminders(session) -> list[dict]:
    """临近截止或已过期、还有学生没交的作业。"""
    window_end = datetime.now() + timedelta(days=NEAR_DEADLINE_DAYS)
    homeworks = (session.query(Homework)
                 .filter(Homework.status == "pending",
                         Homework.class_name.isnot(None),
                         Homework.due_date.isnot(None),
                         Homework.due_date <= window_end).all())
    handled = _handled_signatures(session, "homework")
    reminders = []
    for hw in homeworks:
        signature = f"homework:{hw.id}"
        if signature in handled:
            continue
        roster = (session.query(Student)
                  .filter(Student.class_name == hw.class_name).all())
        submitted = {
            name for (name,) in session.query(
                func.distinct(HomeworkSubmission.student_name))
            .filter(HomeworkSubmission.homework_id == hw.id).all()}
        missing = sorted(s.name for s in roster if s.name not in submitted)
        if not missing:
            continue
        total = len(roster)
        reminders.append({
            "reminder_type": "homework",
            "signature": signature,
            "title": f"作业《{hw.name}》快到截止时间",
            "content": (f"已交 {total - len(missing)}/{total} 人，"
                        f"还剩：{'、'.join(missing)}"),
            "missing": missing,
            "submit_rate": (total - len(missing)) / total if total else 0.0,
            "hw_id": hw.id,
            "class_name": hw.class_name,
        })
    return reminders


def _teaching_reminders(session) -> list[dict]:
    """进度状态为 lag 的章节。"""
    handled = _handled_signatures(session, "teaching")
    rows = (session.query(TeachingProgress)
            .filter(TeachingProgress.status == "lag",
                    TeachingProgress.chapter.isnot(None)).all())
    reminders = []
    for row in rows:
        signature = f"teaching:{row.subject}:{row.grade}:{row.week_number}"
        if signature in handled:
            continue
        reminders.append({
            "reminder_type": "teaching",
            "signature": signature,
            "title": f"{row.chapter} 教学进度落后",
            "content": (f"第 {row.week_number} 周计划内容「{row.chapter}」"
                        "尚未完成，建议尽快安排补课或调整后续计划。"),
        })
    return reminders


def _student_reminders(session) -> list[dict]:
    """成绩连续下降 + 连续未交作业。"""
    handled = _handled_signatures(session, "student")
    reminders: list[dict] = []

    # 1) 最近3次考试总分严格递减
    score_rows = (session.query(Score, Student)
                  .join(Student, Score.student_id == Student.id).all())
    # exam_totals[student_id] = [(exam_id, 总分)]，后按考试日期排序
    exam_date: dict[int, object] = {}
    totals: dict[int, dict[int, float]] = {}
    for score, student in score_rows:
        totals.setdefault(student.id, {}).setdefault(
            score.exam_id, 0.0)
        totals[student.id][score.exam_id] += float(score.score or 0)
        from models.models import Exam
        exam = session.get(Exam, score.exam_id)
        exam_date[score.exam_id] = exam.exam_date if exam else None
    for student_id, by_exam in totals.items():
        ordered = sorted(by_exam.items(),
                         key=lambda kv: exam_date.get(kv[0]) or 0)
        if len(ordered) < 3:
            continue
        last3 = [value for _, value in ordered[-3:]]
        if last3[0] > last3[1] > last3[2]:
            signature = f"student:{student_id}:score_decline"
            if signature not in handled:
                student = session.get(Student, student_id)
                reminders.append({
                    "reminder_type": "student",
                    "signature": signature,
                    "reason": "score_decline",
                    "student_id": student_id,
                    "name": student.name if student else "",
                    "title": f"{student.name if student else ''}成绩连续下降",
                    "content": (f"最近3次考试总分 {last3[0]:.0f} → "
                                f"{last3[1]:.0f} → {last3[2]:.0f}，"
                                "建议尽快沟通了解情况。"),
                    "missing_count": 0,
                })

    # 2) 连续未交作业达到次数
    pending_hws = (session.query(Homework)
                   .filter(Homework.status == "pending",
                           Homework.class_name.isnot(None)).all())
    # miss_map[student_name] = 连续未交份数（从最近的作业往前数）
    roster_by_class: dict[str, list[Student]] = {}
    for hw in pending_hws:
        roster_by_class.setdefault(
            hw.class_name,
            session.query(Student)
            .filter(Student.class_name == hw.class_name).all())
    submitted_by_hw = {
        hw.id: {name for (name,) in session.query(
            func.distinct(HomeworkSubmission.student_name))
            .filter(HomeworkSubmission.homework_id == hw.id).all()}
        for hw in pending_hws}
    miss_counts: dict[str, int] = {}
    student_ids: dict[str, int] = {}
    for hw in sorted(pending_hws, key=lambda h: h.id, reverse=True):
        for stu in roster_by_class.get(hw.class_name, []):
            if stu.name not in submitted_by_hw[hw.id]:
                miss_counts[stu.name] = miss_counts.get(stu.name, 0) + 1
                student_ids[stu.name] = stu.id
            else:
                # 交过一次，连续性中断
                miss_counts.pop(stu.name, None)
    for name, count in miss_counts.items():
        if count < NO_SUBMIT_LIMIT:
            continue
        sid = student_ids.get(name)
        signature = f"student:{sid}:no_submit:{count}"
        if signature in handled:
            continue
        reminders.append({
            "reminder_type": "student",
            "signature": signature,
            "reason": "no_submit",
            "student_id": sid,
            "name": name,
            "title": f"{name}连续{count}次未交作业",
            "content": f"{name} 已连续 {count} 次作业没有提交，建议联系家长。",
            "missing_count": count,
        })
    return reminders


def reminder_text(reminder: dict) -> str:
    """生成可复制发给学生/家长的提醒文案。"""
    if reminder["reminder_type"] == "homework":
        names = "、".join(reminder["missing"])
        return (f"提醒：{names} 同学，作业《{__hw_name(reminder)}》"
                "还没有提交，请尽快完成并上交。")
    if reminder["reminder_type"] == "teaching":
        return reminder["content"]
    return reminder["content"]


def __hw_name(reminder: dict) -> str:
    # title 形如 作业《xxx》快到截止时间，直接从 content 拿不到名字，
    # 调用方一般先有作业对象；这里用占位从标题提取。
    title = reminder.get("title", "")
    if "《" in title and "》" in title:
        return title.split("《", 1)[1].split("》", 1)[0]
    return "本次作业"