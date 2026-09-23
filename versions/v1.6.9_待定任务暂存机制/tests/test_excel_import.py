# -*- coding: utf-8 -*-
"""
学生/成绩 Excel 识别与入库全链路测试（内存数据库）。

用 pandas 现造 DataFrame，不落真实文件，覆盖：列识别、别名、
自动建学生、缺考排除、重复导入更新、唯一约束不报错。
"""

from datetime import date

import pandas as pd
import pytest

from utils import excel_handler as eh
from utils import exam_service as es
from utils import student_service as ss


# ---------------------------------------------------------------------------
# 表头识别
# ---------------------------------------------------------------------------

def test_detect_student_columns_aliases():
    df = pd.DataFrame({"名字": ["张三"], "编号": ["001"], "班别": ["一班"], "性別": ["男"]})
    det = eh.detect_student_columns(df)
    assert det["mapping"]["name"] == "名字"
    assert det["mapping"]["student_no"] == "编号"
    assert det["mapping"]["class_name"] == "班别"
    assert det["mapping"]["gender"] == "性別"
    assert det["problems"] == []


def test_detect_student_columns_missing_name():
    df = pd.DataFrame({"学号": ["001"], "班级": ["一班"]})
    det = eh.detect_student_columns(df)
    assert det["mapping"]["name"] is None
    assert any("姓名" in p for p in det["problems"])


def test_detect_score_columns_strips_suffix():
    # "数学成绩""英语分数" 应被剥成科目名 数学/英语；名次列要排除
    df = pd.DataFrame({
        "姓名": ["张三", "李四"],
        "名次": [1, 2],
        "数学成绩": [90, 80],
        "英语分数": [70, 60],
    })
    det = eh.detect_score_columns(df)
    assert det["name_col"] == "姓名"
    subjects = dict(det["subjects"])
    assert subjects["数学成绩"] == "数学"
    assert subjects["英语分数"] == "英语"
    assert "名次" not in subjects
    assert det["problems"] == []


def test_detect_score_columns_no_subject():
    df = pd.DataFrame({"姓名": ["张三"], "备注": ["x"]})
    det = eh.detect_score_columns(df)
    assert any("成绩列" in p for p in det["problems"])


def test_extract_scores_flags_problems():
    df = pd.DataFrame({"姓名": ["张三", None], "数学": [90, 70]})
    det = eh.detect_score_columns(df)
    records = eh.extract_scores(df, det)
    assert len(records) == 2
    zhang = [r for r in records if r["name"] == "张三"][0]
    assert zhang["scores"]["数学"] == 90 and zhang["problems"] == []
    missing_name = [r for r in records if r["name"] is None][0]
    assert "缺姓名" in missing_name["problems"]


def test_missing_score_becomes_none():
    df = pd.DataFrame({"姓名": ["张三"], "数学": [None]})
    det = eh.detect_score_columns(df)
    # 整列都没数字时识别不到科目；这里补一个有值的行
    df = pd.DataFrame({"姓名": ["张三", "李四"], "数学": [None, 80]})
    det = eh.detect_score_columns(df)
    records = eh.extract_scores(df, det)
    zhang = [r for r in records if r["name"] == "张三"][0]
    assert zhang["scores"]["数学"] is None
    assert any("缺分科目" in p for p in zhang["problems"])


def test_extract_students_skips_blank_rows():
    df = pd.DataFrame({"姓名": ["张三", None], "学号": ["001", None],
                       "班级": [None, None], "备注": [None, None]})
    det = eh.detect_student_columns(df)
    records = eh.extract_students(df, det["mapping"])
    assert len(records) == 1 and records[0]["name"] == "张三"


# ---------------------------------------------------------------------------
# 入库全链路
# ---------------------------------------------------------------------------

def _student_df():
    return pd.DataFrame({
        "姓名": ["张三", "李四", "王五"],
        "学号": ["001", "002", "003"],
        "班级": ["一班", "一班", "二班"],
    })


def _score_df():
    return pd.DataFrame({
        "姓名": ["张三", "李四", "王五"],
        "班级": ["一班", "一班", "二班"],
        "数学": [90, 80, 70],
        "语文": [88, 65, 92],
    })


def test_bulk_import_students(session):
    det = eh.detect_student_columns(_student_df())
    records = eh.extract_students(_student_df(), det["mapping"])
    result = ss.bulk_import_students(session, records)
    session.commit()
    assert result == {"created": 3, "updated": 0, "skipped": 0}
    assert ss.list_classes(session) == ["一班", "二班"]
    # 再导一次：全部变成更新，不重复建
    result2 = ss.bulk_import_students(session, records)
    session.commit()
    assert result2["created"] == 0 and result2["updated"] == 3


def test_import_scores_creates_students_and_rows(session):
    exam = es.create_exam(session, "第一次月考", exam_date=date(2026, 9, 1),
                          full_scores={"数学": 100, "语文": 100})
    session.commit()
    det = eh.detect_score_columns(_score_df())
    records = eh.extract_scores(_score_df(), det)
    result = es.import_scores(session, exam.id, records)
    session.commit()
    assert result["created_students"] == 3
    assert result["scores_written"] == 6
    assert result["scores_updated"] == 0

    rows = es.exam_score_rows(session, exam.id)
    assert len(rows) == 3
    zhang = [r for r in rows if r["name"] == "张三"][0]
    assert zhang["数学"] == 90 and zhang["total"] == 178
    assert sorted(es.exam_subjects(session, exam.id)) == ["数学", "语文"]


def test_import_scores_without_student_list_autocreate(session):
    # 没先导名单，直接导成绩也应自动建学生
    exam = es.create_exam(session, "测验", exam_date=date(2026, 9, 1))
    session.commit()
    det = eh.detect_score_columns(_score_df())
    es.import_scores(session, exam.id, eh.extract_scores(_score_df(), det))
    session.commit()
    assert len(ss.list_students(session)) == 3


def test_reimport_scores_updates_not_duplicates(session):
    exam = es.create_exam(session, "月考", exam_date=date(2026, 9, 1))
    session.commit()
    det = eh.detect_score_columns(_score_df())
    es.import_scores(session, exam.id, eh.extract_scores(_score_df(), det))
    session.commit()

    # 张三数学从 90 改成 95，重新导入
    df2 = _score_df()
    df2.loc[df2["姓名"] == "张三", "数学"] = 95
    det2 = eh.detect_score_columns(df2)
    result = es.import_scores(session, exam.id, eh.extract_scores(df2, det2))
    session.commit()
    assert result["scores_updated"] == 6 and result["scores_written"] == 0

    rows = es.exam_score_rows(session, exam.id)
    zhang = [r for r in rows if r["name"] == "张三"][0]
    assert zhang["数学"] == 95
    # 仍然只有 3 个学生、每人每科一条
    from models.models import Score
    assert session.query(Score).count() == 6


def test_analyze_exam_ranks_and_stats(session):
    exam = es.create_exam(session, "月考", exam_date=date(2026, 9, 1),
                          full_scores={"数学": 100})
    session.commit()
    df = pd.DataFrame({"姓名": ["张三", "李四", "王五"],
                       "班级": ["一班", "一班", "一班"],
                       "数学": [100, 100, 50]})
    det = eh.detect_score_columns(df)
    es.import_scores(session, exam.id, eh.extract_scores(df, det))
    session.commit()

    data = es.analyze_exam(session, exam.id)
    math_stat = data["subject_stats"]["数学"]
    assert math_stat["count"] == 3
    assert math_stat["max"] == 100 and math_stat["min"] == 50
    # 两个 100 并列第 1，50 分第 3
    by_name = {r["name"]: r for r in data["rows"]}
    assert by_name["张三"]["数学_rank"] == 1
    assert by_name["李四"]["数学_rank"] == 1
    assert by_name["王五"]["数学_rank"] == 3
    # 50 分不及格 → 及格率 2/3
    assert math_stat["pass_rate"] == round(2 / 3, 4)


def test_analyze_exam_class_filter(session):
    exam = es.create_exam(session, "月考", exam_date=date(2026, 9, 1),
                          full_scores={"数学": 100})
    session.commit()
    df = pd.DataFrame({"姓名": ["张三", "王五"],
                       "班级": ["一班", "二班"], "数学": [90, 40]})
    det = eh.detect_score_columns(df)
    es.import_scores(session, exam.id, eh.extract_scores(df, det))
    session.commit()
    data1 = es.analyze_exam(session, exam.id, class_name="一班")
    assert len(data1["rows"]) == 1 and data1["rows"][0]["name"] == "张三"


def test_trend_over_three_exams(session):
    dates_exams = [date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)]
    scores_seq = [80, 85, 90]
    exam_ids = []
    for d, sc in zip(dates_exams, scores_seq):
        exam = es.create_exam(session, f"考试{d.day}", exam_date=d,
                              full_scores={"数学": 100})
        session.commit()
        exam_ids.append(exam.id)
        df = pd.DataFrame({"姓名": ["张三"], "班级": ["一班"], "数学": [sc]})
        det = eh.detect_score_columns(df)
        es.import_scores(session, exam.id, eh.extract_scores(df, det))
        session.commit()

    student = ss.find_student(session, "张三", "一班")
    history = es.student_scores_over_time(session, student.id)
    assert [h["数学"] for h in history] == [80, 85, 90]

    # 第三次考试相对第一次：应有进退步数据（跨相邻考试）
    last = es.analyze_exam(session, exam_ids[-1])
    delta = last["deltas"][student.id]
    assert delta["score_delta"] == 5
# ---------------------------------------------------------------------------
# v1.2.1：学生可编辑表格、考试满分逐行编辑、个人趋势合并
# ---------------------------------------------------------------------------

import json  # noqa: E402
import pytest  # noqa: E402
from models.models import Score  # noqa: E402


def test_sync_students_create_update_delete_and_cascade(session):
    stu1, _ = ss.get_or_create_student(session, "张三", "一班", "001")
    stu2, _ = ss.get_or_create_student(session, "李四", "一班", "002")
    stu3, _ = ss.get_or_create_student(session, "王五", "二班", "003")
    exam = es.create_exam(session, "删除级联考试", exam_date=date(2026, 9, 1),
                          full_scores={"数学": 100})
    session.flush()
    es.import_scores(session, exam.id, [
        {"name": "王五", "class_name": "二班", "scores": {"数学": 80}},
    ])
    session.commit()

    rows = [
        {"学生ID": stu1.id, "姓名": "张三改", "学号": "001", "班级": "一班",
         "性别": "男", "标签": "积极", "备注": "更新"},
        {"学生ID": None, "姓名": "赵六", "学号": "004", "班级": "一班",
         "性别": "女", "标签": "", "备注": ""},
        {"学生ID": stu3.id, "姓名": "王五", "学号": "003", "班级": "二班",
         "性别": "", "标签": "", "备注": ""},
    ]
    result = ss.sync_students(session, rows, {stu1.id, stu2.id, stu3.id})
    session.commit()

    assert result == {"created": 1, "updated": 2, "deleted": 1}
    assert session.get(type(stu1), stu1.id).name == "张三改"
    assert ss.find_student(session, "赵六", "一班") is not None
    assert session.get(type(stu2), stu2.id) is None
    # 被删学生的成绩也由 ORM 级联删除
    assert session.query(Score).filter(Score.student_id == stu2.id).count() == 0


def test_sync_students_rejects_blank_name(session):
    with pytest.raises(ValueError, match="姓名不能为空"):
        ss.sync_students(session, [
            {"学生ID": None, "姓名": "  ", "班级": "一班"},
        ], set())


def test_sync_students_rejects_duplicate_pair_in_rows(session):
    with pytest.raises(ValueError, match="重复"):
        ss.sync_students(session, [
            {"学生ID": None, "姓名": "张三", "班级": "一班"},
            {"学生ID": None, "姓名": "张三", "班级": "一班"},
        ], set())


def test_sync_students_rejects_duplicate_pair_in_database(session):
    ss.get_or_create_student(session, "张三", "一班")
    session.commit()
    with pytest.raises(ValueError, match="学生已存在"):
        ss.sync_students(session, [
            {"学生ID": None, "姓名": "张三", "班级": "一班"},
        ], set())


def test_rows_to_full_scores_normalizes_and_ignores_blank():
    rows = [
        {"subject": " 数学 ", "score": 120},
        {"subject": "", "score": 100},
        {"学科": "语文", "满分": "90"},
    ]
    assert es.rows_to_full_scores(rows) == {"数学": 120.0, "语文": 90.0}


@pytest.mark.parametrize("rows", [
    [{"subject": "数学", "score": 0}],
    [{"subject": "数学", "score": -1}],
    [{"subject": "数学", "score": "abc"}],
])
def test_rows_to_full_scores_rejects_invalid_score(rows):
    with pytest.raises(ValueError):
        es.rows_to_full_scores(rows)


def test_rows_to_full_scores_rejects_duplicate_subject():
    rows = [{"subject": "数学", "score": 100},
            {"subject": "数学", "score": 120}]
    with pytest.raises(ValueError, match="学科重复"):
        es.rows_to_full_scores(rows)


def test_exam_full_scores_json_roundtrip(session):
    exam = es.create_exam(
        session, "月考", exam_date=date(2026, 9, 1),
        full_scores=es.rows_to_full_scores([
            {"subject": "数学", "score": 120},
            {"subject": "语文", "score": 100},
        ]))
    session.commit()
    es.update_exam(session, exam.id, full_scores=es.rows_to_full_scores([
        {"subject": "数学", "score": 150},
        {"subject": "英语", "score": 100},
    ]))
    session.commit()
    saved = json.loads(session.get(type(exam), exam.id).full_scores)
    assert saved == {"数学": 150.0, "英语": 100.0}


def test_student_scores_over_time_multi_subjects_with_missing_score(session):
    exam_specs = [
        ("第一次", date(2026, 9, 1), {"数学": 90, "语文": 80}),
        ("第二次", date(2026, 10, 1), {"数学": 70}),  # 语文缺考
        ("第三次", date(2026, 11, 1), {"数学": 85, "语文": 75}),
    ]
    for name, exam_date, scores in exam_specs:
        exam = es.create_exam(session, name, exam_date=exam_date,
                              full_scores={"数学": 100, "语文": 100})
        session.flush()
        es.import_scores(session, exam.id, [
            {"name": "张三", "class_name": "一班", "scores": scores},
        ])
    session.commit()

    student = ss.find_student(session, "张三", "一班")
    history = es.student_scores_over_time(session, student.id)
    assert [h["exam_name"] for h in history] == ["第一次", "第二次", "第三次"]
    assert [h["数学"] for h in history] == [90, 70, 85]
    assert [h["语文"] for h in history] == [80, None, 75]
    # 缺考不补 0，总分只累加实际参加的科目
    assert [h["total"] for h in history] == [170, 70, 160]


# ---------------------------------------------------------------------------
# v1.4.0 成绩导入模板
# ---------------------------------------------------------------------------

def test_score_template_columns_and_sample_row():
    df = eh.score_template_dataframe()
    assert list(df.columns) == eh.SCORE_TEMPLATE_COLUMNS
    assert eh.SCORE_TEMPLATE_COLUMNS == [
        "姓名", "学号", "班级",
        "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
    ]
    assert len(df) == 1  # 第二行（数据首行）是一条示例
    assert df.iloc[0]["姓名"] == "张三"


def test_score_template_score_columns_recognized():
    df = eh.score_template_dataframe()
    detected = eh.detect_score_columns(df)
    assert detected["problems"] == []
    # 学号、班级被识别为元数据列，不会变成科目
    subject_names = {name for _col, name in detected["subjects"]}
    assert subject_names == {
        "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"}
    assert detected["name_col"] == "姓名"
    records = eh.extract_scores(df, detected)
    assert len(records) == 1
    rec = records[0]
    assert rec["name"] == "张三"
    assert rec["class_name"] == "一班"
    # 9 科全部提取为非空数字
    assert len(rec["scores"]) == 9
    assert all(v is not None and v > 0 for v in rec["scores"].values())
