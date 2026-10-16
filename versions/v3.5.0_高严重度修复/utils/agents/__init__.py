# -*- coding: utf-8 -*-
"""四个专业 Agent 的兼容包装。"""
from utils.agent_core.base_agent import BaseAgent

class LessonAgent(BaseAgent):
    name = "备课Agent"; role = "资深备课专家"
    tool_names = ("search_resource", "create_lesson_plan")

class QuestionAgent(BaseAgent):
    name = "出题Agent"; role = "命题专家"
    tool_names = ("generate_questions", "generate_variation", "search_resource")

class GradingAgent(BaseAgent):
    name = "批改Agent"; role = "批改与讲评专家"
    tool_names = ("generate_review", "get_student_profile")

class AnalysisAgent(BaseAgent):
    name = "分析Agent"; role = "学情分析专家"
    tool_names = ("analyze_exam", "diagnose_teaching", "export_report")

__all__ = ["LessonAgent", "QuestionAgent", "GradingAgent", "AnalysisAgent"]
