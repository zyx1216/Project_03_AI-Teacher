# -*- coding: utf-8 -*-
"""v2.6.0 Agent 能力深化（方向二）测试。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Question
from utils import (lesson_chat_service as lcs, workflow_service as wfs,
                   agent_watchlist as aw, agent_tools as at,
                   agent_memory_service as ams,
                   teaching_plan_service as tps)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    Base.metadata.create_all(eng)
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


# --- 方向一：对话式备课 ---

def test_clarify_questions_capped_at_three():
    qs = lcs.build_clarify_questions({}, max_n=3)
    assert len(qs) == 3
    assert all({"field", "question", "default"} <= set(q) for q in qs)


def test_clarify_empty_when_context_complete():
    ctx = {"grade": "初一", "subject": "数学", "chapter": "方程",
           "hours": 1, "include_practice": True}
    assert lcs.build_clarify_questions(ctx) == []


def test_chat_session_roundtrip(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    sess = lcs.new_session("测试对话")
    lcs.append_message(sess["session_id"], "user", "帮我备一节课")
    lcs.append_message(sess["session_id"], "assistant", "好的")
    got = lcs.get_session(sess["session_id"])
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert lcs.last_session()["session_id"] == sess["session_id"]


def test_chat_store_corrupt_fallback(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    (tmp_path / "lesson_chat.json").write_text("{bad", encoding="utf-8")
    store = lcs.load_store()
    assert store["sessions"] == []
    # 不覆盖损坏原文件
    assert (tmp_path / "lesson_chat.json").read_text(encoding="utf-8") == "{bad"


def test_apply_feedback_iterates():
    def fake(sysp, user):
        return json.dumps({"title": "优化后", "objectives": {},
                           "process": [], "board_design": "",
                           "homework": ""})
    out = lcs.apply_feedback({"title": "原"}, "太难了", chat_func=fake)
    assert out["changed"] is True
    assert out["plan"]["title"] == "优化后"


def test_apply_feedback_ai_failure_keeps_plan():
    def bad(sysp, user):
        raise RuntimeError("网络错误")
    out = lcs.apply_feedback({"title": "原"}, "改一下", chat_func=bad)
    assert out["changed"] is False
    assert out["plan"]["title"] == "原"
    assert "失败" in out["reason"]


def test_apply_feedback_empty():
    out = lcs.apply_feedback({"title": "原"}, "")
    assert out["changed"] is False


# --- 方向二：预警名单 ---

def test_watchlist_sorted_by_risk(session, monkeypatch):
    monkeypatch.setattr(
        "utils.agent_alert.check_all_alerts",
        lambda s: [
            {"alert_type": "progress_delay", "title": "慢", "content": "慢"},
            {"alert_type": "student_decline", "title": "退", "content": "退",
             "student_name": "甲", "suggestion": "谈话"},
        ], raising=False)
    result = aw.build_watchlist(session)
    assert result["items"][0]["type"] == "student_decline"
    assert result["items"][0]["risk"] > result["items"][1]["risk"]
    assert result["student_items"]


def test_watchlist_uses_alert_fields(session, monkeypatch):
    monkeypatch.setattr(
        "utils.agent_alert.check_all_alerts",
        lambda s: [{"alert_type": "score_decline", "title": "降",
                    "content": "连续下降", "suggestion": "专项复习"}],
        raising=False)
    item = aw.build_watchlist(session)["items"][0]
    assert item["reason"] == "连续下降"
    assert item["suggestion"] == "专项复习"


def test_tutoring_plan_template_fallback(session, monkeypatch):
    monkeypatch.setattr("utils.agent_advisor.weekly_facts",
                        lambda s: {"weak_points": [{"knowledge_point": "函数"}]},
                        raising=False)
    out = aw.generate_tutoring_plan(session, student_name="甲",
                                    chat_func=lambda s, u: "AI辅导方案")
    assert out["source"] == "ai" and out["plan"] == "AI辅导方案"
    out2 = aw.generate_tutoring_plan(
        session, student_name="甲",
        chat_func=lambda s, u: (_ for _ in ()).throw(RuntimeError("fail")))
    assert out2["source"] == "template" and "辅导" in out2["plan"]


# --- 方向二：教学节奏 ---

def test_suggest_pace_no_data(session):
    out = tps.suggest_pace(session, "数学", "初一", "2026春")
    assert out["status"] == "no_data"
    assert out["suggestions"]


# --- 方向三：工作流 ---

def test_workflow_presets_and_custom(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    tpl = wfs.list_templates()
    assert set(tpl["presets"]) >= {"新授课", "复习课", "试卷讲评课", "习题课"}
    wfs.save_custom_template("我的流程", [["生成教案", "lesson"]])
    assert any(c["name"] == "我的流程" for c in wfs.list_templates()["custom"])
    wfs.delete_custom_template("我的流程")
    assert not wfs.list_templates()["custom"]


def test_workflow_resolve_and_run_stops_on_failure(session, monkeypatch):
    monkeypatch.setattr(wfs, "run_step",
                        lambda s, kind, params: (
                            {"name": kind, "status": "failed", "artifact": {},
                             "summary": "boom"} if kind == "homework"
                            else {"name": kind, "status": "success",
                                  "artifact": {"x": 1}, "summary": "ok"}),
                        raising=False)
    report = wfs.run_workflow(session, "新授课", {"subject": "数学"})
    assert report["status"] == "failed"
    assert report["failed_index"] is not None
    assert report["steps"][-1]["status"] == "failed"


# --- 方向四：风格学习与偏好 ---

def test_style_signal_and_recommend(session):
    ams.record_style_signal(session, "lesson_style", "详细")
    ams.record_style_signal(session, "lesson_style", "详细")
    rec = ams.recommend_for(session, "lesson_template")
    assert rec["recommendation"] == "详细"
    assert rec["source"] == "history"


def test_style_signal_rejects_unknown_kind(session):
    ams.record_style_signal(session, "恶意类型", "x")
    assert ams.top_style_signals(session, "恶意类型") == []


def test_ai_preferences_roundtrip(session):
    ams.save_ai_preferences(session, lesson_style="简洁",
                            difficulty_pref="拔高", proactivity="低",
                            method_pref="探究式")
    session.commit()
    prefs = ams.load_ai_preferences(session)
    assert prefs["lesson_style"] == "简洁"
    assert prefs["proactivity"] == "低"


# --- 方向五：工具 ---

def test_new_tools_registered():
    for name in ("get_student_profile", "create_homework",
                 "compose_exam", "export_document"):
        assert name in at.TOOLS
    assert at.TOOLS["create_homework"]["risk"] == "high"
    assert at.TOOLS["compose_exam"]["risk"] == "high"
    assert at.TOOLS["get_student_profile"]["risk"] == "low"


def test_high_risk_tool_needs_confirmation(session):
    with pytest.raises(at.ToolError):
        at.execute_tool(session, "create_homework", {"name": "作业"},
                        confirmed=False)


def test_unknown_tool_and_bad_params(session):
    with pytest.raises(at.ToolError):
        at.execute_tool(session, "nope", {})
    with pytest.raises(at.ToolError):
        at.execute_tool(session, "get_student_profile", {})


def test_tool_logging_and_stats(session, monkeypatch):
    # 低风险工具正常调用会写审计
    from utils import student_service
    student_service.get_or_create_student(session, "甲", "一班")
    session.commit()
    at.execute_tool(session, "get_student_profile", {"student_name": "甲"})
    session.commit()
    stats = at.tool_usage_stats(session)
    assert any(s["tool"] == "get_student_profile" for s in stats)


def test_execute_chain_chains_output(session):
    calls = []

    def fake_handler(session, params):
        calls.append(params)
        return {"value": len(calls)}

    monkeypatch_tools = dict(at.TOOLS)
    monkeypatch_tools["_t1"] = {"description": "", "risk": "low",
                                "parameters": {}, "handler": fake_handler}
    monkeypatch_tools["_t2"] = {"description": "", "risk": "low",
                                "parameters": {}, "handler": fake_handler}
    at.TOOLS.update(monkeypatch_tools)
    try:
        out = at.execute_chain(session, [
            {"tool_name": "_t1", "params": {}},
            {"tool_name": "_t2", "params": {}, "inject": {"prev": "value"}},
        ])
        assert out["status"] == "success"
        assert calls[1]["prev"] == 1  # 注入上一步输出
    finally:
        at.TOOLS.pop("_t1", None)
        at.TOOLS.pop("_t2", None)


def test_execute_chain_stops_on_failure(session):
    out = at.execute_chain(session, [{"tool_name": "nope", "params": {}}])
    assert out["status"] == "failed" and out["failed_index"] == 0
