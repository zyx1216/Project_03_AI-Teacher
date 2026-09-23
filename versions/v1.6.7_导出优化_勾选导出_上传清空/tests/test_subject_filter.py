# -*- coding: utf-8 -*-
"""v1.2.4 学科深化测试：题库/作业/错题按学科过滤、单科分析、班级单科趋势。"""

from datetime import date

from utils import exam_service as es
from utils import homework_score_service as hscore
from utils import homework_service as hw
from utils import question_service as qs
from utils import student_service as ss


def _question(session, content, subject, qtype="solution", diff=2,
              status="approved", kp="知识点"):
    data = qs.validate_question({
        "content": content, "question_type": qtype, "difficulty": diff,
        "answer": "参考答案", "analysis": "解析", "knowledge_points": kp})
    return qs.create_question(session, data, source="manual",
                              status=status, subject=subject)


# ---------------------------------------------------------------------------
# 题库
# ---------------------------------------------------------------------------

def test_create_question_marks_explicit_subject(session):
    q = _question(session, "物理题", "物理")
    session.flush()
    assert q.subject == "物理"


def test_list_questions_filters_by_subject(session):
    _question(session, "数学题甲", "数学")
    _question(session, "数学题乙", "数学")
    _question(session, "物理题甲", "物理")
    session.flush()
    math_qs = qs.list_questions(session, subject="数学")
    phys_qs = qs.list_questions(session, subject="物理")
    assert len(math_qs) == 2 and all(q.subject == "数学" for q in math_qs)
    assert len(phys_qs) == 1 and phys_qs[0].content == "物理题甲"
    # 不传 subject 维持原行为：不过滤
    assert len(qs.list_questions(session)) == 3


def test_list_questions_subject_combined_with_status(session):
    _question(session, "数学待审", "数学", status="pending")
    _question(session, "物理已审", "物理", status="approved")
    session.flush()
    picked = qs.list_questions(session, status="approved", subject="数学")
    assert picked == []
    picked2 = qs.list_questions(session, status="approved", subject="物理")
    assert len(picked2) == 1


# ---------------------------------------------------------------------------
# 作业 / 模板
# ---------------------------------------------------------------------------

def test_homework_subject_tag_and_filter(session):
    h_math = hw.create_homework(session, "数学作业", subject="数学")
    h_phys = hw.create_homework(session, "物理作业", subject="物理")
    session.flush()
    assert h_math.subject == "数学" and h_phys.subject == "物理"
    math_list = hw.list_homeworks(session, subject="数学")
    phys_list = hw.list_homeworks(session, subject="物理")
    assert [h.id for h in math_list] == [h_math.id]
    assert [h.id for h in phys_list] == [h_phys.id]
    # 不传 subject 不过滤
    assert len(hw.list_homeworks(session)) == 2


def test_template_inherits_source_subject(session):
    src = hw.create_homework(session, "数学源作业", subject="数学")
    tpl = hw.save_as_template(session, src.id, "数学模板")
    session.flush()
    assert tpl.is_template is True and tpl.subject == "数学"
    tpls = hw.list_homeworks(session, templates=True, subject="数学")
    assert [t.id for t in tpls] == [tpl.id]
    assert hw.list_homeworks(session, templates=True, subject="物理") == []


# ---------------------------------------------------------------------------
# 错题按学科
# ---------------------------------------------------------------------------

def test_wrong_answers_filter_by_homework_subject(session):
    # 数学作业 + 物理作业，各 1 题 1 学生 1 错题
    student, _ = ss.get_or_create_student(session, "学生01", "一班")
    results = {}
    for subject in ("数学", "物理"):
        h = hw.create_homework(session, f"{subject}作业", subject=subject)
        q = _question(session, f"{subject}错题", subject)
        hw.add_questions(session, h.id, [q.id])
        session.flush()
        results[subject] = (h, q)
    session.flush()
    for subject, (h, q) in results.items():
        hscore.save_answers(session, h.id, [{
            "student_id": student.id, "question_id": q.id,
            "order_no": 1, "is_correct": False, "error_type": "概念错误"}])
    session.flush()

    math_wrong = hscore.list_wrong_answers(session, subject="数学")
    phys_wrong = hscore.list_wrong_answers(session, subject="物理")
    assert len(math_wrong) == 1 and math_wrong[0]["content"] == "数学错题"
    assert len(phys_wrong) == 1 and phys_wrong[0]["content"] == "物理错题"
    # 不传学科：两科错题都在
    assert len(hscore.list_wrong_answers(session)) == 2


# ---------------------------------------------------------------------------
# 单科考试分析
# ---------------------------------------------------------------------------

def _seed_subject_exams(session):
    """2 名学生、2 场考试、数学单科（满分 100），用于单科进退步。"""
    s1, _ = ss.get_or_create_student(session, "学生01", "一班")
    s2, _ = ss.get_or_create_student(session, "学生02", "一班")
    plan = [
        ("第一次月考", date(2026, 3, 1), {"学生01": 70.0, "学生02": 90.0}),
        ("期中考试", date(2026, 4, 15), {"学生01": 80.0, "学生02": 85.0}),
    ]
    exam_ids = []
    for name, d, scores in plan:
        exam = es.create_exam(session, name, exam_date=d,
                              full_scores={"数学": 100})
        session.flush()
        es.import_scores(session, exam.id, [
            {"name": nm, "class_name": "一班", "scores": {"数学": v}}
            for nm, v in scores.items()])
        exam_ids.append(exam.id)
    return exam_ids


def test_analyze_subject_metrics_and_ranking(session):
    _id1, exam2_id = _seed_subject_exams(session)
    data = es.analyze_subject(session, exam2_id, "数学")
    assert data["subject"] == "数学"
    assert data["full_score"] == 100
    t = data["stats"]
    assert t["count"] == 2
    assert t["mean"] == 82.5          # (80+85)/2
    assert t["max"] == 85 and t["min"] == 80
    # 班内单科并列排名：85 第1，80 第2
    rank_map = {r["name"]: r["数学_rank"] for r in data["rows"]}
    assert rank_map == {"学生02": 1, "学生01": 2}
    # 学生01 数学 70→80 进步 10；学生02 90→85 退步 -5
    deltas = data["deltas"]
    sid_rows = {r["name"]: r["student_id"] for r in data["rows"]}
    assert deltas[sid_rows["学生01"]]["score_delta"] == 10
    assert deltas[sid_rows["学生02"]]["score_delta"] == -5


def test_analyze_subject_empty_for_unrecorded_subject(session):
    _id1, exam2_id = _seed_subject_exams(session)
    # 本场没有物理成绩
    assert es.analyze_subject(session, exam2_id, "物理") == {}


def test_class_trend_single_subject(session):
    _seed_subject_exams(session)
    trend = es.class_trend(session, class_name="一班", subject="数学")
    assert trend["subjects"] == ["数学"]
    assert trend["exams"] == ["第一次月考", "期中考试"]
    # 两场数学均分：80、82.5；单科视角不混总分
    assert trend["series"]["数学"] == [80.0, 82.5]
    assert "total" not in trend["series"]


def test_class_trend_all_subjects_unchanged(session):
    _seed_subject_exams(session)
    trend = es.class_trend(session, class_name="一班")
    assert "数学" in trend["series"] and "total" in trend["series"]
