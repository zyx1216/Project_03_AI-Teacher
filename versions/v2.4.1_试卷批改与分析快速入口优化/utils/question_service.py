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
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

from models.models import Question, QuestionEditLog
from utils import llm_client, logger_service, undo_service
from utils.app_config import (
    DEFAULT_SUBJECT, DISPLAY_GRADE_CHOICES, is_valid_subject,
    to_storage_grade,
)

# 题型白名单与中文映射
QUESTION_TYPES = {
    "choice": "选择题", "fill": "填空题", "judge": "判断题", "solution": "解答题",
}

VARIANT_TYPE_LABELS = {
    "number": "数字变式",
    "context": "情境变式",
    "difficulty": "难度变式",
}
VARIANT_TYPE_ALIASES = {
    "number": "number", "数字": "number", "数字变式": "number",
    "context": "context", "情境": "context", "情境变式": "context", "背景": "context",
    "difficulty": "difficulty", "难度": "difficulty", "难度变式": "difficulty",
}
QUESTION_SOURCE_LABELS = {
    "ai_generated": "AI 生成",
    "manual": "手动录入",
    "imported": "外部导入",
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
    """难度归一到 1/2/3；支持 基础/易、中等、拓展/难 和 ★ 数量。"""
    if isinstance(value, (int, float)):
        v = int(value)
        return min(3, max(1, v))
    text = str(value or "").strip()
    stars = text.count("★") + text.count("☆") + text.count("*")
    if stars:
        return min(3, max(1, stars))
    if "基础" in text or "易" in text or text == "1":
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
                    status: str = "pending", subject: str | None = None,
                    grade: str | None = None) -> Question:
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
        grade=grade,
        source=source,
        status=status,
    )
    session.add(q)
    session.flush()
    undo_service.record_row_change(
        session, "add", Question, f"新增题目 #{q.id}", after=q)
    logger_service.log_operation(
        session, "新增题目", "题库", q.id,
        {"学科": q.subject, "年级": q.grade or ""})
    return q


def _question_filter_query(session, question_type=None, difficulty=None,
                          status=None, source=None, keyword=None,
                          subject=None, grade=None):
    """构造题目筛选查询，供列表、计数和分页复用。"""
    q = session.query(Question)
    if subject:
        q = q.filter(Question.subject == subject)
    if grade:
        q = q.filter(Question.grade == grade)
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
    return q


def list_questions(session, question_type=None, difficulty=None,
                   status=None, source=None, keyword=None, subject=None,
                   grade=None, limit: int | None = None,
                   offset: int | None = None):
    """多条件筛选题目，支持分页。"""
    q = _question_filter_query(
        session, question_type=question_type, difficulty=difficulty,
        status=status, source=source, keyword=keyword,
        subject=subject, grade=grade).order_by(
        Question.created_at.desc(), Question.id.desc())
    if offset is not None:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    return q.all()


def count_questions(session, question_type=None, difficulty=None,
                    status=None, source=None, keyword=None, subject=None,
                    grade=None) -> int:
    """统计筛选后的题目数量。"""
    return int(_question_filter_query(
        session, question_type=question_type, difficulty=difficulty,
        status=status, source=source, keyword=keyword,
        subject=subject, grade=grade).count())
def approve_question(session, question_id: int) -> None:
    q = session.get(Question, question_id)
    if q is not None:
        q.status = "approved"


def approve_questions(session, question_ids: list[int]) -> int:
    """批量审核通过：只处理存在且仍为待审核(pending)的题，返回实际处理数。"""
    count = 0
    for qid in dict.fromkeys(question_ids):  # 去重，保持顺序
        q = session.get(Question, int(qid))
        if q is not None and q.status == "pending":
            q.status = "approved"
            count += 1
    return count


def update_question(session, question_id: int, **fields) -> None:
    """更新题目白名单字段；answer 不允许被改成空。"""
    allowed = {"content", "question_type", "difficulty", "knowledge_points",
               "answer", "analysis", "error_points", "status"}
    q = session.get(Question, question_id)
    if q is None:
        raise ValueError(f"题目不存在：id={question_id}")
    if "answer" in fields and not str(fields["answer"] or "").strip():
        raise ValueError("答案不能为空。")
    before = undo_service._row_dict(Question, q)
    for key, value in fields.items():
        if key in allowed:
            old_value = getattr(q, key)
            if old_value != value:
                _create_edit_log(session, q.id, key, old_value, value)
                setattr(q, key, value)
    undo_service.record_row_change(
        session, "edit", Question, f"修改题目 #{q.id}",
        before=before, after=q)
    logger_service.log_operation(
        session, "修改题目", "题库", q.id, {"字段": list(fields)})


def delete_question(session, question_id: int) -> None:
    """删除题目；变式题不级联删除，改为挂到祖父题或脱离来源。"""
    q = session.get(Question, question_id)
    if q is not None:
        # 题目删除带变式子题链接的特殊级联，用 target 快照（含子题链接），
        # 保证 undo 能恢复父子关系。
        undo_service.record(
            session, "delete_question", {"target": (Question, q.id)},
            f"删除题目 #{q.id}")
        children = (session.query(Question)
                    .filter(Question.parent_question_id == q.id).all())
        for child in children:
            # 有祖父题时继续保留变式链路，否则作为普通题保留。
            child.parent_question_id = q.parent_question_id
        session.delete(q)
        session.flush()
        logger_service.log_operation(
            session, "删除题目", "题库", question_id)


def batch_update_questions(session, question_ids, *, difficulty=None,
                           subject=None, grade=None,
                           add_knowledge_points=None) -> int:
    """批量修改题目；只改传入的非空项，返回实际修改条数。

    - difficulty：整数 1-3；
    - grade：界面显示口径，原样写入；
    - add_knowledge_points：要追加的知识点列表，解析现有 JSON 后合并去重。
    """
    count = 0
    for qid in dict.fromkeys(question_ids):  # 去重保序
        q = session.get(Question, int(qid))
        if q is None:
            continue
        changes = []
        if difficulty is not None:
            if difficulty not in (1, 2, 3):
                raise ValueError("难度必须是 1、2、3。")
            changes.append(("difficulty", q.difficulty, int(difficulty)))
        if subject is not None:
            if not is_valid_subject(subject):
                raise ValueError(f"不支持的学科：{subject}")
            changes.append(("subject", q.subject, subject))
        if grade is not None:
            changes.append(("grade", q.grade, grade))  # 界面口径，不转换
        if add_knowledge_points:
            existing = knowledge_points_list(q)
            candidates = existing + [
                str(x).strip() for x in add_knowledge_points if str(x).strip()]
            seen, merged = set(), []
            for kp in candidates:  # 合并去重保序
                if kp not in seen:
                    seen.add(kp)
                    merged.append(kp)
            new_value = json.dumps(merged, ensure_ascii=False)
            changes.append(("knowledge_points", q.knowledge_points, new_value))
        for field, old_value, new_value in changes:
            if old_value != new_value:
                _create_edit_log(session, q.id, field, old_value, new_value)
                setattr(q, field, new_value)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Word 导出
# ---------------------------------------------------------------------------

DIFFICULTY_LABELS = {1: "基础", 2: "中等", 3: "拓展"}


def _clean_formula_text(text: str) -> str:
    """
    导出前清理公式边界标记：删除全部 $，以及 \\( \\) \\[ \\] 残留。
    不渲染公式，公式内容按普通文本保留。
    """
    text = str(text or "")
    text = text.replace("$", "")
    for token in ("\\(", "\\)", "\\[", "\\]"):
        text = text.replace(token, "")
    return text


def _render_latex_paragraph(doc, text: str):
    """写 Word 段落：先清理公式边界标记，按普通文本展示。"""
    doc.add_paragraph(_clean_formula_text(text))


# 选择题选项标记：A. / A、 / A) / A．（B-D 同理）
_OPTION_MARK_RE = re.compile(r"(?<![A-Za-z0-9])(?P<letter>[A-D])(?P<sep>[.、)．])")


def _split_choice_options(text: str) -> list[str]:
    """
    把选择题拆成 [题干, "    A. xxx", ... "    D. xxx"]。
    仅当 A、B、C、D 四个选项各出现一次且顺序正确时拆分；否则原样返回单元素列表，
    避免误伤填空、解答题。
    """
    text = str(text or "")
    matches = list(_OPTION_MARK_RE.finditer(text))
    letters = [m.group("letter") for m in matches]
    if letters != ["A", "B", "C", "D"]:
        return [text]

    stem = text[:matches[0].start()].strip()
    parts = [stem] if stem else []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        option_text = text[match.end():end].strip()
        parts.append("    " + match.group("letter") + match.group("sep") + " " + option_text)
    return parts


def questions_by_selected_ids(questions: list[Question], selected_ids) -> list[Question]:
    """
    按 selected_ids 的顺序返回题目；数据库结果中不存在的 id 自动跳过。
    导出顺序以勾选顺序为准，不再按数据库顺序重排。
    """
    by_id = {q.id: q for q in questions}
    result = []
    for raw_id in selected_ids:
        question = by_id.get(int(raw_id))
        if question is not None:
            result.append(question)
    return result


def _append_specification_table(doc, specification_table: dict) -> None:
    """在 Word 末尾追加双向细目表附录。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT

    doc.add_page_break()
    doc.add_heading("双向细目表", level=1)

    headers = ["知识点", "基础", "中等", "拓展", "合计", "占比"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    def set_cell(cell, text, bold=False):
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(str(text))
        run.bold = bold

    for index, header in enumerate(headers):
        set_cell(table.rows[0].cells[index], header, bold=True)

    total_score = float(specification_table.get("total", {}).get("score") or 0.0)
    for kp in specification_table.get("knowledge_points", []):
        row = table.add_row().cells
        values = [kp]
        kp_score = 0.0
        for difficulty in ("1", "2", "3"):
            cell = specification_table["cells"][kp][difficulty]
            values.append(f"{cell['count']}题/{cell['score']:g}分")
            kp_score += float(cell["score"])
        total = specification_table["kp_totals"][kp]
        ratio = kp_score / total_score if total_score else 0
        values.extend([
            f"{total['count']}题/{total['score']:g}分",
            f"{ratio * 100:.1f}%",
        ])
        for index, value in enumerate(values):
            set_cell(row[index], value)

    grand = specification_table["total"]
    totals = specification_table["difficulty_totals"]
    row = table.add_row().cells
    values = ["合计"]
    for difficulty in ("1", "2", "3"):
        item = totals[difficulty]
        values.append(f"{item['count']}题/{item['score']:g}分")
    values.extend([f"{grand['count']}题/{grand['score']:g}分", "100%"])
    for index, value in enumerate(values):
        set_cell(row[index], value, bold=True)


def export_questions_word(questions: list[Question], with_answer: bool,
                          title: str | None = None,
                          specification_table: dict | None = None) -> bytes:
    """
    导出题目到 Word。with_answer=False 学生卷（仅题目），True 教师卷（含答案解析）。
    题号按传入列表从 1 连续编号。
    """
    import io
    from docx import Document

    if title is None:
        title = "习题"

    doc = Document()
    doc.add_heading(title, level=0)
    if not with_answer:
        doc.add_paragraph(
            "班级：____________    姓名：____________    得分：____________")
    for idx, q in enumerate(questions, start=1):
        type_label = QUESTION_TYPES.get(q.question_type, "解答题")
        diff_label = DIFFICULTY_LABELS.get(q.difficulty, "")
        kps = knowledge_points_list(q)
        parts = _split_choice_options(q.content)
        if with_answer:
            head = f"{idx}.（{type_label}，{diff_label}）"
            if kps:
                head += f"【{'、'.join(kps)}】"
            doc.add_paragraph(head)
            for part in parts:
                _render_latex_paragraph(doc, part)
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
        else:
            # 学生卷：题号直接并入题干，不输出题型、难度、知识点。
            _render_latex_paragraph(doc, f"{idx}.　{parts[0] if parts else ''}")
            for part in parts[1:]:
                _render_latex_paragraph(doc, part)
        doc.add_paragraph("")

    if specification_table:
        _append_specification_table(doc, specification_table)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# v1.6.0：扩展题型提示、多任务校验
# ---------------------------------------------------------------------------

# 面向出题界面的题型标签；数据库仍只保存四类。
# 所有扩展题型最终归一为 choice（选择）/ fill（填空）/ judge（判断）/ solution（解答）
EXTENDED_TYPE_ALIASES = {
    **TYPE_ALIASES,
    # 解答题大类
    "证明": "solution", "证明题": "solution",
    "阅读理解": "solution", "阅读理解题": "solution",
    "作文": "solution", "作文题": "solution", "书面表达": "solution",
    "材料分析": "solution", "材料分析题": "solution",
    "解答": "solution", "解答题": "solution", "大题": "solution",
    "计算": "solution", "计算题": "solution", "应用": "solution", "应用题": "solution",
    "实验": "solution", "实验题": "solution", "实验探究题": "solution",
    "简答": "solution", "简答题": "solution",
    "论述": "solution", "论述题": "solution",
    "辨析": "solution", "辨析题": "solution",
    "推断": "solution", "推断题": "solution",
    "工艺流程": "solution", "工艺流程题": "solution",
    "有机推断": "solution", "有机推断与合成题": "solution",
    "化学反应原理": "solution", "化学反应原理题": "solution",
    "综合": "solution", "综合题": "solution",
    "读图分析": "solution", "读图分析题": "solution",
    "图表分析": "solution", "图表分析题": "solution",
    "实验设计": "solution", "实验设计题": "solution",
    "识图作答": "solution", "识图作答题": "solution",
    "操作": "solution", "操作题": "solution",
    "图形与几何": "solution", "图形与几何题": "solution",
    "作图": "solution", "作图题": "solution",
    "选考": "solution", "选考题": "solution",
    "开放性": "solution", "开放性试题": "solution",
    "实践探究": "solution", "实践探究题": "solution",
    "古诗文默写": "fill", "默写": "fill",
    "文言文阅读": "solution", "古代诗歌鉴赏": "solution", "诗歌鉴赏": "solution",
    "现代文阅读": "solution", "论述类文本": "solution", "实用类文本": "solution", "文学类文本": "solution",
    "语言文字运用": "solution", "补写句子": "solution", "压缩语段": "solution", "图文转换": "solution", "句式变换": "solution",
    "看拼音写词语": "fill", "形近字辨析": "choice", "多音字辨析": "choice",
    "选词填空": "fill", "词语搭配": "fill", "按课文内容填空": "fill",
    "句子排序": "solution", "修改病句": "solution", "标点符号": "choice",
    "看图写话": "solution", "任务驱动型作文": "solution", "材料作文": "solution",
    "听力选择": "choice", "听力填空": "fill", "字母辨音": "choice",
    "单词拼写": "fill", "完形填空": "fill", "语法填空": "fill", "短文填空": "fill",
    "词汇运用": "fill", "句型转换": "solution", "补全对话": "solution",
    "七选五": "choice", "短文改错": "solution", "应用文写作": "solution",
    "读后续写": "solution", "概要写作": "solution", "小作文": "solution",
    "多项选择": "choice", "多选题": "choice", "单项选择": "choice", "单选题": "choice",
    "力学实验": "solution", "电学实验": "solution", "光学实验": "solution",
    "力学综合": "solution", "电磁学综合": "solution", "力电综合": "solution",
    "热学": "solution", "机械振动与波": "solution", "电磁波": "solution", "相对论": "solution",
    "无机实验": "solution", "有机实验": "solution", "定量实验": "solution",
    "物质结构与性质": "solution", "有机化学基础": "solution",
    "生物技术实践": "solution", "现代生物科技专题": "solution",
    "旅游地理": "solution", "环境保护": "solution", "自然灾害与防治": "solution",
    "历史上重大改革回眸": "solution", "近代社会的民主思想与实践": "solution",
    "20世纪的战争与和平": "solution", "中外历史人物评说": "solution",
    "坐标系与参数方程": "solution", "不等式选讲": "solution",
}


def question_type_options(grade: str, subject: str) -> list[str]:
    """按年级、学科返回出题界面允许使用的题型中文标签（全学科全学段）。"""
    grade = str(grade or "")
    is_primary = grade in (
        "一年级", "二年级", "三年级", "四年级", "五年级", "六年级")
    is_junior = grade in ("七年级", "八年级", "九年级")
    is_senior = grade in ("十年级", "十一年级", "十二年级")

    # ========== 语文 ==========
    if subject == "语文":
        if is_primary:
            return ["看拼音写词语", "形近字辨析", "多音字辨析", "选词填空", "词语搭配",
                    "按课文内容填空", "句子排序", "句型转换", "修改病句", "标点符号",
                    "阅读理解", "看图写话", "作文"]
        if is_junior:
            return ["字音字形", "词语运用", "病句辨析与修改", "语句衔接与排序", "标点符号",
                    "文学常识与名著阅读", "古诗文默写", "文言文阅读", "古代诗歌鉴赏",
                    "现代文阅读", "语言文字运用", "作文"]
        if is_senior:
            return ["选择题", "古诗文默写", "文言文阅读", "古代诗歌鉴赏",
                    "现代文阅读（论述类）", "现代文阅读（实用类）", "现代文阅读（文学类）",
                    "语言文字运用", "作文"]
        return ["选择题", "填空题", "阅读理解", "作文"]

    # ========== 数学 ==========
    if subject == "数学":
        if is_primary:
            return ["选择题", "填空题", "判断题", "计算题", "操作题", "应用题", "图形与几何题"]
        if is_junior:
            return ["选择题", "填空题", "计算题", "解答题", "证明题", "应用题", "作图题"]
        if is_senior:
            return ["单项选择题", "多项选择题", "填空题", "解答题", "证明题",
                    "选考题（坐标系与参数方程）", "选考题（不等式选讲）"]
        return ["选择题", "填空题", "解答题"]

    # ========== 英语 ==========
    if subject == "英语":
        if is_primary:
            return ["听力选择", "听力填空", "字母辨音", "单词拼写", "单项选择",
                    "选词填空", "句型转换", "补全对话", "阅读理解", "书面表达"]
        if is_junior:
            return ["听力选择", "听力填空", "单项选择", "完形填空", "阅读理解",
                    "词汇运用", "语法填空", "句型转换", "补全对话", "短文填空", "书面表达"]
        if is_senior:
            return ["听力选择", "听力填空", "阅读理解", "七选五", "完形填空",
                    "语法填空", "短文改错", "应用文写作", "读后续写", "概要写作"]
        return ["选择题", "填空题", "阅读理解", "作文"]

    # ========== 物理 ==========
    if subject == "物理":
        if is_junior:
            return ["选择题", "填空题", "实验探究题", "计算题", "简答题", "作图题"]
        if is_senior:
            return ["单项选择题", "多项选择题", "实验题", "计算题",
                    "选考题（热学）", "选考题（机械振动与波）", "选考题（光学）"]
        return ["选择题", "填空题", "解答题"]

    # ========== 化学 ==========
    if subject == "化学":
        if is_junior:
            return ["选择题", "填空题", "实验题", "计算题", "推断题", "工艺流程题"]
        if is_senior:
            return ["单项选择题", "填空题", "实验题", "工艺流程题", "有机推断与合成题",
                    "化学反应原理题", "选考题（物质结构与性质）", "选考题（有机化学基础）"]
        return ["选择题", "填空题", "解答题"]

    # ========== 生物 ==========
    if subject == "生物":
        if is_junior:
            return ["选择题", "填空题", "识图作答题", "实验探究题", "简答题"]
        if is_senior:
            return ["单项选择题", "多项选择题", "填空题", "简答题", "实验设计题",
                    "图表分析题", "选考题（生物技术实践）", "选考题（现代生物科技专题）"]
        return ["选择题", "填空题", "解答题"]

    # ========== 政治/道法 ==========
    if subject == "政治":
        if is_primary:
            return ["选择题", "填空题", "判断题", "简答题", "材料分析题"]
        if is_junior:
            return ["选择题", "简答题", "材料分析题", "辨析题", "实践探究题"]
        if is_senior:
            return ["单项选择题", "材料分析题", "简答题", "辨析题", "论述题", "开放性试题"]
        return ["选择题", "材料分析题"]

    # ========== 历史 ==========
    if subject == "历史":
        if is_junior:
            return ["选择题", "材料分析题", "简答题", "论述题", "识图题"]
        if is_senior:
            return ["单项选择题", "材料分析题", "简答题", "论述题", "开放性试题",
                    "选考题（历史上重大改革回眸）", "选考题（中外历史人物评说）"]
        return ["选择题", "材料分析题"]

    # ========== 地理 ==========
    if subject == "地理":
        if is_junior:
            return ["选择题", "综合题", "读图分析题", "填空题", "简答题"]
        if is_senior:
            return ["单项选择题", "多项选择题", "综合题", "读图分析题", "简答题", "论述题",
                    "选考题（旅游地理）", "选考题（环境保护）"]
        return ["选择题", "综合题"]

    # 默认
    return ["选择题", "填空题", "解答题"]


def normalize_prompt_type(value) -> str:
    """扩展题型标签仍归一为 choice/fill/judge/solution。"""
    if value is None:
        return "solution"
    key = str(value).strip().lower().replace(" ", "")
    return EXTENDED_TYPE_ALIASES.get(key, "solution")


def validate_generation_tasks(rows: list[dict], allowed_types: list[str]) -> list[dict]:
    """校验 data_editor 里的出题任务，返回规范化任务。"""
    result = []
    for row in rows:
        qtype = str(row.get("题型") or "").strip()
        if qtype not in allowed_types:
            raise ValueError(f"题型不符合当前年级和学科：{qtype}")
        difficulty = normalize_difficulty(row.get("难度"))
        try:
            count = int(row.get("数量"))
        except (TypeError, ValueError) as exc:
            raise ValueError("出题数量必须是整数。") from exc
        if count <= 0:
            raise ValueError("出题数量必须大于 0。")
        result.append({
            "question_type": qtype,
            "storage_type": normalize_prompt_type(qtype),
            "difficulty": difficulty,
            "count": count,
        })
    if not result:
        raise ValueError("请先添加出题任务。")
    return result




def validate_normalized_tasks(tasks: list[dict], allowed_types: list[str]) -> list[dict]:
    """校验已经归一化的待定任务，供跨学科汇总生成使用。"""
    if not tasks:
        raise ValueError("当前学科还没有出题任务。")
    for task in tasks:
        qtype = str(task.get("question_type") or "").strip()
        if qtype not in allowed_types:
            raise ValueError(f"题型不符合当前年级和学科：{qtype}")
        difficulty = normalize_difficulty(task.get("difficulty"))
        try:
            count = int(task.get("count"))
        except (TypeError, ValueError) as exc:
            raise ValueError("出题数量必须是整数。") from exc
        if count <= 0:
            raise ValueError("出题数量必须大于 0。")
        task["difficulty"] = difficulty
        task["count"] = count
        task["storage_type"] = normalize_prompt_type(qtype)
    return tasks


def build_generated_by_subject(raw_by_subject: dict[str, str]) -> dict[str, dict]:
    """解析多学科模型结果，按学科归类有效题和拒收数。"""
    grouped = {}
    for subject, raw in raw_by_subject.items():
        valid, rejected = build_questions(raw)
        for item in valid:
            item["question_type"] = normalize_prompt_type(
                QUESTION_TYPES.get(item.get("question_type"), item.get("question_type")))
        grouped[subject] = {"valid": valid, "rejected": rejected}
    return grouped


# ---------------------------------------------------------------------------
# v1.6.2：按学科保存待定出题配置
# ---------------------------------------------------------------------------

DRAFTS_STATE_KEY = "question_gen_drafts"


def task_editor_dataframe(tasks: list[dict] | None = None,
                          default_type: str = "选择题",
                          ensure_default: bool = True) -> pd.DataFrame:
    """生成出题任务编辑器数据，删除列只作为页面临时操作。"""
    rows = []
    for task in tasks or []:
        rows.append({
            "题型": task.get("question_type", default_type),
            "难度": int(task.get("difficulty") or 2),
            "数量": int(task.get("count") or 1),
            "删除": bool(task.get("delete", False)),
        })
    if not rows and ensure_default:
        rows.append({"题型": default_type, "难度": 2, "数量": 1, "删除": False})
    return pd.DataFrame(rows, columns=["题型", "难度", "数量", "删除"])


def editor_rows_to_tasks(rows: list[dict], allowed_types: list[str]) -> list[dict]:
    """过滤删除行后复用现有任务校验。"""
    active = []
    for row in rows:
        if bool(row.get("删除", False)):
            continue
        active.append({
            "题型": row.get("题型"),
            "难度": row.get("难度"),
            "数量": row.get("数量"),
        })
    return validate_generation_tasks(active, allowed_types)


def empty_draft(material_id: int | None = None) -> dict:
    """新建一个学科的待定配置。"""
    return {
        "tasks": [],
        "material_id": material_id,
        "knowledge_points": [],
        "extra": "",
    }


def normalize_draft(data: dict | None) -> dict:
    """归一待定配置，避免页面直接处理异常结构。"""
    data = data or {}
    tasks = []
    for item in data.get("tasks", []):
        if not isinstance(item, dict):
            continue
        try:
            count = int(item.get("count", 0))
            difficulty = int(item.get("difficulty", 2))
        except (TypeError, ValueError):
            continue
        qtype = str(item.get("question_type") or "").strip()
        if qtype and count > 0:
            tasks.append({
                "question_type": qtype,
                "storage_type": item.get("storage_type") or normalize_prompt_type(qtype),
                "difficulty": min(3, max(1, difficulty)),
                "count": count,
            })
    material_id = data.get("material_id")
    try:
        material_id = int(material_id) if material_id is not None else None
    except (TypeError, ValueError):
        material_id = None
    knowledge_points = [
        str(x).strip() for x in data.get("knowledge_points", []) if str(x).strip()
    ]
    return {
        "tasks": tasks,
        "material_id": material_id,
        "knowledge_points": list(dict.fromkeys(knowledge_points)),
        "extra": str(data.get("extra") or ""),
    }


def draft_from_editor(task_rows: list[dict], allowed_types: list[str],
                      material_id: int | None, knowledge_points: list[str],
                      extra: str, validate: bool = False) -> dict:
    """从当前页面控件收集一个学科的待定配置。"""
    active_rows = [row for row in task_rows if not bool(row.get("删除", False))]
    tasks = editor_rows_to_tasks(active_rows, allowed_types) if validate else []
    if not validate:
        for row in active_rows:
            try:
                count = int(row.get("数量"))
                difficulty = normalize_difficulty(row.get("难度"))
            except (TypeError, ValueError):
                continue
            qtype = str(row.get("题型") or "").strip()
            if qtype and count > 0:
                tasks.append({
                    "question_type": qtype,
                    "storage_type": normalize_prompt_type(qtype),
                    "difficulty": difficulty,
                    "count": count,
                })
    return {
        "tasks": tasks,
        "material_id": material_id,
        "knowledge_points": list(dict.fromkeys(str(x).strip() for x in knowledge_points if str(x).strip())),
        "extra": str(extra or ""),
    }


def drafts_from_history_config(config_data: dict) -> dict[str, dict]:
    """兼容 v1.6.0 历史结构和 v1.6.2 的按学科待定结构。"""
    config_data = config_data or {}
    if isinstance(config_data.get("drafts"), dict):
        return {
            str(subject): normalize_draft(data)
            for subject, data in config_data["drafts"].items()
        }

    old_tasks = config_data.get("tasks", {})
    subjects = config_data.get("subjects") or list(old_tasks)
    shared_material = config_data.get("material_id")
    shared_kps = config_data.get("knowledge_points", [])
    shared_extra = config_data.get("extra", "")
    drafts = {}
    for subject in subjects:
        rows = []
        for task in old_tasks.get(str(subject), []):
            if isinstance(task, dict):
                rows.append({
                    "question_type": task.get("question_type", "选择题"),
                    "storage_type": task.get("storage_type") or normalize_prompt_type(task.get("question_type")),
                    "difficulty": task.get("difficulty", 2),
                    "count": task.get("count", 1),
                })
        drafts[str(subject)] = normalize_draft({
            "tasks": rows,
            "material_id": shared_material,
            "knowledge_points": shared_kps,
            "extra": shared_extra,
        })
    return drafts

# ---------------------------------------------------------------------------
# v1.6.3：待定任务持久化到 data/question_drafts.json
# ---------------------------------------------------------------------------

DRAFTS_FILE_PATH = None  # 默认走 config.DATA_DIR，测试可 monkeypatch


def _drafts_file_path():
    import config
    if DRAFTS_FILE_PATH is not None:
        return DRAFTS_FILE_PATH
    return config.DATA_DIR / "question_drafts.json"


def load_drafts_file() -> dict:
    """读取待定任务；文件缺失自动创建，JSON 损坏时回退空名单且不覆盖原文件。"""
    path = _drafts_file_path()
    if not path.exists():
        save_drafts_file({})
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): normalize_draft(v) for k, v in data.items()}


def save_drafts_file(drafts: dict) -> None:
    """按归一结构保存待定任务，中文不转义。"""
    cleaned = {
        str(k): normalize_draft(v)
        for k, v in (drafts or {}).items()
        if isinstance(v, dict)
    }
    path = _drafts_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8")



# ---------------------------------------------------------------------------
# v1.6.5：出题任务栏（question_tasks.json 是唯一任务来源）
# ---------------------------------------------------------------------------

QUESTION_TASKS_PATH = None  # 默认走 config.DATA_DIR，测试可 monkeypatch
PENDING_GROUPS_PATH = None  # v1.6.9：待定任务草稿组，测试可 monkeypatch


def _question_tasks_path():
    import config
    if QUESTION_TASKS_PATH is not None:
        return QUESTION_TASKS_PATH
    return config.DATA_DIR / "question_tasks.json"


def load_question_tasks() -> list[dict]:
    """读取任务栏；文件缺失自动创建，损坏时返回空列表且不覆盖原文件。"""
    path = _question_tasks_path()
    if not path.exists():
        save_question_tasks([])
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [normalize_question_task(item, trust_existing=True)
            for item in data if isinstance(item, dict)]


def save_question_tasks(tasks: list[dict]) -> None:
    """保存任务栏，UTF-8、中文不转义。"""
    cleaned = [normalize_question_task(item, trust_existing=True)
               for item in (tasks or []) if isinstance(item, dict)]
    path = _question_tasks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8")


def _canonical_question_type(value, allowed_types: list[str]) -> str:
    """把题型别名收敛到当前年级学科允许的中文标签。"""
    raw = str(value or "").strip()
    if raw in allowed_types:
        return "作文题" if raw == "作文" else raw
    lower = raw.lower().replace(" ", "")

    # 先按扩展题型别名找 storage 类型，再在允许列表里挑同类标签。
    storage_type = EXTENDED_TYPE_ALIASES.get(lower)
    if raw in QUESTION_TYPES.values():
        return raw
    if storage_type:
        same_type = [item for item in allowed_types
                     if normalize_prompt_type(item) == storage_type]
        if same_type:
            if raw == "作文" and any(item == "作文" for item in same_type):
                return "作文题"
            return same_type[0]

    # 常见短别名直接匹配包含词。
    for allowed in allowed_types:
        if raw and (raw in allowed or allowed in raw):
            return "作文题" if allowed == "作文" else allowed
    raise ValueError(f"题型不符合当前年级和学科：{raw}")


def _normalize_task_id(value) -> str:
    text = str(value or "").strip()
    return text if text else uuid.uuid4().hex


def normalize_question_task(data: dict, trust_existing: bool = False) -> dict:
    """归一一条出题任务，并校验学科、年级、题型、数量和知识点。"""
    data = data or {}
    subject = str(data.get("subject") or "").strip()
    if not is_valid_subject(subject):
        raise ValueError(f"学科不合法：{subject}")

    grade = str(data.get("grade") or "").strip()
    if grade not in DISPLAY_GRADE_CHOICES:
        raise ValueError(f"年级不合法：{grade}")

    from utils.app_config import to_storage_grade
    storage_grade = to_storage_grade(grade)
    allowed_types = question_type_options(storage_grade, subject)
    raw_type = data.get("question_type")
    if trust_existing and raw_type in ("作文", "作文题") and "作文" in allowed_types:
        question_type = "作文题"
    else:
        question_type = _canonical_question_type(raw_type, allowed_types)
    storage_type = normalize_prompt_type(question_type)

    difficulty = normalize_difficulty(data.get("difficulty"))
    try:
        count = int(data.get("count"))
    except (TypeError, ValueError) as exc:
        raise ValueError("出题数量必须是整数。") from exc
    if count <= 0:
        raise ValueError(f"出题数量必须大于 0，当前为 {count}。")

    # 章节（来自资料）
    raw_chapters = data.get("chapters", [])
    if isinstance(raw_chapters, str):
        chapters = re.split(r"[，,、;；]\s*", raw_chapters)
    elif isinstance(raw_chapters, list):
        chapters = raw_chapters
    else:
        chapters = []
    chapters = list(dict.fromkeys(
        str(item).strip() for item in chapters if str(item).strip()))

    # 知识点（来自题库）
    raw_kps = data.get("knowledge_points", [])
    if isinstance(raw_kps, str):
        try:
            parsed = json.loads(raw_kps)
            knowledge_points = parsed if isinstance(parsed, list) else [raw_kps]
        except json.JSONDecodeError:
            knowledge_points = re.split(r"[，,、;；]\s*", raw_kps)
    elif isinstance(raw_kps, list):
        knowledge_points = raw_kps
    else:
        knowledge_points = []
    knowledge_points = list(dict.fromkeys(
        str(item).strip() for item in knowledge_points if str(item).strip()))

    # 章节和知识点都是可选的，AI可根据学科年级直接出题

    material_id = data.get("material_id")
    try:
        material_id = int(material_id) if material_id is not None else None
    except (TypeError, ValueError):
        material_id = None

    created_at = str(data.get("created_at") or "").strip()
    if not created_at:
        created_at = datetime.now().isoformat(timespec="seconds")

    return {
        "task_id": _normalize_task_id(data.get("task_id")),
        "subject": subject,
        "grade": grade,
        "question_type": question_type,
        "storage_type": storage_type,
        "difficulty": difficulty,
        "count": count,
        "material_id": material_id,
        "chapters": chapters,
        "knowledge_points": knowledge_points,
        "extra": str(data.get("extra") or "").strip(),
        "selected": bool(data.get("selected", True)),
        "created_at": created_at,
    }


def add_question_tasks(new_tasks: list[dict]) -> list[dict]:
    """追加任务；task_id 重复时拒绝，避免静默覆盖。"""
    tasks = load_question_tasks()
    existing_ids = {task["task_id"] for task in tasks}
    for item in new_tasks or []:
        if not isinstance(item, dict):
            continue
        task = normalize_question_task(item)
        if task["task_id"] in existing_ids:
            raise ValueError(f"任务 ID 已存在：{task['task_id']}")
        tasks.append(task)
        existing_ids.add(task["task_id"])
    save_question_tasks(tasks)
    return tasks


def delete_question_tasks(task_ids: list[str]) -> list[dict]:
    """按 task_id 删除任务；不存在的 id 自动跳过。"""
    remove_ids = {str(item) for item in (task_ids or [])}
    tasks = [task for task in load_question_tasks()
             if task["task_id"] not in remove_ids]
    save_question_tasks(tasks)
    return tasks


def clear_question_tasks() -> list:
    """清空任务栏。"""
    save_question_tasks([])
    return []


def tasks_from_drafts(drafts: dict, grade_display: str) -> list[dict]:
    """把 v1.6.3 的按学科 drafts 展开成任务栏任务。"""
    tasks = []
    for subject, raw_draft in (drafts or {}).items():
        draft = normalize_draft(raw_draft)
        for item in draft["tasks"]:
            tasks.append(normalize_question_task({
                "task_id": uuid.uuid4().hex,
                "subject": subject,
                "grade": grade_display,
                "question_type": item["question_type"],
                "storage_type": item.get("storage_type"),
                "difficulty": item["difficulty"],
                "count": item["count"],
                "material_id": draft["material_id"],
                "knowledge_points": draft["knowledge_points"],
                "extra": draft["extra"],
            }))
    return tasks


# ---------------------------------------------------------------------------
# v1.6.9：待定任务草稿组（一组章节/知识点 + 多行题型）
# ---------------------------------------------------------------------------

def _pending_groups_path():
    import config
    if PENDING_GROUPS_PATH is not None:
        return PENDING_GROUPS_PATH
    return config.DATA_DIR / "pending_question_groups.json"


def load_pending_question_groups() -> list[dict]:
    """读取草稿组；文件缺失自动创建，损坏时返回空列表且不覆盖。"""
    path = _pending_groups_path()
    if not path.exists():
        save_pending_question_groups([])
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [normalize_pending_question_group(item, trust_existing=True)
            for item in data if isinstance(item, dict)]


def save_pending_question_groups(groups: list[dict]) -> None:
    """保存草稿组，UTF-8、中文不转义。"""
    cleaned = [normalize_pending_question_group(item, trust_existing=True)
               for item in (groups or []) if isinstance(item, dict)]
    path = _pending_groups_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8")


def normalize_pending_question_group(data: dict, trust_existing: bool = False) -> dict:
    """归一并校验一整组待定题型。"""
    data = data or {}
    subject = str(data.get("subject") or "").strip()
    if not is_valid_subject(subject):
        raise ValueError(f"学科不合法：{subject}")

    grade = str(data.get("grade") or "").strip()
    if grade not in DISPLAY_GRADE_CHOICES[:-1]:
        raise ValueError(f"年级不合法：{grade}")

    storage_grade = to_storage_grade(grade)
    allowed_types = question_type_options(storage_grade, subject)
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("待定任务组至少要有一行题型。")

    # 第一次暂存传入“题型”中文行；从 JSON 读回时已是 question_type 行。
    editable_rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        if "question_type" in row:
            editable_rows.append({
                "题型": row.get("question_type"),
                "难度": row.get("difficulty"),
                "数量": row.get("count"),
            })
        else:
            editable_rows.append(row)
    if not editable_rows:
        raise ValueError("待定任务组至少要有一行题型。")
    rows = validate_generation_tasks(editable_rows, allowed_types)

    raw_chapters = data.get("chapters", [])
    if isinstance(raw_chapters, str):
        chapters = re.split(r"[，,、;；]\s*", raw_chapters)
    elif isinstance(raw_chapters, list):
        chapters = raw_chapters
    else:
        chapters = []
    chapters = list(dict.fromkeys(
        str(item).strip() for item in chapters if str(item).strip()))

    raw_kps = data.get("knowledge_points", [])
    if isinstance(raw_kps, str):
        try:
            kps = json.loads(raw_kps)
            kps = kps if isinstance(kps, list) else [raw_kps]
        except json.JSONDecodeError:
            kps = re.split(r"[，,、;；]\s*", raw_kps)
    elif isinstance(raw_kps, list):
        kps = raw_kps
    else:
        kps = []
    knowledge_points = list(dict.fromkeys(
        str(item).strip() for item in kps if str(item).strip()))

    material_id = data.get("material_id")
    try:
        material_id = int(material_id) if material_id is not None else None
    except (TypeError, ValueError):
        material_id = None

    created_at = str(data.get("created_at") or "").strip()
    if not created_at:
        created_at = datetime.now().isoformat(timespec="seconds")

    return {
        "group_id": _normalize_task_id(data.get("group_id")),
        "subject": subject,
        "grade": grade,
        "material_id": material_id,
        "chapters": chapters,
        "knowledge_points": knowledge_points,
        "extra": str(data.get("extra") or "").strip(),
        "rows": rows,
        "created_at": created_at,
    }


def add_pending_question_group(group: dict) -> list[dict]:
    """追加一整组草稿；group_id 重复时拒绝。"""
    groups = load_pending_question_groups()
    normalized = normalize_pending_question_group(group)
    if any(item["group_id"] == normalized["group_id"] for item in groups):
        raise ValueError(f"草稿组 ID 已存在：{normalized['group_id']}")
    groups.append(normalized)
    save_pending_question_groups(groups)
    return groups


def delete_pending_question_group(group_id: str) -> list[dict]:
    """按 group_id 删除草稿组；不存在的 id 自动跳过。"""
    remove_id = str(group_id or "")
    groups = [item for item in load_pending_question_groups()
              if item["group_id"] != remove_id]
    save_pending_question_groups(groups)
    return groups


def clear_pending_question_groups() -> list:
    """清空待定任务草稿组。"""
    save_pending_question_groups([])
    return []


def tasks_from_pending_groups(groups: list[dict]) -> list[dict]:
    """把每个草稿组中的每行题型展开成任务栏任务。"""
    tasks = []
    for raw_group in groups or []:
        group = normalize_pending_question_group(raw_group, trust_existing=True)
        for row in group["rows"]:
            tasks.append({
                "subject": group["subject"],
                "grade": group["grade"],
                "question_type": row["question_type"],
                "storage_type": row["storage_type"],
                "difficulty": row["difficulty"],
                "count": row["count"],
                "material_id": group["material_id"],
                "chapters": group["chapters"],
                "knowledge_points": group["knowledge_points"],
                "extra": group["extra"],
            })
    return tasks


def question_task_request_text(task: dict) -> str:
    """生成单条任务的请求文案，确保混合任务互不串年级和学科。"""
    task = normalize_question_task(task, trust_existing=True)
    chapters_text = '、'.join(task.get('chapters', [])) or '无'
    kps_text = '、'.join(task['knowledge_points']) or '无'
    return (
        f"学科：{task['subject']}\n"
        f"年级：{task['grade']}\n"
        f"参考章节：{chapters_text}\n"
        f"知识点：{kps_text}\n"
        f"命题任务：{task['question_type']}，"
        f"{DIFFICULTY_LABELS[task['difficulty']]}，"
        f"恰好 {task['count']} 道\n"
        f"其他要求：{task['extra'] or '无'}\n"
        "扩展题型在 question_type 中按兼容四类题型输出。"
    )

def get_all_knowledge_points(session, subject: str) -> list[str]:
    """聚合当前学科全部题目的知识点，去重后排序，供组卷规则下拉使用。"""
    names = set()
    for question in list_questions(session, subject=subject):
        names.update(knowledge_points_list(question))
    return sorted(names)

# ---------------------------------------------------------------------------
# v1.6.3：题库题目 AgGrid 表格（点行看详情 + 复选框批量审核）
# ---------------------------------------------------------------------------

DIFF_LABELS_BANK = {1: "基础", 2: "中等", 3: "拓展"}
STATUS_LABELS_BANK = {"pending": "待审核", "approved": "已审核"}


def bank_table_rows(questions, counts: dict | None = None) -> list[dict]:
    """把题目列表转成 AgGrid 行数据；question_id/clicked_id 供回传，不在界面显示。"""
    counts = counts or {}
    rows = []
    for q in questions:
        if q.parent_question_id:
            source_text = f"变式自#{q.parent_question_id}"
        else:
            source_text = QUESTION_SOURCE_LABELS.get(q.source, q.source)
        child_count = int(counts.get(q.id, 0))
        rows.append({
            "ID": int(q.id),
            "题型": QUESTION_TYPES.get(q.question_type, q.question_type),
            "难度": DIFF_LABELS_BANK.get(q.difficulty, q.difficulty),
            "状态": STATUS_LABELS_BANK.get(q.status, q.status),
            "知识点": "、".join(knowledge_points_list(q)),
            "变式": f"有{child_count}道变式" if child_count else "",
            "来源": source_text,
            "question_id": int(q.id),
            "clicked_id": "",
        })
    return rows


def build_bank_grid_options() -> dict:
    """题库表格配置：复选框列多选 + 点普通单元格回传题目 id；不使用 innerHTML。"""
    from st_aggrid.shared import JsCode

    on_cell = JsCode("""
    function(params) {
        if (params.colDef.field === '选择') return;
        params.node.setDataValue('clicked_id', params.data.question_id);
    }
    """)

    column_defs = [
        {
            "field": "选择",
            "headerName": "",
            "checkboxSelection": True,
            "headerCheckboxSelection": True,
            "width": 48,
            "minWidth": 48,
            "maxWidth": 48,
            "editable": False,
            "pinned": "left",
        },
        {"field": "ID", "width": 60},
        {"field": "题型", "width": 90},
        {"field": "难度", "width": 80},
        {"field": "状态", "width": 90},
        {"field": "知识点", "minWidth": 130, "flex": 1},
        {"field": "变式", "width": 90},
        {"field": "来源", "width": 100},
        {"field": "question_id", "hide": True},
        {"field": "clicked_id", "hide": True, "editable": True},
    ]
    return {
        "columnDefs": column_defs,
        "rowSelection": "multiple",
        "suppressRowClickSelection": True,
        "defaultColDef": {"resizable": True},
        "onCellClicked": on_cell,
    }


def clicked_question_id(rows: list[dict]):
    """从 AgGrid 返回行里解析本次点击的题目 id；无有效点击返回 None。"""
    for row in rows or []:
        value = row.get("clicked_id") if isinstance(row, dict) else None
        try:
            if value not in (None, ""):
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def selected_question_ids(rows: list[dict]) -> list[int]:
    """取出勾选行的题目 id，去重保序。"""
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            qid = int(row.get("question_id"))
        except (TypeError, ValueError):
            continue
        if qid not in result:
            result.append(qid)
    return result


def _value_text(value) -> str | None:
    """把日志字段值统一转成可存文本。"""
    if value is None:
        return None
    return str(value)


def _create_edit_log(session, question_id: int, field: str,
                     old_value, new_value) -> QuestionEditLog:
    """写入一条题目修改记录。"""
    row = QuestionEditLog(
        question_id=question_id, field=field,
        old_value=_value_text(old_value), new_value=_value_text(new_value))
    session.add(row)
    session.flush()
    return row


def log_question_edit(session, question_id: int, field: str,
                      old_value, new_value) -> QuestionEditLog:
    """对外提供的修改记录写入接口。"""
    return _create_edit_log(session, question_id, field, old_value, new_value)


def list_question_edit_logs(session, question_id: int) -> list[QuestionEditLog]:
    """按时间倒序列出某题的修改记录。"""
    return (session.query(QuestionEditLog)
            .filter(QuestionEditLog.question_id == question_id)
            .order_by(QuestionEditLog.created_at.desc(),
                      QuestionEditLog.id.desc()).all())


# ---------------------------------------------------------------------------
# v1.9.1：题目变式
# ---------------------------------------------------------------------------


def _variant_type_key(value) -> str | None:
    """把变式类型写法归一为 number/context/difficulty。"""
    if value is None:
        return None
    key = str(value).strip().lower().replace(" ", "")
    return VARIANT_TYPE_ALIASES.get(key)


def _merge_parent_knowledge_points(parent: Question, raw: dict) -> str:
    """合并原题与模型返回知识点，按 JSON 数组存储，去空去重。"""
    items = knowledge_points_list(parent)
    extra = raw.get("knowledge_point", raw.get("knowledge_points", raw.get("知识点", "")))
    if isinstance(extra, list):
        candidates = [str(x) for x in extra]
    else:
        candidates = re.split(r"[，,、;；]\s*", str(extra or ""))
    candidates = items + candidates
    seen, merged = set(), []
    for kp in candidates:
        kp = kp.strip()
        if kp and kp not in seen:
            seen.add(kp)
            merged.append(kp)
    return json.dumps(merged, ensure_ascii=False)


def generate_variants(
    question: Question,
    variant_types,
    count: int = 1,
    difficulty_adjust: str = "keep",
) -> list[dict]:
    """调用 AI 生成题目变式，返回经过校验的变式字典列表。"""
    types = []
    for value in variant_types:
        key = _variant_type_key(value)
        if key and key not in types:
            types.append(key)
    if not types:
        raise ValueError("请至少选择一种变式类型。")
    count = int(count)
    if not 1 <= count <= 3:
        raise ValueError("每种变式只能生成 1 到 3 题。")
    if difficulty_adjust not in ("lower", "keep", "higher"):
        raise ValueError("难度调整只能是降低、保持或提高。")

    type_desc = "、".join(VARIANT_TYPE_LABELS[x] for x in types)
    system_prompt = (
        "你是一名资深中小学教研员，擅长题目变式设计。"
        "变式题必须保持原题核心知识点，但改变呈现形式。"
        "只输出 JSON 数组，每题包含 content、answer、analysis、"
        "knowledge_point、variant_type 字段。"
    )
    user_text = (
        f"原题ID：{question.id}\n题型：{QUESTION_TYPES.get(question.question_type)}\n"
        f"原题难度：{DIFFICULTY_LABELS.get(question.difficulty)}\n"
        f"原题知识点：{'、'.join(knowledge_points_list(question)) or '未标注'}\n"
        f"原题干：{question.content}\n原题答案：{question.answer}\n"
        f"原解析：{question.analysis or '无'}\n\n"
        f"需要的变式类型：{type_desc}\n每种类型生成：{count} 题\n"
        "数字变式要改变数字并保持结构；情境变式要改变背景并保持数学结构；"
        "难度变式要增减条件或改变思维层次。"
    )
    if "difficulty" in types:
        adjust_text = {"lower": "降低", "keep": "保持", "higher": "提高"}
        user_text += f"\n难度变式的难度调整：{adjust_text[difficulty_adjust]}。"
    raw_text = llm_client.chat_content(system_prompt, user_text, temperature=0.8)
    return parse_variant_questions(
        raw_text, question, types, count, difficulty_adjust)


def parse_variant_questions(
    text: str,
    parent: Question,
    variant_types: list[str],
    count: int,
    difficulty_adjust: str,
) -> list[dict]:
    """解析并校验 AI 返回的变式；缺题干或缺答案一律拒收。"""
    raw_items = parse_generated_questions(text)
    result = []
    seen_temp = set()
    for index, raw in enumerate(raw_items):
        content = str(raw.get("content") or raw.get("题干") or "").strip()
        answer = str(raw.get("answer") or raw.get("答案") or "").strip()
        if not content or not answer:
            continue
        vtype = _variant_type_key(raw.get("variant_type"))
        if vtype not in variant_types:
            fallback_index = min(index // max(int(count), 1), len(variant_types) - 1)
            vtype = variant_types[fallback_index]
        if vtype == "difficulty":
            offset = {"lower": -1, "keep": 0, "higher": 1}[difficulty_adjust]
            difficulty = int(parent.difficulty) + offset
        else:
            difficulty = int(parent.difficulty)
        difficulty = min(3, max(1, difficulty))
        if raw.get("question_type") or raw.get("题型"):
            qtype = normalize_type(raw.get("question_type") or raw.get("题型"))
        else:
            qtype = parent.question_type
        temp_id = uuid.uuid4().hex[:10]
        while temp_id in seen_temp:
            temp_id = uuid.uuid4().hex[:10]
        seen_temp.add(temp_id)
        result.append({
            "temp_id": temp_id,
            "variant_type": vtype,
            "content": content,
            "answer": answer,
            "analysis": str(raw.get("analysis") or raw.get("解析") or "").strip(),
            "question_type": qtype,
            "difficulty": difficulty,
            "knowledge_points": _merge_parent_knowledge_points(parent, raw),
        })
    if not result:
        raise ValueError("AI 没有返回题干和答案完整的可用变式。")
    return result


def save_variants(session, variants: list[dict], parent_id: int) -> list[int]:
    """把勾选变式保存为待审核题，并写入原题 ID。"""
    parent = session.get(Question, int(parent_id))
    if parent is None:
        raise ValueError(f"原题不存在：id={parent_id}")
    ids = []
    for item in variants:
        data = {
            "content": item["content"],
            "question_type": item["question_type"],
            "difficulty": item["difficulty"],
            "knowledge_points": item["knowledge_points"],
            "answer": item["answer"],
            "analysis": item.get("analysis", ""),
            "error_points": "",
            "verify": None,
        }
        q = create_question(
            session, data, source="ai_generated", status="pending",
            subject=parent.subject, grade=parent.grade)
        q.parent_question_id = parent.id
        session.flush()
        ids.append(q.id)
    return ids


def variant_counts(session) -> dict[int, int]:
    """统计每道原题对应的变式数量。"""
    from sqlalchemy import func
    rows = (session.query(Question.parent_question_id, func.count(Question.id))
            .filter(Question.parent_question_id.isnot(None))
            .group_by(Question.parent_question_id).all())
    return {int(parent_id): int(count) for parent_id, count in rows}

# ---------------------------------------------------------------------------
# v1.9.4：自然语言修正题目
# ---------------------------------------------------------------------------


def question_to_data(question) -> dict:
    """把 Question 对象或题目字典转成统一题目数据。"""
    if isinstance(question, Question):
        return {
            "id": question.id,
            "content": question.content,
            "question_type": question.question_type,
            "difficulty": int(question.difficulty or 2),
            "knowledge_points": json.dumps(knowledge_points_list(question), ensure_ascii=False),
            "answer": question.answer,
            "analysis": question.analysis or "",
            "error_points": question.error_points or "",
        }
    data = dict(question or {})
    if "difficulty" in data:
        data["difficulty"] = normalize_difficulty(data.get("difficulty"))
    if "knowledge_points" not in data:
        data["knowledge_points"] = "[]"
    if "id" not in data:
        data["id"] = None
    return data


def modify_question(question, instruction: str, context: dict | None = None) -> dict:
    """按自然语言修正一道题，返回新题目数据，不直接修改数据库。"""
    original = question_to_data(question)
    raw = llm_client.chat_content(
        _MODIFY_QUESTION_SYSTEM,
        _modify_question_user(original, instruction, context),
        temperature=0.4,
    )
    items = _parse_modified_questions(raw, [original])
    if not items:
        raise ValueError("题目修正失败，请重新描述修改意见。")
    return items[0]


def batch_modify_questions(questions, instruction: str,
                           context: dict | None = None) -> list[dict]:
    """批量修正题目；未命中的题目保持原样返回。"""
    originals = [question_to_data(item) for item in questions]
    if not originals:
        return []
    raw = llm_client.chat_content(
        _MODIFY_QUESTION_SYSTEM,
        _modify_batch_user(originals, instruction, context),
        temperature=0.4,
    )
    parsed = _parse_modified_questions(raw, originals)
    by_index = {int(item.get("source_index", -1)): item for item in parsed}
    result = []
    for index, original in enumerate(originals):
        item = by_index.get(index)
        result.append(item if item is not None else original)
    return result


_MODIFY_QUESTION_SYSTEM = """你是题目修改器。只根据老师的修改意见改题，其他内容保持不变。
输出必须是 JSON：单题修正输出 {"question": {...}}；批量修正输出 {"questions":[{"source_index":0,...}]}。
题目字段包含 content、question_type、difficulty、knowledge_points、answer、analysis。
question_type 只能是 choice/fill/judge/solution；difficulty 只能是 1/2/3；
knowledge_points 必须是字符串数组；答案不能为空。只输出 JSON，不要解释。"""


def _modify_question_user(original: dict, instruction: str, context: dict | None) -> str:
    """构造单题修正请求。"""
    context = context or {}
    return (
        f"修改意见：{instruction}\n"
        f"学科：{context.get('subject') or ''}\n"
        f"年级：{context.get('grade') or ''}\n"
        f"原题目 JSON：{json.dumps(original, ensure_ascii=False)}"
    )


def _modify_batch_user(originals: list[dict], instruction: str,
                       context: dict | None) -> str:
    """构造批量修正请求。"""
    context = context or {}
    return (
        f"批量修改意见：{instruction}\n"
        f"学科：{context.get('subject') or ''}\n"
        f"年级：{context.get('grade') or ''}\n"
        f"原题目列表 JSON：{json.dumps(originals, ensure_ascii=False)}"
    )


def _parse_modified_questions(raw_text: str, originals: list[dict]) -> list[dict]:
    """解析并校验修正后的题目，合并原题知识点。"""
    data = extract_modify_json(raw_text)
    if data is None:
        return []
    if isinstance(data, dict) and isinstance(data.get("question"), dict):
        candidates = [dict(data["question"], source_index=0)]
    elif isinstance(data, dict) and isinstance(data.get("questions"), list):
        candidates = data["questions"]
    else:
        return []

    result = []
    for index, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            continue
        source_index = raw.get("source_index", index)
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            source_index = index
        if source_index < 0 or source_index >= len(originals):
            continue
        original = originals[source_index]
        merged = dict(original)
        for key in ("content", "question_type", "difficulty", "answer", "analysis"):
            if raw.get(key) not in (None, ""):
                merged[key] = raw[key]
        checked = validate_question(merged)
        if checked is None:
            continue
        checked["source_index"] = source_index
        checked["id"] = original.get("id")
        checked["knowledge_points"] = _merge_kp_strings(
            original.get("knowledge_points", "[]"),
            raw.get("knowledge_points", []),
        )
        result.append(checked)
    return result


def extract_modify_json(raw_text: str):
    """从修正结果中提取 JSON。"""
    cleaned = strip_code_fence(str(raw_text or ""))
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _merge_kp_strings(existing_json: str, returned):
    """合并原知识点和模型返回知识点，去空去重。"""
    items = []
    try:
        old = json.loads(existing_json) if existing_json else []
        if isinstance(old, list):
            items.extend(old)
    except json.JSONDecodeError:
        pass
    if isinstance(returned, list):
        items.extend(returned)
    elif returned:
        items.extend(x.strip() for x in re.split(r"[，,、;；]", str(returned)) if x.strip())
    merged = list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))
    return json.dumps(merged, ensure_ascii=False)
