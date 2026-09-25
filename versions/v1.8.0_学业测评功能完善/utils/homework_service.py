# -*- coding: utf-8 -*-
"""
作业服务层。

负责：
- 作业 / 模板的增删改查（模板就是 is_template=True 的作业，同表存放）；
- 作业内题目的加入、移除、上下调序、每题分值、总分汇总；
- 存为模板、从模板复制题目；
- 导出学生卷 / 教师卷 Word；
- AI 自动组卷（规则确定性抽题为主，缺口再调 AI 补题）。

所有函数收外部 session，由页面用 with SessionLocal() 管理事务。
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from models.models import Homework, HomeworkQuestion, Question
from utils.app_config import DEFAULT_SUBJECT, to_display_grade
from utils import llm_client
from utils import question_service as qs
from utils import homework_stats as hstat

# 5 种作业类型：内部值 -> (中文名, emoji)
HOMEWORK_TYPES = {
    "preview": ("课前预习", "📖"),
    "classroom": ("课中练习", "📝"),
    "after_class": ("课后作业", "📚"),
    "review": ("复习作业", "🔄"),
    "exam": ("试卷出题", "📄"),
}

# 各类型默认参数：建议题量、时长（分钟）、总分、难度倾向（仅供弹窗默认值）
DEFAULT_PARAMS = {
    "preview":    {"question_count": 5,  "duration": 20,  "total_score": 50.0},
    "classroom":  {"question_count": 8,  "duration": 25,  "total_score": 80.0},
    "after_class": {"question_count": 12, "duration": 45, "total_score": 100.0},
    "review":     {"question_count": 18, "duration": 60,  "total_score": 120.0},
    "exam":       {"question_count": 20, "duration": 90,  "total_score": 120.0},
}


def type_label(hw_type: str) -> str:
    """作业类型中文标签。"""
    return HOMEWORK_TYPES.get(hw_type, ("作业", "📝"))[0]


def type_emoji(hw_type: str) -> str:
    return HOMEWORK_TYPES.get(hw_type, ("作业", "📝"))[1]


# ---------------------------------------------------------------------------
# 作业 / 模板 CRUD
# ---------------------------------------------------------------------------

def create_homework(session, name: str, homework_type: str = "after_class",
                    class_name: str | None = None, total_score: float | None = None,
                    duration: int | None = None, remark: str | None = None,
                    is_template: bool = False, template_id: int | None = None,
                    subject: str | None = None, grade: str | None = None,
                    status: str = "pending", due_date=None,
                    material_id=None, chapter=None) -> Homework:
    """新建作业；给 template_id 时把模板里的题目（含顺序、分值）复制进来。

    subject 不传时使用默认学科“数学”。
    """
    if not name or not name.strip():
        raise ValueError("作业名称不能为空。")
    defaults = DEFAULT_PARAMS.get(homework_type, DEFAULT_PARAMS["after_class"])
    hw = Homework(
        name=name.strip(), homework_type=homework_type, class_name=class_name,
        total_score=total_score if total_score is not None else defaults["total_score"],
        duration=duration if duration is not None else defaults["duration"],
        remark=remark, is_template=is_template, status=status,
        subject=subject or DEFAULT_SUBJECT, grade=grade, due_date=due_date,
        material_id=material_id, chapter=chapter)
    session.add(hw)
    session.flush()
    if template_id is not None:
        copy_template_questions(session, template_id, hw.id)
    return hw


def copy_template_questions(session, template_id: int, homework_id: int) -> int:
    """把模板的题目关联复制到目标作业，返回复制条数。"""
    links = (session.query(HomeworkQuestion)
             .filter(HomeworkQuestion.homework_id == template_id)
             .order_by(HomeworkQuestion.order).all())
    for link in links:
        session.add(HomeworkQuestion(
            homework_id=homework_id, question_id=link.question_id,
            order=link.order, score=link.score))
    session.flush()
    return len(links)


def list_homeworks(session, templates: bool = False, class_name: str | None = None,
                   subject: str | None = None, keyword: str | None = None,
                   homework_type: str | None = None, grade: str | None = None,
                   status: str | None = None, exclude_types: list[str] | None = None,
                   sort_order: str = "created_desc"):
    """作业列表。

    grade 按存储年级精确匹配；exclude_types 用于作业管理排除试卷；
    sort_order 支持 created_desc/created_asc/opened_desc。
    """
    q = session.query(Homework).filter(Homework.is_template.is_(templates))
    if class_name:
        q = q.filter(Homework.class_name == class_name)
    if subject:
        q = q.filter(Homework.subject == subject)
    if homework_type:
        q = q.filter(Homework.homework_type == homework_type)
    if grade:
        # v1.7.7：年级筛选时兼容grade为NULL的旧作业
        q = q.filter((Homework.grade == grade) | Homework.grade.is_(None))
    if status:
        q = q.filter(Homework.status == status)
    if keyword:
        q = q.filter(Homework.name.like(f"%{keyword.strip()}%"))

    order_map = {
        "created_desc": (Homework.created_at.desc(), Homework.id.desc()),
        "created_asc": (Homework.created_at.asc(), Homework.id.asc()),
        "opened_desc": (Homework.last_opened_at.desc(), Homework.created_at.desc()),
    }
    order_args = order_map.get(sort_order, order_map["created_desc"])
    items = q.order_by(*order_args).all()
    if exclude_types:
        items = [item for item in items if item.homework_type not in set(exclude_types)]
    return items


def list_homework_classes(session, subject: str | None = None) -> list[str]:
    """返回普通作业中出现过的非空班级，供作业管理筛选。"""
    q = (session.query(Homework.class_name)
         .filter(Homework.is_template.is_(False),
                 Homework.class_name.isnot(None),
                 Homework.class_name != ""))
    if subject:
        q = q.filter(Homework.subject == subject)
    return sorted({row[0] for row in q.distinct().all()})


def get_homework(session, homework_id: int) -> Homework | None:
    return session.get(Homework, homework_id)


def update_homework(session, homework_id: int, **fields) -> None:
    # v1.8.0 白名单新增 due_date / material_id / chapter。
    allowed = {"name", "homework_type", "class_name", "total_score", "duration",
           "remark", "status", "completed_at", "last_opened_at",
           "due_date", "material_id", "chapter"}
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    for key, value in fields.items():
        if key in allowed:
            setattr(hw, key, value)


def list_homework_scores_grouped_by_class(session, homework_id: int,
                                          pass_line: float | None = None,
                                          excellent_line: float | None = None) -> list[dict]:
    """按班级聚合作业成绩，用于"多班级对比"。

    返回 [{class_name, count, mean, pass_rate, excellent_rate, max, min}, ...]
    pass_line / excellent_line 传入时同时算及格率、优秀率；否则为 None。
    """
    from models.models import HomeworkScore, Student
    rows = (session.query(HomeworkScore, Student)
            .join(Student, HomeworkScore.student_id == Student.id)
            .filter(HomeworkScore.homework_id == homework_id).all())
    buckets: dict[str, list[float]] = {}
    for hs, stu in rows:
        if hs.total_score is None:
            continue
        cls = stu.class_name or "未分班"
        buckets.setdefault(cls, []).append(float(hs.total_score))
    result = []
    for cls, values in buckets.items():
        count = len(values)
        mean = round(sum(values) / count, 2) if count else None
        pass_rate = None
        excellent_rate = None
        if count and pass_line is not None:
            pass_rate = round(sum(1 for v in values if v >= pass_line) / count * 100, 1)
        if count and excellent_line is not None:
            excellent_rate = round(
                sum(1 for v in values if v >= excellent_line) / count * 100, 1)
        result.append({
            "class_name": cls,
            "count": count,
            "mean": mean,
            "max": max(values) if values else None,
            "min": min(values) if values else None,
            "pass_rate": pass_rate,
            "excellent_rate": excellent_rate,
        })
    # 按班级名排序，便于展示。
    result.sort(key=lambda item: item["class_name"])
    return result


def delete_homework(session, homework_id: int) -> None:
    hw = session.get(Homework, homework_id)
    if hw is not None:
        session.delete(hw)  # 级联删除题目关联、成绩、作答


def delete_homeworks(session, homework_ids: list[int]) -> int:
    """批量删除作业（题目关联、成绩、作答按 ORM 级联清理），返回实际删除数。

    模板也能按 id 删除；调用方负责只传入普通作业 id。
    """
    count = 0
    for hid in dict.fromkeys(homework_ids):
        hw = session.get(Homework, int(hid))
        if hw is not None:
            session.delete(hw)
            count += 1
    return count


def default_retry_homework_name(session, today=None) -> str:
    """错题重做卷默认名称；同日重名时追加序号。"""
    from datetime import date as _date
    today = today or _date.today()
    base = f"错题重做卷_{today.strftime('%Y%m%d')}"
    existing = {hw.name for hw in list_homeworks(session)}
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def generate_retry_homework(session, items: list[dict], name: str,
                            subject: str, class_name: str | None = None,
                            duration: int = 45) -> dict:
    """
    用错题生成普通课后作业。

    items 每项包含 question_id、difficulty、score；难度未变时复用原题，
    难度变化时克隆题目，避免修改原题。返回新作业及复用/克隆统计。
    """
    if not items:
        raise ValueError("没有选择错题。")
    total_score = 0.0
    prepared: list[tuple[int, int, float]] = []
    seen = set()
    reused = cloned = 0

    for item in items:
        question_id = int(item["question_id"])
        if question_id in seen:
            continue
        seen.add(question_id)
        source = session.get(Question, question_id)
        if source is None:
            raise ValueError(f"题目不存在：id={question_id}")
        try:
            score = round(float(item["score"]), 2)
            difficulty = int(item["difficulty"])
        except (TypeError, ValueError) as exc:
            raise ValueError("题目分值和难度必须是数字。") from exc
        if score <= 0:
            raise ValueError("题目分值必须大于 0。")
        if difficulty not in (1, 2, 3):
            raise ValueError("题目难度只能是 1、2、3。")

        if difficulty == source.difficulty:
            target_id = source.id
            reused += 1
        else:
            clone = Question(
                content=source.content,
                question_type=source.question_type,
                difficulty=difficulty,
                knowledge_points=source.knowledge_points,
                answer=source.answer,
                analysis=source.analysis,
                error_points=source.error_points,
                subject=subject,
                source="错题重做",
                status=source.status,
            )
            session.add(clone)
            session.flush()
            target_id = clone.id
            cloned += 1
        prepared.append((target_id, len(prepared) + 1, score))
        total_score += score

    hw = create_homework(
        session, name, homework_type="after_class", class_name=class_name,
        total_score=round(total_score, 2), duration=duration, subject=subject)
    for question_id, order, score in prepared:
        session.add(HomeworkQuestion(
            homework_id=hw.id, question_id=question_id,
            order=order, score=score))
    session.flush()
    return {
        "homework_id": hw.id,
        "question_count": len(prepared),
        "reused_count": reused,
        "cloned_count": cloned,
    }

def save_as_template(session, homework_id: int, template_name: str | None = None) -> Homework:
    """把一份普通作业复制成模板（复制题目关联），不复制成绩。"""
    src = session.get(Homework, homework_id)
    if src is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    tpl = Homework(
        name=(template_name or f"{src.name}（模板）").strip(),
        homework_type=src.homework_type, class_name=src.class_name,
        total_score=src.total_score, duration=src.duration, remark=src.remark,
        is_template=True, subject=src.subject or DEFAULT_SUBJECT, grade=src.grade,
        status="pending", completed_at=None, last_opened_at=None)
    session.add(tpl)
    session.flush()
    copy_template_questions(session, src.id, tpl.id)
    return tpl

# ---------------------------------------------------------------------------
# 作业内题目管理
# ---------------------------------------------------------------------------

def homework_questions(session, homework_id: int) -> list[tuple[HomeworkQuestion, Question]]:
    """按顺序返回作业内的 (关联行, 题目)。"""
    rows = (session.query(HomeworkQuestion, Question)
            .join(Question, HomeworkQuestion.question_id == Question.id)
            .filter(HomeworkQuestion.homework_id == homework_id)
            .order_by(HomeworkQuestion.order, HomeworkQuestion.id).all())
    return rows


def question_count(session, homework_id: int) -> int:
    """统计作业内题目数。"""
    return (session.query(HomeworkQuestion)
            .filter(HomeworkQuestion.homework_id == homework_id).count())


def question_ids_in_homework(session, homework_id: int) -> set[int]:
    """作业里已有的题目 id（防止重复加入）。"""
    return {r[0] for r in session.query(HomeworkQuestion.question_id)
            .filter(HomeworkQuestion.homework_id == homework_id).all()}


def add_questions(session, homework_id: int, question_ids: list[int],
                  default_score: float | None = None) -> int:
    """把题库题加入作业末尾，已存在的自动跳过；返回实际加入条数。"""
    existing = question_ids_in_homework(session, homework_id)
    max_order = (session.query(HomeworkQuestion.order)
                 .filter(HomeworkQuestion.homework_id == homework_id)
                 .order_by(HomeworkQuestion.order.desc()).first())
    order = (max_order[0] or 0) if max_order else 0
    added = 0
    for qid in question_ids:
        if qid in existing:
            continue
        order += 1
        session.add(HomeworkQuestion(
            homework_id=homework_id, question_id=qid, order=order,
            score=default_score))
        existing.add(qid)
        added += 1
    session.flush()
    return added


def remove_question(session, homework_id: int, question_id: int) -> None:
    """从作业移除一题，随后自动重排顺序。"""
    link = (session.query(HomeworkQuestion)
            .filter(HomeworkQuestion.homework_id == homework_id,
                    HomeworkQuestion.question_id == question_id).first())
    if link is not None:
        session.delete(link)
        session.flush()
        _reorder(session, homework_id)


def move_question(session, homework_id: int, question_id: int, delta: int) -> None:
    """把题上移(-1)/下移(+1)，边界处不动。"""
    links = (session.query(HomeworkQuestion)
             .filter(HomeworkQuestion.homework_id == homework_id)
             .order_by(HomeworkQuestion.order, HomeworkQuestion.id).all())
    idx = next((i for i, l in enumerate(links) if l.question_id == question_id), None)
    if idx is None:
        return
    target = idx + delta
    if target < 0 or target >= len(links):
        return
    links[idx], links[target] = links[target], links[idx]
    for i, link in enumerate(links, start=1):
        link.order = i
    session.flush()


def _reorder(session, homework_id: int) -> None:
    """删除后按当前顺序重新编号 1..N。"""
    links = (session.query(HomeworkQuestion)
             .filter(HomeworkQuestion.homework_id == homework_id)
             .order_by(HomeworkQuestion.order, HomeworkQuestion.id).all())
    for i, link in enumerate(links, start=1):
        link.order = i


def set_question_score(session, homework_id: int, question_id: int,
                       score: float | None) -> None:
    """设置某题分值。"""
    link = (session.query(HomeworkQuestion)
            .filter(HomeworkQuestion.homework_id == homework_id,
                    HomeworkQuestion.question_id == question_id).first())
    if link is not None:
        link.score = score


def summed_score(session, homework_id: int) -> float:
    """已设置的每题分值之和（未设置分值的不计）。"""
    rows = session.query(HomeworkQuestion.score).filter(
        HomeworkQuestion.homework_id == homework_id).all()
    return round(sum(r[0] for r in rows if r[0] is not None), 2)


def export_word(session, homework_id: int, with_answer: bool) -> bytes:
    """导出作业 Word：with_answer=False 学生卷，True 教师卷。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    pairs = homework_questions(session, homework_id)
    questions = [q for _link, q in pairs]
    title = f"{hw.name}（教师卷）" if with_answer else hw.name
    return qs.export_questions_word(questions, with_answer=with_answer, title=title)


def mark_homework_completed(session, homework_id: int, completed_at=None) -> Homework:
    """把作业标记为已完成。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    hw.status = "completed"
    hw.completed_at = completed_at or datetime.now()
    session.flush()
    return hw


def reopen_homework(session, homework_id: int) -> Homework:
    """重新打开已完成作业。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    hw.status = "pending"
    hw.completed_at = None
    session.flush()
    return hw


def duplicate_homework(session, homework_id: int, new_name: str | None = None) -> Homework:
    """复制作业和题目关联；成绩、作答不复制。"""
    src = session.get(Homework, homework_id)
    if src is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    name = (new_name or f"{src.name}（副本）").strip()
    clone = Homework(
        name=name, homework_type=src.homework_type, class_name=src.class_name,
        total_score=src.total_score, duration=src.duration, remark=src.remark,
        is_template=False, subject=src.subject or DEFAULT_SUBJECT, grade=src.grade,
        status="pending", completed_at=None, last_opened_at=None)
    session.add(clone)
    session.flush()
    copy_template_questions(session, src.id, clone.id)
    return clone


def touch_homework(session, homework_id: int) -> None:
    """更新最近打开时间。"""
    hw = session.get(Homework, homework_id)
    if hw is not None:
        hw.last_opened_at = datetime.now()
        session.flush()


def export_homeworks_zip(session, homework_ids: list[int], with_answer: bool = False) -> bytes:
    """批量导出多份作业 Word，并打成 ZIP。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names = set()
        for hid in dict.fromkeys(int(x) for x in homework_ids):
            hw = session.get(Homework, hid)
            if hw is None:
                continue
            data = export_word(session, hid, with_answer=with_answer)
            base = f"{hw.name}-{'教师卷' if with_answer else '学生卷'}.docx"
            file_name = base
            index = 2
            while file_name in used_names:
                file_name = f"{Path(base).stem}_{index}.docx"
                index += 1
            used_names.add(file_name)
            zf.writestr(file_name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# AI 自动组卷：规则抽题为主，缺口调内容模型补齐
# ---------------------------------------------------------------------------

def normalize_compose_slots(spec: dict) -> list[dict]:
    """把新旧组卷规格统一展开成逐题槽位。"""
    if not isinstance(spec, dict):
        raise ValueError("组卷规格格式不正确。")
    if "slots" in spec:
        slots = []
        for item in spec["slots"]:
            qtype = str(item.get("question_type") or "").strip()
            if qtype not in {"choice", "fill", "judge", "solution"}:
                raise ValueError(f"不支持的题型：{qtype}")
            try:
                difficulty = int(item.get("difficulty"))
                count = int(item.get("count"))
            except (TypeError, ValueError):
                raise ValueError("题型难度和数量必须是整数。")
            if difficulty not in (1, 2, 3):
                raise ValueError("题目难度必须是 1、2、3。")
            if count <= 0:
                raise ValueError("题目数量必须大于 0。")
            for _ in range(count):
                slots.append({"question_type": qtype, "difficulty": difficulty})
        if not slots:
            raise ValueError("请至少配置一道题。")
        return slots
    return hstat.plan_paper_slots(spec)


def slots_from_type_matrix(rows: list[dict]) -> list[dict]:
    """把页面的“题型 × 难度数量”矩阵转换成新 slots 规格。"""
    slots: list[dict] = []
    for row in rows or []:
        type_name = str(row.get("type") or "").strip()
        alias_key = type_name.lower().replace(" ", "")
        qtype = qs.EXTENDED_TYPE_ALIASES.get(alias_key)
        if qtype is None:
            raise ValueError(f"暂不支持的题型：{type_name}")
        for difficulty, key_name in (
                (1, "easy"), (2, "medium"), (3, "hard")):
            try:
                count = int(row.get(key_name) or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError("题目数量必须是整数。") from exc
            if count < 0:
                raise ValueError("题目数量不能小于 0。")
            for _ in range(count):
                slots.append({
                    "question_type": qtype,
                    "difficulty": difficulty,
                    "count": 1,
                })
    if not slots:
        raise ValueError("请至少配置一道题。")
    return slots


def auto_compose(session, homework_id: int, spec: dict,
                 knowledge_points: list[str] | None = None,
                 ai_context: dict | None = None) -> dict:
    """
    一键自动组卷。

    spec: {"counts": {题型: 题量}, "difficulty_ratio": {1:x, 2:y, 3:z}}
    ai_context: textbook_id/chapters/grade，只用于约束 AI 补题。
    流程：展开槽位 → 从已审核题库确定性抽题 → 缺口调 AI 补题入库并加入作业。
    返回统计与知识点覆盖，供页面提示。AI 不可用时只保留规则抽到的题。
    """
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")

    slots = normalize_compose_slots(spec)
    cur_subject = hw.subject or DEFAULT_SUBJECT
    pool = qs.list_questions(session, status="approved", subject=cur_subject)
    wanted_kps = [str(kp).strip() for kp in (knowledge_points or []) if str(kp).strip()]
    if wanted_kps:
        # Question 没有章节字段，题库只按可落库的知识点过滤。
        pool = [
            question for question in pool
            if any(kp in qs.knowledge_points_list(question) for kp in wanted_kps)
        ]
    existing = question_ids_in_homework(session, homework_id)
    result = hstat.deterministic_pick(pool, slots, exclude_ids=existing)

    picked_ids = [q.id for q in result["picked"]]
    shortage = result["shortage"]
    ai_created = 0
    ai_failed = 0

    if shortage:
        try:
            new_questions = _ai_generate_for_shortage(
                session, shortage, knowledge_points or [], cur_subject,
                ai_context=ai_context or {})
            # 把生成题尽量匹配到剩余槽位（精确题型+难度优先）
            matched = _match_generated_to_slots(new_questions, shortage)
            picked_ids.extend(matched["matched_ids"])
            ai_created = len(matched["matched_ids"])
            ai_failed = len(matched["leftover_slots"])
            shortage = matched["leftover_slots"]
        except Exception:
            # 自动组卷不因 AI 失败而整体失败：保留规则抽到的题
            ai_failed = len(shortage)

    if picked_ids:
        add_questions(session, homework_id, picked_ids)

    # 知识点覆盖检查（基于最终作业内题目）
    pairs = homework_questions(session, homework_id)
    qkps = [(q.id, qs.knowledge_points_list(q)) for _l, q in pairs]
    coverage = hstat.knowledge_coverage(qkps, knowledge_points or [])

    return {
        "rule_picked": len(result["picked"]),
        "ai_generated": ai_created,
        "shortage_count": len(shortage),
        "shortage": shortage,
        "coverage": coverage,
        "total_questions": len(pairs),
    }


def _ai_generate_for_shortage(session, shortage: list[dict],
                              knowledge_points: list[str],
                              subject: str | None = None,
                              ai_context: dict | None = None) -> list:
    """按缺口槽位调内容模型出题，校验入库（待审核），返回新建 Question 列表。"""
    from pathlib import Path
    import config
    from utils import llm_client

    # 聚合每种 (题型,难度) 需要几道
    need: dict[tuple, int] = {}
    for slot in shortage:
        key = (slot["question_type"], slot["difficulty"])
        need[key] = need.get(key, 0) + 1

    type_label = {"choice": "选择题", "fill": "填空题",
                  "judge": "判断题", "solution": "解答题"}
    diff_label = {1: "基础", 2: "中等", 3: "拓展"}
    lines = [f"- {type_label.get(t, t)}{diff_label.get(d, '')}：{n} 道"
             for (t, d), n in need.items()]
    kp_text = "、".join(knowledge_points) if knowledge_points else "由题目确定相关知识点"
    ai_context = ai_context or {}
    chapter_titles = ai_context.get("chapters") or []
    chapter_text = "、".join(str(item) for item in chapter_titles) if chapter_titles else "未指定章节"
    grade_text = to_display_grade(ai_context.get("grade")) or "未指定"
    textbook_id = ai_context.get("textbook_id")

    system_prompt = (Path(config.BASE_DIR) / "prompts" / "question_prompt.txt").read_text(
        encoding="utf-8")
    subject = subject or DEFAULT_SUBJECT
    user_text = (
        f"学科：{subject}\n"
        f"年级：{grade_text}\n"
        f"资料ID：{textbook_id or '未指定'}\n"
        f"参考章节：{chapter_text}\n"
        f"知识点范围：{kp_text}\n"
        f"请严格围绕参考章节和知识点，按下面的题型与难度数量命题（这是一份作业的补缺部分）：\n"
        + "\n".join(lines)
    )
    raw = llm_client.chat_content(system_prompt, user_text, temperature=0.8)
    valid, _rejected = qs.build_questions(raw)

    created = []
    for data in valid:
        question = qs.create_question(session, data, source="ai_generated",
                                      status="pending", subject=subject)
        created.append(question)
    session.flush()
    return created


def _match_generated_to_slots(questions: list, slots: list[dict]) -> dict:
    """把 AI 生成的题匹配到缺口槽位：精确题型+难度优先，其次只对题型。"""
    remaining = list(slots)
    matched_ids = []

    def consume(predicate):
        nonlocal remaining
        used_q = set()
        for q in list(questions):
            if q.id in matched_ids:
                continue
            for i, slot in enumerate(remaining):
                if predicate(q, slot):
                    matched_ids.append(q.id)
                    remaining.pop(i)
                    used_q.add(q.id)
                    break

    # 第一轮：题型 + 难度都匹配
    consume(lambda q, s: q.question_type == s["question_type"]
            and q.difficulty == s["difficulty"])
    # 第二轮：题型匹配即可（难度放宽）
    consume(lambda q, s: q.question_type == s["question_type"])
    return {"matched_ids": matched_ids, "leftover_slots": remaining}

# ---------------------------------------------------------------------------
# v1.6.0：知识点组卷
# ---------------------------------------------------------------------------

def validate_knowledge_paper_rules(rows: list[dict]) -> list[dict]:
    """校验知识点组卷规则。"""
    result = []
    for row in rows:
        knowledge = str(row.get("知识点") or "").strip()
        if not knowledge:
            raise ValueError("知识点不能为空。")
        difficulty = qs.normalize_difficulty(row.get("难度"))
        try:
            count = int(row.get("数量"))
        except (TypeError, ValueError) as exc:
            raise ValueError("抽题数量必须是整数。") from exc
        if count <= 0:
            raise ValueError("抽题数量必须大于 0。")
        result.append({
            "knowledge_point": knowledge,
            "difficulty": difficulty,
            "count": count,
        })
    if not result:
        raise ValueError("请先添加知识点抽题规则。")
    return result


def create_paper_by_rules(session, rules: list[dict], name: str,
                          per_question_score: float = 10.0,
                          subject: str | None = None) -> dict:
    """
    只从当前学科的已审核题目抽题；全部规则满足才创建 exam 作业。
    同一题命中多个规则只保留一次。
    """
    subject = subject or DEFAULT_SUBJECT
    rules = validate_knowledge_paper_rules(rules)
    try:
        score_each = float(per_question_score)
    except (TypeError, ValueError) as exc:
        raise ValueError("每题分值必须是数字。") from exc
    if score_each <= 0:
        raise ValueError("每题分值必须大于 0。")
    name = str(name or "").strip()
    if not name:
        raise ValueError("试卷名称不能为空。")

    pool = qs.list_questions(session, status="approved", subject=subject)
    chosen_ids: list[int] = []
    chosen_set: set[int] = set()
    shortages: list[dict] = []

    for rule in rules:
        need = rule["count"]
        candidates = []
        for question in pool:
            if question.id in chosen_set:
                # 已被其他规则占用的题不重复加入；规则缺口另行报告。
                continue
            if question.difficulty != rule["difficulty"]:
                continue
            kps = qs.knowledge_points_list(question)
            if rule["knowledge_point"] in kps:
                candidates.append(question)
        if len(candidates) < need:
            shortages.append({
                "知识点": rule["knowledge_point"],
                "难度": rule["difficulty"],
                "缺口": need - len(candidates),
            })
        else:
            candidates = candidates[:need]
            for question in candidates:
                chosen_ids.append(question.id)
                chosen_set.add(question.id)

    if shortages:
        message = "题量不足，未创建试卷：" + "；".join(
            f"{item['知识点']}（{qs.DIFFICULTY_LABELS[item['难度']]}缺{item['缺口']}题）"
            for item in shortages)
        raise ValueError(message)

    total_score = round(score_each * len(chosen_ids), 2)
    homework = create_homework(
        session, name, homework_type="exam", class_name=None,
        total_score=total_score, duration=90, subject=subject)
    for order, question_id in enumerate(chosen_ids, start=1):
        session.add(HomeworkQuestion(
            homework_id=homework.id, question_id=question_id,
            order=order, score=score_each))
    session.flush()
    return {"homework_id": homework.id, "question_count": len(chosen_ids),
            "total_score": total_score}

