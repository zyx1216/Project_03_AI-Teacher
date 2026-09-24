# -*- coding: utf-8 -*-
"""v1.5.6 AgGrid 月历服务层测试。"""
from datetime import date

from utils import calendar_service as cs


def test_month_aggrid_rows_padding_and_iso_dates():
    rows = cs.month_aggrid_rows(2026, 9, {}, today=date(2026, 9, 21))

    assert len(rows) == 5
    assert rows[0]["mon"] == ""
    assert rows[0]["date_mon"] == ""
    assert rows[0]["tue"] == "1"
    assert rows[0]["date_tue"] == "2026-09-01"

    last = rows[-1]
    assert last["wed"] == "30"
    assert last["date_wed"] == "2026-09-30"
    for field in ("thu", "fri", "sat", "sun"):
        assert last[field] == ""
        assert last[f"date_{field}"] == ""


def test_month_aggrid_rows_event_text_and_today_mark():
    events = {
        date(2026, 9, 10): [
            {"kind": "exam", "icon": "📊", "id": 1, "title": "第一次月考"},
            {"kind": "homework", "icon": "📝", "id": 2, "title": "课后作业一"},
        ],
        date(2026, 9, 12): [
            {"kind": "lesson", "icon": "📚", "id": 3,
             "title": "这是一个很长的备课标题用来测试截断"},
        ],
    }
    rows = cs.month_aggrid_rows(2026, 9, events, today=date(2026, 9, 21))

    busy = rows[1]
    assert busy["thu"] == "10\n📊第一次月考\n📝课后作业一"
    assert busy["date_thu"] == "2026-09-10"
    assert busy["sat"] == "12\n📚这是一个很长的备…"
    assert rows[3]["mon"] == "🔵 21"
    assert rows[3]["date_mon"] == "2026-09-21"


def test_build_month_grid_options():
    options = cs.build_month_grid_options(date(2026, 9, 21))
    fields = [column["field"] for column in options["columnDefs"]]

    assert fields == [
        "mon", "tue", "wed", "thu", "fri", "sat", "sun", "clicked_date"
    ]
    visible = options["columnDefs"][:7]
    assert all(not column.get("hide", False) for column in visible)
    assert options["columnDefs"][-1]["hide"] is True
    assert options["rowSelection"] == "single"
    assert options["suppressRowClickSelection"] is True

    click_js = options["onCellClicked"].js_code
    style_js = options["defaultColDef"]["cellStyle"].js_code
    js = click_js + style_js
    for token in ("date_", "clicked_date", "setDataValue", "setSelected",
                  "2026-09-21", "pre-wrap", "#dbeafe"):
        assert token in js
    assert "innerHTML" not in js


def test_clicked_date_from_rows():
    start = date(2026, 9, 1)
    end = date(2026, 9, 30)

    assert cs.clicked_date_from_rows(
        [{"clicked_date": "2026-09-21"}], start, end
    ) == date(2026, 9, 21)
    assert cs.clicked_date_from_rows(
        [{"clicked_date": ""}], start, end
    ) is None
    assert cs.clicked_date_from_rows(
        [{"clicked_date": "not-a-date"}], start, end
    ) is None
    assert cs.clicked_date_from_rows(
        [{"clicked_date": "2026-10-01"}], start, end
    ) is None
