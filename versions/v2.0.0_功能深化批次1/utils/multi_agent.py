# -*- coding: utf-8 -*-
"""多Agent协作服务（v1.9.6）。

三个专业 Agent 是“角色封装 + 调现有服务层”：不绕过服务直接让 LLM 产数据，
真实出题/备课/分析与落库都走现有 service，结果可直接保存、不产生游离数据。
Coordinator 负责按场景分派、记录日志和失败重试。

单 Agent 超时由现有 LLM 超时（≤60 秒）保证，不做网络强杀。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

import config
from models.models import Exam, Textbook

LOG_DIR = config.DATA_DIR / "multi_agent_logs"

FULL_LESSON = "full_lesson"
EXAM_IMPROVE = "exam_improve"
LAYERED_TEACHING = "layered_teaching"

SCENARIOS = [FULL_LESSON, EXAM_IMPROVE, LAYERED_TEACHING]

# 每个场景由哪些 Agent、按什么顺序执行。
SCENARIO_STEPS = {
    FULL_LESSON: ["lesson", "question", "analysis"],
    EXAM_IMPROVE: ["analysis", "lesson", "question"],
    LAYERED_TEACHING: ["analysis", "lesson", "question"],
}


def scenario_of(text: str, params: dict | None = None) -> str:
    """按指令规则判定多Agent场景。"""
    content = str(text or "")
    params = params or {}
    if "分层" in content:
        return LAYERED_TEACHING
    if "分析" in content and any(w in content for w in ("改进", "复习", "强化")):
        return EXAM_IMPROVE
    if "备课" in content or "备一节" in content:
        return FULL_LESSON
    if params.get("student_name"):
        return EXAM_IMPROVE
    return FULL_LESSON


# ---------------------------------------------------------------------------
# Agent 定义
# ---------------------------------------------------------------------------

class BaseAgent:
    """Agent 基类：持有名称与角色设定。"""

    key = "base"

    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role

    def run(self, session, task: dict, context: dict) -> dict:
        """子类实现：调用对应服务层执行任务。"""
        raise NotImplementedError

    def _result(self, summary: str, artifact=None, status: str = "success"):
        return {
            "agent": self.key, "agent_name": self.name,
            "status": status, "summary": summary,
            "artifact": artifact or {},
        }


class LessonAgent(BaseAgent):
    """备课Agent：角色封装，执行走 lesson/agent 服务。"""

    key = "lesson"

    def __init__(self):
        super().__init__("📖 备课Agent", "资深教案编写专家，擅长结构化教学设计。")

    def run(self, session, task: dict, context: dict) -> dict:
        from utils import agent_service
        result = agent_service._do_prepare(session, task)
        return self._result(result.get("summary", "教案已生成"),
                            artifact={"route": result.get("route"),
                                      "extra": result.get("extra")})


class QuestionAgent(BaseAgent):
    """出题Agent：角色封装，执行走作业组卷服务。"""

    key = "question"

    def __init__(self):
        super().__init__("✏️ 出题Agent", "命题专家，擅长按知识点与难度精准出题。")

    def run(self, session, task: dict, context: dict) -> dict:
        from utils import homework_service as hw_svc
        # 若上一步已有作业/试卷，则往其中补题；否则新建一份再组卷。
        homework_id = context.get("homework_id")
        created = False
        if not homework_id:
            subject = task.get("subject") or "数学"
            hw = hw_svc.create_homework(
                session, f"{subject}Agent组卷", homework_type="after_class",
                subject=subject,
                grade=task.get("grade") or None,
                class_name=task.get("class_name") or None)
            session.flush()
            homework_id, created = hw.id, True
        slots = task.get("slots") or [
            {"question_type": "choice", "difficulty": 1, "count": 3},
            {"question_type": "fill", "difficulty": 2, "count": 2}]
        stats = hw_svc.auto_compose(session, homework_id, {"slots": slots})
        context["homework_id"] = homework_id
        total = stats.get("total_questions", 0)
        return self._result(
            f"已生成/补充题目，当前共 {total} 题",
            artifact={"homework_id": homework_id, "stats": stats,
                      "created": created})


class AnalysisAgent(BaseAgent):
    """分析Agent：角色封装，执行走考试分析服务。"""

    key = "analysis"

    def __init__(self):
        super().__init__("📊 分析Agent", "学情诊断专家，擅长成绩分析与薄弱点识别。")

    def run(self, session, task: dict, context: dict) -> dict:
        from utils import exam_service
        exam_id = task.get("exam_id") or context.get("exam_id")
        if not exam_id:
            exams = exam_service.list_exams(session)
            if not exams:
                return self._result("暂无考试数据可分析。",
                                    artifact={"has_data": False})
            exam_id = exams[-1].id
            context["exam_id"] = exam_id
        data = exam_service.analyze_exam(session, exam_id)
        total_stats = data.get("total_stats", {})
        summary = (
            f"考试分析完成：班均 {total_stats.get('average')}，"
            f"及格率 {total_stats.get('pass_rate')}")
        return self._result(summary, artifact={
            "exam_id": exam_id, "has_data": True,
            "average": total_stats.get("average"),
            "pass_rate": total_stats.get("pass_rate")})


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class Coordinator:
    """协调者：按场景把任务分派给各 Agent，记录日志、支持重试。"""

    def __init__(self):
        self.agents = {
            "lesson": LessonAgent(),
            "question": QuestionAgent(),
            "analysis": AnalysisAgent(),
        }

    def execute(self, session, scenario: str, task: dict,
                start_index: int = 0) -> dict:
        """按场景顺序分派 Agent；start_index 用于跳过/从失败步重试。"""
        if scenario not in SCENARIO_STEPS:
            raise ValueError(f"未知场景：{scenario}")
        keys = SCENARIO_STEPS[scenario]
        started = time.time()
        agent_out = list(task.get("_agent_out") or [])
        failed_index = None

        for i in range(start_index, len(keys)):
            agent = self.agents[keys[i]]
            t0 = time.time()
            try:
                out = agent.run(session, task, task.setdefault(
                    "_context", {}))
            except Exception as exc:
                failed_index = i
                agent_out.append({
                    "agent": agent.key, "agent_name": agent.name,
                    "status": "failed", "summary": str(exc),
                    "step_index": i,
                    "elapsed": round(time.time() - t0, 2)})
                task["_agent_out"] = agent_out
                return self._finish(
                    "failed", scenario, task, agent_out, failed_index,
                    started, summary=(
                        f"第 {i + 1} 个“{agent.name}”失败：{exc}"))
            out["elapsed"] = round(time.time() - t0, 2)
            out["step_index"] = i
            agent_out.append(out)
            task["_agent_out"] = agent_out

        summary = "多Agent协作完成：" + "；".join(
            a.get("summary", "") for a in agent_out)
        return self._finish("success", scenario, task, agent_out, None,
                            started, summary=summary)

    def _finish(self, status, scenario, task, agent_out, failed_index,
                started, *, summary) -> dict:
        """组装统一返回并写执行日志。"""
        result = {
            "status": status,
            "summary": summary,
            "scenario": scenario,
            "agents": agent_out,
            "failed_index": failed_index,
            "elapsed": round(time.time() - started, 2),
            "task": _safe_task(task),
        }
        try:
            write_log(result)
        except OSError:
            pass
        return result


def _safe_task(task: dict) -> dict:
    """去掉任务里的内部缓存字段，保证日志 JSON 安全。"""
    return {k: v for k, v in task.items()
            if not k.startswith("_")}


# ---------------------------------------------------------------------------
# 执行日志
# ---------------------------------------------------------------------------

def write_log(result: dict) -> str:
    """把一次多Agent执行写入 data/multi_agent_logs/时间戳.json。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    path = LOG_DIR / f"{stamp}.json"
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def list_logs(limit: int = 10) -> list[dict]:
    """读取最近的多Agent执行日志（含文件名与摘要）。"""
    if not LOG_DIR.exists():
        return []
    rows = []
    for path in sorted(LOG_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        data["file"] = path.name
        rows.append(data)
    return rows
