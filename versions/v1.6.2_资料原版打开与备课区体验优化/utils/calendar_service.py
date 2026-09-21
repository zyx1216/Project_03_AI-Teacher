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
from datetime import date, datetime, timedelta

from st_aggrid import JsCode

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


def _month_cell_text(day: date | None, events: dict, today: date) -> str:
    """生成 AgGrid 日期格中的纯文本。"""
    if day is None:
        return ""
    prefix = "🔵 " if day == today else ""
    parts = [f"{prefix}{day.day}"]
    for item in events.get(day, []):
        parts.append(f"{item['icon']}{_truncate_title(item['title'])}")
    return "\n".join(parts)


def month_aggrid_rows(
    year: int,
    month: int,
    events: dict,
    today: date | None = None,
) -> list[dict]:
    """把月历网格转换成 AgGrid 行数据。"""
    today = today or date.today()
    rows: list[dict] = []
    for week in month_weeks(year, month):
        row: dict[str, str] = {"clicked_date": ""}
        for field, day in zip(DISPLAY_FIELDS, week):
            row[field] = _month_cell_text(day, events, today)
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
