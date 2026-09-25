# -*- coding: utf-8 -*-
"""课程安排表服务。

课程表是教师本地维护的每周固定安排，不新增数据库表，运行时保存在
data/class_schedule.json。一条记录表示“某班、星期几、第几节、某学科”。
"""

from __future__ import annotations

import json
from typing import Iterable

import pandas as pd

import config
from utils.app_config import is_valid_subject

CLASS_SCHEDULE_PATH = config.DATA_DIR / "class_schedule.json"
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PERIOD_COUNT = 8
MAX_CLASS_NAME_LEN = 50
CN_WEEKDAYS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7,
    "天": 7,
}


def default_schedule() -> dict:
    return {"entries": []}


def _clean_class_name(class_name) -> str:
    text = str(class_name or "").strip()
    if not text:
        raise ValueError("班级名称不能为空。")
    if len(text) > MAX_CLASS_NAME_LEN:
        raise ValueError(f"班级名称不能超过 {MAX_CLASS_NAME_LEN} 个字。")
    return text


def _as_slot_int(value, label: str, minimum: int, maximum: int) -> int:
    """把节次/星期转成整数；小数和越界值直接拒绝。"""
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是 {minimum}–{maximum} 的整数。")
    try:
        number = int(value)
        if float(value) != number:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"{label}必须是 {minimum}–{maximum} 的整数。")
    if not minimum <= number <= maximum:
        raise ValueError(f"{label}必须是 {minimum}–{maximum} 的整数。")
    return number


def _clean_subject(subject) -> str:
    text = str(subject or "").strip()
    if not is_valid_subject(text):
        raise ValueError(f"学科不受支持：{text}")
    return text


def _normalize_entry(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("课程安排格式错误。")
    return {
        "class_name": _clean_class_name(raw.get("class_name")),
        "weekday": _as_slot_int(raw.get("weekday"), "星期", 1, 7),
        "period": _as_slot_int(raw.get("period"), "节次", 1, PERIOD_COUNT),
        "subject": _clean_subject(raw.get("subject")),
    }


def _normalize_entries(data) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ValueError("课程安排格式错误。")

    unique: dict[tuple[str, int, int], dict] = {}
    for raw in data["entries"]:
        entry = _normalize_entry(raw)
        unique[(entry["class_name"], entry["weekday"], entry["period"])] = entry
    return sorted(
        unique.values(),
        key=lambda x: (x["class_name"], x["weekday"], x["period"]))


def load_schedule() -> dict:
    """读取课程表；文件缺失自动创建，JSON 损坏时回退空名单且不覆盖。"""
    try:
        data = json.loads(CLASS_SCHEDULE_PATH.read_text(encoding="utf-8"))
        return {"entries": _normalize_entries(data)}
    except FileNotFoundError:
        save_entries([])
        return default_schedule()
    except (json.JSONDecodeError, OSError, TypeError, ValueError, AttributeError):
        return default_schedule()


def save_entries(entries: Iterable[dict]) -> None:
    """保存完整课程表。同一班级/星期/节次重复时，后面的记录覆盖前面的。"""
    normalized = _normalize_entries({"entries": list(entries)})
    CLASS_SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLASS_SCHEDULE_PATH.write_text(
        json.dumps({"entries": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def list_entries(class_name: str | None = None) -> list[dict]:
    """列出课程；传入班级时只返回该班课程。"""
    entries = load_schedule()["entries"]
    if class_name is None:
        return entries
    name = _clean_class_name(class_name)
    return [e for e in entries if e["class_name"] == name]


def upsert_entry(class_name, weekday: int, period: int, subject: str) -> None:
    """新增或覆盖某一格课程。"""
    entry = {
        "class_name": _clean_class_name(class_name),
        "weekday": _as_slot_int(weekday, "星期", 1, 7),
        "period": _as_slot_int(period, "节次", 1, PERIOD_COUNT),
        "subject": _clean_subject(subject),
    }
    entries = load_schedule()["entries"]
    key = (entry["class_name"], entry["weekday"], entry["period"])
    unique = {(e["class_name"], e["weekday"], e["period"]): e for e in entries}
    unique[key] = entry
    save_entries(unique.values())


def delete_entry(class_name, weekday: int, period: int) -> None:
    """删除某一格课程。"""
    name = _clean_class_name(class_name)
    wd = _as_slot_int(weekday, "星期", 1, 7)
    pd_no = _as_slot_int(period, "节次", 1, PERIOD_COUNT)
    entries = [
        e for e in load_schedule()["entries"]
        if not (e["class_name"] == name and e["weekday"] == wd
                and e["period"] == pd_no)]
    save_entries(entries)


def week_grid(class_name: str) -> list[dict]:
    """返回某班 8 行 × 7 列的周课表，空单元格为空字符串。"""
    name = _clean_class_name(class_name)
    course_map = {
        (e["weekday"], e["period"]): e["subject"]
        for e in list_entries(name)
    }
    rows = []
    for period in range(1, PERIOD_COUNT + 1):
        row = {"节次": f"第{period}节"}
        for weekday, label in enumerate(WEEKDAY_LABELS, start=1):
            row[label] = course_map.get((weekday, period), "")
        rows.append(row)
    return rows


def sync_week_grid(class_name: str, rows: list[dict]) -> dict:
    """
    用一个班级的完整周课表替换原有安排；空白格删除课程，其他班级不受影响。
    返回 {"saved": 保留课程数, "deleted": 删除课程数}。
    """
    name = _clean_class_name(class_name)
    desired: dict[tuple[int, int], str] = {}

    for index, row in enumerate(rows, start=1):
        period = index
        if period > PERIOD_COUNT:
            break
        if not isinstance(row, dict):
            raise ValueError("课程表格式错误。")
        for weekday, label in enumerate(WEEKDAY_LABELS, start=1):
            value = row.get(label, "")
            if pd.isna(value):
                continue
            text = str(value).strip()
            if not text:
                continue
            desired[(weekday, period)] = _clean_subject(text)

    old_entries = list_entries(name)
    old_keys = {(e["weekday"], e["period"]) for e in old_entries}
    deleted = len(old_keys - set(desired))
    other_entries = [e for e in load_schedule()["entries"] if e["class_name"] != name]
    new_entries = [
        {"class_name": name, "weekday": wd, "period": period, "subject": subject}
        for (wd, period), subject in desired.items()
    ]
    save_entries(other_entries + new_entries)
    return {"saved": len(new_entries), "deleted": deleted}


def schedule_template_dataframe() -> pd.DataFrame:
    """构造课程安排表 Excel 模板。"""
    return pd.DataFrame([{
        "星期": "周一",
        "节次": 1,
        "科目": "数学",
        "班级": "八年级1班",
    }], columns=["星期", "节次", "科目", "班级"])


def _is_blank(value) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip() == ""


def _parse_weekday(value) -> int:
    if _is_blank(value):
        raise ValueError("星期不能为空。")
    text = str(value).strip()
    if text.isdigit():
        return _as_slot_int(text, "星期", 1, 7)

    for prefix in ("星期", "礼拜", "周"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text in CN_WEEKDAYS:
        return CN_WEEKDAYS[text]
    if text.isdigit():
        return _as_slot_int(text, "星期", 1, 7)
    raise ValueError(f"无法识别星期：{value}")


def _parse_period(value) -> int:
    if _is_blank(value):
        raise ValueError("节次不能为空。")
    text = str(value).strip()
    if text.startswith("第"):
        text = text[1:]
    if text.endswith("节"):
        text = text[:-1]
    return _as_slot_int(text.strip(), "节次", 1, PERIOD_COUNT)


def parse_schedule_dataframe(df: pd.DataFrame, known_classes: list[str]) -> list[dict]:
    """解析课程表 Excel；班级必须已经存在，避免导入时悄悄创建未知班级。"""
    if not isinstance(df, pd.DataFrame):
        raise ValueError("课程表数据格式错误。")
    required = ["星期", "节次", "科目", "班级"]
    columns = {str(c).strip(): c for c in df.columns}
    missing = [c for c in required if c not in columns]
    if missing:
        raise ValueError("Excel 缺少列：" + "、".join(missing))

    known = {str(c).strip() for c in known_classes}
    result: dict[tuple[str, int, int], dict] = {}

    for line, (_, row) in enumerate(df.iterrows(), start=2):
        values = [row[columns[c]] for c in required]
        if all(_is_blank(v) for v in values):
            continue

        class_name = str(row[columns["班级"]]).strip()
        if class_name not in known:
            raise ValueError(f"第 {line} 行的班级不存在：{class_name}")
        weekday = _parse_weekday(row[columns["星期"]])
        period = _parse_period(row[columns["节次"]])
        subject = _clean_subject(row[columns["科目"]])
        key = (class_name, weekday, period)
        # Excel 后出现的同一时间格覆盖前面的行，符合“导入以本表为准”的口径。
        result[key] = {
            "class_name": class_name,
            "weekday": weekday,
            "period": period,
            "subject": subject,
        }

    return sorted(
        result.values(),
        key=lambda x: (x["class_name"], x["weekday"], x["period"]))


def import_schedule_entries(
        df: pd.DataFrame, known_classes: list[str]) -> dict:
    """把 Excel 中的课程合并进现有课程表，相同时间格以 Excel 为准。"""
    parsed = parse_schedule_dataframe(df, known_classes)
    existing = load_schedule()["entries"]
    unique = {
        (e["class_name"], e["weekday"], e["period"]): e for e in existing
    }
    for entry in parsed:
        unique[(entry["class_name"], entry["weekday"], entry["period"])] = entry
    save_entries(unique.values())
    return {"imported": len(parsed)}
