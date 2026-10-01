# -*- coding: utf-8 -*-
"""
作业统计纯逻辑层（不依赖 Streamlit、不碰数据库，方便单测）。

包含：
- 提交率、总分基础指标（复用 stats.describe）；
- 每题正确率、高频错题 TOP5、典型错题判定；
- 与上一份同班作业的进退步（复用 stats.score_deltas 的口径）；
- 知识点覆盖度检查；
- 自动组卷的确定性抽题算法（按题型配额 × 难度配比从已审核题不放回抽取）。

输入尽量用普通 list/dict，服务层负责从 ORM 组装数据。
"""

from __future__ import annotations

from utils import stats as stats_mod

# 典型错题：错误人数占比达到该阈值即视为全班共性错误
TYPICAL_WRONG_RATE = 0.4


def submission_rate(submitted_count: int, total_students: int) -> float | None:
    """提交率（0~1）；学生数为 0 返回 None。"""
    if not total_students:
        return None
    return round(submitted_count / total_students, 4)


def overall_scores(rows: list[dict]) -> dict:
    """
    作业总分概览。rows 形如 [{"name":..., "score":float|None}, ...]。
    缺考（score 为 None）计入应到、不计均分。
    """
    values = [r["score"] for r in rows if r.get("score") is not None]
    base = stats_mod.describe(values)
    base["submitted"] = len(values)
    base["total"] = len(rows)
    base["submission_rate"] = submission_rate(len(values), len(rows))
    return base


def question_correct_rate(answers: list[dict]) -> list[dict]:
    """
    每题正确率。answers 形如
    [{"question_id","order_no","is_correct":bool|None,"earned_score":float|None,
      "full_score":float|None}, ...]，按 question_id 聚合。
    返回按 order_no 排序的 [{question_id,order_no,judged,correct,wrong,
    rate,avg_rate,typical}]。
    """
    groups: dict[int, dict] = {}
    for a in answers:
        qid = a["question_id"]
        g = groups.setdefault(qid, {
            "question_id": qid, "order_no": a.get("order_no"),
            "judged": 0, "correct": 0, "wrong": 0,
            "score_sum": 0.0, "score_n": 0, "full_score": a.get("full_score"),
        })
        if g.get("order_no") is None and a.get("order_no") is not None:
            g["order_no"] = a["order_no"]
        if a.get("is_correct") is not None:
            g["judged"] += 1
            if a["is_correct"]:
                g["correct"] += 1
            else:
                g["wrong"] += 1
        if a.get("earned_score") is not None:
            g["score_sum"] += float(a["earned_score"])
            g["score_n"] += 1
            if g.get("full_score") is None:
                g["full_score"] = a.get("full_score")

    result = []
    for g in groups.values():
        rate = round(g["correct"] / g["judged"], 4) if g["judged"] else None
        avg_rate = None
        if g["score_n"] and g.get("full_score"):
            avg_rate = round(g["score_sum"] / g["score_n"] / g["full_score"], 4)
        wrong_rate = (g["wrong"] / g["judged"]) if g["judged"] else 0.0
        result.append({
            "question_id": g["question_id"],
            "order_no": g["order_no"],
            "judged": g["judged"],
            "correct": g["correct"],
            "wrong": g["wrong"],
            "rate": rate,
            "avg_rate": avg_rate,
            "typical": bool(g["judged"] and wrong_rate >= TYPICAL_WRONG_RATE),
        })
    result.sort(key=lambda x: (x["order_no"] is None, x["order_no"] or 0))
    return result


def top_wrong_questions(per_question: list[dict], top_k: int = 5) -> list[dict]:
    """高频错题：按错误人数降序（错误率并列时错误人数多的在前），取 Top-K。"""
    wrongs = [q for q in per_question if q["wrong"] > 0]
    wrongs.sort(key=lambda q: (q["typical"], q["wrong"],
                               (q["judged"] - (q["rate"] or 0) * q["judged"])),
                reverse=True)
    return wrongs[:top_k]


def homework_deltas(current_rows: list[dict], previous_rows: list[dict]) -> dict:
    """
    与上一份同班作业比进退步（按总分）。
    入参每行 {"student_id","name","score"}，缺考 None；返回 {student_id: 分差}，
    只保留两次都有分的学生。
    """
    cur = {r["student_id"]: r["score"] for r in current_rows
           if r.get("score") is not None}
    prev = {r["student_id"]: r["score"] for r in previous_rows
            if r.get("score") is not None}
    deltas = {}
    for sid, score in cur.items():
        if sid in prev and prev[sid] is not None:
            deltas[sid] = round(score - prev[sid], 2)
    return deltas


def knowledge_coverage(question_kps: list[tuple[int, list[str]]],
                       wanted: list[str]) -> dict:
    """
    知识点覆盖检查。
    question_kps: [(question_id, [知识点...]), ...]；wanted: 要求覆盖的知识点。
    返回 {"covered":[...], "missing":[...]}，按名称精确匹配（去空白）。
    """
    covered = set()
    for _qid, kps in question_kps:
        for kp in kps:
            covered.add((kp or "").strip())
    wanted_set = {(w or "").strip() for w in wanted if (w or "").strip()}
    return {
        "covered": sorted(wanted_set & covered),
        "missing": sorted(wanted_set - covered),
    }


# ---------------------------------------------------------------------------
# 自动组卷：确定性抽题
# ---------------------------------------------------------------------------

def plan_paper_slots(spec: dict) -> list[dict]:
    """
    把"各题型题量 + 难度配比"展开成逐题槽位。
    spec: {"counts": {question_type: 题量},
           "difficulty_ratio": {1: 基础%, 2: 中等%, 3: 拓展%}}（百分比和为100）
    返回 [{question_type, difficulty}, ...]，顺序按题型、难度分组。
    """
    ratio = spec.get("difficulty_ratio") or {1: 30, 2: 50, 3: 20}
    slots = []
    for qtype, count in spec.get("counts", {}).items():
        count = int(count or 0)
        if count <= 0:
            continue
        # 按比例切分，余数给中等难度，保证总数等于 count
        targets = {1: 0, 2: 0, 3: 0}
        raw = {d: count * ratio.get(d, 0) / 100.0 for d in (1, 2, 3)}
        for d in (1, 2, 3):
            targets[d] = int(raw[d])
        remainder = count - sum(targets.values())
        # 余数优先补给占比最大的难度，再依次补齐
        order = sorted((1, 2, 3), key=lambda d: ratio.get(d, 0), reverse=True)
        i = 0
        while remainder > 0:
            targets[order[i % 3]] += 1
            remainder -= 1
            i += 1
        for d in (1, 2, 3):
            slots.extend({"question_type": qtype, "difficulty": d}
                         for _ in range(targets[d]))
    return slots


def deterministic_pick(pool: list, slots: list[dict],
                       exclude_ids: set | None = None) -> dict:
    """
    从题库池里按槽位不放回抽题。

    pool: 题目对象或 dict 列表，每项至少含 id/question_type/difficulty。
    slots: plan_paper_slots 的输出。
    exclude_ids: 本次作业已选、不能再抽的题目 id。
    返回 {"picked":[题目...], "shortage":[未满足槽位...]}。
    抽不到精确难度时，先在同题型内找相邻难度，仍没有才算缺口。
    """
    exclude_ids = exclude_ids or set()

    def key(item):
        return (getattr(item, "question_type", None) or item["question_type"],
                int(getattr(item, "difficulty", None) or item["difficulty"]))

    def ident(item):
        return getattr(item, "id", None) or item["id"]

    # 按 (题型,难度) 建可用队列，id 升序保证"确定性"（同库多次结果一致）
    buckets: dict[tuple, list] = {}
    for item in sorted(pool, key=ident):
        if ident(item) in exclude_ids:
            continue
        buckets.setdefault(key(item), []).append(item)

    picked = []
    shortage = []
    used = set()
    for slot in slots:
        chosen = None
        # 1) 精确难度
        for cand in buckets.get((slot["question_type"], slot["difficulty"]), []):
            if ident(cand) not in used:
                chosen = cand
                break
        # 2) 同题型相邻难度兜底（差 1 优先，再差 2）
        if chosen is None:
            for distance in (1, 2):
                for d in (slot["difficulty"] - distance, slot["difficulty"] + distance):
                    if chosen is not None:
                        break
                    for cand in buckets.get((slot["question_type"], d), []):
                        if ident(cand) not in used and 1 <= d <= 3:
                            chosen = cand
                            break
        if chosen is None:
            shortage.append(slot)
        else:
            used.add(ident(chosen))
            picked.append(chosen)
    return {"picked": picked, "shortage": shortage}