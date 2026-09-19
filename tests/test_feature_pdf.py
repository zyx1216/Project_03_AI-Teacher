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


def test_versions_data_complete():
    """结构化版本数据覆盖 5 个版本且每版都有功能要点。"""
    ids = [v["id"] for v in g.VERSIONS]
    assert ids == ["v0.1", "v0.2", "v0.3", "v0.4", "v1.0"]
    for v in g.VERSIONS:
        assert v["stage"] and v["when"] and v["core"]
        items = [item for _, group in v["groups"] for item in group]
        assert 4 <= len(items) <= 20