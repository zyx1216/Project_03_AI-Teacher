# -*- coding: utf-8 -*-
"""v2.9.0 变式题服务。

对外统一提供五种变式：换数字、换情境、换问法、逆向思维、拓展提升。
生成阶段只返回内存中的候选题，教师预览勾选后再写入题库。
"""

from __future__ import annotations

import json
import uuid

from models.models import Question
from utils import llm_client
from utils import question_service as qs

VARIATION_TYPE_LABELS = {
    "number": "换数字",
    "context": "换情境",
    "wording": "换问法",
    "reverse": "逆向思维",
    "extension": "拓展提升",
}
_ALIASES = {
    "number": "number", "换数字": "number", "数字": "number", "数字变式": "number",
    "context": "context", "换情境": "context", "情境": "context", "情境变式": "context",
    "wording": "wording", "换问法": "wording", "问法": "wording",
    "reverse": "reverse", "逆向思维": "reverse", "逆向": "reverse",
    "extension": "extension", "拓展提升": "extension", "拓展": "extension", "难度变式": "extension", "难度": "extension",
}


def normalize_variation_type(value) -> str | None:
    """把界面值和模型返回值归一成五种内部类型。"""
    if value is None:
        return None
    key = str(value).strip().lower().replace(" ", "")
    return _ALIASES.get(key)


def _normalize_difficulty(value) -> str:
    text = str(value or "keep").strip().lower()
    mapping = {
        "keep": "keep", "保持": "keep", "保持原题": "keep",
        "lower": "lower", "简单一些": "lower", "简单": "lower",
        "higher": "higher", "难一些": "higher", "难": "higher",
        "mixed": "mixed", "混合": "mixed",
    }
    if text not in mapping:
        raise ValueError("难度只能是保持原题、简单一些、难一些或混合。")
    return mapping[text]


def _difficulty_offset(difficulty: str, index: int, parent_difficulty: int) -> int:
    if difficulty == "mixed":
        return (-1, 0, 1)[index % 3]
    return {"lower": -1, "keep": 0, "higher": 1}[difficulty]


def generate_variations(session, question_id, variation_types, count=5,
                        difficulty="keep") -> list[dict]:
    """调用 AI 生成变式候选，返回经过基础校验的题目字典列表。"""
    parent = session.get(Question, int(question_id))
    if parent is None:
        raise ValueError(f"原题不存在：id={question_id}")
    types = []
    for value in variation_types or []:
        key = normalize_variation_type(value)
        if key and key not in types:
            types.append(key)
    if not types:
        raise ValueError("请至少选择一种变式类型。")
    try:
        count = int(count)
    except (TypeError, ValueError) as exc:
        raise ValueError("生成数量必须是 3 到 10 道。") from exc
    if not 3 <= count <= 10:
        raise ValueError("生成数量必须是 3 到 10 道。")
    difficulty = _normalize_difficulty(difficulty)

    type_text = "、".join(VARIATION_TYPE_LABELS[x] for x in types)
    system_prompt = (
        "你是一名资深中小学教研员，负责为主题相同的题目设计变式。"
        "只输出 JSON 数组，每项包含 content、answer、analysis、"
        "error_points、question_type、difficulty、knowledge_point、variant_type。"
        "换数字只改变数字，换情境只改变背景，换问法只改变提问方式，"
        "逆向思维把已知条件与所求互换，拓展提升增加综合运用或难度。"
        "不得删除原题核心知识点，答案必须完整。"
    )
    user_text = (
        f"原题ID：{parent.id}\n题型：{qs.QUESTION_TYPES.get(parent.question_type)}\n"
        f"原题难度：{qs.DIFFICULTY_LABELS.get(parent.difficulty)}\n"
        f"原题知识点：{'、'.join(qs.knowledge_points_list(parent)) or '未标注'}\n"
        f"原题干：{parent.content}\n原题答案：{parent.answer}\n"
        f"原解析：{parent.analysis or '无'}\n"
        f"需要的变式类型：{type_text}\n"
        f"总共生成：恰好 {count} 道\n"
        f"难度要求：{'混合' if difficulty == 'mixed' else {'lower': '简单一些', 'keep': '保持原题', 'higher': '难一些'}[difficulty]}。"
    )
    raw_text = llm_client.chat_content(system_prompt, user_text, temperature=0.8)
    raw_items = qs.parse_generated_questions(raw_text)
    result = []
    for index, raw in enumerate(raw_items):
        content = str(raw.get("content") or raw.get("题干") or "").strip()
        answer = str(raw.get("answer") or raw.get("答案") or "").strip()
        if not content or not answer:
            continue
        variant_type = normalize_variation_type(
            raw.get("variant_type") or raw.get("变式类型"))
        if variant_type not in types:
            variant_type = types[min(index // max(1, count // len(types)), len(types) - 1)]
        offset = _difficulty_offset(difficulty, index, int(parent.difficulty or 2))
        raw_difficulty = raw.get("difficulty") or raw.get("难度")
        if raw_difficulty is not None and difficulty in ("keep", "mixed"):
            item_difficulty = qs.normalize_difficulty(raw_difficulty)
        else:
            item_difficulty = int(parent.difficulty or 2) + offset
        item_difficulty = max(1, min(3, item_difficulty))
        extra_kp = raw.get("knowledge_point") or raw.get("knowledge_points") or raw.get("知识点") or ""
        kps = qs.knowledge_points_list(parent)
        if isinstance(extra_kp, list):
            candidates = [str(x) for x in extra_kp]
        else:
            import re
            candidates = re.split(r"[，,、;；]\s*", str(extra_kp or ""))
        seen, merged = set(), []
        for kp in kps + candidates:
            kp = str(kp).strip()
            if kp and kp not in seen:
                seen.add(kp)
                merged.append(kp)
        result.append({
            "temp_id": uuid.uuid4().hex[:10],
            "variant_type": variant_type,
            "content": content,
            "answer": answer,
            "analysis": str(raw.get("analysis") or raw.get("解析") or "").strip(),
            "error_points": str(raw.get("error_points") or raw.get("易错点") or "").strip(),
            "question_type": qs.normalize_type(
                raw.get("question_type") or raw.get("题型") or parent.question_type),
            "difficulty": item_difficulty,
            "knowledge_points": json.dumps(merged, ensure_ascii=False),
        })
        if len(result) >= count:
            break
    if not result:
        raise ValueError("AI 没有返回题干和答案完整的可用变式。")
    return result


def save_variations(session, variants, parent_id) -> list[int]:
    """把教师确认的候选变式写入题库，来源标记为 variation。"""
    return qs.save_variants(session, variants, parent_id, source="variation")
