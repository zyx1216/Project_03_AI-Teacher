# -*- coding: utf-8 -*-
"""v3.2.0 教师端功能增强测试。"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework, Student
from utils import batch_service, class_interaction_service as interaction
from utils import library_service


@pytest.fixture()
def session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'v320.db').as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def test_v320_tables_and_migration():
    from migrations.v3_2_0_migration import migrate
    assert len(Base.metadata.tables) == 38
    assert {'class_interaction_logs', 'favorites', 'templates'} <= set(Base.metadata.tables)
    eng = create_engine('sqlite:///:memory:')
    assert set(migrate(eng)['tables']) == {'class_interaction_logs', 'favorites', 'templates'}
    assert migrate(eng)['tables'] == ['class_interaction_logs', 'favorites', 'templates']
    eng.dispose()


def test_interaction_pick_and_log(session):
    session.add_all([Student(name='A', class_name='一班'), Student(name='B', class_name='一班')])
    session.commit()
    picked = interaction.pick_student(session, '一班', '均匀随机', exclude_ids=[])
    assert picked['student_id']
    interaction.log_interaction(session, '一班', 'random_pick', picked)
    session.commit()
    assert len(interaction.list_interactions(session, '一班')) == 1
    groups = interaction.create_groups(session, '一班', 2)
    assert len(groups) == 2 and sum(len(x) for x in groups) == 2


def test_favorites_and_templates(session):
    fav = library_service.add_favorite(session, 'question', 1, '题1', ['基础'], '常错')
    tpl = library_service.create_template(session, 'question', '模板1',
                                          {'content': 'x'}, ['基础'], '数学', '高一')
    session.commit()
    assert library_service.list_favorites(session)[0].id == fav.id
    assert library_service.list_templates(session, keyword='模板')[0].id == tpl.id
    assert library_service.export_template_json(session, [tpl.id])[:2] == b'PK'
    assert library_service.delete_template(session, tpl.id)


def test_batch_assign_to_classes(session):
    source = Homework(name='作业', homework_type='after_class', class_name='一班', subject='数学')
    session.add(source)
    session.flush()
    clones = batch_service.assign_homeworks_to_classes(session, [source.id], ['二班', '三班'])
    session.commit()
    assert len(clones) == 2
    assert {session.get(Homework, hid).class_name for hid in clones} == {'二班', '三班'}


def test_new_pages_apptest(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / 'v320_app.db', tmp_path / 'feature.json'),
        default_timeout=30)
    at.run()
    for page in ('🎯 课堂互动', '📁 我的模板'):
        at.session_state['app_top_page'] = page
        at.run()
        assert not at.exception, [str(e) for e in at.exception]
