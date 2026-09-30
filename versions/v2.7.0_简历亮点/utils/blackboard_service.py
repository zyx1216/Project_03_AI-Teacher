# -*- coding: utf-8 -*-
"""板书设计生成服务（v2.1.0）。"""

from __future__ import annotations

import json
import textwrap

STYLES = {
    "structured": "结构化",
    "mindmap": "思维导图",
    "list": "清单式",
    # v2.7.0 新增四种风格
    "outline": "提纲式",
    "diagram": "图解式",
    "table": "表格式",
    "contrast": "对比式",
}

# 表格式/对比式风格需要两列表格结构
TABULAR_STYLES = ("table", "contrast")


def normalize_blackboard_design(raw, style="structured") -> dict:
    """把 LLM 返回的板书 JSON 归一化。"""
    if not isinstance(raw, dict):
        raise ValueError("板书结果格式不正确。")
    title = str(raw.get("title", "")).strip()
    sections = raw.get("sections") or []
    if isinstance(sections, dict):
        sections = [{"title": k, "items": v} for k, v in sections.items()]
    clean_sections = []
    for section in sections:
        if isinstance(section, str):
            section = {"title": "", "items": [section]}
        if not isinstance(section, dict):
            continue
        items = section.get("items") or section.get("content") or []
        if isinstance(items, str):
            items = [items]
        clean_sections.append({
            "title": str(section.get("title", "")).strip(),
            "items": [str(item).strip() for item in items
                      if str(item).strip()],
        })
    summary = str(raw.get("summary", "")).strip()
    if not title or not clean_sections:
        raise ValueError("板书缺少标题或分区内容。")
    return {"style": style, "title": title,
            "sections": clean_sections, "summary": summary}


def generate_blackboard_design(plan, style="structured",
                               chat_func=None) -> dict:
    """根据教案生成板书；AI 不可用时用确定性内容兜底。"""
    system = (
        "你是数学教师板书设计助手。只输出 JSON："
        "{\"title\":\"课题\",\"sections\":[{\"title\":\"分区\","
        "\"items\":[\"要点\"]}],\"summary\":\"课堂小结\"}。"
        "不要输出 JSON 以外的内容。")
    user = (
        f"板书风格：{STYLES.get(style, style)}\n教案内容："
        f"{json.dumps(plan, ensure_ascii=False)}")
    try:
        if chat_func is None:
            from utils import llm_client
            chat_func = llm_client.chat_content
        match = json.loads(str(chat_func(system, user, 0.2)))
        return normalize_blackboard_design(match, style)
    except Exception:
        return _fallback_design(plan, style)


def _fallback_design(plan: dict, style: str) -> dict:
    """无 AI 时直接从教案字段拼板书。"""
    title = str(plan.get("subject", "")) + " " + str(plan.get("title", ""))
    sections = []
    objectives = plan.get("objectives", {})
    if isinstance(objectives, dict):
        objective_text = "；".join(str(v) for v in objectives.values() if v)
    else:
        objective_text = str(objectives)
    if objective_text:
        sections.append({"title": "学习目标", "items": [objective_text]})

    process = plan.get("process") or []
    key_items = []
    if isinstance(process, list):
        for item in process:
            if isinstance(item, dict) and item.get("content"):
                key_items.append(f"{item.get('stage', '')}：{item['content']}")
    if key_items:
        sections.append({"title": "知识框架", "items": key_items[:5]})
    if plan.get("difficult_points"):
        sections.append({"title": "重难点",
                         "items": [str(plan["difficult_points"])]})
    if not sections and plan.get("board_design"):
        sections.append({"title": "板书",
                         "items": [str(plan["board_design"])]})
    sections = sections or [{"title": "要点", "items": ["待补充"]}]
    if style in TABULAR_STYLES:
        # 表格式/对比式：把要点整理成「两列对照」结构
        left, right = [], []
        for sec in sections:
            items = sec.get("items") or []
            if not items:
                continue
            left.append(f"{sec.get('title', '')}：{items[0]}")
            if len(items) > 1:
                right.append(f"{items[1]}")
        rows = list(zip(left, right)) or [(x, "") for x in left]
        return {
            "style": style,
            "title": title.strip() or "课堂板书",
            "columns": ["要点", "对应/对比"],
            "rows": [list(r) for r in rows],
            "sections": sections,
            "summary": str(plan.get("summary", "")) or "对照理解，抓住差异。",
        }
    if style == "outline":
        # 提纲式：一级标题 + 多层要点
        outline = []
        for i, sec in enumerate(sections, start=1):
            outline.append(f"{i}. {sec.get('title', '')}")
            for item in (sec.get("items") or [])[:5]:
                outline.append(f"   - {item}")
        return {"style": "outline", "title": title.strip() or "课堂板书",
                "outline": outline, "sections": sections,
                "summary": str(plan.get("summary", "")) or "按提纲层层展开。"}
    if style == "diagram":
        # 图解式：中心 + 分支
        center = title.strip() or "课堂板书"
        branches = [{"label": sec.get("title", ""),
                     "items": (sec.get("items") or [])[:3]} for sec in sections]
        return {"style": "diagram", "title": center, "center": center,
                "branches": branches, "sections": sections,
                "summary": str(plan.get("summary", "")) or "用结构图梳理关系。"}
    return {
        "style": style,
        "title": title.strip() or "课堂板书",
        "sections": sections,
        "summary": str(plan.get("summary", "")) or "结合课堂练习巩固。",
    }


def render_blackboard_text(design) -> str:
    """把板书转成可编辑纯文本。"""
    lines = [f"# {design.get('title', '')}"]
    for section in design.get("sections", []):
        lines.append(f"\n## {section.get('title', '')}")
        for index, item in enumerate(section.get("items", []), start=1):
            lines.append(f"{index}. {item}")
    if design.get("summary"):
        lines.append(f"\n课堂小结：{design['summary']}")
    return "\n".join(lines)


def export_blackboard_png(design) -> bytes:
    """用 Pillow 导出板书 PNG。"""
    from PIL import Image, ImageDraw, ImageFont

    width = 1600
    font_path = r"C:\Windows\Fonts\msyh.ttc"
    title_font = ImageFont.truetype(font_path, 46)
    section_font = ImageFont.truetype(font_path, 34)
    text_font = ImageFont.truetype(font_path, 28)
    dummy = Image.new("RGB", (width, 100), "white")
    draw = ImageDraw.Draw(dummy)

    blocks = [("title", design.get("title", ""))]
    for section in design.get("sections", []):
        blocks.append(("section", section.get("title", "")))
        for item in section.get("items", []):
            blocks.append(("text", item))
    if design.get("summary"):
        blocks.append(("section", "课堂小结"))
        blocks.append(("text", design["summary"]))

    wrapped = []
    for kind, text in blocks:
        font = {"title": title_font, "section": section_font}.get(
            kind, text_font)
        line_width = 34 if kind == "title" else (42 if kind == "section" else 48)
        chunks = textwrap.wrap(str(text), width=line_width) or [""]
        for chunk in chunks:
            wrapped.append((kind, chunk, font))

    height = 80 + len(wrapped) * 58 + 80
    image = Image.new("RGB", (width, height), "#FFFDF5")
    draw = ImageDraw.Draw(image)
    y = 55
    colors = {"title": "#1F4E79", "section": "#2E75B6", "text": "#222222"}
    for kind, text, font in wrapped:
        if kind == "text":
            draw.text((95, y), "•", fill="#555555", font=font)
            draw.text((135, y), text, fill=colors[kind], font=font)
        else:
            draw.text((70, y), text, fill=colors[kind], font=font)
        y += 58
    draw.rectangle((50, 35, width - 50, height - 35),
                   outline="#BFBFBF", width=3)
    buffer = __import__("io").BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
