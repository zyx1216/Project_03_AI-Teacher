# -*- coding: utf-8 -*-
"""作业成绩测试：总分 Excel 导入/更新、手动录分排名、逐题作答正确率、进退步。"""

import pandas as pd

from utils import homework_service as hw
from utils import homework_score_service as hs
from utils import question_service as qs
from utils import student_service as ss
from utils import excel_handler as eh


def _homework_with_questions(session, n=2, class_name="一班"):
    """建一份带 n 道题、每题 10 分的作业。"""
    h = hw.create_homework(session, "作业", class_name=class_name, total_score=100)
    ids = []
    for i in range(n):
        data = qs.validate_question({
            "content": f"第{i+1}题", "question_type": "choice",
            "difficulty": 2, "answer": "A", "knowledge_points": "方程"})
        q = qs.create_question(session, data, source="manual", status="approved")
        ids.append(q.id)
    hw.add_questions(session, h.id, ids)
    for link, _q in hw.homework_questions(session, h.id):
        link.score = 10
    session.flush()
    return h, ids


def _students(session, names, class_name="一班"):
    out = []
    for name in names:
        stu, _ = ss.get_or_create_student(session, name, class_name)
        out.append(stu)
    session.flush()
    return out


def test_total_scores_excel_import_and_update(session):
    h, _ = _homework_with_questions(session)
    df = pd.DataFrame({"姓名": ["学生01", "学生02"], "数学作业分数": [90, 80]})
    detected = eh.detect_score_columns(df)
    assert detected["name_col"] == "姓名"
    extracted = eh.extract_scores(df, detected)
    records = [{"name": r["name"], "class_name": r["class_name"],
                "score": list(r["scores"].values())[0]} for r in extracted]
    result = hs.import_total_scores(session, h.id, records)
    session.flush()
    assert result["written"] == 2 and result["created_students"] == 2

    # 重复导入：更新而非新增，学生不重复建
    df2 = pd.DataFrame({"姓名": ["学生01", "学生03"], "分数": [95, 70]})
    detected2 = eh.detect_score_columns(df2)
    extracted2 = eh.extract_scores(df2, detected2)
    records2 = [{"name": r["name"], "class_name": "一班",
                 "score": list(r["scores"].values())[0]} for r in extracted2]
    result2 = hs.import_total_scores(session, h.id, records2)
    assert result2["updated"] == 1 and result2["written"] == 1
    rows = {r["name"]: r["score"] for r in hs.score_rows(session, h.id)}
    assert rows["学生01"] == 95 and rows["学生03"] == 70
    assert len([r for r in rows]) == 3


def test_manual_save_and_competition_rank(session):
    h, _ = _homework_with_questions(session)
    stus = _students(session, ["甲", "乙", "丙"])
    hs.save_total_score(session, h.id, stus[0].id, 90)
    hs.save_total_score(session, h.id, stus[1].id, 90)
    hs.save_total_score(session, h.id, stus[2].id, 80)
    session.flush()
    data = hs.analyze_homework(session, h.id)
    rank_of = {r["name"]: r["rank"] for r in data["rows"]}
    assert rank_of["甲"] == 1 and rank_of["乙"] == 1 and rank_of["丙"] == 3


def test_submission_rate_and_absent(session):
    h, _ = _homework_with_questions(session)
    stus = _students(session, ["甲", "乙", "丙", "丁"])
    hs.save_total_score(session, h.id, stus[0].id, 90)
    hs.save_total_score(session, h.id, stus[1].id, 80)
    # 丙、丁不交
    session.flush()
    data = hs.analyze_homework(session, h.id)
    assert data["overall"]["submitted"] == 2
    assert data["overall"]["total"] == 4
    assert data["overall"]["submission_rate"] == 0.5


def test_per_question_and_top_wrong(session):
    h, qids = _homework_with_questions(session, n=3)
    stus = _students(session, ["甲", "乙", "丙", "丁", "戊"])
    # 第1题：4 错 1 对（典型错题）；第2题：1 错 4 对；第3题全对
    for i, stu in enumerate(stus):
        hs.save_answers(session, h.id, [
            {"student_id": stu.id, "question_id": qids[0], "order_no": 1,
             "is_correct": i == 0, "earned_score": 10 if i == 0 else 2,
             "error_type": "计算错误" if i else None},
            {"student_id": stu.id, "question_id": qids[1], "order_no": 2,
             "is_correct": i != 0, "earned_score": 10 if i != 0 else 0},
            {"student_id": stu.id, "question_id": qids[2], "order_no": 3,
             "is_correct": True, "earned_score": 10},
        ])
    session.flush()
    data = hs.analyze_homework(session, h.id)
    pq = {item["question_id"]: item for item in data["per_question"]}
    assert pq[qids[0]]["rate"] == 0.2 and pq[qids[0]]["typical"] is True
    assert pq[qids[1]]["rate"] == 0.8 and pq[qids[1]]["typical"] is False
    # 高频错题第一名是第1题（错 4 人）
    assert data["top_wrong"][0]["question_id"] == qids[0]
    assert data["top_wrong"][0]["wrong"] == 4


def test_previous_homework_deltas(session):
    stus = _students(session, ["甲", "乙"])
    h1 = hw.create_homework(session, "第一次", class_name="一班")
    h2 = hw.create_homework(session, "第二次", class_name="一班")
    hs.save_total_score(session, h1.id, stus[0].id, 80)
    hs.save_total_score(session, h1.id, stus[1].id, 70)
    hs.save_total_score(session, h2.id, stus[0].id, 90)  # +10
    hs.save_total_score(session, h2.id, stus[1].id, 60)  # -10
    session.flush()
    assert hs.previous_homework(session, h2.id).id == h1.id
    data = hs.analyze_homework(session, h2.id)
    assert data["deltas"] == {stus[0].id: 10, stus[1].id: -10}