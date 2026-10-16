# -*- coding: utf-8 -*-
"""版本历史服务（v3.4.0）。

作业/试卷的保存快照落 version_history 表：每次显式保存追加一版，
只保留最近 N 版（N 从 data/version_settings.json 读，默认 10）。
教案历史继续用 lesson_plan_versions（utils/lesson_service.py），上限同样读这里。
"""
from __future__ import annotations

import json

import config
from models.models import Homework, HomeworkQuestion, Question, VersionHistory

VERSION_SETTINGS_PATH = config.DATA_DIR / "version_settings.json"
DEFAULT_VERSION_LIMIT = 10
ITEM_TYPE_LABELS = {"homework": "作业/试卷", "lesson": "教案"}


def load_settings() -> dict:
    """读版本设置；文件缺失或损坏回退默认，且不覆盖原文件。"""
    try:
        if VERSION_SETTINGS_PATH.exists():
            data = json.loads(VERSION_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                limit = int(data.get("version_limit") or DEFAULT_VERSION_LIMIT)
                return {"version_limit": max(1, min(50, limit))}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    return {"version_limit": DEFAULT_VERSION_LIMIT}


def get_version_limit() -> int:
    """当前保留版本数（默认 10）。"""
    return int(load_settings()["version_limit"])


def set_version_limit(limit: int) -> int:
    """保存保留版本数（限 1-50）。"""
    value = max(1, min(50, int(limit)))
    VERSION_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERSION_SETTINGS_PATH.write_text(
        json.dumps({"version_limit": value}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return value


def homework_snapshot(session, homework_id: int) -> dict:
    """把作业/试卷拍成快照：头部字段 + 题目顺序与分值。"""
    hw = session.get(Homework, int(homework_id))
    if hw is None:
        raise ValueError("作业不存在。")
    links = (session.query(HomeworkQuestion)
             .filter(HomeworkQuestion.homework_id == hw.id)
             .order_by(HomeworkQuestion.order, HomeworkQuestion.id).all())
    items = []
    for link in links:
        question = session.get(Question, link.question_id)
        items.append({
            "question_id": link.question_id,
            "order": int(link.order or 0),
            "score": link.score,
            "content": (question.content if question else "")[:200],
        })
    return {
        "id": hw.id, "name": hw.name, "homework_type": hw.homework_type,
        "class_name": hw.class_name, "subject": hw.subject, "grade": hw.grade,
        "total_score": hw.total_score, "duration": hw.duration,
        "remark": hw.remark, "questions": items,
    }


def snapshot(session, item_type: str, item_id: int, content: dict,
             change_summary: str = "") -> int:
    """追加一版并只保留最近 N 版，返回新版本行 id。"""
    item_type = str(item_type)
    item_id = int(item_id)
    last = (session.query(VersionHistory)
            .filter(VersionHistory.item_type == item_type,
                    VersionHistory.item_id == item_id)
            .order_by(VersionHistory.version.desc()).first())
    version = int(last.version) + 1 if last is not None else 1
    row = VersionHistory(
        item_type=item_type, item_id=item_id, version=version,
        content_json=json.dumps(content, ensure_ascii=False, default=str),
        change_summary=str(change_summary or "")[:200])
    session.add(row)
    session.flush()
    _prune(session, item_type, item_id)
    return row.id


def snapshot_homework(session, homework_id: int, change_summary: str = "") -> int:
    """给作业/试卷拍一版快照（头部 + 题目）。"""
    content = homework_snapshot(session, homework_id)
    if not change_summary:
        change_summary = (f"题目 {len(content['questions'])} 道，"
                          f"总分 {content.get('total_score') or '—'}")
    return snapshot(session, "homework", int(homework_id), content,
                    change_summary)


def _prune(session, item_type: str, item_id: int) -> None:
    """只保留最近 N 版。"""
    rows = (session.query(VersionHistory)
            .filter(VersionHistory.item_type == item_type,
                    VersionHistory.item_id == int(item_id))
            .order_by(VersionHistory.version.desc()).all())
    for old in rows[get_version_limit():]:
        session.delete(old)
    session.flush()


def list_versions(session, item_type: str, item_id: int) -> list[VersionHistory]:
    """按版本号倒序列出。"""
    return (session.query(VersionHistory)
            .filter(VersionHistory.item_type == str(item_type),
                    VersionHistory.item_id == int(item_id))
            .order_by(VersionHistory.version.desc()).all())


def get_version(session, version_id: int) -> VersionHistory | None:
    return session.get(VersionHistory, int(version_id))


def _flat(content: dict) -> dict:
    """把作业/试卷快照摊平成“字段 -> 文本”，题目按序号展开。"""
    fields = {
        "名称": content.get("name", ""),
        "类型": content.get("homework_type", ""),
        "班级": content.get("class_name", ""),
        "学科": content.get("subject", ""),
        "年级": content.get("grade", ""),
        "总分": str(content.get("total_score") or ""),
        "建议用时": str(content.get("duration") or ""),
        "说明": content.get("remark", ""),
    }
    for index, item in enumerate(content.get("questions") or [], start=1):
        fields[f"第{index}题"] = (
            f"题目ID {item.get('question_id')}｜分值 {item.get('score')}｜"
            f"{(item.get('content') or '').strip()}")
    return fields


def compare_versions(session, version_id1: int, version_id2: int) -> str:
    """对比两版，返回中文差异文本（逐字段 + 逐题列出增删改）。"""
    v1 = session.get(VersionHistory, int(version_id1))
    v2 = session.get(VersionHistory, int(version_id2))
    if v1 is None or v2 is None:
        raise ValueError("历史版本不存在。")
    try:
        c1 = json.loads(v1.content_json or "{}")
        c2 = json.loads(v2.content_json or "{}")
    except (TypeError, ValueError):
        raise ValueError("版本内容不是合法 JSON。")
    f1, f2 = _flat(c1), _flat(c2)
    lines = []
    for key in list(dict.fromkeys(list(f1.keys()) + list(f2.keys()))):
        a, b = str(f1.get(key, "")).strip(), str(f2.get(key, "")).strip()
        if a == b:
            continue
        if not a:
            lines.append(f"【新增】{key}")
        elif not b:
            lines.append(f"【删除】{key}")
        else:
            lines.append(f"【修改】{key}\n  旧：{a}\n  新：{b}")
    if not lines:
        return "两版内容一致，无差异。"
    head = f"版本 {v1.version} → 版本 {v2.version}：共 {len(lines)} 处差异"
    return head + "\n" + "\n".join(lines)


def rollback_version(session, version_id: int) -> dict:
    """把历史版本写回作业/试卷；回滚前先给当前内容打一版。"""
    version = session.get(VersionHistory, int(version_id))
    if version is None:
        raise ValueError("历史版本不存在。")
    if version.item_type != "homework":
        raise ValueError("该版本不是作业/试卷版本。")
    hw = session.get(Homework, int(version.item_id))
    if hw is None:
        raise ValueError("原作业已被删除，无法回滚。")
    # 回滚前先备份当前内容，保证可再回退。
    snapshot_homework(session, hw.id, "回滚前自动备份")
    content = json.loads(version.content_json or "{}")
    for field in ("name", "homework_type", "class_name", "subject", "grade",
                  "total_score", "duration", "remark"):
        if field in content:
            setattr(hw, field, content[field])
    # 逐条删除并 flush：批量 delete 会在 identity map 里留下旧行，
    # 紧接着写回同主键的关联会触发 SAWarning，这里改走逐条删除。
    for link in (session.query(HomeworkQuestion)
                 .filter(HomeworkQuestion.homework_id == hw.id).all()):
        session.delete(link)
    session.flush()
    for item in content.get("questions") or []:
        session.add(HomeworkQuestion(
            homework_id=hw.id, question_id=int(item["question_id"]),
            order=int(item.get("order") or 0), score=item.get("score")))
    session.flush()
    return {"homework_id": hw.id, "restored_version": int(version.version)}
