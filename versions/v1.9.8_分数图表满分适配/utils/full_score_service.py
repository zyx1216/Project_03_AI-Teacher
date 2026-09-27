# -*- coding: utf-8 -*-
"""满分与得分率统一服务。

集中处理考试、作业的满分读取，以及跨满分比较时使用的得分率口径。
旧数据缺配置时按年级默认值兜底，仍找不到就按 100 分处理。
"""

from __future__ import annotations

import json

from models.models import Exam, HomeworkQuestion

_PRIMARY_SUBJECTS = ("语文", "数学", "英语")
_OTHER_SUBJECTS = ("物理", "化学", "生物", "政治", "历史", "地理")
_ALL_SUBJECTS = _PRIMARY_SUBJECTS + _OTHER_SUBJECTS


def _grade_stage(grade: str | None) -> str:
    """识别小学、初中、高中；无法识别返回空字符串。"""
    text = str(grade or "").strip()
    if not text:
        return ""
    if "小学" in text:
        return "primary"
    if "初中" in text:
        return "junior"
    if "高中" in text:
        return "senior"
    if any(x in text for x in ("一年级", "二年级", "三年级", "四年级", "五年级", "六年级")):
        return "primary"
    if any(x in text for x in ("初一", "初二", "初三", "七年级", "八年级", "九年级")):
        return "junior"
    if any(x in text for x in ("高一", "高二", "高三")):
        return "senior"
    return ""


def get_grade_default_full_scores(grade: str | None) -> dict[str, float]:
    """按年级返回默认满分；未知年级给 9 科 100 分。"""
    stage = _grade_stage(grade)
    if stage == "primary":
        scores = {subject: 100.0 for subject in _PRIMARY_SUBJECTS}
    elif stage in {"junior", "senior"}:
        scores = {subject: 150.0 for subject in _PRIMARY_SUBJECTS}
        scores.update({subject: 100.0 for subject in _OTHER_SUBJECTS})
    else:
        scores = {subject: 100.0 for subject in _ALL_SUBJECTS}
    return scores


def _safe_json_object(raw: str | None) -> dict:
    """读取 JSON 对象；损坏或类型不对时返回空字典。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_exam_full_scores(session, exam_id: int) -> dict[str, float]:
    """获取一场考试的各科满分。

    优先使用考试保存的 full_scores；缺项用考试年级默认值，再缺则按 100。
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return {subject: 100.0 for subject in _ALL_SUBJECTS}

    defaults = get_grade_default_full_scores(exam.grade)
    saved = _safe_json_object(exam.full_scores)
    result = dict(defaults)
    for subject, raw_full in saved.items():
        name = str(subject).strip()
        if not name:
            continue
        try:
            full = float(raw_full)
        except (TypeError, ValueError):
            full = defaults.get(name, 100.0)
        result[name] = full if full > 0 else defaults.get(name, 100.0)
    return result


def get_subject_full_score(session, subject: str, exam_id: int | None = None,
                           grade: str | None = None) -> float:
    """获取单个学科满分；优先级为考试配置、年级默认、100。"""
    name = str(subject or "").strip()
    if not name:
        return 100.0
    if exam_id is not None:
        return get_exam_full_scores(session, exam_id).get(name, 100.0)
    return get_grade_default_full_scores(grade).get(name, 100.0)


def get_homework_full_score(session, homework_id: int) -> float:
    """获取作业满分：优先汇总作业内题目分值，其次登记总分，最后 100。"""
    rows = (session.query(HomeworkQuestion.score)
            .filter(HomeworkQuestion.homework_id == homework_id).all())
    values = []
    for (score,) in rows:
        if score is not None:
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            if value > 0:
                values.append(value)
    if values:
        return round(sum(values), 2)

    from models.models import Homework
    hw = session.get(Homework, homework_id)
    if hw is not None and hw.total_score is not None:
        try:
            total = float(hw.total_score)
        except (TypeError, ValueError):
            total = 0.0
        if total > 0:
            return total
    return 100.0


def calc_rate(score: float | None, full_score: float | None) -> float | None:
    """计算百分制得分率；空分数、非法满分返回 None。"""
    if score is None or full_score is None:
        return None
    try:
        value = float(score)
        full = float(full_score)
    except (TypeError, ValueError):
        return None
    if full <= 0:
        return None
    return round(value / full * 100.0, 1)


def rate_bands() -> list[dict]:
    """返回标准得分率分段。"""
    return [
        {"label": "不及格", "low": 0.0, "high": 60.0},
        {"label": "及格", "low": 60.0, "high": 70.0},
        {"label": "中等", "low": 70.0, "high": 80.0},
        {"label": "良好", "low": 80.0, "high": 90.0},
        {"label": "优秀", "low": 90.0, "high": 10**9},
    ]
