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

from models.models import Homework, HomeworkQuestion, Question
from utils.app_config import DEFAULT_SUBJECT
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
                    subject: str | None = None) -> Homework:
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
        remark=remark, is_template=is_template,
        subject=subject or DEFAULT_SUBJECT)
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
                   homework_type: str | None = None):
    """作业列表（默认只列普通作业），按创建时间倒序。

    keyword 模糊匹配作业名称；homework_type 精确匹配五类作业。
    """
    q = session.query(Homework).filter(Homework.is_template.is_(templates))
    if class_name:
        q = q.filter(Homework.class_name == class_name)
    if subject:
        q = q.filter(Homework.subject == subject)
    if homework_type:
        q = q.filter(Homework.homework_type == homework_type)
    if keyword:
        q = q.filter(Homework.name.like(f"%{keyword.strip()}%"))
    return q.order_by(Homework.created_at.desc(), Homework.id.desc()).all()


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
    allowed = {"name", "homework_type", "class_name", "total_score", "duration", "remark"}
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    for key, value in fields.items():
        if key in allowed:
            setattr(hw, key, value)


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
        is_template=True, subject=src.subject or DEFAULT_SUBJECT)
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

# ---------------------------------------------------------------------------
# AI 自动组卷：规则抽题为主，缺口调内容模型补齐
# ---------------------------------------------------------------------------

def auto_compose(session, homework_id: int, spec: dict,
                 knowledge_points: list[str] | None = None) -> dict:
    """
    一键自动组卷。

    spec: {"counts": {题型: 题量}, "difficulty_ratio": {1:x, 2:y, 3:z}}
    流程：展开槽位 → 从已审核题库确定性抽题 → 缺口调 AI 补题入库并加入作业。
    返回统计与知识点覆盖，供页面提示。AI 不可用时只保留规则抽到的题。
    """
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")

    slots = hstat.plan_paper_slots(spec)
    cur_subject = hw.subject or DEFAULT_SUBJECT
    pool = qs.list_questions(session, status="approved", subject=cur_subject)
    existing = question_ids_in_homework(session, homework_id)
    result = hstat.deterministic_pick(pool, slots, exclude_ids=existing)

    picked_ids = [q.id for q in result["picked"]]
    shortage = result["shortage"]
    ai_created = 0
    ai_failed = 0

    if shortage:
        try:
            new_questions = _ai_generate_for_shortage(session, shortage,
                                                      knowledge_points or [],
                                                      cur_subject)
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
                              subject: str | None = None) -> list:
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

    system_prompt = (Path(config.BASE_DIR) / "prompts" / "question_prompt.txt").read_text(
        encoding="utf-8")
    subject = subject or DEFAULT_SUBJECT
    user_text = (
        f"学科：{subject}\n"
        f"知识点范围：{kp_text}\n"
        f"请严格按下面的题型与难度数量命题（这是一份试卷的补缺部分）：\n"
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
