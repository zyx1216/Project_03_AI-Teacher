# -*- coding: utf-8 -*-
"""v3.2.0 批量操作服务。"""
from __future__ import annotations
import io
import json
import zipfile
from utils import grading_service, homework_score_service, homework_service, lesson_service, question_service


def assign_homeworks_to_classes(session, homework_ids, class_names, due_date=None):
    """为每个班级复制独立作业，避免多班共用同一成绩记录。"""
    created = []
    for homework_id in homework_ids:
        source = session.get(homework_service.Homework, int(homework_id))
        if source is None:
            continue
        for class_name in class_names:
            clone = homework_service.duplicate_homework(session, source.id)
            homework_service.update_homework(
                session, clone.id, class_name=class_name,
                due_date=due_date, status="pending")
            created.append(clone.id)
    session.flush()
    return created


def export_homeworks_zip(session, homework_ids, with_answer=False,
                         progress=None):
    """批量导出作业/试卷 ZIP；progress(done, total) 可选，用于页面进度条。"""
    ids = [int(x) for x in dict.fromkeys(homework_ids or [])]
    if progress is None:
        return homework_service.export_homeworks_zip(
            session, ids, with_answer=with_answer)
    out = io.BytesIO()
    total = max(1, len(ids))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, hid in enumerate(ids, start=1):
            one = homework_service.export_homeworks_zip(
                session, [hid], with_answer=with_answer)
            with zipfile.ZipFile(io.BytesIO(one)) as inner:
                for name in inner.namelist():
                    zf.writestr(name, inner.read(name))
            progress(index, total)
    return out.getvalue()


def export_lessons_zip(session, lesson_ids, progress=None):
    """批量导出教案 ZIP；progress(done, total) 可选。"""
    ids = [int(x) for x in dict.fromkeys(lesson_ids or [])]
    total = max(1, len(ids))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, lesson_id in enumerate(ids, start=1):
            lesson = session.get(lesson_service.LessonPlan, int(lesson_id))
            if lesson is None:
                continue
            data = lesson_service.export_word(lesson, lesson_service.load_plan(lesson))
            zf.writestr(f"{lesson.title}_{lesson.id}.docx", data)
            if progress:
                progress(index, total)
    return out.getvalue()


def export_questions_zip(session, question_ids, fmt="json", progress=None):
    """批量导出题目 ZIP；progress(done, total) 可选。"""
    ids = [int(x) for x in dict.fromkeys(question_ids or [])]
    total = max(1, len(ids))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, qid in enumerate(ids, start=1):
            row = session.get(question_service.Question, int(qid))
            if row is None:
                continue
            if fmt == "json":
                payload = {"id": row.id, "content": row.content,
                           "question_type": row.question_type,
                           "difficulty": row.difficulty,
                           "knowledge_points": row.knowledge_points,
                           "answer": row.answer, "analysis": row.analysis}
                zf.writestr(f"question_{row.id}.json",
                            json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                zf.writestr(f"question_{row.id}.txt",
                            f"{row.content}\n\n答案：{row.answer}\n解析：{row.analysis or ''}")
    return out.getvalue()


def batch_grade_objective(session, homework_ids):
    """批量批改客观题并汇总结果；失败项逐条返回，不中断整批。"""
    results = []
    for homework_id in homework_ids:
        try:
            grade_result = grading_service.grade_homework_objective(
                session, int(homework_id), force=True)
            analysis = homework_score_service.analyze_homework(
                session, int(homework_id))
            results.append({"homework_id": int(homework_id), "status": "success",
                            "grade": grade_result, "analysis": analysis})
        except Exception as exc:  # noqa: BLE001
            results.append({"homework_id": int(homework_id), "status": "failed",
                            "error": str(exc)})
    return results


def delete_items(session, model, item_ids):
    count = 0
    for item_id in item_ids:
        row = session.get(model, int(item_id))
        if row is not None:
            session.delete(row)
            count += 1
    session.flush()
    return count
