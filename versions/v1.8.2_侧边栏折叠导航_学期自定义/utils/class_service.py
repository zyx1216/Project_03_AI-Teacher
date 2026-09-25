# -*- coding: utf-8 -*-
"""班级名单配置与批量调班服务。

班级仍然不是独立数据表：历史班级来自 students.class_name，空班级用
data/class_names.json 保留。这样能支持“先建班级、后导入学生”，同时保持
13 张数据表不变。
"""

from __future__ import annotations

import json
from typing import Iterable

import config
from models.models import Homework, Student

CLASS_NAMES_PATH = config.DATA_DIR / "class_names.json"
MAX_CLASS_NAME_LEN = 50


def _clean_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        raise ValueError("班级名称不能为空。")
    if len(text) > MAX_CLASS_NAME_LEN:
        raise ValueError(f"班级名称不能超过 {MAX_CLASS_NAME_LEN} 个字。")
    return text


def default_config() -> dict:
    return {"classes": []}


def _normalize_config(data) -> dict:
    """读取配置时容错：非法项忽略，去重并排序；损坏文件由调用方处理。"""
    if not isinstance(data, dict) or not isinstance(data.get("classes"), list):
        return default_config()
    names = []
    seen = set()
    for item in data["classes"]:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in seen and len(name) <= MAX_CLASS_NAME_LEN:
            names.append(name)
            seen.add(name)
    return {"classes": sorted(names)}


def save_configured_classes(names: Iterable[str]) -> None:
    """保存完整班级名单。重复名在这里直接拒绝，避免静默写错配置。"""
    result = []
    seen = set()
    for item in names:
        name = _clean_name(item)
        if name in seen:
            raise ValueError(f"班级已存在：{name}")
        seen.add(name)
        result.append(name)
    CLASS_NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLASS_NAMES_PATH.write_text(
        json.dumps({"classes": sorted(result)}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def load_configured_classes() -> list[str]:
    """读取预设班级；文件缺失时自动创建，JSON 损坏时回退空名单且不覆盖。"""
    try:
        data = json.loads(CLASS_NAMES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        save_configured_classes([])
        return []
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        return []
    return _normalize_config(data).get("classes", [])


def _student_classes(session) -> set[str]:
    rows = (session.query(Student.class_name)
            .filter(Student.class_name.isnot(None), Student.class_name != "")
            .distinct().all())
    return {r[0].strip() for r in rows if r[0] and r[0].strip()}


def _homework_classes(session) -> set[str]:
    rows = (session.query(Homework.class_name)
            .filter(Homework.is_template.is_(False),
                    Homework.class_name.isnot(None),
                    Homework.class_name != "")
            .distinct().all())
    return {r[0].strip() for r in rows if r[0] and r[0].strip()}


def list_class_names(session) -> list[str]:
    """预设空班级 + 学生表/普通作业里已经出现的班级。"""
    names = set(load_configured_classes())
    names.update(_student_classes(session))
    names.update(_homework_classes(session))
    return sorted(names)


def class_usage(session, class_name: str) -> dict:
    """统计班级当前被多少学生和普通作业引用，供删除前判断。"""
    name = _clean_name(class_name)
    student_count = session.query(Student).filter(Student.class_name == name).count()
    homework_count = (session.query(Homework)
                      .filter(Homework.is_template.is_(False),
                              Homework.class_name == name).count())
    return {"students": student_count, "homeworks": homework_count}


def add_class(session, name: str) -> None:
    """新增一个预设班级；学生或作业里已有同名班级也算重复。"""
    name = _clean_name(name)
    if name in list_class_names(session):
        raise ValueError(f"班级已存在：{name}")
    names = load_configured_classes()
    names.append(name)
    save_configured_classes(names)


def rename_class(session, old_name: str, new_name: str) -> int:
    """重命名班级，同步学生、作业（含模板）和 JSON 预设名单，返回更新的学生数。"""
    old_name = _clean_name(old_name)
    new_name = _clean_name(new_name)
    if old_name == new_name:
        raise ValueError("新班级名称和原名称相同。")

    conflict_student = (session.query(Student)
                        .filter(Student.class_name == new_name).first())
    conflict_hw = (session.query(Homework)
                   .filter(Homework.class_name == new_name).first())
    if conflict_student is not None or conflict_hw is not None or new_name in load_configured_classes():
        raise ValueError(f"班级已存在：{new_name}")

    student_count = session.query(Student).filter(Student.class_name == old_name).count()
    session.query(Homework).filter(Homework.class_name == old_name).update(
        {Homework.class_name: new_name}, synchronize_session=False)
    session.query(Student).filter(Student.class_name == old_name).update(
        {Student.class_name: new_name}, synchronize_session=False)

    names = [new_name if x == old_name else x for x in load_configured_classes()]
    if old_name in names or new_name not in names:
        names.append(new_name)
    save_configured_classes(names)
    session.flush()
    return student_count


def delete_class(session, name: str) -> None:
    """删除空班级；仍有学生或普通作业引用时拒绝，避免误删业务上下文。"""
    name = _clean_name(name)
    usage = class_usage(session, name)
    if usage["students"] or usage["homeworks"]:
        raise ValueError("班级下还有学生或作业，请先移动学生或改用重命名。")
    names = [x for x in load_configured_classes() if x != name]
    save_configured_classes(names)


def _row_optional_text(row: dict, *keys: str) -> str | None:
    """读取表格单元格；空值（含 NaN）归一为 None，其余去首尾空格。"""
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return None


def sync_classes(session, rows: list[dict]) -> dict:
    """
    按可编辑班级表格同步预设名单：只处理新增行和改名行，不删除（删除走勾选确认）。

    每行包含“原班级名”（新增行为空）和“班级名”（新名称）。重命名沿用
    rename_class 的校验，并同步学生、作业（含模板）和 JSON 名单。
    返回 {"added": 新增数, "renamed": 改名数}。
    """
    added = renamed = 0
    seen_new_names: set[str] = set()

    for row in rows:
        old_name = _row_optional_text(row, "原班级名", "old_name")
        new_name = _row_optional_text(row, "班级名", "班级", "name")
        if not new_name:
            raise ValueError("班级名称不能为空。")
        if new_name in seen_new_names:
            raise ValueError(f"表格中存在重复班级：{new_name}")
        seen_new_names.add(new_name)

        if old_name is None:
            add_class(session, new_name)
            added += 1
        elif old_name != new_name:
            rename_class(session, old_name, new_name)
            renamed += 1

    return {"added": added, "renamed": renamed}


def move_students(session, student_ids: list[int], target_class: str) -> int:
    """把多名学生批量调到目标班级；成绩通过学生关联自动跟随。"""
    target_class = _clean_name(target_class)
    ids = [int(i) for i in student_ids or []]
    if not ids:
        raise ValueError("请先选择要调班的学生。")
    students = session.query(Student).filter(Student.id.in_(ids)).all()
    if len(students) != len(set(ids)):
        raise ValueError("部分学生不存在，请刷新后重试。")

    # 不同班里可能有同名学生；一次把两个同名学生调入同一班也会撞唯一业务口径。
    incoming_names = [s.name for s in students]
    if len(incoming_names) != len(set(incoming_names)):
        raise ValueError("所选学生中存在同名学生，不能一起调到同一班级。")

    # 同一目标班不能造成“姓名+班级”重复。
    incoming = set(incoming_names)
    conflicts = (session.query(Student)
                 .filter(Student.class_name == target_class,
                         Student.name.in_(incoming)).all())
    blocked = [s for s in conflicts if s.id not in set(ids)]
    if blocked:
        names = "、".join(sorted({s.name for s in blocked}))
        raise ValueError(f"目标班级已有同名学生：{names}")

    for student in students:
        student.class_name = target_class
    names = load_configured_classes()
    if target_class not in names:
        names.append(target_class)
        save_configured_classes(names)
    session.flush()
    return len(students)
