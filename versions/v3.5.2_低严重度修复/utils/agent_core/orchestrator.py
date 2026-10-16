# -*- coding: utf-8 -*-
"""Agent Orchestrator：规划并执行自然语言任务。"""
from __future__ import annotations
from utils.agent_core import executor, planner

def plan(task: str) -> list[dict]:
    return planner.build_plan(task)

def run(session, task: str, confirmed: bool = False, retries: int = 1) -> dict:
    plan_steps = planner.build_plan(task)
    result = executor.execute_plan(session, task, plan_steps, confirmed=confirmed,
                                   retries=retries)
    result["plan"] = plan_steps
    return result
