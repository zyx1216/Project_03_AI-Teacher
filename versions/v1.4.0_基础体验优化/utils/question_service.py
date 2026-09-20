# -*- coding: utf-8 -*-
"""
题目服务层。

负责：
- AI 出题结果的 JSON 解析与容错修复；
- 逐题校验（铁律：答案为空一律拒收）、题型/难度归一；
- SymPy 自动验算（只验算模型主动给出可解析算式的题，三态结果）；
- 题库的增删改查、审核、筛选；
- 题目导出 Word（习题卷 / 教师卷）。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from models.models import Question
from utils.app_config import DEFAULT_SUBJECT

# 题型白名单与中文映射
QUESTION_TYPES = {
    "choice": "选择题", "fill": "填空题", "judge": "判断题", "solution": "解答题",
}
TYPE_ALIASES = {
    "选择": "choice", "选择题": "choice", "单选": "choice", "单选题": "choice", "单项选择题": "choice", "单选选择题": "choice", "choice": "choice",
    "填空": "fill", "填空题": "fill", "fill": "fill", "blank": "fill",
    "判断": "judge", "判断题": "judge", "judge": "judge", "truefalse": "judge",
    "解答": "solution", "解答题": "solution", "计算": "solution", "计算题": "solution",
    "应用": "solution", "大题": "solution", "solution": "solution",
}


def normalize_type(value) -> str:
    """把各种题型写法归一到 choice/fill/judge/solution，无法识别默认 solution。"""
    if value is None:
        return "solution"
    key = str(value).strip().lower().replace(" ", "")
    return TYPE_ALIASES.get(key, "solution")


def normalize_difficulty(value) -> int:
    """难度归一到 1/2/3；中文 基础/中等/拓展 也识别。"""
    if isinstance(value, (int, float)):
        v = int(value)
        return min(3, max(1, v))
    text = str(value or "").strip()
    if "基础" in text or text == "1":
        return 1
    if "拓展" in text or "难" in text or text == "3":
        return 3
    if "中等" in text or text == "2":
        return 2
    return 2


def normalize_knowledge_points(value) -> str:
    """知识点统一存成 JSON 数组字符串；输入可能是 list 或逗号分隔字符串。"""
    if isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
    elif value:
        items = [x.strip() for x in re.split(r"[，,、;；]\s*", str(value)) if x.strip()]
    else:
        items = []
    return json.dumps(items, ensure_ascii=False)


def knowledge_points_list(question: Question) -> list[str]:
    """把题目的知识点 JSON 字符串还原成列表。"""
    try:
        data = json.loads(question.knowledge_points) if question.knowledge_points else []
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 围栏。"""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return fence.group(1).strip() if fence else text


def parse_generated_questions(text: str) -> list[dict]:
    """
    解析 AI 出题输出为题目字典列表。
    兼容：纯 JSON 数组、带围栏、外层包了个 {"questions": [...]}。
    解析失败返回空列表。
    """
    cleaned = strip_code_fence(text)
    candidates = [cleaned]
    # 尝试截取第一个 [ 到最后一个 ]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start >= 0 and end > start:
        candidates.append(cleaned[start:end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict) and isinstance(data.get("questions"), list):
                data = data["questions"]
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except json.JSONDecodeError:
            continue
    return []


def validate_question(item: dict) -> Optional[dict]:
    """
    校验并归一化一道题。答案为空返回 None（拒收），否则返回规范化字典。
    """
    content = str(item.get("content") or item.get("题干") or item.get("question") or "").strip()
    answer = str(item.get("answer") or item.get("答案") or "").strip()
    if not content or not answer:
        return None
    return {
        "content": content,
        "question_type": normalize_type(item.get("question_type") or item.get("题型")),
        "difficulty": normalize_difficulty(item.get("difficulty") or item.get("难度")),
        "knowledge_points": normalize_knowledge_points(
            item.get("knowledge_points") or item.get("知识点") or item.get("knowledge")),
        "answer": answer,
        "analysis": str(item.get("analysis") or item.get("解析") or "").strip(),
        "error_points": str(item.get("error_points") or item.get("易错点") or "").strip(),
        "verify": item.get("verify"),  # 可选的 SymPy 验算描述
    }


def build_questions(text: str) -> tuple[list[dict], int]:
    """
    解析并校验整批 AI 题目。
    返回 (有效题目列表, 因缺答案/题干被拒收的数量)。
    """
    raw_list = parse_generated_questions(text)
    valid, rejected = [], 0
    for raw in raw_list:
        q = validate_question(raw)
        if q is None:
            rejected += 1
        else:
            valid.append(q)
    return valid, rejected


# ---------------------------------------------------------------------------
# SymPy 验算
# ---------------------------------------------------------------------------

def verify_with_sympy(verify) -> dict:
    """
    根据题目自带的 verify 字段验算。
    verify 形如 {"expr": "2*x + 3*x", "expect": "5*x"} 或
              {"expr": "Rational(1,2)+Rational(1,3)", "expect": "5/6"}。
    返回 {"status": "pass"/"fail"/"skip", "detail": 说明}。
    自然语言题、无法解析的题一律 skip，不拦截入库。
    """
    if not isinstance(verify, dict):
        return {"status": "skip", "detail": "未提供可验算算式"}
    expr_str = verify.get("expr") or verify.get("expression")
    expect_str = verify.get("expect") or verify.get("expected")
    if not expr_str or expect_str is None:
        return {"status": "skip", "detail": "验算字段不完整"}

    import sympy
    # 允许常见未知数与常用函数，不做 eval 任意代码执行
    safe_names = {s: getattr(sympy, s) for s in dir(sympy) if not s.startswith("_")}
    safe_names.update({x: sympy.Symbol(x) for x in ("x", "y", "z", "a", "b", "c", "n", "t", "k")})
    try:
        expr = sympy.sympify(expr_str, locals=safe_names)
        expect = sympy.sympify(str(expect_str), locals=safe_names)
    except (sympy.SympifyError, SyntaxError, TypeError, ValueError):
        return {"status": "skip", "detail": "算式无法解析，未自动验算"}

    diff = sympy.simplify(expr - expect)
    if diff == 0:
        return {"status": "pass", "detail": f"{expr_str} = {expect_str}，验算通过"}
    return {"status": "fail",
            "detail": f"模型算式 {expr_str} 化简为 {sympy.simplify(expr)}，与期望 {expect_str} 不一致"}


# ---------------------------------------------------------------------------
# 数据库操作
# ---------------------------------------------------------------------------

def create_question(session, data: dict, source: str = "ai_generated",
                    status: str = "pending", subject: str | None = None) -> Question:
    """新建一道题。data 为 validate_question 归一化后的字典（必须含 answer）。

    subject 不传时使用默认学科“数学”。
    """
    if not data.get("answer"):
        raise ValueError("题目必须有答案，不能入库。")
    q = Question(
        content=data["content"],
        question_type=data.get("question_type", "solution"),
        difficulty=data.get("difficulty", 2),
        knowledge_points=data.get("knowledge_points"),
        answer=data["answer"],
        analysis=data.get("analysis"),
        error_points=data.get("error_points"),
        subject=subject or DEFAULT_SUBJECT,
        source=source,
        status=status,
    )
    session.add(q)
    session.flush()
    return q


def list_questions(session, question_type=None, difficulty=None,
                   status=None, source=None, keyword=None, subject=None):
    """多条件筛选题目。keyword 同时搜题干和知识点；subject 传值时按学科过滤。"""
    q = session.query(Question)
    if subject:
        q = q.filter(Question.subject == subject)
    if question_type:
        q = q.filter(Question.question_type == question_type)
    if difficulty:
        q = q.filter(Question.difficulty == difficulty)
    if status:
        q = q.filter(Question.status == status)
    if source:
        q = q.filter(Question.source == source)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Question.content.like(like)) |
                     (Question.knowledge_points.like(like)))
    return q.order_by(Question.created_at.desc(), Question.id.desc()).all()


def approve_question(session, question_id: int) -> None:
    q = session.get(Question, question_id)
    if q is not None:
        q.status = "approved"


def update_question(session, question_id: int, **fields) -> None:
    """更新题目白名单字段；answer 不允许被改成空。"""
    allowed = {"content", "question_type", "difficulty", "knowledge_points",
               "answer", "analysis", "error_points", "status"}
    q = session.get(Question, question_id)
    if q is None:
        raise ValueError(f"题目不存在：id={question_id}")
    if "answer" in fields and not str(fields["answer"] or "").strip():
        raise ValueError("答案不能为空。")
    for key, value in fields.items():
        if key in allowed:
            setattr(q, key, value)


def delete_question(session, question_id: int) -> None:
    q = session.get(Question, question_id)
    if q is not None:
        session.delete(q)


# ---------------------------------------------------------------------------
# Word 导出
# ---------------------------------------------------------------------------

DIFFICULTY_LABELS = {1: "基础", 2: "中等", 3: "拓展"}


def _render_latex_paragraph(doc, text: str):
    """
    把含 $...$ 的文本按普通段落写（Word 里保留 LaTeX 源码，老师可辨认）。
    不引入公式转换库，保持简单可靠。
    """
    doc.add_paragraph(text or "")


def export_questions_word(questions: list[Question], with_answer: bool,
                          title: str | None = None) -> bytes:
    """
    导出题目到 Word。with_answer=False 学生卷（仅题目），True 教师卷（含答案解析）。
    """
    import io
    from docx import Document

    if title is None:
        title = "习题"

    doc = Document()
    doc.add_heading(title, level=0)
    for idx, q in enumerate(questions, start=1):
        type_label = QUESTION_TYPES.get(q.question_type, "解答题")
        diff_label = DIFFICULTY_LABELS.get(q.difficulty, "")
        kps = knowledge_points_list(q)
        head = f"{idx}.（{type_label}，{diff_label}）"
        if kps:
            head += f"【{'、'.join(kps)}】"
        doc.add_paragraph(head)
        _render_latex_paragraph(doc, q.content)
        if with_answer:
            p = doc.add_paragraph()
            p.add_run("【答案】").bold = True
            _render_latex_paragraph(doc, q.answer)
            if q.analysis:
                p2 = doc.add_paragraph()
                p2.add_run("【解析】").bold = True
                _render_latex_paragraph(doc, q.analysis)
            if q.error_points:
                p3 = doc.add_paragraph()
                p3.add_run("【易错点】").bold = True
                _render_latex_paragraph(doc, q.error_points)
        doc.add_paragraph("")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()