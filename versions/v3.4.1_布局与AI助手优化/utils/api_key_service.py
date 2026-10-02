# -*- coding: utf-8 -*-
"""API Key 管理（v1.9.7）。

Key 存在本地 data/api_keys.json，只用于 FastAPI 接口的简单认证；
与 AI 模型的 API Key（Windows 凭据管理器）完全分开。
文件缺失自建，JSON 损坏回退默认且不覆盖原文件。
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime

import config

API_KEYS_PATH = config.DATA_DIR / "api_keys.json"


def default_state() -> dict:
    """默认存储结构。"""
    return {"keys": []}


def load_keys() -> dict:
    """读取；缺失自建，损坏回退默认且不覆盖。"""
    path = API_KEYS_PATH
    try:
        if not path.exists():
            state = default_state()
            save_keys(state)
            return state
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
            return default_state()
        return data
    except (json.JSONDecodeError, OSError):
        return default_state()


def save_keys(state: dict) -> None:
    """持久化，UTF-8、ensure_ascii=False。"""
    API_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    API_KEYS_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def create_key(name: str = "默认密钥") -> dict:
    """生成一个新 key 并保存；返回含明文 key 的记录（仅此一次可见）。"""
    state = load_keys()
    plain = "mt-" + secrets.token_urlsafe(24)
    record = {
        "id": secrets.token_hex(6),
        "name": str(name or "密钥").strip() or "密钥",
        "key": _hash(plain),
        "key_prefix": plain[:8],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "revoked": False,
    }
    state["keys"].append(record)
    save_keys(state)
    record["plain_key"] = plain
    return record


def verify_key(plain_key: str) -> bool:
    """校验请求里的 key 是否有效且未吊销。"""
    if not plain_key:
        return False
    digest = _hash(plain_key)
    return any(k.get("key") == digest and not k.get("revoked")
               for k in load_keys()["keys"])


def revoke_key(key_id: str) -> bool:
    """吊销一个 key。"""
    state = load_keys()
    ok = False
    for k in state["keys"]:
        if k.get("id") == key_id:
            k["revoked"] = True
            ok = True
    if ok:
        save_keys(state)
    return ok


def mask_key(record: dict) -> str:
    """给设置页展示掩码。"""
    return f'{record.get("key_prefix", "")}••••••'


def _hash(plain: str) -> str:
    """用 SHA-256 存 key 摘要，不存明文。"""
    import hashlib
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
