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
STACK_LIMIT = 50

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


def _row_dict(model, row) -> dict:
    """把 ORM 行转成普通字典；已经是 dict 时直接拷贝，兼容不同调用口径。"""
    if isinstance(row, dict):
        return dict(row)
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


def record_row_change(session, action_type: str, model, label: str,
                      before=None, after=None) -> None:
    """记录单行新增、编辑或删除。

    before/after 为 ORM 行；新增只有 after，删除只有 before，编辑两者都有。
    session 参数仅为保持调用口径一致。
    """
    operation = {"add": "add", "edit": "edit", "update": "edit",
                 "delete": "delete"}.get(action_type)
    if operation is None:
        raise ValueError("action_type 只支持 add/edit/update/delete。")
    tables: dict[str, list[dict]] = {}
    if before is not None:
        tables.setdefault(model.__tablename__, []).append(
            _row_dict(model, before))
    if after is not None:
        tables.setdefault("__after__", []).append(
            _row_dict(model, after))
        tables["__after_table__"] = [model.__tablename__]
    action = {
        "action_type": action_type, "label": label,
        "tables": tables, "operation": operation}
    _undo_stack.append(action)
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
    if action.get("operation", "delete") == "delete":
        _restore_tables(session, action["tables"])
        _restore_question_child_links(session, action["tables"])
    else:
        _undo_row_change(session, action)
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
    if action.get("operation", "delete") == "delete":
        _delete_restored(session, action["tables"])
    else:
        _redo_row_change(session, action)
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

def _change_model(action: dict):
    """返回行变更对应的模型。"""
    tables = action["tables"]
    if action.get("operation") == "add":
        name = tables.get("__after_table__", [""])[0]
    else:
        normal = [k for k in tables if not k.startswith("__")]
        name = normal[0] if normal else ""
    return _TABLE_TO_MODEL[name]


def _replace_row(session, model, row: dict) -> None:
    """用给定字典替换目标行；不存在则插入。"""
    pk_name = _PRIMARY[model]
    current = session.get(model, row[pk_name])
    if current is not None:
        session.delete(current)
        session.flush()
    session.add(model(**row))
    session.flush()


def _delete_row(session, model, row: dict) -> None:
    """按主键删除一行。"""
    current = session.get(model, row[_PRIMARY[model]])
    if current is not None:
        session.delete(current)
        session.flush()


def _undo_row_change(session, action: dict) -> None:
    """撤销新增=删除；撤销编辑=用操作前行替换。"""
    model = _change_model(action)
    if action.get("operation") == "add":
        for row in action["tables"].get("__after__", []):
            _delete_row(session, model, row)
        return
    before_name = [k for k in action["tables"] if not k.startswith("__")][0]
    for row in action["tables"][before_name]:
        _replace_row(session, model, row)


def _redo_row_change(session, action: dict) -> None:
    """重做新增/编辑/删除：新增编辑用操作后行替换，删除重新按主键删除。"""
    model = _change_model(action)
    if action.get("operation") == "delete":
        normal = [k for k in action["tables"] if not k.startswith("__")]
        for _name in normal:
            for row in action["tables"][_name]:
                _delete_row(session, model, row)
        return
    for row in action["tables"].get("__after__", []):
        _replace_row(session, model, row)

