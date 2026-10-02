# -*- coding: utf-8 -*-
"""v3.1.0 Agent 能力深化测试。"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import AgentExecutionLog, AgentMemory, Base
from utils import agent_core


@pytest.fixture()
def session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'v310.db').as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def test_tables_and_migration():
    from migrations.v3_1_0_migration import migrate
    assert len(Base.metadata.tables) == 38
    assert 'agent_execution_logs' in Base.metadata.tables
    assert {'id', 'task', 'plan_json', 'steps_json', 'result', 'status',
            'duration', 'created_at'} <= {c.name for c in AgentExecutionLog.__table__.columns}
    eng = create_engine('sqlite:///:memory:')
    assert migrate(eng)['tables'] == ['agent_execution_logs']
    assert migrate(eng)['tables'] == ['agent_execution_logs']
    eng.dispose()


def test_tool_registry_and_planner():
    names = {item['name'] for item in agent_core.list_tools()}
    assert len(names) >= 15
    assert {'create_unit_plan', 'generate_variation', 'generate_review',
            'diagnose_teaching', 'export_report', 'manage_calendar'} <= names
    assert agent_core.plan('帮我备课')[0]['tool_name'] == 'search_resource'
    assert agent_core.plan('出一份试卷')[0]['tool_name'] == 'generate_questions'
    assert agent_core.plan('分析最近考试')[0]['tool_name'] == 'diagnose_teaching'


def test_executor_logs_and_failure(session):
    result = agent_core.execute_plan(
        session, '测试任务',
        [{'step': 1, 'agent': 'analysis', 'tool_name': 'manage_calendar', 'params': {}}],
        confirmed=True)
    assert result['status'] == 'success' and result['log_id']
    assert len(agent_core.list_logs(session)) == 1
    bad = agent_core.execute_plan(
        session, '坏工具',
        [{'step': 1, 'agent': 'analysis', 'tool_name': 'not_exists', 'params': {}}],
        retries=0)
    assert bad['status'] == 'failed'


def test_high_risk_requires_confirmation(session):
    with pytest.raises(ValueError, match='确认'):
        agent_core.execute_tool(session, 'generate_variation',
                                {'question_id': 1}, confirmed=False)


def test_memory_reuses_agent_memory(session):
    row = agent_core.remember(session, 'lesson_style', '简洁', category='teacher')
    session.commit()
    assert isinstance(row, AgentMemory)
    assert agent_core.recall(session, 'lesson_style', category='teacher').value == '简洁'
    assert agent_core.allowed_preferences(session)['lesson_style'] == '简洁'


def test_ai_assistant_apptest(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / 'v310_app.db', tmp_path / 'feature.json'),
        default_timeout=30)
    at.run()
    at.session_state['app_top_page'] = '🤖 AI助手'
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any('AI助手' in str(x.value) for x in at.subheader)
    assert any(x.key == 'ai_assistant_run' for x in at.button)
