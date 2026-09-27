# -*- coding: utf-8 -*-
"""功能说明 PDF 生成脚本测试（纯文档产物，不联网、不碰业务数据）。"""

import re
from pathlib import Path

import pytest

import fitz

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_feature_pdf as g  # noqa: E402


def test_fonts_available_or_skip():
    """系统没有微软雅黑时跳过（CI/非 Windows 环境），本机正常会跑。"""
    if not (g.FONT_REGULAR.exists() and g.FONT_BOLD.exists()):
        pytest.skip("缺少微软雅黑字体，无法生成中文 PDF")


def test_build_feature_pdf(tmp_path):
    out = tmp_path / "功能说明.pdf"
    returned = g.build_feature_pdf(out)

    # 返回路径且文件真实存在、体积受控（字体子集化后应远小于 800KB）
    assert Path(returned) == out
    assert out.exists()
    assert out.stat().st_size > 10 * 1024
    assert out.stat().st_size < 800 * 1024

    doc = fitz.open(str(out))
    assert 5 <= doc.page_count <= 12

    # 提取全文，去掉所有空白（含 PyMuPDF 在中英/粗体间插的不间断空格）再匹配
    full = "".join(page.get_text() for page in doc)
    compact = re.sub(r"\s+", "", full)
    for keyword in ("功能说明", "版本总览", "v0.1", "v0.2", "v0.3", "v0.4", "v1.0",
                    "项目骨架", "学情", "备课", "作业", "正式版",
                    "教学反思", "期末评语", "错题本", "自动组卷",
                    "streamlitrunapp.py", "9张", "13张"):
        assert keyword in compact, f"PDF 缺少关键内容：{keyword}"

    # 不能出现乱码替换符
    assert "\ufffd" not in full

    # 字体应已子集化嵌入（名字带 ABCDEE+ 前缀），且是雅黑
    fonts = {f[3] for page_no in range(doc.page_count)
             for f in doc.get_page_fonts(page_no)}
    assert fonts, "PDF 没有嵌入字体"
    assert any("YaHei" in name for name in fonts)
    assert all("+" in name for name in fonts), f"字体未子集化：{fonts}"
    doc.close()


def test_overview_table_fixed_layout(tmp_path):
    """总览表固定列宽：窄列不竖排，核心交付列最宽，五行数据不跨页。"""
    out = tmp_path / "总览列宽.pdf"
    g.build_feature_pdf(out)
    doc = fitz.open(str(out))

    overview_pages = [
        (page_index, page)
        for page_index, page in enumerate(doc)
        if page.search_for("一、版本总览")
    ]
    assert len(overview_pages) == 1
    page_index, page = overview_pages[0]
    assert page_index == 1  # 封面第 1 页，总览从第 2 页开始

    vertical_x = set()
    horizontal_y = set()
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.x - p2.x) < 0.8 and 85 < p1.y < 290:
                vertical_x.add(round(p1.x, 1))
            if abs(p1.y - p2.y) < 0.8 and 55 < p1.x < 540 and 85 < p1.y < 290:
                horizontal_y.add(round(p1.y, 1))

    expected_x = [60.5, 102.5, 178.5, 290.5, 492.5, 534.5]
    assert len(vertical_x) == len(expected_x)
    for expected, actual in zip(expected_x, sorted(vertical_x)):
        assert abs(expected - actual) < 1.0

    expected_y = [91.3, 117.3, 151.3, 185.3, 219.3, 253.3, 287.3]
    for expected in expected_y:
        assert any(abs(expected - actual) < 1.0 for actual in horizontal_y)

    # 表头应横排在第一行；起始 x 分别落在五个目标列内。
    header_x = {
        "版本": 72.5,
        "日期": 131.5,
        "阶段": 184.5,
        "核心交付": 296.5,
        "数据表": 500.0,
    }
    for label, expected in header_x.items():
        rects = [r for r in page.search_for(label) if 90 < r.y0 < 117]
        assert len(rects) == 1, f"总览表头找不到或重复：{label}"
        assert abs(rects[0].x0 - expected) < 2.0

    # 五个版本号都在同一页的数据区，且各自落在第一列。
    version_ys = []
    for version in ("v0.1", "v0.2", "v0.3", "v0.4", "v1.0"):
        rects = [
            r for r in page.search_for(version)
            if 117 < r.y0 < 287 and 60.5 < r.x0 < 102.5
        ]
        assert len(rects) == 1, f"总览数据行缺少 {version}"
        version_ys.append(rects[0].y0)
    assert version_ys == sorted(version_ys)

    # 最后一行的版本号和“13 张”仍在同一张表内，防止表格跨页。
    last_version = [
        r for r in page.search_for("v1.0")
        if 253 < r.y0 < 287 and 60.5 < r.x0 < 102.5
    ]
    last_tables = [
        r for r in page.search_for("13 张")
        if 253 < r.y0 < 287 and 492.5 < r.x0 < 534.5
    ]
    assert len(last_version) == 1
    assert len(last_tables) == 1

    full_text = "".join(p.get_text() for p in doc)
    assert g.OVERVIEW_MARKER not in full_text
    assert "\ufffd" not in full_text
    doc.close()


def test_versions_data_complete():
    """结构化版本数据覆盖 5 个版本且每版都有功能要点。"""
    ids = [v["id"] for v in g.VERSIONS]
    assert ids == ["v0.1", "v0.2", "v0.3", "v0.4", "v1.0"]
    for v in g.VERSIONS:
        assert v["stage"] and v["when"] and v["core"]
        items = [item for _, group in v["groups"] for item in group]
        assert 4 <= len(items) <= 20