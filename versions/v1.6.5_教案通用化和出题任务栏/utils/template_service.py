# -*- coding: utf-8 -*-
"""
教案模板、PPT 模板的本地 JSON 管理。

不新增数据库表：模板元数据写 data/lesson_templates.json 和
data/ppt_templates.json；自定义 PPT 原文件放 data/templates/ppt/。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import config

LESSON_TEMPLATES_PATH = config.DATA_DIR / "lesson_templates.json"
PPT_TEMPLATES_PATH = config.DATA_DIR / "ppt_templates.json"
PPT_TEMPLATE_DIR = config.DATA_DIR / "templates" / "ppt"

BUILTIN_LESSON_TEMPLATES = {
    "通用模板": """请按以下结构生成教案：
一、教学目标
1. 知识与技能
2. 过程与方法
3. 情感态度与价值观
二、教学重点
三、教学难点
四、教学准备
五、教学过程
1. 导入新课
2. 讲授新知
3. 课堂练习
4. 课堂小结
5. 作业布置
六、板书设计
七、教学反思""",
}
OLD_BUILTIN_LESSON_TEMPLATE_NAMES = {"语文模板", "数学模板"}

DEFAULT_PPT_THEMES = {
    "简约": {"builtin": True, "colors": ["1F4E79", "000000"]},
    "教育": {"builtin": True, "colors": ["2E7D32", "000000"]},
    "商务": {"builtin": True, "colors": ["2F455C", "000000"]},
}

_LOCK = threading.RLock()
_CORRUPT: set[str] = set()
_MEMORY: dict[str, dict] = {}


def _read_json(path: Path, default: dict) -> dict:
    """读 JSON；文件缺失返回默认结构，损坏时回退且不覆盖。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default)
    except FileNotFoundError:
        return dict(default)
    except (json.JSONDecodeError, OSError):
        _CORRUPT.add(str(path))
        return dict(_MEMORY.get(str(path), {}))


def _write_json(path: Path, data: dict) -> None:
    """UTF-8、中文不转义；若原文件损坏，只保留进程内状态。"""
    key = str(path)
    if key in _CORRUPT:
        _MEMORY[key] = dict(data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _lesson_default() -> dict:
    return {
        "templates": [
            {"name": name, "content": content, "builtin": True}
            for name, content in BUILTIN_LESSON_TEMPLATES.items()
        ]
    }


def list_lesson_templates() -> list[dict]:
    """返回通用模板和自定义教案模板；旧语文/数学内置模板不再显示。"""
    with _LOCK:
        data = _read_json(LESSON_TEMPLATES_PATH, _lesson_default())
    raw_templates = data.get("templates", [])
    templates = []
    for item in raw_templates:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item.get("name"))
        if name in OLD_BUILTIN_LESSON_TEMPLATE_NAMES:
            continue
        if name == "通用模板":
            # 持久化文件可能是旧结构，界面统一使用当前通用模板。
            item = dict(item)
            item["content"] = BUILTIN_LESSON_TEMPLATES["通用模板"]
            item["builtin"] = True
        templates.append(item)
    return templates


def lesson_template_content(name: str) -> str:
    """按名称读取教案模板正文。"""
    for item in list_lesson_templates():
        if item.get("name") == name:
            return str(item.get("content") or "")
    return ""


def save_custom_lesson_template(name: str, content: str) -> None:
    """保存自定义教案模板；空名称或空正文拒绝。"""
    name = str(name or "").strip()
    content = str(content or "").strip()
    if not name:
        raise ValueError("模板名称不能为空。")
    if not content:
        raise ValueError("模板内容不能为空。")
    if name in BUILTIN_LESSON_TEMPLATES:
        raise ValueError("不能覆盖内置模板名称，请换个名称。")

    with _LOCK:
        data = _read_json(LESSON_TEMPLATES_PATH, _lesson_default())
        templates = []
        for item in data.get("templates", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            item_name = str(item.get("name"))
            # 下次保存自定义模板时，顺手清掉旧内置语文/数学模板。
            if item_name in OLD_BUILTIN_LESSON_TEMPLATE_NAMES:
                continue
            if item_name == name and not item.get("builtin"):
                continue
            if item_name == "通用模板":
                item = dict(item)
                item["content"] = BUILTIN_LESSON_TEMPLATES["通用模板"]
                item["builtin"] = True
            templates.append(item)
        templates.append({"name": name, "content": content, "builtin": False})
        data["templates"] = templates
        _write_json(LESSON_TEMPLATES_PATH, data)


def _ppt_default() -> dict:
    return {
        "themes": [
            {"name": name, "builtin": True, "file": "", **meta}
            for name, meta in DEFAULT_PPT_THEMES.items()
        ]
    }


def list_ppt_templates() -> list[dict]:
    """列出三种内置主题和已上传的自定义 PPT 模板。"""
    with _LOCK:
        data = _read_json(PPT_TEMPLATES_PATH, _ppt_default())
    themes = data.get("themes", [])
    return [item for item in themes if isinstance(item, dict) and item.get("name")]


def ppt_template_info(name: str) -> dict | None:
    """读取单个 PPT 模板信息。"""
    for item in list_ppt_templates():
        if item.get("name") == name:
            return dict(item)
    return None


def validate_pptx(file_bytes: bytes) -> None:
    """校验文件能被 python-pptx 打开且存在可用版式。"""
    import io
    from pptx import Presentation

    try:
        prs = Presentation(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError("文件不是有效的 PPTX 模板。") from exc
    if not prs.slide_layouts:
        raise ValueError("该 PPT 模板没有可用版式。")


def save_custom_ppt_template(name: str, file_bytes: bytes) -> None:
    """保存自定义 PPT 模板原文件和元数据。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("模板名称不能为空。")
    if name in DEFAULT_PPT_THEMES:
        raise ValueError("不能使用内置主题名称，请换个名称。")
    validate_pptx(file_bytes)

    filename = f"{name}.pptx"
    safe_name = "".join(ch for ch in filename if ch not in '\\/:*?"<>|')
    PPT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    path = PPT_TEMPLATE_DIR / safe_name
    path.write_bytes(file_bytes)

    with _LOCK:
        data = _read_json(PPT_TEMPLATES_PATH, _ppt_default())
        themes = [item for item in data.get("themes", [])
                  if not (isinstance(item, dict)
                          and item.get("name") == name
                          and not item.get("builtin"))]
        try:
            file_value = str(path.relative_to(config.BASE_DIR))
        except ValueError:
            # 测试或自定义运行目录不在项目内时，元数据允许保存绝对路径。
            file_value = str(path)
        themes.append({
            "name": name, "builtin": False,
            "file": file_value,
        })
        data["themes"] = themes
        _write_json(PPT_TEMPLATES_PATH, data)

def _ppt_template_path(item: dict):
    """把元数据里的文件位置解析成 Path（支持项目相对路径和绝对路径）。"""
    file_value = str(item.get("file") or "")
    path = Path(file_value)
    return path if path.is_absolute() else config.BASE_DIR / file_value


def rename_ppt_template(old_name: str, new_name: str) -> None:
    """重命名自定义 PPT 模板：改文件名和元数据；内置主题或重名校验失败时报错。"""
    old_name, new_name = str(old_name or "").strip(), str(new_name or "").strip()
    if not new_name:
        raise ValueError("模板名称不能为空。")
    if new_name in DEFAULT_PPT_THEMES:
        raise ValueError("不能使用内置主题名称，请换个名称。")

    with _LOCK:
        data = _read_json(PPT_TEMPLATES_PATH, _ppt_default())
        themes = data.get("themes", [])
        target = next((item for item in themes
                       if isinstance(item, dict) and item.get("name") == old_name), None)
        if target is None:
            raise ValueError("模板不存在。")
        if target.get("builtin"):
            raise ValueError("内置主题不能重命名。")
        if any(isinstance(item, dict) and item.get("name") == new_name
               for item in themes):
            raise ValueError("已存在同名模板，请换个名称。")

        old_path = _ppt_template_path(target)
        safe_name = "".join(ch for ch in f"{new_name}.pptx"
                            if ch not in '\/:*?"<>|')
        new_path = old_path.with_name(safe_name)
        if old_path.exists():
            old_path.replace(new_path)
        try:
            file_value = str(new_path.relative_to(config.BASE_DIR))
        except ValueError:
            file_value = str(new_path)
        target["name"] = new_name
        target["file"] = file_value
        _write_json(PPT_TEMPLATES_PATH, data)


def delete_ppt_template(name: str) -> None:
    """删除自定义 PPT 模板文件和元数据；内置主题拒绝删除。"""
    name = str(name or "").strip()
    with _LOCK:
        data = _read_json(PPT_TEMPLATES_PATH, _ppt_default())
        themes = data.get("themes", [])
        target = next((item for item in themes
                       if isinstance(item, dict) and item.get("name") == name), None)
        if target is None:
            raise ValueError("模板不存在。")
        if target.get("builtin"):
            raise ValueError("内置主题不能删除。")

        file_path = _ppt_template_path(target)
        try:
            file_path.unlink()
        except FileNotFoundError:
            pass
        themes = [item for item in themes
                  if not (isinstance(item, dict) and item.get("name") == name)]
        data["themes"] = themes
        _write_json(PPT_TEMPLATES_PATH, data)

