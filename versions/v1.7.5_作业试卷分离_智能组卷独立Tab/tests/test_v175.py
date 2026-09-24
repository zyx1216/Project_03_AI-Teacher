# -*- coding: utf-8 -*-
"""v1.7.5 作业试卷分离与智能组卷独立 Tab 测试。"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework
from modules import homework as homework_mod
from utils import feature_subjects as fs
from utils import homework_service
from utils import question_service


def _engine(db_file: Path):
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    return eng


def _seed_three_math_questions(db_file: Path):
    """造选择题、填空题、解答题各 1 道，默认配置下可全部被抽中。"""
    eng = _engine(db_file)
    session = sessionmaker(bind=eng)()
    for qtype in ("choice", "fill", "solution"):
        question_service.create_question(
            session,
            {
                "content": f"数学{qtype}题干",
                "question_type": qtype,
                "difficulty": 2,
                "knowledge_points": '["通用知识点"]',
                "answer": "参考答案",
                "analysis": "",
                "error_points": "",
            },
            source="manual",
            status="approved",
            subject="数学",
        )
    session.commit()
    session.close()
    return eng


def _apptest(db_file: Path, tmp_path: Path, code: str | None = None):
    from streamlit.testing.v1 import AppTest
    from tests import test_app_smoke as smoke

    app_code = code or smoke._isolated_app_code(
        db_file, tmp_path / "feature.json")
    return AppTest.from_string(app_code, default_timeout=30)


def _open_homework_page(at):
    at.run()
    at.sidebar.radio[0].set_value("📝 学业测评").run()


def test_constants_and_main_tabs(tmp_path):
    db_file = tmp_path / "structure.db"
    at = _apptest(db_file, tmp_path)
    _open_homework_page(at)

    assert fs.SMART_COMPOSE_SUBJECT in fs.FEATURE_KEYS
    assert homework_mod._TYPE_KEYS == [
        "preview", "classroom", "after_class", "review"]
    assert "exam" not in homework_mod._TYPE_KEYS
    assert [item.label for item in at.tabs] == [
        "作业管理", "🤖 智能组卷", "成绩录入", "作业分析", "错题本"]

    next(b for b in at.button if b.label == "➕ 新建作业").click().run()
    assert not any("试卷出题" in b.label for b in at.button)
    template_labels = " ".join(str(x.value) for x in at.markdown)
    assert homework_mod.SMART_COMPOSE_DRAFT_PREFIX not in template_labels
    assert not at.exception


def test_smart_compose_create_formal_paper(tmp_path):
    db_file = tmp_path / "smart_formal.db"
    eng = _seed_three_math_questions(db_file)
    at = _apptest(db_file, tmp_path)
    _open_homework_page(at)

    next(b for b in at.button if b.key == "smart_compose_run").click().run()
    assert not at.exception
    assert at.session_state["smart_compose_result"] is not None

    name_box = next(x for x in at.text_input
                    if x.key == "smart_compose_paper_name")
    name_box.input("数学一年级阶段测试卷").run()
    next(b for b in at.button if b.key == "confirm_smart_paper").click().run()
    assert not at.exception

    assert at.session_state["homework_tab"] == "作业管理"
    session = sessionmaker(bind=eng)()
    paper = session.query(Homework).one()
    assert paper.name == "数学一年级阶段测试卷"
    assert paper.homework_type == "exam"
    assert paper.is_template is False
    assert paper.grade == "一年级"
    assert len(homework_service.homework_questions(session, paper.id)) == 3
    assert at.session_state["hw_open_id"] == paper.id
    session.close()
    eng.dispose()


def test_reconfigure_and_discard_delete_draft(tmp_path):
    db_file = tmp_path / "smart_reconfigure.db"
    eng = _seed_three_math_questions(db_file)
    at = _apptest(db_file, tmp_path)
    _open_homework_page(at)

    next(b for b in at.button if b.key == "smart_compose_run").click().run()
    next(b for b in at.button if b.key == "reconfigure_smart_paper").click().run()
    assert not at.exception
    assert at.session_state.get("smart_compose_result") is None
    session = sessionmaker(bind=eng)()
    assert session.query(Homework).count() == 0
    session.close()

    # 重新配置保留控件内容，可再次组卷；放弃后清空配置。
    next(b for b in at.button if b.key == "smart_compose_run").click().run()
    next(b for b in at.button if b.key == "discard_smart_paper").click().run()
    assert not at.exception
    session = sessionmaker(bind=eng)()
    assert session.query(Homework).count() == 0
    session.close()
    # 回到初始状态不是删除 key，而是年级恢复默认值，其他配置清空。
    assert at.session_state["smart_compose_grade"] == "一年级"
    assert at.session_state["smart_compose_material"] is None
    assert at.session_state["smart_compose_chapters"] == []
    assert at.session_state["smart_compose_kps"] == []
    eng.dispose()


def test_smart_compose_failure_deletes_draft(tmp_path):
    from tests import test_app_smoke as smoke

    db_file = tmp_path / "smart_failure.db"
    code = smoke._isolated_app_code(db_file, tmp_path / "feature.json")
    old_run = f'runpy.run_path(r"{smoke.APP_FILE}", run_name="__main__")'
    patch = """
import utils.homework_service as _real_hw_service
import modules.homework as _homework_module
class _FailingHWService:
    def __getattr__(self, name):
        return getattr(_real_hw_service, name)
    def auto_compose(self, *args, **kwargs):
        raise RuntimeError("模拟组卷失败")
_original_hw_svc = _homework_module.hw_svc
_homework_module.hw_svc = _FailingHWService()
try:
    runpy.run_path(r"__APPFILE__", run_name="__main__")
finally:
    _homework_module.hw_svc = _original_hw_svc
"""
    patch = patch.replace("__APPFILE__", str(smoke.APP_FILE))
    assert code.count(old_run) == 1
    code = code.replace(old_run, patch.strip(), 1)
    at = _apptest(db_file, tmp_path, code=code)
    _open_homework_page(at)

    next(b for b in at.button if b.key == "smart_compose_run").click().run()
    assert not at.exception
    assert any("组卷没有完成" in str(x.value) for x in at.error)

    eng = _engine(db_file)
    session = sessionmaker(bind=eng)()
    assert session.query(Homework).count() == 0
    session.close()
    eng.dispose()


def test_historical_exam_opens_without_smart_compose_editor_tab(tmp_path):
    db_file = tmp_path / "historical_exam.db"
    eng = _engine(db_file)
    session = sessionmaker(bind=eng)()
    exam = homework_service.create_homework(
        session,
        "历史正式试卷",
        homework_type="exam",
        total_score=100.0,
        duration=90,
        subject="数学",
    )
    question = question_service.create_question(
        session,
        {
            "content": "历史试卷题",
            "question_type": "choice",
            "difficulty": 1,
            "knowledge_points": '["旧知识点"]',
            "answer": "A",
            "analysis": "",
            "error_points": "",
        },
        source="manual",
        status="approved",
        subject="数学",
    )
    homework_service.add_questions(session, exam.id, [question.id])
    session.commit()
    exam_id = exam.id
    session.close()

    at = _apptest(db_file, tmp_path)
    _open_homework_page(at)
    next(b for b in at.button if b.key == f"open_{exam_id}").click().run()
    assert not at.exception

    expected = ["从题库选题", "AI 即时出题", "外部导入", "手动添加"]
    editor_labels = [item.label for item in at.tabs if item.label in expected]
    assert editor_labels == expected

    session = sessionmaker(bind=eng)()
    stored = session.get(Homework, exam_id)
    assert stored.homework_type == "exam"
    assert stored.is_template is False
    session.close()
    eng.dispose()

