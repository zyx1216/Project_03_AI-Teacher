# -*- coding: utf-8 -*-
"""Agent 执行器：顺序执行、重试并写入执行日志。"""
from __future__ import annotations
import json
import time
from datetime import datetime
from models.models import AgentExecutionLog
from utils.agent_core import tool_registry

def execute_plan(session, task: str, plan: list[dict], confirmed: bool = False,
                 retries: int = 1, start_step: int = 0) -> dict:
    started = time.time()
    steps = []
    status = "success"
    for item in plan:
        index = int(item.get("step") or len(steps) + 1)
        if index <= start_step:
            continue
        params = dict(item.get("params") or {})
        last_error = None
        for attempt in range(max(0, retries) + 1):
            try:
                result = tool_registry.execute_tool(
                    session, item.get("tool_name"), params, confirmed=confirmed)
                steps.append({"step": index, "agent": item.get("agent", ""),
                              "tool_name": item.get("tool_name"),
                              "status": "success", "result": result})
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        if last_error is not None:
            steps.append({"step": index, "agent": item.get("agent", ""),
                          "tool_name": item.get("tool_name"),
                          "status": "failed", "error": last_error})
            status = "failed"
            break
    row = AgentExecutionLog(
        task=task,
        plan_json=json.dumps(plan, ensure_ascii=False),
        steps_json=json.dumps(steps, ensure_ascii=False, default=str),
        result=json.dumps({"status": status,
                           "summary": f"完成 {sum(1 for x in steps if x['status']=='success')}/{len(plan)} 步"},
                          ensure_ascii=False),
        status=status, duration=round(time.time() - started, 3),
        created_at=datetime.now())
    session.add(row)
    session.flush()
    return {"status": status, "log_id": row.id, "steps": steps}

def list_logs(session, limit=50):
    return (session.query(AgentExecutionLog)
            .order_by(AgentExecutionLog.created_at.desc(), AgentExecutionLog.id.desc())
            .limit(limit).all())

def get_log(session, log_id):
    return session.get(AgentExecutionLog, int(log_id))
