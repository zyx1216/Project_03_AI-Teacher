# -*- coding: utf-8 -*-
"""v3.0.0 代码质量提升测试：结构兼容与入口稳定性。"""

from __future__ import annotations

import ast
from pathlib import Path

import config
from models.models import Base


def test_version_and_database_unchanged():
    assert config.APP_VERSION == "3.4.0"
    assert len(Base.metadata.tables) == 38


def test_legacy_and_new_page_packages_export():
    import modules.lesson_plan as legacy_lesson
    import modules.homework as legacy_homework
    import modules.analysis as legacy_analysis
    import modules.lesson as lesson
    import modules.assessment as assessment
    import modules.analytics as analytics

    for name in ("tab_materials", "tab_lesson", "tab_question_gen",
                 "tab_unit_design", "tab_bank"):
        assert callable(getattr(legacy_lesson, name))
    for name in ("tab_manage", "tab_smart_compose", "tab_grading_analysis",
                 "tab_tiered_homework", "tab_wrong_book"):
        assert callable(getattr(legacy_homework, name))
    for name in ("tab_students", "tab_scores", "tab_exam_analysis",
                 "tab_trends", "tab_profile", "tab_diagnosis"):
        assert callable(getattr(legacy_analysis, name))
    assert callable(lesson.show)
    assert callable(assessment.show)
    assert callable(analytics.show)


def test_utils_category_compatibility_exports():
    from utils.ai import llm_client, rag_service, knowledge_graph_service
    from utils.data import excel_handler, ocr_service
    from utils.business import question_service, grading_service
    from utils.ui import chart_service, ppt_generator
    from utils.core import db, error_handler
    from utils.constants import SUBJECT_NAMES, DIFFICULTY_LABELS

    assert llm_client.__name__ == "utils.llm_client"
    assert rag_service.__name__ == "utils.rag_service"
    assert knowledge_graph_service.__name__ == "utils.knowledge_graph_service"
    assert excel_handler.__name__ == "utils.excel_handler"
    assert ocr_service.__name__ == "utils.ocr_service"
    assert question_service.__name__ == "utils.question_service"
    assert grading_service.__name__ == "utils.grading_service"
    assert chart_service.__name__ == "utils.chart_service"
    assert ppt_generator.__name__ == "utils.ppt_generator"
    assert db.__name__ == "utils.db"
    assert error_handler.__name__ == "utils.error_handler"
    assert "数学" in SUBJECT_NAMES and len(DIFFICULTY_LABELS) == 3


def test_new_modules_have_no_bare_except():
    roots = [Path("modules/lesson"), Path("modules/assessment"),
             Path("modules/analytics"), Path("utils/ai"), Path("utils/data"),
             Path("utils/business"), Path("utils/ui"), Path("utils/core")]
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    raise AssertionError(f"{path}:{node.lineno} 存在裸 except")


def test_app_smoke_import_compatibility(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "v300.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.value == "📐 AI教学辅助" for x in at.sidebar.title)
