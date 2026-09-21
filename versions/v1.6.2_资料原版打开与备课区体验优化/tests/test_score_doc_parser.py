# -*- coding: utf-8 -*-
"""v1.2.5：Word/PDF 成绩解析、预览转换、排名图数据、趋势截断测试。

PDF 用例依赖系统微软雅黑（用于嵌入中文画线框表），字体缺失则跳过。
全部在临时目录/内存库进行，不碰真实 data/database.db。
"""

import pathlib
from datetime import date

import pandas as pd
import pytest

from utils import excel_handler as eh
from utils import exam_service, student_service
from utils import score_doc_parser as sdp
from modules import analysis as analysis_mod

FONT = r"C:\Windows\Fonts\msyh.ttc"

GRID = [
    ["姓名", "班级", "数学成绩", "语文成绩"],
    ["学生01", "一班", "88", "76"],
    ["学生02", "一班", "76.5", "90"],
    ["学生03", "二班", "", "81"],  # 数学缺考
]


def _make_docx(path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("期中考试成绩表")
    table = doc.add_table(rows=len(GRID), cols=len(GRID[0]))
    table.style = "Table Grid"
    for i, row in enumerate(GRID):
        for j, val in enumerate(row):
            table.cell(i, j).text = val
    # 无关表格（无成绩数字），不应被选中
    other = doc.add_table(rows=2, cols=2)
    other.style = "Table Grid"
    other.cell(0, 0).text = "项目"
    other.cell(0, 1).text = "备注"
    other.cell(1, 0).text = "说明"
    other.cell(1, 1).text = "无成绩"
    doc.save(path)


def _make_pdf(path):
    import pymupdf
    if not pathlib.Path(FONT).exists():
        pytest.skip("缺少微软雅黑字体，无法构造含中文的线框 PDF")
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="msyh", fontfile=FONT)
    x0, y0 = 60, 80
    col_w = [70, 70, 90, 90]
    xs = [0]
    for w in col_w:
        xs.append(xs[-1] + w)  # 累加列边界坐标
    rh = 26
    shape = page.new_shape()
    for ri, row in enumerate(GRID):
        for ci, val in enumerate(row):
            rect = __import__("pymupdf").Rect(
                x0 + xs[ci], y0 + ri * rh,
                x0 + xs[ci + 1], y0 + (ri + 1) * rh)
            shape.draw_rect(rect)
            shape.finish(color=(0, 0, 0), width=0.8)
            if val:
                shape.insert_text((rect.x0 + 5, rect.y0 + 18), val,
                                  fontsize=11, fontname="msyh")
    shape.commit()
    pdf.save(path)
    pdf.close()


def _assert_dataframe_shape(df):
    assert list(df.columns) == ["姓名", "班级", "数学成绩", "语文成绩"]
    records = df.to_dict("records")
    assert records[0]["姓名"] == "学生01"
    assert records[0]["数学成绩"] in ("88", 88)
    # 缺考单元格为 None
    assert records[2]["数学成绩"] is None
    detected = eh.detect_score_columns(df)
    assert detected["problems"] == []
    assert dict(detected["subjects"]).get("数学成绩") == "数学"
    scores = eh.extract_scores(df, detected)
    by_name = {r["name"]: r for r in scores}
    assert by_name["学生01"]["scores"]["数学"] == 88.0
    assert by_name["学生03"]["scores"]["数学"] is None
    assert any("缺分科目：数学" in p for p in by_name["学生03"]["problems"])


def test_docx_score_dataframe(tmp_path):
    path = tmp_path / "score.docx"
    _make_docx(path)
    df = sdp.docx_score_dataframe(path)
    assert df is not None
    _assert_dataframe_shape(df)


def test_docx_bytes_input(tmp_path):
    path = tmp_path / "score.docx"
    _make_docx(path)
    df = sdp.docx_score_dataframe(path.read_bytes())
    assert df is not None and "姓名" in df.columns


def test_docx_no_table_returns_none(tmp_path):
    from docx import Document
    path = tmp_path / "plain.docx"
    doc = Document()
    doc.add_paragraph("只有文字，没有表格")
    doc.save(path)
    assert sdp.docx_score_dataframe(path) is None


def test_pdf_score_dataframe(tmp_path):
    path = tmp_path / "score.pdf"
    _make_pdf(path)
    df = sdp.pdf_score_dataframe(path)
    assert df is not None
    _assert_dataframe_shape(df)


def test_pdf_blank_returns_none(tmp_path):
    import pymupdf
    path = tmp_path / "blank.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    assert sdp.pdf_score_dataframe(path) is None


def test_docx_import_to_db_roundtrip(tmp_path, session):
    path = tmp_path / "score.docx"
    _make_docx(path)
    df = sdp.docx_score_dataframe(path)
    detected = eh.detect_score_columns(df)
    records = eh.extract_scores(df, detected)
    exam = exam_service.create_exam(
        session, "导入考试", exam_date=date(2026, 5, 1),
        full_scores={"数学": 100, "语文": 100})
    session.flush()
    result = exam_service.import_scores(session, exam.id, records)
    session.commit()
    assert result["created_students"] == 3
    assert result["scores_written"] == 5  # 3 名学生，数学缺考 1 条
    # 重复导入走更新而非新建
    result2 = exam_service.import_scores(session, exam.id, records)
    session.commit()
    assert result2["created_students"] == 0
    assert result2["scores_updated"] == 5
    assert session.query(student_service.Student).count() == 3


def test_preview_round_trip():
    records = [
        {"row_no": 2, "name": "甲", "class_name": "一班",
         "scores": {"数学": 90.0}, "problems": []},
        {"row_no": 3, "name": "乙", "class_name": None,
         "scores": {"数学": None}, "problems": ["缺分科目：数学"]},
    ]
    frame, subjects = eh.scores_preview_frame(records)
    assert subjects == ["数学"]
    assert list(frame.columns) == ["Excel行号", "姓名", "班级", "数学", "问题"]
    back = eh.preview_to_records(frame, subjects)
    assert back[0]["name"] == "甲" and back[0]["scores"]["数学"] == 90.0
    assert back[1]["name"] == "乙" and back[1]["scores"]["数学"] is None
    assert any("缺分科目：数学" in p for p in back[1]["problems"])
    # 老师在预览里改分
    edited = frame.copy()
    edited.loc[0, "数学"] = "95"
    back2 = eh.preview_to_records(edited, subjects)
    assert back2[0]["scores"]["数学"] == 95.0


def test_rank_chart_data_sorted_and_excludes_none():
    rows = [
        {"name": "甲", "class_name": "一班", "total": 70.0},
        {"name": "乙", "class_name": "一班", "total": 95.0},
        {"name": "丙", "class_name": "一班", "total": None},  # 缺分排除
        {"name": "丁", "class_name": "一班", "total": 88.0},
    ]
    names, values = analysis_mod.rank_chart_data(rows, "total")
    assert names == ["甲（一班）", "丁（一班）", "乙（一班）"]
    assert values == [70.0, 88.0, 95.0]  # 升序，条形图 reversed 后最高在最上


def test_rank_chart_data_subject_key():
    rows = [{"name": "甲", "class_name": None, "数学": 60.0},
            {"name": "乙", "class_name": None, "数学": 55.0}]
    names, values = analysis_mod.rank_chart_data(rows, "数学")
    assert names == ["乙", "甲"] and values == [55.0, 60.0]


def test_rank_chart_data_low_to_high_order():
    rows = [
        {"name": "甲", "total": 70.0},
        {"name": "乙", "total": 95.0},
        {"name": "丙", "total": 88.0},
    ]
    names, values = analysis_mod.rank_chart_data(rows, "total", descending=True)
    assert names == ["乙", "丙", "甲"]
    assert values == [95.0, 88.0, 70.0]


def test_apply_limit_trend():
    names = [f"第{i}次" for i in range(1, 12)]  # 11 场
    assert analysis_mod._apply_limit(names, 3) == ["第9次", "第10次", "第11次"]
    assert analysis_mod._apply_limit(names, 5) == names[-5:]
    assert analysis_mod._apply_limit(names, 10) == names[-10:]
    assert analysis_mod._apply_limit(names, None) == names
    # 不足所选次数显示全部
    assert analysis_mod._apply_limit(["a", "b"], 10) == ["a", "b"]
