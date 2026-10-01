# -*- coding: utf-8 -*-
"""v1.9.6 RAG 知识库 + 多Agent协作测试。

全程临时 SQLite/JSON，不读真实 data、不触发真实 AI/embedding；
LLM 与向量检索全部 monkeypatch。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Textbook
from streamlit.testing.v1 import AppTest
from tests.test_app_smoke import (
    _isolated_app_code, goto_assistant, goto_sub)
from utils import llm_client, multi_agent, rag_service, vector_store
from utils import agent_service, material_service
from utils import homework_service as hw_svc
from utils import exam_service


# ---------------------------------------------------------------------------
# 临时库与路径隔离
# ---------------------------------------------------------------------------

@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rag_service, "RAG_CONFIG_PATH", tmp_path / "rag_config.json")
    monkeypatch.setattr(
        multi_agent, "LOG_DIR", tmp_path / "multi_agent_logs")
    monkeypatch.setattr(
        agent_service, "AGENT_HISTORY_PATH",
        tmp_path / "agent_history.json")
    engine = create_engine(f"sqlite:///{(tmp_path / 'v196.db').as_posix()}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    engine.dispose()


def _material(sess, name="数学课本", subject="数学"):
    m = Textbook(name=name, file_type="text", subject=subject,
                 grade="高一", vectorized=False)
    sess.add(m)
    sess.flush()
    return m


def _rr(text, chapter, method, distance=0.0):
    return vector_store.RetrievalResult(text, chapter, method, distance)


# ---------------------------------------------------------------------------
# 一、RAG 配置
# ---------------------------------------------------------------------------

def test_rag_config_default_and_corrupt(tmp_path, monkeypatch):
    cfg_path = tmp_path / "rag_config.json"
    monkeypatch.setattr(rag_service, "RAG_CONFIG_PATH", cfg_path)
    cfg = rag_service.load_config()  # 缺失自建
    assert cfg["top_k"] == 5
    assert cfg_path.exists()
    cfg_path.write_text("{坏 JSON", encoding="utf-8")  # 损坏回退不覆盖
    assert rag_service.load_config()["top_k"] == 5
    assert cfg_path.read_text(encoding="utf-8") == "{坏 JSON"


# ---------------------------------------------------------------------------
# 二、ensure_index
# ---------------------------------------------------------------------------

def test_ensure_index_states(session, monkeypatch):
    m = _material(session)

    monkeypatch.setattr(vector_store, "has_vector_index", lambda tb: True)
    info = rag_service.ensure_index(session, m.id)
    assert info == {"textbook_id": m.id, "indexed": True, "method": "vector"}

    monkeypatch.setattr(vector_store, "has_vector_index", lambda tb: False)
    monkeypatch.setattr(rag_service, "load_chunks_for",
                        lambda s, tb: [{"chapter_title": "第一章", "text": "正文"}])
    monkeypatch.setattr(vector_store, "build_index",
                        lambda tb, chunks: "local")
    info = rag_service.ensure_index(session, m.id)
    assert info["indexed"] is True and info["method"] == "local"

    monkeypatch.setattr(vector_store, "build_index",
                        lambda tb, chunks: "keyword")
    info = rag_service.ensure_index(session, m.id)
    assert info["indexed"] is False and info["method"] == "keyword"

    monkeypatch.setattr(rag_service, "load_chunks_for", lambda s, tb: [])
    info = rag_service.ensure_index(session, m.id)
    assert info["method"] == "empty" and info["indexed"] is False


# ---------------------------------------------------------------------------
# 三、retrieve 多资料归并
# ---------------------------------------------------------------------------

def test_retrieve_merge_multi_sources(session, monkeypatch):
    m1 = _material(session, "资料一")
    m2 = _material(session, "资料二")

    def fake_search(tb_id, chunks, query, top_k=5):
        if tb_id == m1.id:
            return [_rr("函数定义", "第一章 函数", "cloud", 0.1),
                    _rr("关键词命中", "第二章", "keyword")]
        return [_rr("另一定义", "第三章", "local", 0.2)]

    monkeypatch.setattr(vector_store, "search", fake_search)
    monkeypatch.setattr(rag_service, "load_chunks_for",
                        lambda s, tb: [{"chapter_title": "x", "text": "x"}])
    hits = rag_service.retrieve(session, "函数定义", [m1.id, m2.id], top_k=5)
    assert len(hits) == 3
    # 向量命中排在关键词兜底之前。
    assert hits[-1]["method"] == "keyword"
    assert hits[0]["similarity"] == 0.9
    assert {h["textbook_id"] for h in hits[:2]} == {m1.id, m2.id}
    # JSON 安全。
    json.dumps(hits, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 四、rag_answer 与置信度三档
# ---------------------------------------------------------------------------

def _hit(chapter="第一章", method="cloud", sim=0.9, tb=1):
    return {"textbook_id": tb, "textbook_name": "课本", "chapter": chapter,
            "text": "正文", "method": method, "similarity": sim}


def test_confidence_levels(session, monkeypatch):
    # 高：top 相似度 ≥0.75 且来源（章节）≥2。
    hits = [_hit("第一章", sim=0.9), _hit("第二章", sim=0.85)]
    assert rag_service._confidence(hits) == "高"
    # 中：单条向量命中 sim≥0.55。
    assert rag_service._confidence([_hit("第一章", sim=0.6)]) == "中"
    # 低：仅关键词兜底。
    assert rag_service._confidence(
        [_hit(method="keyword", sim=0.3)]) == "低"
    # 低：单条低相似度向量命中。
    assert rag_service._confidence([_hit(sim=0.4)]) == "低"


def test_rag_answer_success(session, monkeypatch):
    hits = [_hit("第一章"), _hit("第二章", sim=0.85)]
    monkeypatch.setattr(rag_service, "retrieve",
                        lambda s, q, ids, top_k=None: hits)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.3: "函数是一种对应关系。")
    out = rag_service.rag_answer(session, "函数是什么", [1])
    assert out["answer"] == "函数是一种对应关系。"
    assert out["confidence"] == "高"
    assert len(out["sources"]) == 2
    assert out["sources"][0]["chapter"] == "第一章"


def test_rag_answer_no_hit(session, monkeypatch):
    monkeypatch.setattr(rag_service, "retrieve",
                        lambda s, q, ids, top_k=None: [])
    out = rag_service.rag_answer(session, "无关问题", [1])
    assert out["confidence"] == "低" and out["sources"] == []
    assert "没有" in out["answer"]


def test_rag_answer_keyword_only_low(session, monkeypatch):
    hits = [_hit(method="keyword", sim=0.3, chapter="全文")]
    monkeypatch.setattr(rag_service, "retrieve",
                        lambda s, q, ids, top_k=None: hits)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.3: "关键词相关回答。")
    out = rag_service.rag_answer(session, "问题", [1])
    assert out["confidence"] == "低"


# ---------------------------------------------------------------------------
# 五、AI 助手接入 RAG
# ---------------------------------------------------------------------------

def test_agent_rag_query_intent(session, monkeypatch):
    m = _material(session)
    intent = json.dumps({
        "intent": "rag_query",
        "params": {"subject": "数学", "grade": "高一", "class_name": "",
                   "chapter": "函数", "knowledge_points": [],
                   "question_type": "", "count": 0, "difficulty": 0,
                   "student_name": "", "time_range": "",
                   "topic": "函数的定义"}}, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.0: intent)
    monkeypatch.setattr(material_service, "list_materials",
                        lambda s, subject=None: [m])
    monkeypatch.setattr(rag_service, "ensure_index",
                        lambda s, tb: {"indexed": True, "method": "vector"})
    monkeypatch.setattr(rag_service, "rag_answer",
                        lambda s, q, ids: {
                            "answer": "函数是对应关系。",
                            "sources": [{"textbook_id": m.id,
                                         "textbook_name": m.name,
                                         "chapter": "第一章",
                                         "similarity": 0.9}],
                            "confidence": "高"})
    result = agent_service.run_instruction(session, "从课本里找一下函数的定义")
    assert result["status"] == "success"
    assert "置信度" in result["summary"]
    assert result["sub"] == "📚 RAG知识库"


def test_run_quick_info_rag_phrase_not_intercepted(session):
    # RAG 口语不应被 quick_info 拦截。
    assert agent_service.run_quick_info(session, "从课本里找函数定义") is None


# ---------------------------------------------------------------------------
# 六、多Agent场景判定
# ---------------------------------------------------------------------------

def test_scenario_of():
    assert multi_agent.scenario_of("帮我做分层教学设计") == "layered_teaching"
    assert (multi_agent.scenario_of("分析这次考试并给出改进方案")
            == "exam_improve")
    assert multi_agent.scenario_of("帮我准备这节课") == "full_lesson"


# ---------------------------------------------------------------------------
# 七、Coordinator 分派：顺序、调服务层、失败保留、日志
# ---------------------------------------------------------------------------

def _patch_agent_services(monkeypatch):
    monkeypatch.setattr(
        agent_service, "_do_prepare",
        lambda s, p: {"status": "success", "summary": "教案已生成",
                      "route": "📚 备课", "extra": {}})

    class _FakeHW:
        id = 7

    monkeypatch.setattr(hw_svc, "create_homework",
                        lambda *a, **k: _FakeHW())
    monkeypatch.setattr(hw_svc, "auto_compose",
                        lambda s, hw, spec: {"total_questions": 5})
    monkeypatch.setattr(exam_service, "list_exams", lambda s: [])
    monkeypatch.setattr(exam_service, "analyze_exam",
                        lambda s, e: {"total_stats": {
                            "average": 80, "pass_rate": 0.9}})


def test_coordinator_full_lesson_order(session, monkeypatch):
    _patch_agent_services(monkeypatch)
    task = {"subject": "数学", "grade": "高一"}
    result = multi_agent.Coordinator().execute(
        session, multi_agent.FULL_LESSON, task)
    assert result["status"] == "success"
    assert [a["agent"] for a in result["agents"]] == [
        "lesson", "question", "analysis"]
    assert result["failed_index"] is None
    # 出题Agent 确实走了服务层并产出作业。
    assert result["agents"][1]["artifact"]["homework_id"] == 7


def test_coordinator_agent_failure_keeps_previous(session, monkeypatch):
    _patch_agent_services(monkeypatch)

    def _fail(s, p):
        raise RuntimeError("备课服务异常")

    monkeypatch.setattr(agent_service, "_do_prepare", _fail)
    task = {"subject": "数学"}
    result = multi_agent.Coordinator().execute(
        session, multi_agent.FULL_LESSON, task)
    assert result["status"] == "failed"
    assert result["failed_index"] == 0
    assert len(result["agents"]) == 1  # 后续 Agent 未执行
    assert "备课服务异常" in result["summary"]


def test_coordinator_start_index_skips(session, monkeypatch):
    _patch_agent_services(monkeypatch)
    task = {"subject": "数学"}
    result = multi_agent.Coordinator().execute(
        session, multi_agent.FULL_LESSON, task, start_index=1)
    # 从第二个 Agent 开始，只执行 question/analysis。
    assert [a["agent"] for a in result["agents"]] == ["question", "analysis"]


def test_multi_agent_log_written(session, monkeypatch):
    _patch_agent_services(monkeypatch)
    task = {"subject": "数学"}
    multi_agent.Coordinator().execute(
        session, multi_agent.FULL_LESSON, task)
    logs = multi_agent.list_logs()
    assert len(logs) == 1
    log = logs[0]
    for key in ("status", "scenario", "agents", "elapsed", "task", "file"):
        assert key in log
    assert len(log["agents"]) == 3


# ---------------------------------------------------------------------------
# 八、AppTest
# ---------------------------------------------------------------------------

def _app(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at, db_file


def test_app_rag_subtab_empty_library(tmp_path):
    """v2.4.0：RAG 并入「资料管理」AI智能检索模式，空库提示先上传资料。"""
    at, _ = _app(tmp_path, "rag_empty")
    # 备课子功能不再有独立 RAG 项。
    goto_sub(at, "lesson_plan_tab", "资料管理", "📚 备课")
    at.session_state["material_view_mode"] = "AI智能检索"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("资料" in x.value for x in at.info)


def test_app_rag_ask_with_sources(tmp_path, monkeypatch):
    """有资料：建索引→提问→答案含来源与置信度。"""
    at, db_file = _app(tmp_path, "rag_ask")
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    seed = sessionmaker(bind=engine)()
    m = Textbook(name="数学课本", file_type="text", subject="数学",
                 grade="高一", vectorized=True)
    seed.add(m)
    seed.commit()
    material_id = m.id
    seed.close()

    monkeypatch.setattr(rag_service, "load_chunks_for",
                        lambda s, tb: [
                            {"chapter_title": "第一章", "text": "函数定义正文"}])
    monkeypatch.setattr(vector_store, "has_vector_index", lambda tb: True)
    monkeypatch.setattr(vector_store, "search",
                        lambda tb, chunks, q, top_k=5: [
                            _rr("函数定义正文", "第一章 函数", "cloud", 0.1),
                            _rr("更多说明", "第二章 性质", "cloud", 0.12)])
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.3: "函数是一种对应关系。")

    goto_sub(at, "lesson_plan_tab", "📚 RAG知识库", "📚 备课")
    assert not at.exception, [str(e) for e in at.exception]
    next(x for x in at.multiselect if x.key == "rag_material_pick"
         ).set_value([material_id]).run()
    next(x for x in at.text_input if x.key == "rag_question_input"
         ).set_value("函数是什么").run()
    next(x for x in at.button if x.key == "rag_ask_btn").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    chat = at.session_state["rag_chat"]
    assert len(chat) == 1
    item = chat[0]
    assert item["answer"] == "函数是一种对应关系。"
    assert item["confidence"] == "高"
    assert len(item["sources"]) == 2

    # 重新生成 / 清空对话无异常。
    next(x for x in at.button if x.key == "rag_regen_btn").click().run()
    assert not at.exception
    next(x for x in at.button if x.key == "rag_clear_btn").click().run()
    assert not at.exception
    assert at.session_state["rag_chat"] == []


def test_app_multi_agent_complex_still_confirms_first(tmp_path, monkeypatch):
    """多Agent模式下 complex 仍先出计划，确认后走协作流程。"""
    at, _ = _app(tmp_path, "ma_complex")
    intent = json.dumps({
        "intent": "prepare_lesson",
        "params": {"subject": "数学", "grade": "高一", "class_name": "",
                   "chapter": "", "knowledge_points": [],
                   "question_type": "", "count": 0, "difficulty": 0,
                   "student_name": "", "time_range": "",
                   "topic": "准备下周的课"}}, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.0: intent)
    goto_assistant(at)

    next(x for x in at.checkbox if x.key == "ai_assistant_multi_agent"
         ).set_value(True).run()
    next(x for x in at.text_area if x.key == "ai_assistant_page_input"
         ).set_value("帮我准备下周的课").run()
    next(x for x in at.button if x.key == "ai_assistant_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    # 首轮只出计划预览，无执行结果。
    preview = at.session_state.get("ai_assistant_plan_preview")
    assert preview and preview["plan"]
    assert at.session_state.get("ai_assistant_plan_result") is None

    # 确认后走 Coordinator。
    _patch_agent_services(monkeypatch)
    next(x for x in at.button if x.key == "ai_assistant_plan_confirm").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    result = at.session_state["ai_assistant_plan_result"]
    assert result["via_multi_agent"] is True
    assert result["status"] == "success"
    assert len(result["agents"]) == 3
    # UI 出现各 Agent 的展开区与重执行按钮。
    assert any(x.key == "ai_assistant_agent_reexec_0" for x in at.button)


def test_app_submit_entry_unaffected(tmp_path):
    """提交页旧入口不受影响。"""
    db_file = tmp_path / "submit_old.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "submit_feature.json"),
        default_timeout=30)
    at.query_params["page"] = "submit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
