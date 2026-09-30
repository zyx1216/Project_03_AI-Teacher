# -*- coding: utf-8 -*-
"""v2.7.0 简历亮点功能（方向三）测试。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Textbook
from utils import (knowledge_graph_service as kgs, rag_service,
                   blackboard_service as bbs, grading_service as gs,
                   databoard_service as dbs, student_report_service as srs)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    Base.metadata.create_all(eng)
    import config
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


# --- 表口径 ---

def test_tables_include_knowledge_graph():
    # v2.9.0 后总表数为 26（v2.7 知识图谱 + v2.8 任务/缓存 + v2.9 讲评记录）
    assert len(Base.metadata.tables) == 30
    assert "knowledge_nodes" in Base.metadata.tables
    assert "knowledge_edges" in Base.metadata.tables


def test_business_tables_include_knowledge_graph():
    from utils import backup_service
    assert len(backup_service.BUSINESS_TABLES) == 30
    assert "knowledge_nodes" in backup_service.BUSINESS_TABLES


# --- 知识图谱 ---

def _mk_material(session, tmp_path, mid=1, text="第一章 函数\n函数的定义\n第二章 方程\n方程求解"):
    session.add(Textbook(id=mid, name=f"资料{mid}", file_type="text",
                         subject="数学", type="textbook"))
    session.commit()
    d = tmp_path / "text"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{mid}.txt").write_text(text, encoding="utf-8")


def test_build_graph_fallback(session, tmp_path):
    _mk_material(session, tmp_path)
    out = kgs.build_graph_from_material(session, 1, chat_func=None)
    session.commit()
    assert out["nodes"] >= 1
    assert out["source"] == "fallback"
    nodes = kgs.list_nodes(session, 1)
    assert nodes and all(n["name"] for n in nodes)


def test_build_graph_with_ai(session, tmp_path):
    _mk_material(session, tmp_path)
    def fake(sp, up):
        return json.dumps({
            "nodes": [{"name": "函数", "type": "概念", "importance": 5,
                       "description": "d"},
                      {"name": "定义域", "type": "概念", "importance": 4,
                       "description": "d"}],
            "edges": [{"source": "定义域", "target": "函数",
                       "relation_type": "前置", "weight": 3}]},
            ensure_ascii=False)
    out = kgs.build_graph_from_material(session, 1, chat_func=fake)
    session.commit()
    assert out["source"] == "ai"
    edges = kgs.list_edges(session, 1)
    assert len(edges) == 1 and edges[0]["relation_type"] == "前置"


def test_graph_rebuild_idempotent(session, tmp_path):
    _mk_material(session, tmp_path)
    kgs.build_graph_from_material(session, 1, chat_func=None)
    session.commit()
    n1 = len(kgs.list_nodes(session, 1))
    kgs.build_graph_from_material(session, 1, chat_func=None)
    session.commit()
    assert len(kgs.list_nodes(session, 1)) == n1  # 覆盖重建，不翻倍


def test_prerequisites_and_path(session, tmp_path):
    _mk_material(session, tmp_path)
    def fake(sp, up):
        return json.dumps({
            "nodes": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "edges": [{"source": "A", "target": "B", "relation_type": "前置"},
                      {"source": "B", "target": "C", "relation_type": "递进"}]},
            ensure_ascii=False)
    kgs.build_graph_from_material(session, 1, chat_func=fake)
    session.commit()
    assert kgs.prerequisites_of(session, 1, "C") == ["B"]
    path = kgs.learning_path(session, 1, "C")
    assert path[0] == "A" and path[-1] == "C"


def test_graph_for_visual(session, tmp_path):
    _mk_material(session, tmp_path)
    kgs.build_graph_from_material(session, 1, chat_func=None)
    session.commit()
    data = kgs.graph_for_visual(session, 1, subject="数学")
    assert data["empty"] is False
    assert all("color" in n and "size" in n for n in data["nodes"])


def test_graph_answer_types(session, tmp_path):
    _mk_material(session, tmp_path)
    def fake(sp, up):
        return json.dumps({
            "nodes": [{"name": "函数"}, {"name": "定义域"}],
            "edges": [{"source": "定义域", "target": "函数",
                       "relation_type": "前置"}]}, ensure_ascii=False)
    kgs.build_graph_from_material(session, 1, chat_func=fake)
    session.commit()
    out = rag_service.graph_answer(session, "函数的前置知识是什么", 1,
                                   chat_func=lambda s, u: "函数需要先学定义域")
    assert out["question_type"] == "前置"
    assert out["evidence"] == ["定义域"]
    assert rag_service.classify_graph_question("A和B的区别") == "对比"
    assert rag_service.classify_graph_question("想学好C需要先掌握哪些") in ("路径", "前置")


def test_graph_answer_empty(session):
    out = rag_service.graph_answer(session, "函数前置知识", 999,
                                   chat_func=None)
    assert out["source"] == "empty"


# --- 混合检索 ---

def test_hybrid_retrieve_returns_rerank(session, tmp_path):
    _mk_material(session, tmp_path)
    hits = rag_service.hybrid_retrieve(session, "函数", [1], top_k=3,
                                       subject="数学", material_id=1)
    assert all("rerank_score" in h for h in hits)


# --- 板书 4 风格 ---

@pytest.mark.parametrize("style", ["outline", "diagram", "table", "contrast"])
def test_blackboard_new_styles(style):
    assert bbs.STYLES[style]
    design = bbs.generate_blackboard_design(
        {"title": "测试课", "objectives": {"knowledge": "目标"},
         "process": [{"stage": "导入", "content": "内容"}]},
        style=style, chat_func=None)
    assert design["style"] == style
    png = bbs.export_blackboard_png(design)
    assert isinstance(png, (bytes, bytearray)) and len(png) > 100


# --- 图片批改强化 ---

def test_uncertain_answer_detection():
    assert gs.is_uncertain_answer("") is True
    assert gs.is_uncertain_answer("A") is True
    assert gs.is_uncertain_answer("无法识别") is True
    assert gs.is_uncertain_answer("x=1 正确") is False


# --- 大屏与教学质量 ---

def test_big_screen_empty(session):
    data = dbs.big_screen_data(session)
    assert "metrics" in data and data["has_data"] is False


def test_teaching_quality_empty(session):
    out = dbs.teaching_quality(session, subject="数学")
    assert "knowledge" in out and "suggestions" in out


# --- 学生报告 ---

def test_student_report_and_pdf(session):
    from utils import student_service
    stu, _ = student_service.get_or_create_student(session, "甲", "一班")
    session.commit()
    report = srs.generate_student_report(session, stu.id)
    assert report["name"] == "甲"
    assert report["notes"]  # 无数据时应有说明
    html = srs.render_student_report_html(report)
    assert "甲" in html
    pdf = srs.export_student_report_pdf(report)
    assert isinstance(pdf, (bytes, bytearray)) and len(pdf) > 100


def test_student_reports_zip(session):
    from utils import student_service
    ids = []
    for nm in ("甲", "乙"):
        stu, _ = student_service.get_or_create_student(session, nm, "一班")
        ids.append(stu.id)
    session.commit()
    data = srs.export_reports_zip(session, ids)
    import zipfile, io
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert len(zf.namelist()) == 2


# --- API ---

def test_api_token_and_auth():
    from fastapi.testclient import TestClient
    from api.main import app
    c = TestClient(app)
    r = c.post("/api/auth/token", json={"subject": "t"})
    assert r.status_code == 200
    token = r.json()["token"]
    # 无认证 -> 401
    assert c.get("/api/materials").status_code == 401
    # Bearer token -> 200
    r2 = c.get("/api/materials", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


def test_api_health_ok():
    from fastapi.testclient import TestClient
    from api.main import app
    assert TestClient(app).get("/api/health").status_code == 200
