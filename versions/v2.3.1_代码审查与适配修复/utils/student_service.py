# -*- coding: utf-8 -*-
"""
学生数据服务层。

所有函数都接收一个 SQLAlchemy session（由调用方用 with SessionLocal() 管理），
把"按姓名+班级判重、自动建学生、批量导入"等规则集中在这里，页面不直接写 ORM。
"""

from __future__ import annotations

import math
import re
from typing import Any

from models.models import Student
from utils import logger_service, undo_service
from utils import class_service


def list_classes(session) -> list[str]:
    """返回所有可选班级：JSON 预设空班级 + 学生/作业中已有班级。"""
    return class_service.list_class_names(session)


def find_student(session, name: str, class_name: str | None):
    """按 姓名+班级 找学生；班级为空时只按姓名匹配（单人小工具够用）。"""
    if not name:
        return None
    q = session.query(Student).filter(Student.name == name)
    if class_name:
        q = q.filter(Student.class_name == class_name)
    return q.first()


def get_or_create_student(session, name: str, class_name: str | None,
                          student_no: str | None = None) -> tuple[Student, bool]:
    """找到学生则返回(学生, False)，否则新建并返回(学生, True)。"""
    student = find_student(session, name, class_name)
    if student:
        return student, False
    student = Student(name=name, class_name=class_name, student_no=student_no)
    session.add(student)
    session.flush()  # 拿到 id，但不提交（由外层统一提交）
    undo_service.record_row_change(
        session, "add", Student, f"新增学生：{student.name}",
        after=student)
    return student, True


def _student_filter_query(session, class_name=None, keyword=None,
                          gender=None, tag=None):
    """构造学生筛选查询，供列表和计数复用。"""
    q = session.query(Student)
    if class_name:
        q = q.filter(Student.class_name == class_name)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Student.name.like(like)) | (Student.student_no.like(like)))
    if gender == "未设置":
        q = q.filter((Student.gender.is_(None)) | (Student.gender == ""))
    elif gender:
        q = q.filter(Student.gender == gender)
    if tag:
        q = q.filter(Student.tags.like(f"%{tag}%"))
    return q


def list_students(session, class_name: str | None = None,
                  keyword: str | None = None, gender: str | None = None,
                  tag: str | None = None, limit: int | None = None,
                  offset: int | None = None):
    """学生列表，可按班级、姓名/学号、性别、标签筛选，也可分页。"""
    q = _student_filter_query(
        session, class_name=class_name, keyword=keyword,
        gender=gender, tag=tag).order_by(
        Student.class_name, Student.student_no, Student.id)
    if offset is not None:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    return q.all()


def count_students(session, class_name=None, keyword=None,
                   gender=None, tag=None) -> int:
    """统计筛选后的学生总数。"""
    return int(_student_filter_query(
        session, class_name=class_name, keyword=keyword,
        gender=gender, tag=tag).count())


def list_student_ids(session, class_name=None, keyword=None,
                     gender=None, tag=None) -> set[int]:
    """返回筛选结果中的全部学生 ID，用于分页编辑时保留其他页数据。"""
    return {int(row[0]) for row in _student_filter_query(
        session, class_name=class_name, keyword=keyword,
        gender=gender, tag=tag).with_entities(Student.id).all()}

def list_student_tags(session) -> list[str]:
    """从老师标签文本中拆分标签；兼容逗号、中文逗号和顿号。"""
    tags = set()
    for (value,) in session.query(Student.tags).filter(Student.tags.isnot(None)).all():
        for item in re.split(r"[,，、]", str(value)):
            item = item.strip()
            if item:
                tags.add(item)
    return sorted(tags)


def update_student(session, student_id: int, **fields) -> None:
    """更新学生信息，只接受白名单字段。"""
    allowed = {"name", "student_no", "class_name", "gender", "tags", "remark"}
    student = session.get(Student, student_id)
    if student is None:
        raise ValueError(f"学生不存在：id={student_id}")
    before = undo_service._row_dict(Student, student)
    for key, value in fields.items():
        if key in allowed:
            setattr(student, key, value)
    undo_service.record_row_change(
        session, "edit", Student, f"修改学生：{student.name}",
        before=before, after=student)
    logger_service.log_operation(
        session, "修改学生", "学生管理", student.id, {"字段": list(fields)})


def delete_student(session, student_id: int) -> None:
    """删除学生（其成绩由 ORM 级联删除）。"""
    student = session.get(Student, student_id)
    if student is None:
        raise ValueError(f"学生不存在：id={student_id}")
    undo_service.record_row_change(
        session, "delete", Student, f"删除学生：{student.name}",
        before=student)
    session.delete(student)
    logger_service.log_operation(
        session, "删除学生", "学生管理", student_id)


def delete_students(session, student_ids: list[int], log: bool = True) -> int:
    """批量删除学生（成绩、评语按 ORM 级联清理）；不存在的 id 跳过，返回实际删除数。"""
    count = 0
    for sid in dict.fromkeys(student_ids):
        student = session.get(Student, int(sid))
        if student is not None:
            if log:
                undo_service.record_row_change(
                    session, "delete", Student,
                    f"删除学生：{student.name}", before=student)
            session.delete(student)
            if log:
                logger_service.log_operation(
                    session, "批量删除学生", "学生管理", student.id)
            count += 1
    return count


def bulk_import_students(session, records: list[dict]) -> dict:
    """
    批量导入学生预览记录（excel_handler.extract_students 的输出）。
    跳过缺姓名的行；姓名+班级已存在则更新可补全的字段。
    返回统计 {created, updated, skipped}。
    """
    created = updated = skipped = 0
    for rec in records:
        name = rec.get("name")
        if not name:
            skipped += 1
            continue
        student, was_created = get_or_create_student(
            session, name, rec.get("class_name"), rec.get("student_no"))
        if was_created:
            created += 1
            # 新建时把其余字段补上
            student.gender = rec.get("gender")
            student.remark = rec.get("remark")
        else:
            updated += 1
            # 已存在：只补空字段，不覆盖老师手动维护的数据
            for field in ("student_no", "gender", "remark"):
                if not getattr(student, field) and rec.get(field):
                    setattr(student, field, rec.get(field))
    return {"created": created, "updated": updated, "skipped": skipped}

def _clean_optional(value: Any) -> str | None:
    """把表格空值统一成 None；非字符串转成去掉首尾空格的字符串。"""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _row_student_id(row: dict) -> int | None:
    """读取表格里隐藏的学生 ID；新增行是空值。"""
    value = row.get("学生ID", row.get("id", row.get("ID")))
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def sync_students(session, rows: list[dict], existing_ids: set[int] | None = None) -> dict:
    """
    按可编辑表格整批同步学生。

    rows 每行包含 id/ID（新增行留空）、姓名、学号、班级、性别、标签、备注。
    existing_ids 为页面进入编辑时的学生 ID 集合；集合里有、表格里没有的 ID 视为删除。
    """
    existing = {s.id: s for s in session.query(Student).all()}
    if existing_ids is None:
        existing_ids = set(existing)
    existing_ids = {int(i) for i in existing_ids}

    normalized = []
    seen_pairs: set[tuple[str, str | None]] = set()
    retained_ids: set[int] = set()

    for row in rows:
        student_id = _row_student_id(row)
        name = _clean_optional(row.get("姓名", row.get("name")))
        class_name = _clean_optional(row.get("班级", row.get("class_name")))
        student_no = _clean_optional(row.get("学号", row.get("student_no")))
        gender_raw = _clean_optional(row.get("性别", row.get("gender")))
        tags = _clean_optional(row.get("标签", row.get("tags")))
        remark = _clean_optional(row.get("备注", row.get("remark")))
        gender = gender_raw if gender_raw in ("男", "女") else None

        if not name:
            raise ValueError("学生姓名不能为空。")
        if student_id is not None:
            if student_id not in existing_ids or student_id not in existing:
                raise ValueError(f"表格包含不存在的学生 ID：{student_id}")
            retained_ids.add(student_id)

        pair = (name, class_name)
        if pair in seen_pairs:
            raise ValueError(f"表格中存在重复的学生：{name}（{class_name or '未分班'}）")
        seen_pairs.add(pair)

        # 与表格内其他行、数据库其他学生做“姓名+班级”判重。
        other = find_student(session, name, class_name)
        if other is not None and other.id != student_id:
            raise ValueError(f"学生已存在：{name}（{class_name or '未分班'}）")

        normalized.append({
            "id": student_id, "name": name, "student_no": student_no,
            "class_name": class_name, "gender": gender,
            "tags": tags, "remark": remark,
        })

    created = updated = 0
    for item in normalized:
        student_id = item["id"]
        if student_id is None:
            new_student = Student(
                name=item["name"], student_no=item["student_no"],
                class_name=item["class_name"], gender=item["gender"],
                tags=item["tags"], remark=item["remark"])
            session.add(new_student)
            session.flush()
            undo_service.record_row_change(
                session, "add", Student,
                f"新增学生：{new_student.name}", after=new_student)
            created += 1
        else:
            student = existing[student_id]
            before = undo_service._row_dict(Student, student)
            student.name = item["name"]
            student.student_no = item["student_no"]
            student.class_name = item["class_name"]
            student.gender = item["gender"]
            student.tags = item["tags"]
            student.remark = item["remark"]
            undo_service.record_row_change(
                session, "edit", Student,
                f"修改学生：{student.name}", before=before, after=student)
            updated += 1

    deleted_ids = existing_ids - retained_ids
    for student_id in deleted_ids:
        student = existing[student_id]
        undo_service.record_row_change(
            session, "delete", Student,
            f"删除学生：{student.name}", before=student)
        session.delete(student)
    session.flush()

    return {"created": created, "updated": updated, "deleted": len(deleted_ids)}
