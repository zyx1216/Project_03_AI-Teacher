# -*- coding: utf-8 -*-
"""备份 / 恢复 / 清空服务层测试（全部在临时目录和内存库上做，不碰真实 data）。"""

import io
import json
import zipfile
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from models.models import Base, Student, Exam, Score, CommentTemplate
from utils import backup_service as bs
from utils import exam_service


@pytest.fixture()
def fake_data_dir(tmp_path):
    """造一个最小 data 目录：配置文件 + 上传文件 + 备份子目录。"""
    d = tmp_path / "data"
    (d / "uploads").mkdir(parents=True)
    (d / "backups").mkdir(parents=True)
    (d / "llm_config.json").write_text(
        json.dumps({"model": "test-model"}, ensure_ascii=False), encoding="utf-8")
    (d / "uploads" / "课本.txt").write_text("一些教学资料", encoding="utf-8")
    # 一个不应该进新备份的旧备份 zip
    (d / "backups" / "old.zip").write_bytes(b"PK old backup")
    # 临时锁文件，打包应跳过
    (d / "database.db-journal").write_text("x", encoding="utf-8")
    return d


def _populated_session(engine):
    """在给定引擎上建表并写入几条业务数据 + 一条模板。"""
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    exam = exam_service.create_exam(session, "月考", exam_date=date(2026, 3, 1))
    session.flush()
    session.add(CommentTemplate(name="模板", content="正文", style="鼓励"))
    session.add(Student(name="学生01", class_name="一班"))
    session.flush()
    exam_service.import_scores(
        session, exam.id,
        [{"name": "学生01", "class_name": "一班", "scores": {"数学": 88}}])
    session.commit()
    return session


def test_backup_zip_contains_db_config_and_manifest(fake_data_dir):
    # 先在假 data 里放一个数据库文件
    engine = create_engine(f"sqlite:///{(fake_data_dir / 'database.db').as_posix()}")
    _populated_session(engine)
    engine.dispose()

    blob = bs.backup_data_dir(fake_data_dir)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        assert bs.MANIFEST_NAME in names
        assert "llm_config.json" in names
        assert "database.db" in names
        assert "uploads/课本.txt" in names
        # 临时锁文件和旧备份不进包
        assert "database.db-journal" not in names
        assert not any(n.startswith("backups/") and n.endswith(".zip") for n in names)
        manifest = json.loads(zf.read(bs.MANIFEST_NAME).decode("utf-8"))
        assert manifest["app"]


def test_restore_roundtrip_files_match(tmp_path, fake_data_dir):
    blob = bs.backup_data_dir(fake_data_dir)
    zip_path = tmp_path / "restore.zip"
    zip_path.write_bytes(blob)

    # 删掉原 data，恢复回来文件应一致
    import shutil
    shutil.rmtree(fake_data_dir)
    manifest = bs.restore_from_zip(zip_path, fake_data_dir)
    assert manifest["version"]
    assert (fake_data_dir / "llm_config.json").read_text(encoding="utf-8")
    assert (fake_data_dir / "uploads" / "课本.txt").read_text(encoding="utf-8") == "一些教学资料"

    # 旧 data 被改名成 data.bak-*（恢复前目录已删除，此场景无 bak，改为覆盖场景再验）
    # 覆盖恢复：再恢复一次，现有 data 应被改名保留
    zip_path2 = tmp_path / "restore2.zip"
    zip_path2.write_bytes(blob)
    bs.restore_from_zip(zip_path2, fake_data_dir)
    parent = fake_data_dir.parent
    baks = list(parent.glob("data.bak-*"))
    assert baks, "恢复前应把旧 data 改名备份"


def test_restore_rejects_bad_zip(tmp_path, fake_data_dir):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        bs.restore_from_zip(bad, fake_data_dir)
    # 校验失败不能动现有 data
    assert (fake_data_dir / "llm_config.json").exists()

    # 缺清单的 zip 也拒绝
    good_but_no_manifest = tmp_path / "nomanifest.zip"
    with zipfile.ZipFile(good_but_no_manifest, "w") as zf:
        zf.writestr("x.txt", "y")
    with pytest.raises(ValueError):
        bs.restore_from_zip(good_but_no_manifest, fake_data_dir)


def test_restore_failure_rolls_back(tmp_path, fake_data_dir):
    """解包阶段失败时，旧 data 必须能改回来（不丢数据）。"""
    # 先做一个合法备份
    blob = bs.backup_data_dir(fake_data_dir)
    # 手工构造一个能过清单校验、但含路径穿越成员的坏包
    bad_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(io.BytesIO(blob)) as src:
        manifest = src.read(bs.MANIFEST_NAME)
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr(bs.MANIFEST_NAME, manifest)
        zf.writestr("../evil.txt", b"x")
    with pytest.raises(ValueError):
        bs.restore_from_zip(bad_zip, fake_data_dir)
    # 回退后原文件仍在
    assert (fake_data_dir / "llm_config.json").exists()


def test_wipe_clears_business_tables_but_keeps_config_and_backups(tmp_path):
    db_file = tmp_path / "data" / "database.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    (db_file.parent / "llm_config.json").write_text("{}", encoding="utf-8")
    (db_file.parent / "backups").mkdir(exist_ok=True)
    (db_file.parent / "backups" / "keep.zip").write_bytes(b"PK")

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    session = _populated_session(engine)
    assert session.query(Student).count() == 1
    assert session.query(CommentTemplate).count() == 1

    cleared = bs.wipe_business_data(session)
    session.commit()
    assert "students" in cleared and len(cleared) == 13
    assert session.query(Student).count() == 0
    assert session.query(Exam).count() == 0
    assert session.query(Score).count() == 0
    assert session.query(CommentTemplate).count() == 0
    # 表本身还在，只是数据被清空
    assert "students" in inspect(engine).get_table_names()
    session.close()
    engine.dispose()

    # 配置文件和备份 zip 原样保留
    assert (db_file.parent / "llm_config.json").exists()
    assert (db_file.parent / "backups" / "keep.zip").exists()
