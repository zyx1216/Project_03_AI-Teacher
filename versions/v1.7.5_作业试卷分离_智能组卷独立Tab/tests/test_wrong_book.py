# -*- coding: utf-8 -*-
"""错题本测试：自动收集、四类筛选、详情字段、典型错题置顶、Word 导出。"""

import io

from utils import homework_service as hw
from utils import homework_score_service as hs
from utils import question_service as qs
from utils import student_service as ss


def _setup(session, class_name="一班"):
    """2 名学生、1 份作业、2 道题（每题 10 分）。"""
    h = hw.create_homework(session, "作业", class_name=class_name)
    ids = []
    for kp in ("方程", "韦达定理"):
        data = qs.validate_question({
            "content": f"{kp}题", "question_type": "solution",
            "difficulty": 2, "answer": "答", "analysis": "解析",
            "knowledge_points": kp})
        q = qs.create_question(session, data, source="manual", status="approved")
        ids.append(q.id)
    hw.add_questions(session, h.id, ids)
    s1, _ = ss.get_or_create_student(session, "学生01", class_name)
    s2, _ = ss.get_or_create_student(session, "学生02", class_name)
    session.flush()
    return h, ids, [s1, s2]


def test_wrong_auto_collected_only_when_false(session):
    h, qids, stus = _setup(session)
    hs.save_answers(session, h.id, [
        {"student_id": stus[0].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "earned_score": 2, "error_type": "计算错误"},
        {"student_id": stus[0].id, "question_id": qids[1], "order_no": 2,
         "is_correct": True, "earned_score": 10},
        {"student_id": stus[1].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "earned_score": 0, "error_type": "概念错误"},
    ])
    session.flush()
    rows = hs.list_wrong_answers(session, homework_id=h.id)
    # 只有判错的进错题本：第1题两人错 = 2 条，第2题对不进
    assert len(rows) == 2
    assert all(r["content"] == "方程题" for r in rows)


def test_wrong_filters(session):
    h, qids, stus = _setup(session)
    hs.save_answers(session, h.id, [
        {"student_id": stus[0].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "error_type": "计算错误"},
        {"student_id": stus[1].id, "question_id": qids[1], "order_no": 2,
         "is_correct": False, "error_type": "概念错误"},
    ])
    session.flush()
    # 按学生
    only1 = hs.list_wrong_answers(session, student_id=stus[0].id)
    assert len(only1) == 1 and only1[0]["student_name"] == "学生01"
    # 按错误类型
    calc = hs.list_wrong_answers(session, error_type="计算错误")
    assert len(calc) == 1 and calc[0]["error_type"] == "计算错误"
    # 按知识点关键词
    kp = hs.list_wrong_answers(session, knowledge_keyword="韦达")
    assert len(kp) == 1 and "韦达定理" in kp[0]["knowledge_points"]


def test_wrong_detail_fields(session):
    h, qids, stus = _setup(session)
    hs.save_answers(session, h.id, [
        {"student_id": stus[0].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "earned_score": 3, "error_type": "审题错误"}])
    session.flush()
    row = hs.list_wrong_answers(session)[0]
    assert row["answer"] == "答" and row["analysis"] == "解析"
    assert row["student_name"] == "学生01" and row["homework_name"] == "作业"
    assert row["earned_score"] == 3 and row["order_no"] == 1


def test_typical_wrong_flag_and_sort(session):
    """某题全班错率 >=40% 时，两个学生的该错题都标典型并置顶。"""
    h, qids, stus = _setup(session)
    # 第1题两人都错（错误率 100%）
    hs.save_answers(session, h.id, [
        {"student_id": stus[0].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "error_type": "计算错误"},
        {"student_id": stus[1].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "error_type": "概念错误"},
        # 第2题只 1 人错（50% 也达阈值），用第三、四个学生稀释需要更多人，这里保持简单
    ])
    session.flush()
    rows = hs.list_wrong_answers(session, homework_id=h.id)
    assert len(rows) == 2
    assert all(r["typical"] for r in rows)
    assert rows[0]["typical"] is True


def test_export_wrong_word(session):
    h, qids, stus = _setup(session)
    hs.save_answers(session, h.id, [
        {"student_id": stus[0].id, "question_id": qids[0], "order_no": 1,
         "is_correct": False, "error_type": "计算错误"}])
    session.flush()
    rows = hs.list_wrong_answers(session)
    data = hs.export_wrong_word(rows, title="错题本")
    from docx import Document
    text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "学生01" in text and "方程题" in text and "计算错误" in text