# -*- coding: utf-8 -*-
"""v2.9.1 教师端功能补全（第二批）测试。"""
from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.models import Base, Exam, Score, Student
from utils import diagnosis_service, unit_design_service

@pytest.fixture()
def session(tmp_path):
    eng=create_engine(f"sqlite:///{(tmp_path/'v291.db').as_posix()}")
    Base.metadata.create_all(eng); s=sessionmaker(bind=eng)(); yield s; s.close(); eng.dispose()

def test_v291_tables_and_migration():
    from migrations.v2_9_1_migration import migrate
    assert len(Base.metadata.tables)==30
    assert {'teaching_diagnosis','unit_plans','unit_lessons'} <= set(Base.metadata.tables)
    eng=create_engine('sqlite:///:memory:')
    assert set(migrate(eng)['tables'])=={'teaching_diagnosis','unit_plans','unit_lessons'}
    assert migrate(eng)['tables']==['teaching_diagnosis','unit_plans','unit_lessons']
    eng.dispose()

def test_diagnosis_collect_generate_compare(session):
    exam=Exam(name='月考',grade='高一'); session.add(exam); session.flush()
    stu=Student(name='学生A',class_name='一班'); session.add(stu); session.flush()
    session.add(Score(exam_id=exam.id,student_id=stu.id,subject='数学',score=50)); session.commit()
    data=diagnosis_service.collect_diagnosis_data(session,'一班','数学','高一',{'type':'exam','exam_id':exam.id})
    assert data['exams'][0]['average']==50
    one=diagnosis_service.generate_diagnosis(session,'一班','数学','高一',{'type':'exam','exam_id':exam.id})
    two=diagnosis_service.generate_diagnosis(session,'一班','数学','高一',{'type':'exam','exam_id':exam.id})
    session.commit(); assert one.score and two.score
    assert 'score_delta' in diagnosis_service.compare_diagnoses(session,one.id,two.id)
    assert diagnosis_service.export_diagnosis_word(one)[:2]==b'PK'
    assert diagnosis_service.export_diagnosis_pdf(one)[:4]==b'%PDF'

def test_unit_design_manual_and_progress(session):
    obj=unit_design_service.generate_unit_objectives(None,'第一单元','数学','初一','第一单元',None,3)
    assert obj['lesson_hours']==3
    unit=unit_design_service.create_unit_plan(session,'第一单元','数学','初一',None,'第一单元',obj)
    assert unit.lesson_count==3
    assert unit_design_service.generate_all_lessons(session,unit.id)==3
    session.commit(); lesson=unit.lessons[0]
    assert lesson.plan_id is not None
    unit_design_service.update_lesson_status(session,lesson.id,'completed'); session.commit()
    assert unit.status=='active'
    copied=unit_design_service.copy_unit_plan(session,unit.id); session.commit()
    assert copied.id!=unit.id and len(copied.lessons)==3
    assert unit_design_service.export_unit_word(session,unit.id)[:2]==b'PK'

def test_app_v291_empty_and_data(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_sub
    empty=AppTest.from_string(_isolated_app_code(tmp_path/'empty.db',tmp_path/'feature.json'),default_timeout=30); empty.run()
    goto_sub(empty,'analysis_tab','🔍 AI教学诊断','📊 学情'); assert not empty.exception, [str(e) for e in empty.exception]
    goto_sub(empty,'lesson_plan_tab','📚 单元整体设计','📚 备课'); assert not empty.exception, [str(e) for e in empty.exception]
    db=tmp_path/'data.db'; eng=create_engine(f"sqlite:///{db.as_posix()}",connect_args={'check_same_thread':False}); Base.metadata.create_all(eng)
    s=sessionmaker(bind=eng)(); exam=Exam(name='月考',grade='高一'); s.add(exam); s.flush(); stu=Student(name='学生A',class_name='一班'); s.add(stu); s.flush(); s.add(Score(exam_id=exam.id,student_id=stu.id,subject='数学',score=80)); s.commit(); s.close(); eng.dispose()
    at=AppTest.from_string(_isolated_app_code(db,tmp_path/'feature2.json'),default_timeout=30); at.run()
    goto_sub(at,'analysis_tab','🔍 AI教学诊断','📊 学情'); assert not at.exception, [str(e) for e in at.exception]
    goto_sub(at,'lesson_plan_tab','📚 单元整体设计','📚 备课'); assert not at.exception, [str(e) for e in at.exception]
