# -*- coding: utf-8 -*-
"""v1.4.2 班级名单 JSON 服务测试。"""

import json

import pytest
from models.models import Homework, Student
from utils import class_service, homework_service


@pytest.fixture()
def class_file(tmp_path, monkeypatch):
    path = tmp_path / "class_names.json"
    monkeypatch.setattr(class_service, "CLASS_NAMES_PATH", path)
    return path


def test_missing_file_auto_created_and_empty(class_file, session):
    assert class_service.load_configured_classes() == []
    assert class_file.exists()
    assert json.loads(class_file.read_text(encoding="utf-8")) == {"classes": []}


def test_add_preset_empty_class_and_merge_existing(class_file, session):
    class_service.add_class(session, " 三班 ")
    session.add(Student(name="甲", class_name="一班"))
    session.commit()
    assert class_service.list_class_names(session) == ["一班", "三班"]
    assert json.loads(class_file.read_text(encoding="utf-8")) == {"classes": ["三班"]}
    # 中文不转义
    assert "三班" in class_file.read_text(encoding="utf-8")


def test_add_duplicate_and_invalid_name_rejected(class_file, session):
    class_service.add_class(session, "一班")
    session.commit()
    with pytest.raises(ValueError, match="已存在"):
        class_service.add_class(session, "一班")
    with pytest.raises(ValueError, match="不能为空"):
        class_service.add_class(session, "  ")
    with pytest.raises(ValueError, match="不能超过"):
        class_service.add_class(session, "班" * 51)


def test_rename_updates_students_homeworks_and_json(class_file, session):
    class_service.add_class(session, "一班")
    session.add_all([
        Student(name="甲", class_name="一班"),
        Student(name="乙", class_name="二班"),
    ])
    homework_service.create_homework(session, "一班作业", class_name="一班")
    homework_service.create_homework(session, "模板", class_name="一班",
                                     is_template=True)
    session.commit()

    count = class_service.rename_class(session, "一班", "三班")
    session.commit()

    assert count == 1
    assert class_service.load_configured_classes() == ["三班"]
    assert session.query(Student).filter(Student.class_name == "三班").count() == 1
    assert (session.query(Homework)
            .filter(Homework.class_name == "三班").count()) == 2


def test_rename_conflict_rejected(class_file, session):
    session.add_all([Student(name="甲", class_name="一班"),
                     Student(name="甲", class_name="二班")])
    session.commit()
    with pytest.raises(ValueError, match="已存在"):
        class_service.rename_class(session, "一班", "二班")


def test_delete_empty_preset_class(class_file, session):
    class_service.add_class(session, "空班")
    class_service.delete_class(session, "空班")
    assert class_service.load_configured_classes() == []


def test_delete_used_class_rejected(class_file, session):
    # 学生表自动聚合出的班级不在 JSON 中，但仍不能当空班级删除。
    session.add(Student(name="甲", class_name="一班"))
    session.commit()
    with pytest.raises(ValueError, match="先移动学生"):
        class_service.delete_class(session, "一班")


def test_move_students_batch_and_duplicate_guard(class_file, session):
    s1 = Student(name="甲", class_name="一班")
    s2 = Student(name="乙", class_name="一班")
    s3 = Student(name="丙", class_name="二班")
    session.add_all([s1, s2, s3])
    session.commit()

    assert class_service.move_students(session, [s1.id, s2.id], "二班") == 2
    session.commit()
    assert session.query(Student).filter(Student.class_name == "二班").count() == 3
    assert "二班" in class_service.load_configured_classes()

    # 目标一班已有甲，再把二班的另一名甲调过去会触发同名保护。
    target_same_name = Student(name="甲", class_name="一班")
    other = Student(name="甲", class_name="二班")
    session.add_all([target_same_name, other])
    session.commit()
    with pytest.raises(ValueError, match="同名学生"):
        class_service.move_students(session, [other.id], "一班")


def test_corrupt_json_falls_back_without_overwrite(class_file, session):
    class_file.write_text("{坏JSON", encoding="utf-8")
    assert class_service.load_configured_classes() == []
    assert class_file.read_text(encoding="utf-8") == "{坏JSON"
