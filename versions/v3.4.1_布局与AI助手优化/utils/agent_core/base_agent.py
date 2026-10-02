# -*- coding: utf-8 -*-
"""Agent 基类适配层。"""
from __future__ import annotations
from utils import agent_core

class BaseAgent:
    """统一 think/act/observe/run 接口，实际工具调用走注册表。"""
    name = "Agent"
    role = "通用教学助手"
    tool_names: tuple[str, ...] = ()

    def __init__(self, session=None):
        self.session = session

    def think(self, task: str) -> dict:
        return {"task": task, "agent": self.name, "role": self.role,
                "tools": list(self.tool_names)}

    def act(self, tool_name: str, params: dict, confirmed: bool = False) -> dict:
        return agent_core.execute_tool(self.session, tool_name, params, confirmed=confirmed)

    def observe(self, result: dict) -> str:
        if not isinstance(result, dict):
            return str(result)
        return str(result.get("summary") or result.get("message") or "已完成")

    def run(self, task: str, params: dict | None = None, confirmed: bool = False) -> dict:
        steps = []
        for tool_name in self.tool_names:
            call_params = dict(params or {})
            try:
                result = self.act(tool_name, call_params, confirmed=confirmed)
                steps.append({"tool_name": tool_name, "status": "success",
                              "result": result, "observation": self.observe(result)})
            except Exception as exc:  # noqa: BLE001
                steps.append({"tool_name": tool_name, "status": "failed",
                              "error": str(exc)})
                break
        return {"agent": self.name, "task": task, "steps": steps}
