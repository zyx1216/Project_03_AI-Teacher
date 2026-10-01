# -*- coding: utf-8 -*-
"""Agent 工具注册表：兼容现有 15 个工具并补充缺失工具。"""
from __future__ import annotations
import json
from utils import agent_tools

def _require(params, keys):
    missing = [key for key in keys if params.get(key) in (None, "")]
    if missing:
        raise ValueError("缺少参数：" + "、".join(missing))

def create_unit_plan(session, params):
    from utils import unit_design_service
    _require(params, ("name", "subject"))
    objectives = unit_design_service.generate_unit_objectives(
        session, params["name"], params["subject"], params.get("grade", ""),
        params.get("chapter", ""), params.get("textbook_id"),
        int(params.get("lesson_count") or 6))
    unit = unit_design_service.create_unit_plan(
        session, params["name"], params["subject"], params.get("grade", ""),
        params.get("textbook_id"), params.get("chapter", ""), objectives)
    return {"unit_id": unit.id, "name": unit.name, "lesson_count": unit.lesson_count}

def generate_variation(session, params):
    from utils import variation_service
    _require(params, ("question_id",))
    variants = variation_service.generate_variations(
        session, int(params["question_id"]),
        params.get("variation_types") or ["换数字"],
        int(params.get("count") or 5), params.get("difficulty") or "keep")
    ids = variation_service.save_variations(session, variants, int(params["question_id"]))
    return {"question_ids": ids, "count": len(ids)}

def generate_review(session, params):
    from utils import review_service
    _require(params, ("homework_id",))
    result = review_service.build_review_files(session, int(params["homework_id"]))
    return {"record_id": result["record"].id,
            "ppt": result["ppt_rel"], "script": result["script_rel"]}

def diagnose_teaching(session, params):
    from utils import diagnosis_service
    period = params.get("period") or {"type": "month"}
    row = diagnosis_service.generate_diagnosis(
        session, params.get("class_name"), params.get("subject") or "数学",
        params.get("grade"), period)
    return {"diagnosis_id": row.id, "score": row.score}

def export_report(session, params):
    from utils import diagnosis_service
    _require(params, ("diagnosis_id",))
    row = session.get(diagnosis_service.TeachingDiagnosis, int(params["diagnosis_id"]))
    if row is None:
        raise ValueError("诊断记录不存在。")
    data = diagnosis_service.export_diagnosis_pdf(row)
    return {"diagnosis_id": row.id, "size": len(data), "format": "pdf"}

def manage_calendar(session, params):
    return {"message": "日历操作请在「教学日历」页完成。",
            "action": params.get("action") or "查看"}

_EXTRA = {
    "create_unit_plan": {"description": "创建单元整体设计（高风险，需确认）", "risk": "high",
                         "parameters": {"type": "object", "required": ["name", "subject"],
                                        "properties": {"name": {"type": "string"}, "subject": {"type": "string"}}},
                         "handler": create_unit_plan},
    "generate_variation": {"description": "生成并保存变式题（高风险，需确认）", "risk": "high",
                           "parameters": {"type": "object", "required": ["question_id"],
                                          "properties": {"question_id": {"type": "integer"}}},
                           "handler": generate_variation},
    "generate_review": {"description": "生成作业讲评材料（高风险，需确认）", "risk": "high",
                        "parameters": {"type": "object", "required": ["homework_id"],
                                       "properties": {"homework_id": {"type": "integer"}}},
                        "handler": generate_review},
    "diagnose_teaching": {"description": "生成教学诊断报告", "risk": "medium",
                          "parameters": {"type": "object", "properties": {}},
                          "handler": diagnose_teaching},
    "export_report": {"description": "导出诊断报告", "risk": "low",
                      "parameters": {"type": "object", "required": ["diagnosis_id"],
                                     "properties": {"diagnosis_id": {"type": "integer"}}},
                      "handler": export_report},
    "manage_calendar": {"description": "查看或准备日历操作", "risk": "low",
                        "parameters": {"type": "object", "properties": {}},
                        "handler": manage_calendar},
}
REGISTRY = dict(agent_tools.TOOLS)
REGISTRY.update(_EXTRA)

def list_tools() -> list[dict]:
    return [{"name": name, "description": item.get("description", ""),
             "risk": item.get("risk", "low"), "parameters": item.get("parameters", {})}
            for name, item in REGISTRY.items()]

def get_tool(name: str) -> dict:
    if name not in REGISTRY:
        raise ValueError(f"未知工具：{name}")
    return REGISTRY[name]

def execute_tool(session, name: str, params: dict | None = None, confirmed: bool = False):
    tool = get_tool(name)
    if tool.get("risk") == "high" and not confirmed:
        raise ValueError(f"高风险工具“{name}”必须先确认。")
    return tool["handler"](session, dict(params or {}))
