# -*- coding: utf-8 -*-
"""可注册、可审计的 Agent 工具调用系统。"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from utils import agent_memory_service


class ToolError(ValueError):
    """工具调用错误，消息必须是中文。"""


def _require(params: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        value = params.get(key)
        if value is None or str(value).strip() == "":
            raise ToolError(f"缺少必要参数：{key}")


def _json_safe_analysis(data: dict) -> dict:
    return {
        "exam_id": data["exam"].id,
        "exam_name": data["exam"].name,
        "subjects": data["subjects"],
        "total_full": data["total_full"],
        "average": data["total_stats"].get("mean"),
        "pass_rate": data["total_stats"].get("pass_rate"),
        "excellent_rate": data["total_stats"].get("excellent_rate"),
        "student_count": len(data["rows"]),
    }


def query_student_score(session, params: dict) -> dict:
    """查询学生成绩。"""
    _require(params, ("student_name",))
    from utils import student_service, exam_service
    students = student_service.list_students(session, keyword=params["student_name"])
    if not students:
        return {"student": params["student_name"], "scores": []}
    history = exam_service.student_scores_over_time(session, students[0].id)
    return {"student": students[0].name, "scores": history[-10:]}


def search_resource(session, params: dict) -> dict:
    """查询教学资料。"""
    from utils import material_service
    items = material_service.list_materials(
        session, subject=params.get("subject"),
        name=params.get("keyword"))
    return {"resources": [
        {"id": x.id, "name": x.name, "subject": x.subject,
         "grade": x.grade, "type": x.file_type}
        for x in items]}


def generate_questions(session, params: dict) -> dict:
    """生成题目/试卷：复用 Agent 服务，确保落库规则不绕过。"""
    from utils import agent_service
    normalized = {
        "subject": params.get("subject") or "数学",
        "grade": params.get("grade") or "",
        "class_name": params.get("class_name") or "",
        "chapter": params.get("chapter") or "",
        "knowledge_points": params.get("knowledge_points") or [],
        "question_type": params.get("question_type") or "",
        "count": int(params.get("count") or 10),
        "difficulty": int(params.get("difficulty") or 0),
    }
    return agent_service._do_compose(session, normalized)


def create_lesson_plan(session, params: dict) -> dict:
    """生成教案：复用 Agent 服务。"""
    from utils import agent_service
    normalized = {
        "subject": params.get("subject") or "数学",
        "grade": params.get("grade") or "",
        "class_name": params.get("class_name") or "",
        "chapter": params.get("chapter") or "",
        "topic": params.get("topic") or params.get("chapter") or "",
    }
    return agent_service._do_prepare(session, normalized)


def generate_chart(session, params: dict):
    """返回 Plotly 图表对象，不生成临时文件。"""
    import plotly.graph_objects as go
    _require(params, ("exam_id",))
    from utils import exam_service
    data = exam_service.analyze_exam(
        session, int(params["exam_id"]),
        class_name=params.get("class_name"))
    if not data:
        raise ToolError("考试不存在，无法生成图表。")
    subjects = data["subjects"]
    averages = [data["subject_stats"][s].get("mean") or 0 for s in subjects]
    fig = go.Figure(go.Bar(x=subjects, y=averages))
    fig.update_layout(
        title="各科平均分", xaxis_title="学科", yaxis_title="平均分",
        height=380)
    return fig


def analyze_exam_tool(session, params: dict) -> dict:
    """分析考试：复用考试分析服务。"""
    _require(params, ("exam_id",))
    from utils import exam_service
    data = exam_service.analyze_exam(
        session, int(params["exam_id"]),
        class_name=params.get("class_name"))
    if not data:
        raise ToolError("考试不存在。")
    return _json_safe_analysis(data)


def update_student_score(session, params: dict) -> dict:
    """新增/更新一条成绩。"""
    _require(params, ("student_name", "subject", "score"))
    if "exam_id" not in params and not params.get("exam_name"):
        raise ToolError("缺少必要参数：exam_id 或 exam_name")
    from utils import exam_service
    if params.get("exam_id"):
        exam_id = int(params["exam_id"])
    else:
        exam = exam_service.create_exam(
            session, str(params["exam_name"]),
            exam_date=params.get("exam_date"),
            subject=params.get("subject"))
        session.flush()
        exam_id = exam.id
    result = exam_service.import_scores(session, exam_id, [{
        "name": params["student_name"],
        "class_name": params.get("class_name"),
        "scores": {params["subject"]: float(params["score"])},
    }])
    return {"exam_id": exam_id, **result}


def add_student(session, params: dict) -> dict:
    """新增学生。"""
    _require(params, ("name",))
    from utils import student_service
    student, created = student_service.get_or_create_student(
        session, params["name"], params.get("class_name"),
        params.get("student_no"))
    return {"student_id": student.id, "created": created}


def create_exam_tool(session, params: dict) -> dict:
    """新建考试。"""
    _require(params, ("name",))
    from utils import exam_service
    full_scores = params.get("full_scores") or None
    exam = exam_service.create_exam(
        session, params["name"], exam_date=params.get("exam_date"),
        grade=params.get("grade"), term=params.get("term"),
        full_scores=full_scores)
    session.flush()
    return {"exam_id": exam.id}


def delete_question_tool(session, params: dict) -> dict:
    """删除题目。高风险，需确认。"""
    _require(params, ("question_id",))
    from models.models import Question
    question = session.get(Question, int(params["question_id"]))
    if question is None:
        raise ToolError("题目不存在。")
    session.delete(question)
    session.flush()
    return {"deleted": int(params["question_id"])}


class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._href = None
        self._capture = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            href = attrs["href"]
            if href.startswith("http") and "duckduckgo.com" not in href:
                self._href = href
                self._capture = True
                self._text = []

    def handle_data(self, data):
        if self._capture:
            self._text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and self._capture:
            title = " ".join(x for x in self._text if x)
            if self._href and title:
                self.results.append({"title": title, "url": self._href})
            self._href = None
            self._capture = False


def web_search_tool(session, params: dict) -> dict:
    """用标准库请求 DuckDuckGo Lite，不新增搜索 API Key。"""
    _require(params, ("query",))
    url = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(params["query"])
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except OSError as exc:
        raise ToolError(f"网络搜索失败：{exc}") from exc
    parser = _DDGParser()
    parser.feed(html)
    return {"results": parser.results[:5]}


def get_student_profile(session, params: dict) -> dict:
    """获取学生画像（成绩/知识点/作业概览）。"""
    _require(params, ("student_name",))
    from utils import student_service, exam_service
    name = str(params["student_name"]).strip()
    students = student_service.list_students(session)
    stu = next((x for x in students if x.name == name), None)
    if stu is None:
        raise ToolError(f"未找到学生：{name}")
    history = exam_service.student_scores_over_time(session, stu.id) or []
    if params.get("subject"):
        history = [h for h in history
                   if h.get("subject") in (None, params["subject"])
                   or params["subject"] in (h.get("subjects") or [])]
    return {"student_id": stu.id, "name": stu.name,
            "class_name": stu.class_name,
            "exam_count": len(history), "history": history[:20]}


def create_homework(session, params: dict) -> dict:
    """创建一份草稿作业（高风险，需确认）。"""
    _require(params, ("name",))
    from utils import homework_service
    hw = homework_service.create_homework(
        session, str(params["name"])[:100],
        homework_type=params.get("homework_type") or "after_class",
        subject=params.get("subject") or "数学",
        grade=params.get("grade"),
        class_name=params.get("class_name"))
    return {"homework_id": hw.id, "name": hw.name, "status": hw.status}


def compose_exam(session, params: dict) -> dict:
    """创建一份草稿试卷（高风险，需确认）。"""
    _require(params, ("name",))
    from utils import homework_service
    hw = homework_service.create_homework(
        session, str(params["name"])[:100], homework_type="exam",
        subject=params.get("subject") or "数学",
        grade=params.get("grade"),
        total_score=params.get("total_score"))
    return {"homework_id": hw.id, "name": hw.name, "status": hw.status}


def export_document(session, params: dict) -> dict:
    """导出文档（教案/作业/成绩）字节，返回大小与类型。"""
    _require(params, ("kind", "target_id"))
    kind = str(params["kind"]).strip()
    target_id = int(params["target_id"])
    if kind == "lesson":
        from utils import lesson_service
        lesson = session.get(__import__("models.models", fromlist=["LessonPlan"]).LessonPlan, target_id)
        if lesson is None:
            raise ToolError("教案不存在。")
        data = lesson_service.export_word(lesson, lesson_service.load_plan(lesson))
    elif kind == "homework":
        from utils import homework_service
        data = homework_service.export_word(session, target_id, with_answer=False)
    else:
        raise ToolError("不支持的导出类型，可选：lesson/homework。")
    return {"kind": kind, "target_id": target_id, "size": len(data)}

TOOLS = {
    "query_student_score": {
        "description": "按学生姓名查询最近成绩",
        "risk": "low",
        "parameters": {"type": "object",
                       "required": ["student_name"],
                       "properties": {"student_name": {"type": "string"}}},
        "handler": query_student_score},
    "search_resource": {
        "description": "按关键词或学科查询教学资料",
        "risk": "low", "parameters": {"type": "object", "properties": {}},
        "handler": search_resource},
    "generate_questions": {
        "description": "生成题目或试卷",
        "risk": "medium",
        "parameters": {"type": "object", "properties": {}},
        "handler": generate_questions},
    "create_lesson_plan": {
        "description": "生成教案",
        "risk": "medium",
        "parameters": {"type": "object", "properties": {}},
        "handler": create_lesson_plan},
    "generate_chart": {
        "description": "生成 Plotly 图表",
        "risk": "low",
        "parameters": {"type": "object", "required": ["exam_id"],
                       "properties": {"exam_id": {"type": "integer"}}},
        "handler": generate_chart},
    "analyze_exam": {
        "description": "分析一次考试",
        "risk": "low",
        "parameters": {"type": "object", "required": ["exam_id"],
                       "properties": {"exam_id": {"type": "integer"}}},
        "handler": analyze_exam_tool},
    "update_student_score": {
        "description": "新增或更新学生成绩",
        "risk": "high",
        "parameters": {"type": "object",
                       "required": ["student_name", "subject", "score"],
                       "properties": {}},
        "handler": update_student_score},
    "add_student": {
        "description": "新增学生",
        "risk": "medium",
        "parameters": {"type": "object", "required": ["name"],
                       "properties": {"name": {"type": "string"}}},
        "handler": add_student},
    "create_exam": {
        "description": "新建考试",
        "risk": "medium",
        "parameters": {"type": "object", "required": ["name"],
                       "properties": {"name": {"type": "string"}}},
        "handler": create_exam_tool},
    "delete_question": {
        "description": "删除题目",
        "risk": "high",
        "parameters": {"type": "object", "required": ["question_id"],
                       "properties": {"question_id": {"type": "integer"}}},
        "handler": delete_question_tool},
    "web_search": {
        "description": "搜索互联网资料",
        "risk": "low",
        "parameters": {"type": "object", "required": ["query"],
                       "properties": {"query": {"type": "string"}}},
        "handler": web_search_tool},
    # v2.6.0 新增 4 个工具
    "get_student_profile": {
        "description": "获取学生画像（成绩/作业概览）",
        "risk": "low",
        "parameters": {"type": "object", "required": ["student_name"],
                       "properties": {"student_name": {"type": "string"},
                                      "subject": {"type": "string"}}},
        "handler": get_student_profile},
    "create_homework": {
        "description": "创建草稿作业（高风险，需确认）",
        "risk": "high",
        "parameters": {"type": "object", "required": ["name"],
                       "properties": {"name": {"type": "string"}}},
        "handler": create_homework},
    "compose_exam": {
        "description": "创建草稿试卷（高风险，需确认）",
        "risk": "high",
        "parameters": {"type": "object", "required": ["name"],
                       "properties": {"name": {"type": "string"}}},
        "handler": compose_exam},
    "export_document": {
        "description": "导出教案/作业文档",
        "risk": "low",
        "parameters": {"type": "object", "required": ["kind", "target_id"],
                       "properties": {"kind": {"type": "string"},
                                      "target_id": {"type": "integer"}}},
        "handler": export_document},
}


def execute_tool(session, tool_name, params, confirmed: bool = False):
    """执行注册工具；高风险工具必须 confirmed=True。"""
    name = str(tool_name or "").strip()
    if name not in TOOLS:
        raise ToolError(f"未知工具：{name}")
    if not isinstance(params, dict):
        raise ToolError("工具参数必须是 JSON 对象。")
    tool = TOOLS[name]
    if tool["risk"] == "high" and not confirmed:
        raise ToolError(f"高风险工具“{name}”必须先确认。")
    import time as _time
    _t0 = _time.time()
    try:
        result = tool["handler"](session, params)
    except ToolError as exc:
        log_tool_call(session, name, params, {"error": str(exc)},
                      int((_time.time() - _t0) * 1000), ok=False)
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        log_tool_call(session, name, params, {"error": str(exc)},
                      int((_time.time() - _t0) * 1000), ok=False)
        raise ToolError(f"工具“{name}”参数不合法：{exc}") from exc
    log_tool_call(session, name, params, result,
                  int((_time.time() - _t0) * 1000), ok=True)
    return result


def parse_and_execute(session, ai_response, confirmed: bool = False):
    """解析 AI 输出的工具调用 JSON 并执行。"""
    if isinstance(ai_response, dict):
        data = ai_response
    else:
        try:
            data = json.loads(str(ai_response))
        except json.JSONDecodeError as exc:
            raise ToolError("AI 没有返回可识别的工具调用 JSON。") from exc
    tool_name = data.get("tool_name") or data.get("name")
    params = data.get("params") or data.get("arguments") or {}
    return execute_tool(session, tool_name, params,
                        confirmed=confirmed or bool(data.get("confirmed")))


# ---------------------------------------------------------------------------
# v2.6.0：工具调用审计 + 多工具链式调用
# ---------------------------------------------------------------------------

def _safe_result(result):
    """把工具结果裁剪成可安全落库的摘要。"""
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(result)
    return text[:500]


def log_tool_call(session, tool_name: str, params: dict, result,
                  elapsed_ms: int = 0, ok: bool = True) -> None:
    """把一次工具调用写入 operation_logs（module=Agent工具，detail 已脱敏）。"""
    try:
        from utils import logger_service
        logger_service.log_operation(
            session, "工具调用", "Agent工具", tool_name,
            {"参数": params, "结果摘要": _safe_result(result),
             "耗时毫秒": int(elapsed_ms), "成功": bool(ok)})
    except Exception:  # noqa: BLE001 —— 审计失败不影响主流程
        pass


def tool_usage_stats(session) -> list[dict]:
    """统计各工具的调用次数与成功率（基于 operation_logs）。"""
    from models.models import OperationLog
    rows = (session.query(OperationLog)
            .filter(OperationLog.module == "Agent工具").all())
    buckets = {}
    for r in rows:
        name = r.target or ""
        b = buckets.setdefault(name, {"tool": name, "calls": 0, "ok": 0})
        b["calls"] += 1
        detail = r.detail or ""
        if '"成功": true' in detail or '"成功":true' in detail:
            b["ok"] += 1
    out = []
    for b in buckets.values():
        rate = round(b["ok"] / b["calls"], 4) if b["calls"] else None
        out.append({"tool": b["tool"], "calls": b["calls"], "ok": b["ok"],
                    "success_rate": rate})
    out.sort(key=lambda x: x["calls"], reverse=True)
    return out


def execute_chain(session, steps: list[dict], confirmed: bool = False,
                  start_index: int = 0) -> dict:
    """按序执行多个工具；上一步输出可作为下一步参数。

    steps: [{"tool_name","params","inject":{下一步参数名: 上一步结果里的键}}]
    任一步失败即停；可用 start_index 从失败处续跑。
    """
    steps = list(steps or [])
    results = []
    failed_index = None
    last_output = None
    for idx, step in enumerate(steps):
        if idx < start_index:
            continue
        name = step.get("tool_name")
        params = dict(step.get("params") or {})
        # 注入上一步输出
        inject = step.get("inject") or {}
        if last_output and inject:
            for target_key, src_key in inject.items():
                if isinstance(last_output, dict) and src_key in last_output:
                    params.setdefault(target_key, last_output[src_key])
        try:
            out = execute_tool(session, name, params, confirmed=confirmed)
            results.append({"index": idx, "tool_name": name,
                            "status": "success", "output": out})
            last_output = out
        except ToolError as exc:
            results.append({"index": idx, "tool_name": name,
                            "status": "failed", "error": str(exc)})
            failed_index = idx
            break
    return {"status": "success" if failed_index is None else "failed",
            "failed_index": failed_index, "steps": results}
