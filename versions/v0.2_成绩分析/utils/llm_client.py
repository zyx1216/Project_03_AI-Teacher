# -*- coding: utf-8 -*-
"""
LLM 调用封装（OpenAI 兼容接口）。

密钥与配置分开存：
- API Key 用 keyring 存进 Windows 凭据管理器（服务名见 KEYRING_SERVICE）；
- Base URL、模型名等非敏感配置存 data/llm_config.json（data 目录已被 git 忽略）。

对外部调用统一：超时 30 秒，失败最多重试 2 次，间隔 1s、2s；
最终失败抛出 LLMConfigError / LLMCallError，由页面捕获后给老师友好提示。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import config

# Windows 凭据管理器里的服务名/用户名，固定值，方便定位和删除
KEYRING_SERVICE = "math-ai-teacher"
KEYRING_USERNAME = "llm_api_key"

CONFIG_PATH = Path(config.DATA_DIR) / "llm_config.json"

# 调用参数（遵守项目规范：外部请求必须有超时和重试）
TIMEOUT_SECONDS = 30
MAX_RETRIES = 2          # 首次失败后的额外尝试次数
RETRY_BACKOFF = [1, 2]   # 每次重试前等待秒数

DEFAULT_CONFIG = {
    "base_url": config.DEFAULT_API_BASE,
    "model": config.DEFAULT_MODEL,
}


class LLMConfigError(Exception):
    """配置不完整或无效（如没填 Key）。"""


class LLMCallError(Exception):
    """调用模型失败（网络、鉴权、超时等），消息用大白话写。"""


def load_llm_config() -> dict:
    """读取非敏感配置；文件不存在时返回默认值。"""
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    result = dict(DEFAULT_CONFIG)
    result.update({k: v for k, v in saved.items() if v is not None})
    return result


def save_llm_config(base_url: str, model: str) -> None:
    """保存 Base URL 和模型名到本地配置文件。"""
    config.ensure_dirs()
    data = {"base_url": (base_url or "").strip(),
            "model": (model or "").strip()}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_api_key() -> str | None:
    """从 Windows 凭据管理器读取 API Key；读不到（如非 Windows 环境）返回 None。"""
    try:
        import keyring
    except ImportError:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        # keyring 后端在个别机器上可能不可用，统一当作"未配置"处理
        return None


def set_api_key(api_key: str) -> None:
    """把 API Key 写入凭据管理器；传空字符串表示删除已存的 Key。"""
    try:
        import keyring
    except ImportError as exc:
        raise LLMConfigError("当前环境缺少 keyring 库，无法安全保存密钥") from exc
    api_key = (api_key or "").strip()
    try:
        if api_key:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)
        else:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        # 本来就没有 Key，删除时忽略
        pass
    except Exception as exc:
        raise LLMConfigError(f"写入系统凭据管理器失败：{exc}") from exc


def is_configured() -> bool:
    """是否已具备调用条件：有 Key、有模型名。"""
    cfg = load_llm_config()
    return bool(get_api_key()) and bool(cfg.get("model"))


def _build_client():
    """构造 OpenAI 客户端；配置不全时抛 LLMConfigError。"""
    from openai import OpenAI

    cfg = load_llm_config()
    api_key = get_api_key()
    if not api_key:
        raise LLMConfigError("还没有配置 API Key，请到“设置 → LLM 配置”填写。")
    if not cfg.get("model"):
        raise LLMConfigError("还没有填写模型名称，请到“设置 → LLM 配置”填写。")
    return OpenAI(api_key=api_key, base_url=cfg["base_url"],
                  timeout=TIMEOUT_SECONDS), cfg["model"]


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """
    调用聊天模型，返回文本结果。
    失败按 1s、2s 间隔重试，共最多重试 2 次；仍失败抛 LLMCallError。
    """
    client, model = _build_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature)
            content = resp.choices[0].message.content
            if content:
                return content.strip()
            raise LLMCallError("模型返回了空内容，请重试或更换模型。")
        except LLMConfigError:
            raise
        except Exception as exc:  # 网络/鉴权/超时等，统一转成友好错误
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF[attempt])
    friendly = _friendly_error(last_error)
    raise LLMCallError(friendly) from last_error


def test_connection() -> tuple[bool, str]:
    """
    发一条最简单的消息验证配置。
    返回 (是否成功, 说明文字)，不抛异常，供设置页直接展示。
    """
    try:
        reply = chat("你是一个连接测试助手。", "只回复两个字：正常", temperature=0)
        return True, f"连接成功，模型回复：{reply[:30]}"
    except LLMConfigError as exc:
        return False, str(exc)
    except LLMCallError as exc:
        return False, str(exc)


def _friendly_error(exc) -> str:
    """把底层异常翻译成老师能看懂的大白话。"""
    text = str(exc).lower()
    if "authentication" in text or "401" in text or "api key" in text:
        return "API Key 不正确或已失效，请检查后重新填写。"
    if "404" in text or "model" in text and "not" in text:
        return "找不到这个模型，请核对模型名称（如 deepseek-chat）。"
    if "timeout" in text or "timed out" in text:
        return "请求超时了（超过 30 秒），可能是网络慢，请稍后再试。"
    if "connection" in text or "resolve host" in text or "10013" in text:
        return "连不上服务器，请检查网络或 Base URL 是否填对。"
    return f"调用失败（已重试 2 次）：{str(exc)[:120]}"