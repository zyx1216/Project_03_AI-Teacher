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

import pandas as pd

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
    is_primary = grade.endswith(("一年级", "二年级", "三年级", "四年级", "五年级", "六年级"))
    is_junior = grade in ("七年级", "八年级", "九年级")
    is_senior = grade in ("高一", "高二", "高三") or grade.endswith(("高一", "高二", "高三"))

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


def bank_table_rows(questions) -> list[dict]:
    """把题目列表转成 AgGrid 行数据；question_id/clicked_id 供回传，不在界面显示。"""
    rows = []
    for q in questions:
        rows.append({
            "ID": int(q.id),
            "题型": QUESTION_TYPES.get(q.question_type, q.question_type),
            "难度": DIFF_LABELS_BANK.get(q.difficulty, q.difficulty),
            "状态": STATUS_LABELS_BANK.get(q.status, q.status),
            "题干": (q.content or "")[:30],
            "知识点": "、".join(knowledge_points_list(q)),
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
        {"field": "题干", "minWidth": 220, "flex": 1},
        {"field": "知识点", "minWidth": 140, "flex": 1},
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

