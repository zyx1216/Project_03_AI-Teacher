# -*- coding: utf-8 -*-
"""v1.6.3 备课区全面优化：服务层新增能力测试。"""

import json
from pathlib import Path

import pytest

from models.models import Textbook
from utils import app_config as ac
from utils import material_service as material
from utils import question_service as qs
from utils import vector_store
from utils import ppt_generator
from utils import template_service
from utils import lesson_service as lesson_svc
from utils import question_history_service as qh


# ---------------------------------------------------------------------------
# 年级双向映射
# ---------------------------------------------------------------------------

def test_grade_storage_to_display_junior():
    assert ac.to_display_grade("七年级") == "初一"
    assert ac.to_display_grade("八年级") == "初二"
    assert ac.to_display_grade("九年级") == "初三"


def test_grade_display_to_storage_junior():
    assert ac.to_storage_grade("初一") == "七年级"
    assert ac.to_storage_grade("初二") == "八年级"
    assert ac.to_storage_grade("初三") == "九年级"


def test_grade_mapping_primary_and_senior_unchanged():
    for name in ("一年级", "六年级", "高一", "高二", "高三", "未指定"):
        assert ac.to_display_grade(name) == name
        assert ac.to_storage_grade(name) == name
    assert ac.to_display_grade(None) == ""
    assert ac.to_storage_grade(None) == ""


def test_display_grade_choices_contains_senior():
    choices = ac.DISPLAY_GRADE_CHOICES
    assert choices.index("初一") < choices.index("初二") < choices.index("初三")
    assert "高一" in choices and "高三" in choices


# ---------------------------------------------------------------------------
# 出题待定任务文件持久化
# ---------------------------------------------------------------------------

@pytest.fixture()
def drafts_file(tmp_path, monkeypatch):
    path = tmp_path / "question_drafts.json"
    monkeypatch.setattr(qs, "DRAFTS_FILE_PATH", path)
    return path


def _one_draft():
    return {
        "tasks": [{"question_type": "选择题", "storage_type": "choice",
                   "difficulty": 2, "count": 3}],
        "material_id": None,
        "knowledge_points": ["函数"],
        "extra": "",
    }


def test_drafts_file_missing_auto_create(drafts_file):
    assert qs.load_drafts_file() == {}
    assert drafts_file.exists()


def test_drafts_save_chinese_not_escaped(drafts_file):
    qs.save_drafts_file({"数学": _one_draft()})
    raw = drafts_file.read_text(encoding="utf-8")
    assert "函数" in raw
    assert "\\u" not in raw
    loaded = qs.load_drafts_file()
    assert loaded["数学"]["tasks"][0]["count"] == 3


def test_drafts_corrupt_file_falls_back_without_overwrite(drafts_file):
    drafts_file.write_text("{损坏", encoding="utf-8")
    assert qs.load_drafts_file() == {}
    assert drafts_file.read_text(encoding="utf-8") == "{损坏"


def test_task_editor_dataframe_handles_none_values():
    # 显式 None 不应触发 int(None)，而是回退默认值
    df = qs.task_editor_dataframe(
        [{"question_type": "选择题", "difficulty": None, "count": None}],
        ensure_default=False)
    row = df.to_dict("records")[0]
    assert row["难度"] == 2
    assert row["数量"] == 1


# ---------------------------------------------------------------------------
# 知识点聚合
# ---------------------------------------------------------------------------

def _make_question(session, kps, subject="数学", status="approved"):
    qs.create_question(
        session,
        {"content": f"题目{kps}", "question_type": "choice", "difficulty": 2,
         "knowledge_points": json.dumps(kps, ensure_ascii=False),
         "answer": "A"},
        source="manual", status=status, subject=subject)


def test_get_all_knowledge_points_dedup_and_sort(session):
    _make_question(session, ["函数", "方程"])
    _make_question(session, ["函数", "几何"])
    names = qs.get_all_knowledge_points(session, "数学")
    assert names == sorted(set(names))
    assert set(names) == {"函数", "方程", "几何"}


def test_get_all_knowledge_points_filters_subject(session):
    _make_question(session, ["数学点"], subject="数学")
    _make_question(session, ["语文点"], subject="语文")
    assert qs.get_all_knowledge_points(session, "数学") == ["数学点"]


# ---------------------------------------------------------------------------
# 题库表格数据与 Grid Options
# ---------------------------------------------------------------------------

def test_bank_table_rows_shape(session):
    _make_question(session, ["函数"])
    questions = qs.list_questions(session, subject="数学")
    rows = qs.bank_table_rows(questions)
    assert set(rows[0]) >= {"ID", "题型", "难度", "状态", "题干", "知识点",
                            "question_id", "clicked_id"}
    assert rows[0]["知识点"] == "函数"


def test_build_bank_grid_options_no_inner_html():
    options = qs.build_bank_grid_options()
    fields = [c["field"] for c in options["columnDefs"]]
    assert "question_id" in fields and "clicked_id" in fields
    hidden = {c["field"]: c.get("hide", False) for c in options["columnDefs"]}
    assert hidden["question_id"] is True and hidden["clicked_id"] is True
    assert options["rowSelection"] == "multiple"
    js = options["onCellClicked"].js_code
    assert "question_id" in js and "setDataValue" in js
    assert "innerHTML" not in js


def test_clicked_question_id_and_selected_ids():
    rows = [
        {"question_id": 1, "clicked_id": ""},
        {"question_id": 2, "clicked_id": "2"},
    ]
    assert qs.clicked_question_id(rows) == 2
    assert qs.selected_question_ids(rows) == [1, 2]
    assert qs.clicked_question_id([{"question_id": 1, "clicked_id": "x"}]) is None


# ---------------------------------------------------------------------------
# 资料删除（级联）
# ---------------------------------------------------------------------------

@pytest.fixture()
def material_paths(tmp_path, monkeypatch):
    original_dir = tmp_path / "original"
    static_dir = tmp_path / "static_original"
    text_dir = tmp_path / "material_text"
    monkeypatch.setattr(material, "ORIGINAL_DIR", original_dir)
    monkeypatch.setattr(material, "STATIC_ORIGINAL_DIR", static_dir)
    return {"original": original_dir, "static": static_dir, "text": text_dir}


def _make_textbook(session, name="资料甲", file_type="pdf"):
    tb = Textbook(name=name, file_type=file_type, subject="数学",
                   grade="八年级", vectorized=False)
    session.add(tb)
    session.commit()
    return tb


def test_delete_material_cascade(session, material_paths, tmp_path, monkeypatch):
    import config
    fake_upload = tmp_path / "uploads"
    (fake_upload / "text").mkdir(parents=True)
    monkeypatch.setattr(config, "UPLOAD_DIR", fake_upload)

    tb = _make_textbook(session)
    (fake_upload / "text" / f"{tb.id}.txt").write_text("正文", encoding="utf-8")
    canonical = material.original_file_path(tb.id, "pdf")
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"pdf")
    static_file = material.static_original_file_path(tb.id, "pdf")
    static_file.parent.mkdir(parents=True, exist_ok=True)
    static_file.write_bytes(b"pdf")

    # 向量删除被调用但不阻断（这里 monkeypatch drop_index）
    dropped = []
    monkeypatch.setattr(vector_store, "drop_index",
                        lambda i: dropped.append(i))

    material.delete_material(session, tb.id)
    session.commit()
    assert session.get(Textbook, tb.id) is None
    assert not canonical.exists() and not static_file.exists()
    assert not (fake_upload / "text" / f"{tb.id}.txt").exists()
    assert dropped == [tb.id]


def test_delete_material_missing_raises(session):
    with pytest.raises(ValueError):
        material.delete_material(session, 999)


def test_delete_material_vector_failure_does_not_block(session, material_paths,
                                                       tmp_path, monkeypatch):
    import config
    fake_upload = tmp_path / "uploads"
    (fake_upload / "text").mkdir(parents=True)
    monkeypatch.setattr(config, "UPLOAD_DIR", fake_upload)
    monkeypatch.setattr(vector_store, "drop_index",
                        lambda i: (_ for _ in ()).throw(RuntimeError("boom")))
    tb = _make_textbook(session, file_type="text")
    material.delete_material(session, tb.id)
    session.commit()
    assert session.get(Textbook, tb.id) is None


# ---------------------------------------------------------------------------
# 教案草稿
# ---------------------------------------------------------------------------

def test_find_plan_by_title_and_draft_reuse(session):
    plan = lesson_svc.empty_plan()
    lesson_svc.save_plan(session, "课题甲（草稿）", plan, subject="数学")
    session.commit()
    found = lesson_svc.find_plan_by_title(session, "课题甲（草稿）", subject="数学")
    assert found is not None
    assert lesson_svc.find_plan_by_title(session, "课题甲（草稿）", subject="语文") is None


def test_save_plan_with_id_updates_instead_of_insert(session):
    plan = lesson_svc.empty_plan()
    lesson = lesson_svc.save_plan(session, "课题甲（草稿）", plan, subject="数学")
    session.commit()
    lesson_svc.save_plan(session, "课题甲", plan, plan_id=lesson.id, subject="数学")
    session.commit()
    assert len(lesson_svc.list_plans(session, subject="数学")) == 1
    assert session.get(type(lesson), lesson.id).title == "课题甲"


# ---------------------------------------------------------------------------
# 出题历史题目快照
# ---------------------------------------------------------------------------

def test_add_history_saves_question_snapshot(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    monkeypatch.setattr(qh, "HISTORY_PATH", history_file)
    qh._CORRUPT = False
    config_data = {"grade": "八年级", "subjects": ["数学"]}
    snapshot = [{"subject": "数学", "question_type": "选择题", "difficulty": 2,
                 "content": "题干", "answer": "A"}]
    item = qh.add_history(config_data, 1, question_snapshot=snapshot)
    assert item["question_snapshot"][0]["content"] == "题干"
    again = qh.get_history(item["id"])
    assert again["question_snapshot"][0]["answer"] == "A"


def test_add_history_without_snapshot_omits_field(tmp_path, monkeypatch):
    monkeypatch.setattr(qh, "HISTORY_PATH", tmp_path / "history.json")
    qh._CORRUPT = False
    item = qh.add_history({"grade": "八年级", "subjects": ["数学"]}, 2)
    assert "question_snapshot" not in item


# ---------------------------------------------------------------------------
# PPT 预览与模板管理
# ---------------------------------------------------------------------------

def test_ppt_preview_and_template_rename_delete(session, tmp_path, monkeypatch):
    # 先造一份教案并生成真实 PPT
    lesson = lesson_svc.save_plan(
        session, "课题甲", lesson_svc.empty_plan(), subject="数学")
    session.commit()
    data = ppt_generator.generate_ppt(lesson, lesson_svc.load_plan(lesson))
    info = ppt_generator.preview_ppt(data)
    assert info["slide_count"] >= 1
    assert info["slides"][0]["index"] == 1


def test_ppt_template_rename_and_delete(tmp_path, monkeypatch):
    ppt_json = tmp_path / "ppt.json"
    ppt_dir = tmp_path / "ppt_templates"
    monkeypatch.setattr(template_service, "PPT_TEMPLATES_PATH", ppt_json)
    monkeypatch.setattr(template_service, "PPT_TEMPLATE_DIR", ppt_dir)

    # 用真实 PPT 字节作为自定义模板
    prs_bytes = ppt_generator._new_presentation()
    import io
    buf = io.BytesIO()
    prs_bytes.save(buf)
    template_service.save_custom_ppt_template("我的模板", buf.getvalue())

    template_service.rename_ppt_template("我的模板", "新模板")
    assert template_service.ppt_template_info("新模板") is not None
    assert template_service.ppt_template_info("我的模板") is None

    template_service.delete_ppt_template("新模板")
    assert template_service.ppt_template_info("新模板") is None


def test_ppt_template_builtin_cannot_rename_or_delete():
    with pytest.raises(ValueError):
        template_service.rename_ppt_template("简约", "别的")
    with pytest.raises(ValueError):
        template_service.delete_ppt_template("简约")


def test_ppt_template_rename_duplicate_name_rejected(tmp_path, monkeypatch):
    ppt_json = tmp_path / "ppt.json"
    ppt_dir = tmp_path / "ppt_templates"
    monkeypatch.setattr(template_service, "PPT_TEMPLATES_PATH", ppt_json)
    monkeypatch.setattr(template_service, "PPT_TEMPLATE_DIR", ppt_dir)
    import io
    prs = ppt_generator._new_presentation()
    buf = io.BytesIO()
    prs.save(buf)
    template_service.save_custom_ppt_template("模板甲", buf.getvalue())
    template_service.save_custom_ppt_template("模板乙", buf.getvalue())
    with pytest.raises(ValueError):
        template_service.rename_ppt_template("模板甲", "模板乙")