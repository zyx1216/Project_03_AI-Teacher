# -*- coding: utf-8 -*-
"""v3.5.2 低严重度问题修复测试。"""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base
from utils import (exam_service, excel_handler as eh, export_service,
                   parent_report_service, student_report_service,
                   template_service)
from modules import lesson_plan


@pytest.fixture()
def session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'v352.db').as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def _seed_exam(session):
    """两班两人、数学满分 100 的考试。"""
    exam = exam_service.create_exam(session, "第一次月考",
                                    exam_date=date(2026, 9, 20),
                                    full_scores={"数学": 100})
    exam_service.import_scores(session, exam.id, [
        {"name": "学生甲", "class_name": "一班", "scores": {"数学": 90}},
        {"name": "学生乙", "class_name": "二班", "scores": {"数学": 80}},
    ])
    session.commit()
    return exam


# ---------------------------------------------------------------------------
# 修复1：科目后缀（"英语分"等）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("英语分", "英语"),
    ("语文成绩", "语文"),
    ("数学分数", "数学"),
    ("政治", "政治"),
    ("科学", None),
])
def test_normalize_subject_name_single_char_suffix(raw, expected):
    assert eh.normalize_subject_name(raw) == expected


# ---------------------------------------------------------------------------
# 修复2：缺考 / 未录分区分
# ---------------------------------------------------------------------------

def test_extract_scores_distinguishes_absent_and_unrecorded():
    df = pd.DataFrame({"姓名": ["甲", "乙", "丙"],
                       "数学": ["缺考", None, 88],
                       "英语": [70, 60, 50]})
    det = eh.detect_score_columns(df)
    records = {r["name"]: r for r in eh.extract_scores(df, det)}
    assert records["甲"]["problems"] == ["数学 - 缺考"]
    assert records["甲"]["scores"]["数学"] is None
    assert records["乙"]["problems"] == ["数学 - 未录分"]
    assert records["乙"]["scores"]["数学"] is None
    assert records["丙"]["problems"] == []
    assert records["丙"]["scores"]["数学"] == 88


def test_preview_round_trip_keeps_absent_and_unrecorded():
    # 必须留一个正常分数，否则识别不出这一科
    df = pd.DataFrame({"姓名": ["甲", "乙", "丙"],
                       "数学": ["缺考", None, 88]})
    det = eh.detect_score_columns(df)
    frame, subjects = eh.scores_preview_frame(eh.extract_scores(df, det))
    back = eh.preview_to_records(frame, subjects)
    assert back[0]["problems"] == ["数学 - 缺考"]
    assert back[1]["problems"] == ["数学 - 未录分"]
    assert back[2]["problems"] == []


# ---------------------------------------------------------------------------
# 修复3：内置教案模板（通用 + 小学/初中/高中）
# ---------------------------------------------------------------------------

def test_builtin_lesson_templates_all_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(template_service, "LESSON_TEMPLATES_PATH",
                        tmp_path / "lesson_templates.json")
    names = [t["name"] for t in template_service.list_lesson_templates()]
    assert names == ["通用模板", "小学教案模板", "初中教案模板", "高中教案模板"]
    for name, keyword in (("小学教案模板", "游戏活动"),
                          ("初中教案模板", "学法指导"),
                          ("高中教案模板", "高考考点分析")):
        content = template_service.lesson_template_content(name)
        assert keyword in content
        for must in ("教学目标", "教学重点", "教学难点", "教学准备",
                     "教学过程", "板书设计", "教学反思"):
            assert must in content
    assert "课堂互动设计" in template_service.lesson_template_content("小学教案模板")
    assert "例题讲解" in template_service.lesson_template_content("初中教案模板")
    assert "能力提升" in template_service.lesson_template_content("高中教案模板")


def test_builtin_templates_merged_into_existing_json(tmp_path, monkeypatch):
    path = tmp_path / "lesson_templates.json"
    path.write_text(json.dumps({"templates": [
        {"name": "通用模板", "content": "旧内容", "builtin": True},
        {"name": "我的模板", "content": "自定义正文", "builtin": False},
    ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(template_service, "LESSON_TEMPLATES_PATH", path)
    names = [t["name"] for t in template_service.list_lesson_templates()]
    assert names == ["通用模板", "小学教案模板", "初中教案模板",
                     "高中教案模板", "我的模板"]
    # 内置模板正文以代码为准，不被旧 JSON 覆盖
    assert template_service.lesson_template_content("通用模板").startswith(
        "请按以下结构生成教案")
    with pytest.raises(ValueError):
        template_service.save_custom_lesson_template("小学教案模板", "占用内置名")
    template_service.save_custom_lesson_template("我的模板2", "新正文")
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved_names = [t["name"] for t in saved["templates"]]
    assert saved_names[:4] == ["通用模板", "小学教案模板", "初中教案模板",
                               "高中教案模板"]
    assert "我的模板2" in saved_names


# ---------------------------------------------------------------------------
# 修复4：成绩导出补"满分标注 / 总得分率 / 年级排名"
# ---------------------------------------------------------------------------

def test_score_report_has_grade_rank_and_rate(session):
    exam = _seed_exam(session)
    ws = load_workbook(io.BytesIO(
        exam_service.build_score_report_xlsx(session, exam.id))).active
    assert [ws.cell(2, col).value for col in range(1, 9)] == [
        "姓名", "学号", "班级", "数学(满分100)", "总分", "总得分率",
        "班级排名", "年级排名"]
    rows = [[ws.cell(r, col).value for col in range(1, 9)]
            for r in (3, 4)]
    assert ["学生甲", None, "一班", 90, 90, 0.9, 1, 1] in rows
    assert ["学生乙", None, "二班", 80, 80, 0.8, 1, 2] in rows
    rate_cell = ws.cell(3, 6)
    assert rate_cell.value == pytest.approx(0.9)
    assert rate_cell.number_format == "0.0%"
    assert ws.cell(2, 4).font.bold is True


def test_score_report_single_class_keeps_grade_rank(session):
    """只导一个班时，年级排名仍按全年级口径给。"""
    exam = _seed_exam(session)
    ws = load_workbook(io.BytesIO(
        exam_service.build_score_report_xlsx(session, exam.id, "一班"))).active
    assert ws["A1"].value == "一班 第一次月考 成绩单"
    assert [ws.cell(3, col).value for col in range(1, 9)] == [
        "学生甲", None, "一班", 90, 90, 0.9, 1, 1]


# ---------------------------------------------------------------------------
# 修复5：选择题选项统一"每行一个"
# ---------------------------------------------------------------------------

INLINE_CHOICE = "下列正确的是（  ）A. 甲 B. 乙 C. 丙 D. 丁"
TWO_OPTIONS = "只有两个选项 A. 甲 B. 乙"


class _Question:
    id = 1
    content = INLINE_CHOICE
    question_type = "choice"
    answer = "C"
    analysis = None
    error_points = None
    difficulty = 1
    knowledge_points = '["有理数"]'


class _Homework:
    id = 1
    name = "测试卷"
    subject = "数学"
    grade = "七年级"
    class_name = "一班"
    total_score = 100
    duration = 90
    homework_type = "exam"


def test_pdf_html_options_one_per_line():
    html = export_service._exam_html(_Homework(), [(None, _Question())],
                                     school="测试中学", with_answer=False)
    for option in ("A. 甲", "B. 乙", "C. 丙", "D. 丁"):
        assert f"<p>{option}</p>" in html
    # 题干与四个选项共 5 段，不会挤在一行
    assert "A. 甲 B. 乙" not in html


def test_page_preview_options_one_per_line():
    text = lesson_plan._format_question_content(INLINE_CHOICE, "choice")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    assert lines[0] == "下列正确的是（  ）"
    assert lines[1:] == ["- **A.** 甲", "- **B.** 乙",
                         "- **C.** 丙", "- **D.** 丁"]


def test_incomplete_choice_options_not_split():
    assert lesson_plan._format_question_content(TWO_OPTIONS, "choice") == TWO_OPTIONS


# ---------------------------------------------------------------------------
# 修复6/7：家长报告去重 + 学生报告标题
# ---------------------------------------------------------------------------

def test_parent_report_html_has_no_duplicate_subject_text(session):
    exam = _seed_exam(session)
    student = exam_service.exam_score_rows(session, exam.id)[0]
    report = parent_report_service.generate_parent_report(
        session, student["student_id"], exam_id=exam.id,
        chat_func=lambda _s, _u: "")
    html = parent_report_service.render_html(report)
    assert "得分率" in html and "班级排名" in html and "年级排名" in html
    # 表格已经列了各科成绩，不再重复整段文字
    assert report["subjects"] not in html


def test_student_report_title_has_no_stray_space():
    html = student_report_service.render_student_report_html({"name": "张三"})
    assert "张三的学情报告" in html
    assert "张三 学情报告" not in html


# ---------------------------------------------------------------------------
# 版本与表数
# ---------------------------------------------------------------------------

def test_version_and_database_unchanged():
    import config
    assert config.APP_VERSION == "3.5.3"
    assert len(Base.metadata.tables) == 38
