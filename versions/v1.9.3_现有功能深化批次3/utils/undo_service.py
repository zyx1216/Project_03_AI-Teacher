# -*- coding: utf-8 -*-
"""撤销 / 重做服务（v1.9.0）。

覆盖操作：删除题目、教案、作业、学生，批量修改题目，成绩导入。
口径：
- 操作前把受影响表的整行（含级联关联）快照成 dict；
- 删除按原始主键恢复；重做重新执行该操作；
- 撤销/重做栈各最多 10 步；新操作清空 redo 栈；
- 一级页面切换时由 app.py 调 clear()。

状态只保存在当前进程内存里（Streamlit session_state 不适合存 ORM 行），
符合“只在当前会话内撤销”的使用预期。
"""

from __future__ import annotations

from models.models import (
    Question, LessonPlan, Homework, Student,
    HomeworkQuestion, HomeworkScore, HomeworkAnswer, Score,
)

# 每个动作：{"action_type","label","tables":{表名:[行dict,...]}}
_undo_stack: list[dict] = []
_redo_stack: list[dict] = []
STACK_LIMIT = 10

# 需要级联快照的关联表（删除主记录时一并保存）
_CASCADE = {
    "homework": [
        (HomeworkQuestion, {"homework_id"}),
        (HomeworkScore, {"homework_id"}),
        (HomeworkAnswer, {"homework_id"}),
    ],
    "question": [
        (HomeworkQuestion, {"question_id"}),
        (HomeworkAnswer, {"question_id"}),
    ],
    "student": [
        (HomeworkScore, {"student_id"}),
        (HomeworkAnswer, {"student_id"}),
        (Score, {"student_id"}),
    ],
}

_PRIMARY = {
    Question: "id", LessonPlan: "id", Homework: "id", Student: "id",
    HomeworkQuestion: "id", HomeworkScore: "id", HomeworkAnswer: "id",
    Score: "id",
}
_TABLE_TO_MODEL = {
    model.__tablename__: model
    for model in (Question, LessonPlan, Homework, Student,
                  HomeworkQuestion, HomeworkScore, HomeworkAnswer, Score)
}


def can_undo() -> bool:
    return bool(_undo_stack)


def can_redo() -> bool:
    return bool(_redo_stack)


def clear() -> None:
    """清空撤销/重做栈（一级页面切换时调用）。"""
    _undo_stack.clear()
    _redo_stack.clear()


def record(session, action_type: str, payload: dict, label: str) -> None:
    """登记一个可撤销动作。

    payload 两种形式：
    - {"snapshot": {model或表名: [行dict,...]}}：已自己快照好；
    - {"target": (model, 主键)}：record 负责连级联一起快照。
    """
    tables: dict[str, list[dict]] = {}
    if "snapshot" in payload:
        for key, rows in payload["snapshot"].items():
            name = key.__tablename__ if hasattr(key, "__tablename__") else str(key)
            tables[name] = [dict(r) for r in rows]
    elif "target" in payload:
        model, pk = payload["target"]
        _snapshot_target(session, model, pk, tables)
    else:
        raise ValueError("undo record 需要 snapshot 或 target。")

    _undo_stack.append({
        "action_type": action_type, "label": label, "tables": tables})
    if len(_undo_stack) > STACK_LIMIT:
        del _undo_stack[0]
    _redo_stack.clear()


def _snapshot_target(session, model, pk, tables):
    rows = session.query(model).filter(
        getattr(model, _PRIMARY[model]) == pk).all()
    tables.setdefault(model.__tablename__, []).extend(
        {c.name: _col_value(getattr(r, c.name)) for c in model.__table__.columns}
        for r in rows)
    cascade_key = {
        Question: "question", LessonPlan: None, Homework: "homework",
        Student: "student",
    }.get(model)
    if cascade_key and cascade_key in _CASCADE:
        for rel_model, fk_names in _CASCADE[cascade_key]:
            for fk in fk_names:
                rel_rows = session.query(rel_model).filter(
                    getattr(rel_model, fk) == pk).all()
                tables.setdefault(rel_model.__tablename__, []).extend(
                    {c.name: _col_value(getattr(r, c.name))
                     for c in rel_model.__table__.columns}
                    for r in rel_rows)
    if model is Question:
        # 记录被改挂的变式子题，撤销父题删除后恢复原父子关系。
        child_rows = (session.query(Question)
                      .filter(Question.parent_question_id == pk).all())
        tables.setdefault("__question_child_links__", []).extend(
            {c.name: _col_value(getattr(r, c.name))
             for c in Question.__table__.columns}
            for r in child_rows)


def _col_value(value):
    """把 ORM 列值转成可安全重放的普通值；datetime 保持原样（SQLite 可写）。"""
    return value


def undo(session) -> dict:
    """撤销最近一步：把快照行按原主键插回；返回 {label}。"""
    if not _undo_stack:
        raise ValueError("没有可撤销的操作。")
    action = _undo_stack.pop()
    _restore_tables(session, action["tables"])
    _restore_question_child_links(session, action["tables"])
    _redo_stack.append(action)
    return {"label": action["label"], "action_type": action["action_type"]}



def _restore_question_child_links(session, tables: dict):
    """恢复删除父题前的变式父子链接。"""
    for row in tables.get("__question_child_links__", []):
        child = session.get(Question, row["id"])
        if child is not None:
            child.parent_question_id = row.get("parent_question_id")
    session.flush()

def redo(session) -> dict:
    """重做：重新删除当前快照里的主记录（关联已级联）。"""
    if not _redo_stack:
        raise ValueError("没有可重做的操作。")
    action = _redo_stack.pop()
    # 重做 = 再删一次主表记录；按表依赖顺序，先删关联再删主表。
    _delete_restored(session, action["tables"])
    _undo_stack.append(action)
    return {"label": action["label"], "action_type": action["action_type"]}


def _restore_tables(session, tables: dict):
    """按“先主表后关联”的顺序把行插回（关联有外键）。"""
    order = ["students", "lesson_plans", "homeworks", "questions",
             "scores", "homework_questions", "homework_scores", "homework_answers"]
    for name in sorted(tables, key=lambda n: order.index(n) if n in order else 99):
        if name.startswith("__"):
            continue
        model = _TABLE_TO_MODEL[name]
        for row in tables[name]:
            if session.get(model, row[_PRIMARY[model]]) is None:
                session.add(model(**row))
    session.flush()


def _delete_restored(session, tables: dict):
    """重做删除：先删关联表，再删主表。"""
    main_order = ["homework_answers", "homework_scores", "homework_questions",
                  "scores", "questions", "homeworks", "lesson_plans", "students"]
    for name in sorted(tables, key=lambda n: main_order.index(n) if n in main_order else -1):
        if name.startswith("__"):
            continue
        model = _TABLE_TO_MODEL[name]
        pk_name = _PRIMARY[model]
        for row in tables[name]:
            obj = session.get(model, row[pk_name])
            if obj is not None:
                session.delete(obj)
    session.flush()
