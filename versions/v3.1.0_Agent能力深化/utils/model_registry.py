# -*- coding: utf-8 -*-
"""常用 LLM 模型清单（v2.5.1）。

仅用于设置页下拉展示与状态提示，不改动 config.py 默认值。
status: stable / deprecated / offline / custom。
use_for: main（主模型）/ content（内容模型）/ both。
"""

from __future__ import annotations

CHAT_MODELS = [
    {
        "id": "Doubao-Seed-2.1-pro",
        "name": "Doubao-Seed-2.1-pro",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "中文内容生成强，适合教案/出题",
        "speed": "中等",
        "context": "128K",
        "use_for": "content",
    },
    {
        "id": "Doubao-Seed-2.1-lite",
        "name": "Doubao-Seed-2.1-lite",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "快速响应，适合分析总结",
        "speed": "快",
        "context": "128K",
        "use_for": "main",
    },
    {
        "id": "Doubao-Seed-2.0-pro",
        "name": "Doubao-Seed-2.0-pro",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "稳定通用",
        "speed": "中等",
        "context": "128K",
        "use_for": "both",
    },
    {
        "id": "Doubao-Seed-2.0-lite",
        "name": "Doubao-Seed-2.0-lite",
        "status": "deprecated",
        "status_label": "⚠️即将下线（10月9日）",
        "ability": "轻量快速",
        "speed": "快",
        "context": "128K",
        "use_for": "both",
    },
    {
        "id": "deepseek-chat",
        "name": "deepseek-chat",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "推理能力强",
        "speed": "中等",
        "context": "128K",
        "use_for": "both",
    },
    {
        "id": "deepseek-reasoner",
        "name": "deepseek-reasoner",
        "status": "stable",
        "status_label": "✅稳定",
        "ability": "深度推理，适合难题",
        "speed": "慢",
        "context": "128K",
        "use_for": "content",
    },
    {
        "id": "custom",
        "name": "自定义输入...",
        "status": "custom",
        "status_label": "",
        "ability": "",
        "speed": "",
        "context": "",
        "use_for": "both",
    },
]

EMBED_MODELS = [
    {"id": "Doubao-embedding-vision", "name": "Doubao-embedding-vision",
     "status": "stable", "status_label": "✅稳定"},
    {"id": "Doubao-embedding-text", "name": "Doubao-embedding-text",
     "status": "stable", "status_label": "✅稳定"},
    {"id": "text-embedding-3-small", "name": "text-embedding-3-small",
     "status": "stable", "status_label": "✅稳定"},
    {"id": "custom", "name": "自定义输入...", "status": "custom",
     "status_label": ""},
]

# 快速配置方案：preset -> {main, content}
PRESETS = {
    "均衡模式": {"main": "Doubao-Seed-2.1-lite", "content": "Doubao-Seed-2.1-pro"},
    "高质量模式": {"main": "Doubao-Seed-2.1-pro", "content": "Doubao-Seed-2.1-pro"},
    "低成本模式": {"main": "Doubao-Seed-2.1-lite", "content": "Doubao-Seed-2.1-lite"},
}

# 模型下线后的推荐替代
DEPRECATED_SUGGEST = {
    "Doubao-Seed-2.0-lite": "Doubao-Seed-2.1-lite",
    "Doubao-Seed-2.0-pro": "Doubao-Seed-2.1-pro",
}


def find_model(model_id: str, models=None) -> dict | None:
    """按 id 查模型条目。"""
    for item in (models if models is not None else CHAT_MODELS):
        if item["id"] == model_id:
            return item
    return None


def is_deprecated(model_id: str, models=None) -> bool:
    """模型是否已标记即将下线。"""
    item = find_model(model_id, models)
    return bool(item and item.get("status") == "deprecated")


def suggest_for(model_id: str) -> str | None:
    """返回下线模型的推荐替代 id。"""
    return DEPRECATED_SUGGEST.get(model_id)


def model_options(models=None) -> list[str]:
    """下拉用 id 列表（含 custom）。"""
    return [m["id"] for m in (models if models is not None else CHAT_MODELS)]
