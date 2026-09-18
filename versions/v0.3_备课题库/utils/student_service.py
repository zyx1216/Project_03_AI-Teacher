# -*- coding: utf-8 -*-
"""
学生数据服务层。

所有函数都接收一个 SQLAlchemy session（由调用方用 with SessionLocal() 管理），
把"按姓名+班级判重、自动建学生、批量导入"等规则集中在这里，页面不直接写 ORM。
"""

from __future__ import annotations

from models.models import Student


def list_classes(session) -> list[str]:
    """返回所有非空班级名（去重、排序）。"""
    rows = (session.query(Student.class_name)
            .filter(Student.class_name.isnot(None), Student.class_name != "")
            .distinct().all())
    return sorted({r[0] for r in rows})


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
    return student, True


def list_students(session, class_name: str | None = None,
                  keyword: str | None = None):
    """学生列表，可按班级筛选、按姓名/学号关键字搜索。"""
    q = session.query(Student)
    if class_name:
        q = q.filter(Student.class_name == class_name)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Student.name.like(like)) | (Student.student_no.like(like)))
    return q.order_by(Student.class_name, Student.student_no, Student.id).all()


def update_student(session, student_id: int, **fields) -> None:
    """更新学生信息，只接受白名单字段。"""
    allowed = {"name", "student_no", "class_name", "gender", "tags", "remark"}
    student = session.get(Student, student_id)
    if student is None:
        raise ValueError(f"学生不存在：id={student_id}")
    for key, value in fields.items():
        if key in allowed:
            setattr(student, key, value)


def delete_student(session, student_id: int) -> None:
    """删除学生（其成绩由 ORM 级联删除）。"""
    student = session.get(Student, student_id)
    if student is None:
        raise ValueError(f"学生不存在：id={student_id}")
    session.delete(student)


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