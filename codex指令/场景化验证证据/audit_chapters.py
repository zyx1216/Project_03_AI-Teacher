# -*- coding: utf-8 -*-
"""审计脚本2：章节提取 / 目录识别 / 页码偏移（只读产品逻辑）。"""
from __future__ import annotations
import io
import sys
from pathlib import Path

ROOT = Path(r"D:\Codex\Project_03_AI数学教师工作台")
sys.path.insert(0, str(ROOT))

import pymupdf
from utils import material_service as ms


def dump(title, chapters):
    print("=" * 70)
    print("### " + title)
    print(f"-- 切出 {len(chapters)} 章")
    for c in chapters:
        head = (c.get("content") or "").strip().splitlines()
        preview = head[0][:40] if head else "(空内容)"
        print(f"   [{c['title']}] 内容长度={len((c.get('content') or ''))} 首行={preview!r}")


print("#" * 70)
print("# A. split_chapters")
print("#" * 70)

TEXTBOOK = """第一章 有理数
1.1 正数和负数
生活中有许多相反意义的量，比如零上5℃和零下5℃。
1.2 有理数的加减法
同号两数相加，取相同的符号。
第二章 整式的加减
2.1 单项式
表示数或字母的积的式子叫做单项式。
"""
dump("A1 标准课本正文（第X章 + 1.1 编号）", ms.split_chapters(TEXTBOOK))

WITH_TOC = """目录
第一章 有理数 …………………… 1
第二章 整式的加减 ……………… 15
第一章 有理数
1.1 正数和负数
零上5℃和零下5℃是相反意义的量。
"""
dump("A2 正文里带目录页（目录条目是否被当成章节）", ms.split_chapters(WITH_TOC))

FALSE_POSITIVE = """第一单元的内容比较抽象，同学们要认真体会。
第二课时我们要学习新的知识点。
第一章 有理数
本章我们学习有理数的概念。
"""
dump("A3 正文中的疑似标题句（句末标点/超长）", ms.split_chapters(FALSE_POSITIVE))

STANDALONE_UNIT = """第一单元
小数乘法
小数乘法与整数乘法意义相同。
第二单元
位置
用数对表示位置。
"""
dump("A4 单独成行的“第X单元”+下一行标题（合并逻辑）", ms.split_chapters(STANDALONE_UNIT))

NO_HEADING = """这是一篇没有章节标题的短资料，只有一段说明文字。
第二句话仍然是正文。
"""
dump("A5 无任何章节标题（应回退“全文”）", ms.split_chapters(NO_HEADING))

REVIEW = """第一章 有理数
本章小结
本章我们学习了有理数的概念。
整理与复习
请完成下列练习。
第二章 整式的加减
单项式的概念。
"""
dump("A6 章内“本章小结/整理与复习”小节", ms.split_chapters(REVIEW))

print()
print("#" * 70)
print("# B. 目录识别（extract_toc_by_regex）")
print("#" * 70)
TOC_TEXT = """目录
第一章 有理数 …………………………… 1
1.1 正数和负数 …………………………… 2
第二章 整式的加减 ……………………… 15
2.1 单项式 ………………………………… 16
"""
toc = ms.extract_toc_by_regex(TOC_TEXT)
print("-- 识别到的目录条目:", len(toc))
for item in toc:
    print("   ", item)

TOC_NO_FIRST = """目录
数与代数 …………………………… 3
第一章 有理数 …………………………… 5
第二章 整式的加减 ……………………… 20
"""
print("-- 缺首个章节页码的补全样本:", ms.extract_toc_by_regex(TOC_NO_FIRST))

print()
print("#" * 70)
print("# C. _looks_like_toc_page / pdf_bookmarks / detect_page_offset")
print("#" * 70)
print("_looks_like_toc_page(目录文本) =", ms._looks_like_toc_page(TOC_TEXT))
print("_looks_like_toc_page(正文文本) =", ms._looks_like_toc_page("这是一段普通正文，没有页码。"))


def build_pdf(pages, toc=None):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=14, fontname="china-s")
    if toc:
        doc.set_toc(toc)
    data = doc.tobytes()
    doc.close()
    return data


# 前置页 2 页（封面 + 目录），正文从第 3 页开始，印刷页码从 1 开始 → 期望 offset=2
pdf_bytes = build_pdf([
    "封面：高一数学必修一",
    "目录 第一章 有理数 1 第二章 整式的加减 15",
    "第一章 有理数 本章学习有理数的概念",
    "第二章 整式的加减 单项式与多项式",
])
print("-- detect_page_offset（期望 2）:", ms.detect_page_offset(
    pdf_bytes, [{"title": "第一章 有理数", "page": 1}]))
print("-- pdf_bookmarks（无书签 PDF）:", ms.pdf_bookmarks(pdf_bytes))

pdf_with_bookmark = build_pdf(
    ["封面", "第一章 有理数", "第二章 整式的加减"],
    toc=[[1, "第一章 有理数", 2], [1, "第二章 整式的加减", 3]])
print("-- pdf_bookmarks（带书签 PDF）:", ms.pdf_bookmarks(pdf_with_bookmark))

print("-- apply_page_offset 裁剪:")
chapters = [{"title": "第一章", "page": 1}, {"title": "第二章", "page": 15}]
print("   ", ms.apply_page_offset(chapters, 2, 4))