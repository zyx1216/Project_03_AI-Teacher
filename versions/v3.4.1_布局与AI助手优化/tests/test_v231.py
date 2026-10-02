# -*- coding: utf-8 -*-
"""v2.3.1 代码审查与多样化适配修复测试。"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from utils import excel_handler as eh
from utils import question_service as qs


# ---------------------------------------------------------------------------
# 性别归一
# ---------------------------------------------------------------------------

def test_gender_male_variants():
    for value in ["男", "男生", "M", "m", "male", "1"]:
        assert eh.normalize_gender(value) == "男", value


def test_gender_female_variants():
    for value in ["女", "女生", "F", "f", "female", "0"]:
        assert eh.normalize_gender(value) == "女", value


def test_gender_unknown_is_none():
    assert eh.normalize_gender("未知") is None
    assert eh.normalize_gender("") is None
    assert eh.normalize_gender(None) is None


def test_extract_students_normalizes_gender():
    df = pd.DataFrame({
        "姓名": ["甲", "乙", "丙"],
        "性别": ["M", "女生", "未知"],
        "班级": ["1班"] * 3,
    })
    detected = eh.detect_student_columns(df)
    records = eh.extract_students(df, detected["mapping"])
    assert [r["gender"] for r in records] == ["男", "女", None]


# ---------------------------------------------------------------------------
# 成绩科目别名
# ---------------------------------------------------------------------------

def test_subject_alias_to_standard():
    assert eh.normalize_subject_name("Chinese") == "语文"
    assert eh.normalize_subject_name("数 学") == "数学"
    assert eh.normalize_subject_name("English成绩") == "英语"
    assert eh.normalize_subject_name("语文") == "语文"
    assert eh.normalize_subject_name("数学成绩") == "数学"


def test_subject_non_standard_returns_none():
    assert eh.normalize_subject_name("科学") is None
    assert eh.normalize_subject_name("道德与法治") is None


def test_detect_score_columns_non_standard_kept():
    df = pd.DataFrame({
        "姓名": ["甲"],
        "Chinese": [85],
        "数 学": [90],
        "科学": [88],
    })
    detected = eh.detect_score_columns(df)
    subjects = dict(detected["subjects"])
    assert subjects["Chinese"] == "语文"
    assert subjects["数 学"] == "数学"
    assert subjects["科学"] == "科学"  # 非标保留原名
    assert detected["non_standard_subjects"] == ["科学"]


def test_collect_non_standard_subjects():
    records = [{"scores": {"语文": 80, "科学": 90, "道德与法治": 70}}]
    assert eh.collect_non_standard_subjects(records) == ["科学", "道德与法治"]


# ---------------------------------------------------------------------------
# 长表成绩
# ---------------------------------------------------------------------------

def test_long_table_merges_by_student():
    df = pd.DataFrame({
        "姓名": ["甲", "甲", "乙"],
        "班级": ["1班", "1班", "1班"],
        "科目": ["Chinese", "数 学", "科学"],
        "分数": [80, 90, 70],
    })
    records = eh.parse_long_table(df)
    assert records is not None
    first = next(r for r in records if r["name"] == "甲")
    assert first["scores"] == {"语文": 80.0, "数学": 90.0}
    second = next(r for r in records if r["name"] == "乙")
    assert second["scores"] == {"科学": 70.0}
    assert eh.collect_non_standard_subjects(records) == ["科学"]


def test_long_table_with_score_suffix_header():
    df = pd.DataFrame({
        "姓名": ["甲"],
        "学科": ["数学"],
        "score": [95],
    })
    records = eh.parse_long_table(df)
    assert records is not None
    assert records[0]["scores"] == {"数学": 95.0}


def test_wide_table_not_treated_as_long():
    # 宽表无「科目」列，parse_long_table 应返回 None。
    df = pd.DataFrame({"姓名": ["甲"], "语文": [80], "数学": [90]})
    assert eh.parse_long_table(df) is None


def test_parse_long_table_missing_required_returns_none():
    df = pd.DataFrame({"姓名": ["甲"], "科目": ["语文"]})  # 缺分数列
    assert eh.parse_long_table(df) is None


# ---------------------------------------------------------------------------
# 难度方言
# ---------------------------------------------------------------------------

def test_difficulty_text_variants():
    assert qs.normalize_difficulty("易") == 1
    assert qs.normalize_difficulty("中") == 2
    assert qs.normalize_difficulty("难") == 3
    assert qs.normalize_difficulty("基础") == 1
    assert qs.normalize_difficulty("中等") == 2
    assert qs.normalize_difficulty("拓展") == 3


def test_difficulty_stars():
    assert qs.normalize_difficulty("★") == 1
    assert qs.normalize_difficulty("★★") == 2
    assert qs.normalize_difficulty("★★★") == 3
    assert qs.normalize_difficulty("★★★★") == 3  # 封顶
    assert qs.normalize_difficulty("*") == 1


def test_difficulty_numeric_unchanged():
    assert qs.normalize_difficulty(1) == 1
    assert qs.normalize_difficulty(2) == 2
    assert qs.normalize_difficulty(3) == 3
    assert qs.normalize_difficulty(9) == 3


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _xlsx_bytes(rows) -> bytes:
    """把 dict 行列表写成 xlsx 字节。"""
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def _feature_file(path):
    import json
    path.write_text(json.dumps({
        "materials_subject": "数学",
        "lesson_plan_subject": "数学",
        "question_gen_subject": "数学",
        "question_bank_subject": "数学",
        "homework_list_subject": "数学",
        "homework_analysis_subject": "数学",
        "wrong_book_subject": "数学",
    }, ensure_ascii=False), encoding="utf-8")


def _skip_onboarding(db_file):
    import json
    (db_file.parent / "onboarding.json").write_text(json.dumps({
        "completed_steps": [], "skipped": True,
        "snooze_until": "", "updated_at": ""}, ensure_ascii=False),
        encoding="utf-8")


def test_app_student_import_gender_preview(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_sub

    db_file = tmp_path / "stu231.db"
    _skip_onboarding(db_file)
    feature = tmp_path / "feature.json"
    _feature_file(feature)
    at = AppTest.from_string(_isolated_app_code(db_file, feature),
                             default_timeout=40)
    at.run()
    goto_sub(at, "analysis_tab", "学生管理", "📊 学情")

    data = _xlsx_bytes([
        {"姓名": "甲", "性别": "M", "班级": "1班"},
        {"姓名": "乙", "性别": "女生", "班级": "1班"},
    ])
    next(x for x in at.file_uploader if x.key == "student_upload").upload(
        "名单.xlsx", data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").run()
    assert not at.exception, [str(e) for e in at.exception]
    # 预览表中性别已归一。
    assert any("男" in str(x.value) for x in at.dataframe)


def test_app_score_wide_alias_and_nonstandard(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_sub

    db_file = tmp_path / "wide231.db"
    _skip_onboarding(db_file)
    feature = tmp_path / "feature.json"
    _feature_file(feature)
    at = AppTest.from_string(_isolated_app_code(db_file, feature),
                             default_timeout=40)
    at.run()
    goto_sub(at, "analysis_tab", "成绩管理", "📊 学情")
    # 成绩导入在折叠 expander 内，AppTest 折叠时不实例化内容，先展开它。
    at.session_state["score_import_expander"] = True
    at.run()
    # 空库无已有考试，切到“新建考试”，否则面板提前返回、上传控件不渲染。
    at.session_state["score_import_target_mode"] = "新建考试"
    at.run()

    data = _xlsx_bytes([
        {"姓名": "甲", "班级": "1班", "Chinese": 85,
         "数 学": 90, "科学": 88},
    ])
    next(x for x in at.file_uploader if x.key == "score_upload").upload(
        "成绩.xlsx", data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").run()
    assert not at.exception, [str(e) for e in at.exception]
    info_text = " ".join(str(x.value) for x in at.info)
    assert "科学" in info_text
    assert "标准学科" in info_text


def test_app_score_long_table(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_sub

    db_file = tmp_path / "long231.db"
    _skip_onboarding(db_file)
    feature = tmp_path / "feature.json"
    _feature_file(feature)
    at = AppTest.from_string(_isolated_app_code(db_file, feature),
                             default_timeout=40)
    at.run()
    goto_sub(at, "analysis_tab", "成绩管理", "📊 学情")
    at.session_state["score_import_expander"] = True
    at.run()
    # 空库切到新建考试，否则上传控件不渲染。
    at.session_state["score_import_target_mode"] = "新建考试"
    at.run()

    data = _xlsx_bytes([
        {"姓名": "甲", "班级": "1班", "科目": "语文", "分数": 80},
        {"姓名": "甲", "班级": "1班", "科目": "数学", "分数": 90},
        {"姓名": "乙", "班级": "1班", "科目": "科学", "分数": 70},
    ])
    next(x for x in at.file_uploader if x.key == "score_upload").upload(
        "长表.xlsx", data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").run()
    assert not at.exception, [str(e) for e in at.exception]
    toast_text = " ".join(str(x.value) for x in at.toast)
    assert "长表" in toast_text
    info_text = " ".join(str(x.value) for x in at.info)
    assert "科学" in info_text

