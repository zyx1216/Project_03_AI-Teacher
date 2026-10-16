# -*- coding: utf-8 -*-
"""自动化工作流服务（v2.6.0）。

工作流模板存 data/agent_workflows.json（预设 4 个 + 自定义）；
执行时按步骤调用现有服务，产物一律落草稿/待审核，不自动审批。
"""

from __future__ import annotations

import json
from datetime import datetime

import config

# 4 个预设工作流；(步骤名, 类型)
PRESET_WORKFLOWS = {
    "新授课": [("生成教案", "lesson"), ("生成PPT", "ppt"),
             ("生成课堂练习", "practice"), ("生成课后作业", "homework")],
    "复习课": [("知识点梳理", "lesson"), ("典型例题", "lesson"),
             ("变式练习", "practice"), ("生成测试卷", "exam")],
    "试卷讲评课": [("试卷分析", "analysis"), ("错题讲解", "lesson"),
                ("变式练习", "practice"), ("巩固作业", "homework")],
    "习题课": [("例题讲解", "lesson"), ("课堂练习", "practice"),
             ("课后作业", "homework")],
}


def _path():
    return config.DATA_DIR / "agent_workflows.json"


def _empty() -> dict:
    return {"custom": []}


def load_workflows() -> dict:
    """读取工作流模板；缺失自建、损坏回退默认且不覆盖原文件。"""
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _empty()
    if not path.exists():
        try:
            path.write_text(json.dumps(_empty(), ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError:
            pass
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("结构非法")
        data.setdefault("custom", [])
        return data
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        return _empty()


def save_workflows(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def list_templates() -> dict:
    """返回 {"presets": {name: [步骤]}, "custom": [...]}。"""
    return {"presets": PRESET_WORKFLOWS,
            "custom": list(load_workflows().get("custom") or [])}


def save_custom_template(name: str, steps: list[list[str]]) -> list[dict]:
    """保存/覆盖一条自定义工作流模板。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("请填写模板名称。")
    if not steps:
        raise ValueError("请至少配置一个步骤。")
    data = load_workflows()
    items = [i for i in (data.get("custom") or [])
             if i.get("name") != name]
    items.append({"name": name,
                  "steps": [{"name": s[0], "kind": s[1]} for s in steps],
                  "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    data["custom"] = items
    save_workflows(data)
    return items


def delete_custom_template(name: str) -> list[dict]:
    data = load_workflows()
    data["custom"] = [i for i in (data.get("custom") or [])
                      if i.get("name") != name]
    save_workflows(data)
    return data["custom"]


def resolve_steps(template_name: str) -> list[dict]:
    """按模板名取步骤定义（预设优先，其次自定义）。"""
    if template_name in PRESET_WORKFLOWS:
        return [{"name": n, "kind": k}
                for n, k in PRESET_WORKFLOWS[template_name]]
    for item in load_workflows().get("custom") or []:
        if item.get("name") == template_name:
            return list(item.get("steps") or [])
    raise ValueError(f"未找到工作流模板：{template_name}")


def run_step(session, kind: str, params: dict) -> dict:
    """执行单个工作流步骤，返回 {"name","status","artifact","summary"}。

    只读/生成草稿；写库类（作业/试卷）落 pending/草稿，不自动审批。
    """
    subject = params.get("subject") or "数学"
    grade = params.get("grade") or ""
    chapter = params.get("chapter") or ""
    try:
        if kind == "lesson":
            from utils import lesson_service
            plan = lesson_service.generate_plan_text(
                subject=subject, grade=grade, chapter=chapter,
                hours=int(params.get("hours") or 1),
                style=params.get("style") or "标准")
            saved = lesson_service.save_plan(
                session, params.get("title") or f"{chapter}教案", plan,
                grade=grade, chapter=chapter, subject=subject)
            return {"name": "生成教案", "status": "success",
                    "artifact": {"plan_id": saved.id, "title": saved.title},
                    "summary": f"教案已保存（#{saved.id}）"}
        if kind == "practice":
            from utils import question_service
            items = question_service.generate_questions_for_knowledge_points(
                [chapter] if chapter else [], subject=subject, grade=grade,
                count_per_kp=3)
            ids = []
            for item in items:
                data = question_service.validate_question(item)
                if not data:
                    continue
                q = question_service.create_question(
                    session, data, source="ai_generated",
                    status="pending", subject=subject)
                ids.append(q.id)
            return {"name": "生成练习/题目", "status": "success",
                    "artifact": {"question_ids": ids},
                    "summary": f"生成 {len(ids)} 道待审核题"}
        if kind in ("homework", "exam"):
            from utils import homework_service
            hw_type = "exam" if kind == "exam" else "after_class"
            name = params.get("title") or (f"{chapter}{'测试卷' if kind == 'exam' else '作业'}")
            hw = homework_service.create_homework(
                session, name[:100], homework_type=hw_type,
                subject=subject, grade=grade)
            return {"name": ("生成测试卷" if kind == "exam" else "生成作业"),
                    "status": "success",
                    "artifact": {"homework_id": hw.id, "name": hw.name},
                    "summary": f"已创建草稿（#{hw.id}）"}
        if kind == "ppt":
            return {"name": "生成PPT", "status": "skipped",
                    "artifact": {},
                    "summary": "PPT 需在 AI 备课页基于已保存教案生成"}
        if kind == "analysis":
            return {"name": "试卷分析", "status": "skipped",
                    "artifact": {}, "summary": "请在学情页对具体考试做分析"}
        return {"name": kind, "status": "skipped", "artifact": {},
                "summary": "未知步骤类型"}
    except Exception as exc:  # noqa: BLE001 —— 单步失败返回错误，不抛给上层
        return {"name": kind, "status": "failed", "artifact": {},
                "summary": f"执行失败：{exc}"}


def run_workflow(session, template_name: str, params: dict,
                 start_index: int = 0) -> dict:
    """按模板逐步执行；任一步失败即停，可带 start_index 续跑。"""
    steps = resolve_steps(template_name)
    results = []
    failed_index = None
    for idx, step in enumerate(steps):
        if idx < start_index:
            continue
        out = run_step(session, step.get("kind"), params)
        out["step_index"] = idx
        out["step_name"] = step.get("name")
        results.append(out)
        if out["status"] == "failed":
            failed_index = idx
            break
    ok = failed_index is None
    report = {
        "template": template_name,
        "status": "success" if ok else "failed",
        "failed_index": failed_index,
        "steps": results,
        "artifacts": [r["artifact"] for r in results if r.get("artifact")],
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return report
