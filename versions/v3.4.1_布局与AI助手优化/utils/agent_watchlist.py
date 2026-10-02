# -*- coding: utf-8 -*-
"""学生预警名单与辅导方案（v2.6.0）。

复用 utils/agent_alert.py 的 5 类检测，聚合成按风险排序的名单；
辅导方案由 LLM 生成，AI 不可用时用规则模板兜底。
"""

from __future__ import annotations

import json

# 预警类型 -> 风险权重（越大越紧急）
RISK_WEIGHT = {
    "student_decline": 3,   # 连续退步
    "score_decline": 2,     # 班级/科目连降
    "homework_submission": 2,
    "progress_delay": 1,
    "question_bank_low": 1,
}

# 预警类型 -> 建议干预措施
SUGGESTIONS = {
    "student_decline": "安排个别辅导，排查近期学习状态，降低练习起点。",
    "score_decline": "针对薄弱知识点做专项复习，增加过关小测。",
    "homework_submission": "与家长沟通作业完成情况，布置可完成的分层作业。",
    "progress_delay": "适当放慢进度，增加复习课时。",
    "question_bank_low": "补充题库题目，便于组卷与练习。",
}


def build_watchlist(session) -> dict:
    """按风险排序的学生/班级预警名单。

    返回 {"items":[{risk,type,title,reason,evidence,suggestion}],
          "student_items":[...], "class_items":[...]}。
    """
    from utils import agent_alert

    alerts = agent_alert.check_all_alerts(session) or []
    items = []
    for a in alerts:
        atype = a.get("alert_type") or a.get("type") or ""
        items.append({
            "risk": RISK_WEIGHT.get(atype, 1),
            "type": atype,
            "severity": a.get("severity") or "",
            "title": a.get("title") or "预警",
            "reason": a.get("content") or "",
            "evidence": a.get("content") or "",
            "suggestion": a.get("suggestion") or SUGGESTIONS.get(
                atype, "关注并跟进。"),
            "route": a.get("route") or "",
            "sub": a.get("sub") or "",
            "student_name": a.get("student_name") or "",
            "student_id": a.get("student_id"),
        })
    items.sort(key=lambda x: x["risk"], reverse=True)
    student_items = [i for i in items if i["student_id"] or i["student_name"]]
    class_items = [i for i in items if i not in student_items]
    return {"items": items, "student_items": student_items,
            "class_items": class_items}


def generate_tutoring_plan(session, student_id: int | None = None,
                           student_name: str = "",
                           chat_func=None) -> dict:
    """为预警学生生成个性化辅导计划。

    返回 {"plan": str, "source": "ai|template", "reason": str}。
    数据不足时给明确提示，不编造。
    """
    from utils import agent_advisor

    facts = {}
    try:
        facts = agent_advisor.weekly_facts(session) or {}
    except Exception:  # noqa: BLE001 —— 数据缺失不阻断
        facts = {}
    weak = facts.get("weak_points") or []
    if not weak and not student_name:
        return {"plan": "", "source": "template",
                "reason": "暂无可用的薄弱点数据，无法生成辅导方案。"}

    weak_text = "、".join(
        str(w.get("knowledge_point") or w.get("name") or w)
        for w in weak[:5]) if weak else "暂无明确薄弱点"
    fallback = (f"个性化辅导方案（{student_name or '该生'}）："
                f"近期薄弱点：{weak_text}。建议先补齐基础概念，"
                "再做同类变式练习，每两天一次小过关；两周后复测跟踪提升。")
    if chat_func is None:
        try:
            from utils import llm_client
            if not llm_client.is_configured():
                return {"plan": fallback, "source": "template",
                        "reason": "AI 未配置，已给基础辅导方案。"}
            chat_func = lambda s, u: llm_client.chat_content(s, u)
        except Exception as exc:  # noqa: BLE001
            return {"plan": fallback, "source": "template",
                    "reason": f"AI 不可用：{exc}"}

    system = ("你是资深教研助手。根据学生薄弱点写一份中文个性化辅导方案，"
              "包含：目标、分阶段措施、练习建议、复测安排；不超过200字。")
    user = f"学生：{student_name or '未指定'}；薄弱点：{weak_text}"
    try:
        plan = str(chat_func(system, user) or "").strip()
        if not plan:
            raise ValueError("AI 返回为空")
        return {"plan": plan, "source": "ai", "reason": ""}
    except Exception as exc:  # noqa: BLE001
        return {"plan": fallback, "source": "template",
                "reason": f"AI 生成失败：{exc}"}
