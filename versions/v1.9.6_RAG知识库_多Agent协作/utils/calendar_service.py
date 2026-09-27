# -*- coding: utf-8 -*-
"""教学日历服务层。

- month_weeks：月历按周切分日期网格；
- collect_events：按日期合并考试 / 作业 / 教案；
- month_aggrid_rows / build_month_grid_options：AgGrid 月历数据与配置；
- week_preview_rows：首页本周日历预览。

约定：考试用 exam_date，作业和教案用 created_at；不新增日期字段。
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta

from st_aggrid import JsCode

import config
from models.models import Exam, Homework, LessonPlan

DISPLAY_FIELDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_HEADERS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def month_weeks(year: int, month: int) -> list[list[date | None]]:
    """返回某年某月按周切分的日期网格（周一开头）。"""
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    grid: list[list[date | None]] = []
    for week in weeks:
        row: list[date | None] = []
        for day in week:
            row.append(date(year, month, day) if day != 0 else None)
        grid.append(row)
    return grid


def week_range(day: date) -> tuple[date, date]:
    """返回 day 所在周的周一和周日。"""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


# ---------------------------------------------------------------------------
# v1.8.2：学期配置（data/semester.json）与周次计算
# ---------------------------------------------------------------------------

SEMESTER_PATH = config.DATA_DIR / "semester.json"


def default_semester(today: date | None = None) -> dict:
    """默认本年 9 月 1 日开学、次年 1 月 31 日放假。"""
    today = today or date.today()
    return {"start": date(today.year, 9, 1).isoformat(),
            "end": date(today.year + 1, 1, 31).isoformat()}


def _semester_dates(semester: dict):
    """把配置解析成 (开学日, 放假日)，非法时回退默认。"""
    fallback = default_semester()
    try:
        start = date.fromisoformat(semester["start"])
        end = date.fromisoformat(semester["end"])
    except (TypeError, KeyError, ValueError):
        return (date.fromisoformat(fallback["start"]),
                date.fromisoformat(fallback["end"]))
    if end < start:
        return (date.fromisoformat(fallback["start"]),
                date.fromisoformat(fallback["end"]))
    return start, end


def load_semester(path=None) -> dict:
    """读取学期配置；缺失自建，JSON 损坏回退默认但不覆盖原文件。"""
    path = path or SEMESTER_PATH
    if not path.exists():
        data = default_semester()
        save_semester(data, path)
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        start, end = _semester_dates(raw)
    except (json.JSONDecodeError, TypeError, OSError):
        return default_semester()
    return {"start": start.isoformat(), "end": end.isoformat()}


def save_semester(semester: dict, path=None) -> dict:
    """校验并保存学期配置，返回归一化后的配置。"""
    path = path or SEMESTER_PATH
    start, end = _semester_dates(semester)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"start": start.isoformat(), "end": end.isoformat()}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return data


def semester_first_monday(semester: dict) -> date:
    """开学日所在周的周一（第 1 周从这天对齐）。"""
    start, _ = _semester_dates(semester)
    return start - timedelta(days=start.weekday())


def get_week_of_semester(day: date, semester: dict) -> int:
    """某日期是学期第几周；早于开学返回 0。"""
    start, _ = _semester_dates(semester)
    if day < start:
        return 0
    first_monday = semester_first_monday(semester)
    return (day - first_monday).days // 7 + 1


def get_semester_weeks(semester: dict) -> list[list[date]]:
    """学期内各周，每周周一至周五；尾周按放假日期截断。"""
    start, end = _semester_dates(semester)
    first_monday = start - timedelta(days=start.weekday())
    weeks: list[list[date]] = []
    cursor = first_monday
    while cursor <= end:
        week = []
        for i in range(5):  # 周一至周五
            day = cursor + timedelta(days=i)
            if start <= day <= end:
                week.append(day)
        if week:
            weeks.append(week)
        cursor += timedelta(days=7)
    return weeks


def semester_week_no_map(semester: dict) -> dict[date, int]:
    """学期内日期 -> 周次（整周 7 天，便于月视图跨月标注）。"""
    start, end = _semester_dates(semester)
    first_monday = semester_first_monday(semester)
    result = {}
    cursor = first_monday
    week_no = 1
    while cursor <= end:
        for i in range(7):
            day = cursor + timedelta(days=i)
            if start <= day:
                result[day] = week_no
        cursor += timedelta(days=7)
        week_no += 1
    return result


def semester_progress(today: date, semester: dict) -> tuple[int, int, int]:
    """返回 (当前周次, 总周数, 已过百分比)。"""
    weeks = get_semester_weeks(semester)
    total = len(weeks)
    start, end = _semester_dates(semester)
    if today < start:
        current, percent = 0, 0
    elif today > end:
        current, percent = total, 100
    else:
        current = get_week_of_semester(today, semester)
        percent = round((today - start).days
                        / max(1, (end - start).days) * 100)
    return current, total, max(0, min(100, percent))


def _semester_cell_text(day: date, events: dict, week_no: int) -> str:
    """学期视图单元格：日 + 第X周 + 事项图标。"""
    parts = [f"{day.day}", f"第{week_no}周"]
    for item in events.get(day, []):
        parts.append(f"{item['icon']}{_truncate_title(item['title'], 6)}")
    return "\n".join(parts)


SEMESTER_FIELDS = ("s_mon", "s_tue", "s_wed", "s_thu", "s_fri")
SEMESTER_HEADERS = ("周一", "周二", "周三", "周四", "周五")


def semester_aggrid_rows(semester: dict, events: dict) -> list[dict]:
    """把学期各周转成 AgGrid 行数据。"""
    rows = []
    for week in get_semester_weeks(semester):
        week_no = get_week_of_semester(week[0], semester)
        row = {"clicked_date": "", "week_label": f"第{week_no}周"}
        for field, i in zip(SEMESTER_FIELDS, range(5)):
            day = week[i] if i < len(week) else None
            if day is not None:
                row[field] = _semester_cell_text(
                    day, events, get_week_of_semester(day, semester))
                row[f"date_{field}"] = day.isoformat()
            else:
                row[field] = ""
                row[f"date_{field}"] = ""
        rows.append(row)
    return rows


def build_semester_grid_options() -> dict:
    """学期视图 AgGrid 配置（点单元格写 clicked_date）。"""
    click_handler = JsCode(
        """
        function(params) {
          if (!params.colDef || params.colDef.field === 'clicked_date') return;
          if (params.colDef.field === 'week_label') return;
          var baseField = params.colDef.field.replace('s_', '');
          var dateField = 'date_s_' + baseField;
          var clickedDate = params.data ? params.data[dateField] : '';
          if (clickedDate) {
            params.node.setDataValue('clicked_date', clickedDate);
            params.node.setSelected(true);
          }
        }
        """
    )
    column_defs = [{"field": "week_label", "headerName": "周次",
                    "minWidth": 80, "editable": False}]
    column_defs += [
        {"field": field, "headerName": header, "editable": False,
         "minWidth": 150}
        for field, header in zip(SEMESTER_FIELDS, SEMESTER_HEADERS)
    ]
    column_defs.append({"field": "clicked_date", "hide": True})
    return {
        "columnDefs": column_defs,
        "defaultColDef": {"cellStyle": {"whiteSpace": "pre-wrap",
                                        "verticalAlign": "top"},
                          "resizable": True, "sortable": False,
                          "filter": False},
        "rowHeight": 95,
        "headerHeight": 36,
        "rowSelection": "single",
        "suppressRowClickSelection": True,
        "animateRows": False,
        "onCellClicked": click_handler,
    }


def clicked_semester_date(rows) -> date | None:
    """读取学期视图点击的日期。"""
    for row in rows or []:
        value = (row or {}).get("clicked_date")
        if value:
            try:
                return date.fromisoformat(value)
            except (TypeError, ValueError):
                continue
    return None


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _in_range(day: date | None, start: date, end: date) -> bool:
    return day is not None and start <= day <= end


def collect_events(session, start: date, end: date) -> dict[date, list[dict]]:
    """收集 [start, end] 内事项，按日期归并。"""
    result: dict[date, list[dict]] = {}

    def add(day: date | None, item: dict):
        if day and _in_range(day, start, end):
            result.setdefault(day, []).append(item)

    for exam in session.query(Exam).all():
        add(_as_date(exam.exam_date), {
            "kind": "exam", "icon": "📊", "id": exam.id,
            "title": exam.name})
    for hw in session.query(Homework).filter(Homework.is_template.is_(False)):
        add(_as_date(hw.created_at), {
            "kind": "homework", "icon": "📝", "id": hw.id,
            "title": hw.name})
    for plan in session.query(LessonPlan).all():
        add(_as_date(plan.created_at), {
            "kind": "lesson", "icon": "📚", "id": plan.id,
            "title": plan.title})

    order = {"exam": 0, "homework": 1, "lesson": 2}
    for day in result:
        result[day].sort(key=lambda e: (order[e["kind"]], e["title"]))
    return dict(sorted(result.items()))


def upcoming_exams(session, start: date, days: int = 7) -> list[dict]:
    """未来 days 天内（含 start）的考试，按日期升序。"""
    end = start + timedelta(days=days - 1)
    events = collect_events(session, start, end)
    exams = []
    for day, items in events.items():
        for item in items:
            if item["kind"] == "exam":
                exams.append({"date": day, **item})
    return sorted(exams, key=lambda e: (e["date"], e["title"]))


def _truncate_title(text: str, n: int = 8) -> str:
    return text if len(text) <= n else text[:n] + "…"


def _month_cell_text(day: date | None, events: dict, today: date,
                     week_no_map: dict | None = None) -> str:
    """生成 AgGrid 日期格中的纯文本；学期内日期追加“第X周”。"""
    if day is None:
        return ""
    if week_no_map and day in week_no_map:
        week_part = f"第{week_no_map[day]}周"
    else:
        week_part = None
    prefix = "🔵 " if day == today else ""
    parts = [f"{prefix}{day.day}"]
    if week_part:
        parts.append(week_part)
    for item in events.get(day, []):
        parts.append(f"{item['icon']}{_truncate_title(item['title'])}")
    return "\n".join(parts)


def month_aggrid_rows(
    year: int,
    month: int,
    events: dict,
    today: date | None = None,
    week_no_map: dict | None = None,
) -> list[dict]:
    """把月历网格转换成 AgGrid 行数据。"""
    today = today or date.today()
    rows: list[dict] = []
    for week in month_weeks(year, month):
        row: dict[str, str] = {"clicked_date": ""}
        for field, day in zip(DISPLAY_FIELDS, week):
            row[field] = _month_cell_text(day, events, today, week_no_map)
            row[f"date_{field}"] = day.isoformat() if day is not None else ""
        rows.append(row)
    return rows


def build_month_grid_options(today: date) -> dict:
    """返回教学日历 AgGrid 配置。"""
    today_iso = today.isoformat()
    click_handler = JsCode(
        """
        function(params) {
          if (!params.colDef || params.colDef.field === 'clicked_date') return;
          var dateField = 'date_' + params.colDef.field;
          var clickedDate = params.data ? params.data[dateField] : '';
          if (clickedDate) {
            params.node.setDataValue('clicked_date', clickedDate);
            params.node.setSelected(true);
          }
        }
        """
    )
    style_handler = JsCode(
        f"""
        function(params) {{
          var style = {{
            whiteSpace: 'pre-wrap',
            verticalAlign: 'top',
            lineHeight: '1.35'
          }};
          if (params.colDef && params.colDef.field !== 'clicked_date') {{
            var dateField = 'date_' + params.colDef.field;
            if (params.data && params.data[dateField] === '{today_iso}') {{
              style.backgroundColor = '#dbeafe';
            }}
          }}
          return style;
        }}
        """
    )
    column_defs = [
        {
            "field": field,
            "headerName": header,
            "editable": False,
            "minWidth": 145,
        }
        for field, header in zip(DISPLAY_FIELDS, WEEKDAY_HEADERS)
    ]
    column_defs.append({
        "field": "clicked_date",
        "headerName": "点击日期",
        "hide": True,
    })
    return {
        "columnDefs": column_defs,
        "defaultColDef": {
            "cellStyle": style_handler,
            "resizable": True,
            "sortable": False,
            "filter": False,
        },
        "rowHeight": 105,
        "headerHeight": 36,
        "rowSelection": "single",
        "suppressRowClickSelection": True,
        "animateRows": False,
        "onCellClicked": click_handler,
    }


def clicked_date_from_rows(rows, start: date, end: date) -> date | None:
    """从 AgGrid 回传行中读取当前查看范围内的点击日期。"""
    for row in rows or []:
        value = (row or {}).get("clicked_date")
        if not value:
            continue
        try:
            clicked = date.fromisoformat(value)
        except (TypeError, ValueError):
            continue
        if start <= clicked <= end:
            return clicked
    return None


def week_preview_rows(session, day: date) -> list[dict]:
    """返回本周 7 天的首页预览数据：考试、普通作业、教案。"""
    monday, sunday = week_range(day)
    events = collect_events(session, monday, sunday)
    labels = ["一", "二", "三", "四", "五", "六", "日"]
    rows = []
    for index, current in enumerate(
        [monday + timedelta(days=i) for i in range(7)], start=1
    ):
        items = events.get(current, [])

        def titles(kind):
            return "、".join(
                item["title"] for item in items if item["kind"] == kind
            )

        rows.append({
            "日期": ("🔵 " if current == day else "") +
                    current.strftime("%m月%d日"),
            "星期": "周" + labels[index - 1],
            "状态": "今天" if current == day else "",
            "考试": titles("exam"),
            "作业": titles("homework"),
            "教案": titles("lesson"),
        })
    return rows
