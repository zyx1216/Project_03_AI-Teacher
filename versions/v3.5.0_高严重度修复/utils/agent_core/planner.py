# -*- coding: utf-8 -*-
"""Agent 任务规划器：复用现有意图和工具，输出结构化步骤。"""
from __future__ import annotations

def build_plan(task: str) -> list[dict]:
    text = str(task or "")
    if "单元" in text:
        return [{"step": 1, "agent": "lesson", "tool_name": "create_unit_plan", "params": {}}]
    if "备课" in text:
        return [{"step": 1, "agent": "lesson", "tool_name": "search_resource", "params": {}},
                {"step": 2, "agent": "lesson", "tool_name": "create_lesson_plan", "params": {}}]
    if "试卷" in text or "出题" in text:
        return [{"step": 1, "agent": "question", "tool_name": "generate_questions", "params": {}}]
    if "讲评" in text or "批改" in text:
        return [{"step": 1, "agent": "grading", "tool_name": "generate_review", "params": {}}]
    if "分析" in text or "诊断" in text:
        return [{"step": 1, "agent": "analysis", "tool_name": "diagnose_teaching", "params": {}}]
    return [{"step": 1, "agent": "analysis", "tool_name": "diagnose_teaching", "params": {}}]
