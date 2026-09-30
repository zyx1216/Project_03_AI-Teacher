# -*- coding: utf-8 -*-
"""
LLM 调用封装（OpenAI 兼容接口）。

三组配置（都存在 data/llm_config.json，Key 单独存 Windows 凭据管理器）：
- 主模型 base_url/model：阶段 1 的考试分析、学情总结使用；
- 内容模型 content_base_url/content_model：阶段 2 的教案生成、出题使用（建议用
  中文能力更强的通用模型）；留空时自动回退到主模型；
- 向量模型 embed_base_url/embed_model：课本 RAG 用的 embedding（OpenAI 兼容
  /embeddings 接口）；留空时向量检索回退到本地模型或关键词检索。

对外部调用统一：超时 30 秒，失败最多重试 2 次，间隔 1s、2s。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import config

# Windows 凭据管理器里的服务名/用户名
KEYRING_SERVICE = "math-ai-teacher"
KEYRING_USERNAME = "llm_api_key"

CONFIG_PATH = Path(config.DATA_DIR) / "llm_config.json"

TIMEOUT_SECONDS = 120
MAX_RETRIES = 2          # 首次失败后的额外尝试次数（v2.8.0：1 → 2）
RETRY_BACKOFF = [1, 2]   # 每次重试前等待秒数（指数退避）

# 默认配置；内容/向量模型默认留空，由界面填写或回退
DEFAULT_CONFIG = {
    "base_url": config.DEFAULT_API_BASE,
    "model": config.DEFAULT_MODEL,
    "content_base_url": "",
    "content_model": "",
    "embed_base_url": "",
    "embed_model": "",
}


class LLMConfigError(Exception):
    """配置不完整或无效（如没填 Key）。"""


class LLMCallError(Exception):
    """调用模型失败（网络、鉴权、超时等），消息用大白话写。"""


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------

def load_llm_config() -> dict:
    """读取非敏感配置；文件不存在或字段缺失时用默认值补齐（旧配置平滑兼容）。"""
    saved = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, json.JSONDecodeError):
            saved = {}
    result = dict(DEFAULT_CONFIG)
    result.update({k: v for k, v in saved.items() if v is not None})
    return result


def save_llm_config(base_url: str = None, model: str = None, **extra) -> dict:
    """
    合并保存配置（不覆盖未传入的字段，避免把内容/向量配置抹掉）。
    位置参数兼容阶段 1 的 save_llm_config(base_url, model) 调用。
    返回保存后的完整配置。
    """
    config.ensure_dirs()
    current = load_llm_config()
    if base_url is not None:
        current["base_url"] = (base_url or "").strip()
    if model is not None:
        current["model"] = (model or "").strip()
    for key, value in extra.items():
        if key in DEFAULT_CONFIG and value is not None:
            current[key] = str(value).strip()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current


def get_api_key() -> str | None:
    """从 Windows 凭据管理器读取 API Key；读不到返回 None。"""
    try:
        import keyring
    except ImportError:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
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
        pass  # 本来就没有 Key
    except Exception as exc:
        raise LLMConfigError(f"写入系统凭据管理器失败：{exc}") from exc


def is_configured() -> bool:
    """主模型是否可用：有 Key、有模型名。"""
    cfg = load_llm_config()
    return bool(get_api_key()) and bool(cfg.get("model"))


def is_content_configured() -> bool:
    """内容生成模型是否可用（内容模型留空时回退主模型，故只看主模型可用性）。"""
    return is_configured()


# ---------------------------------------------------------------------------
# 聊天调用
# ---------------------------------------------------------------------------

def _resolve_chat_target(cfg: dict, profile: str) -> tuple[str, str]:
    """按 profile（main/content）解析出实际使用的 base_url 和 model。"""
    if profile == "content":
        base_url = cfg.get("content_base_url") or cfg.get("base_url")
        model = cfg.get("content_model") or cfg.get("model")
    else:
        base_url = cfg.get("base_url")
        model = cfg.get("model")
    return base_url, model


def _build_chat_client(profile: str = "main"):
    """构造 OpenAI 客户端和模型名；配置不全抛 LLMConfigError。"""
    from openai import OpenAI

    cfg = load_llm_config()
    api_key = get_api_key()
    if not api_key:
        raise LLMConfigError("还没有配置 API Key，请到“设置 → LLM 配置”填写。")
    base_url, model = _resolve_chat_target(cfg, profile)
    if not model:
        raise LLMConfigError("还没有填写模型名称，请到“设置 → LLM 配置”填写。")
    return OpenAI(api_key=api_key, base_url=base_url,
                  timeout=TIMEOUT_SECONDS), model


def classify_error(exc: BaseException) -> str:
    """把异常归为：网络错误 / API错误 / 内容过滤 / 其他（v2.8.0）。"""
    text = str(exc).lower()
    if any(k in text for k in ("timeout", "timed out", "connection",
                               "network", "unreachable", "ssl")):
        return "网络错误"
    if any(k in text for k in ("content_filter", "content filter",
                               "safety", "敏感", "内容过滤")):
        return "内容过滤"
    if any(k in text for k in ("api", "401", "403", "400", "500", "502",
                               "503", "429", "rate limit")):
        return "API错误"
    return "其他"


def _chat_once(profile: str, system_prompt: str, user_prompt: str,
               temperature: float) -> str:
    """单模型调用 + 重试（不改动缓存逻辑）。"""
    client, model = _build_chat_client(profile)
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
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF[attempt])
    raise LLMCallError(_friendly_error(last_error)) from last_error


def _chat(profile: str, system_prompt: str, user_prompt: str,
          temperature: float = 0.7) -> str:
    """聊天调用内核：缓存（低温）→ 主模型 → 失败降级到内容模型（v2.8.0）。"""
    from utils import cache_service, monitor_service
    use_cache = float(temperature) <= 0.3
    cache_key = None
    if use_cache:
        try:
            cfg = load_llm_config()
            cache_key = cache_service.make_llm_key(
                system_prompt, user_prompt, temperature,
                cfg.get("model") or "", cfg.get("base_url") or "")
            cached = cache_service.get_llm_cache(cache_key)
            if cached is not None:
                return cached
        except Exception:  # noqa: BLE001 —— 缓存异常不影响调用
            cache_key = None

    start = time.perf_counter()
    try:
        text = _chat_once(profile, system_prompt, user_prompt, temperature)
    except LLMCallError as exc:
        # 主模型失败时降级到内容模型（content 例外，避免自我降级）
        if profile == "main":
            try:
                text = _chat_once("content", system_prompt, user_prompt,
                                  temperature)
            except Exception:  # noqa: BLE001
                raise exc
        else:
            raise
    finally:
        try:
            monitor_service.record_metric(
                "llm", f"chat_{profile}",
                (time.perf_counter() - start) * 1000)
        except Exception:  # noqa: BLE001
            pass

    if cache_key:
        try:
            cache_service.set_llm_cache(cache_key, text)
        except Exception:  # noqa: BLE001
            pass
    return text


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """用主模型聊天（阶段 1 的考试分析、学情总结）。"""
    return _chat("main", system_prompt, user_prompt, temperature)


def chat_content(system_prompt: str, user_prompt: str,
                 temperature: float = 0.7) -> str:
    """用内容生成模型聊天（教案、出题）；未单独配置时回退主模型。"""
    return _chat("content", system_prompt, user_prompt, temperature)


def test_connection(profile: str = "main") -> tuple[bool, str]:
    """
    发一条最简单的消息验证配置。profile: main 主模型 / content 内容模型。
    返回 (是否成功, 说明)，不抛异常，供设置页直接展示。
    """
    try:
        reply = _chat(profile, "你是一个连接测试助手。", "只回复两个字：正常",
                      temperature=0)
        label = "内容模型" if profile == "content" else "主模型"
        return True, f"{label}连接成功，回复：{reply[:30]}"
    except (LLMConfigError, LLMCallError) as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# 向量 embedding
# ---------------------------------------------------------------------------

def embedding_config_ready() -> bool:
    """是否填写了 embedding 模型（base_url/model 都要有）。"""
    cfg = load_llm_config()
    return bool(cfg.get("embed_base_url")) and bool(cfg.get("embed_model"))


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    调用 OpenAI 兼容 /embeddings 接口把文本转向量。
    没配置 embedding 模型时抛 LLMConfigError，由调用方降级（本地模型/关键词）。
    """
    cfg = load_llm_config()
    api_key = get_api_key()
    if not api_key:
        raise LLMConfigError("未配置 API Key")
    if not embedding_config_ready():
        raise LLMConfigError("未配置 embedding 模型")

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=cfg["embed_base_url"],
                    timeout=TIMEOUT_SECONDS)
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.embeddings.create(model=cfg["embed_model"], input=texts)
            return [item.embedding for item in resp.data]
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF[attempt])
    raise LLMCallError(_friendly_error(last_error)) from last_error


def _friendly_error(exc) -> str:
    """把底层异常翻译成老师能看懂的大白话。"""
    text = str(exc).lower()
    if "authentication" in text or "401" in text or "api key" in text:
        return "API Key 不正确或已失效，请检查后重新填写。"
    if "404" in text or ("model" in text and "not" in text):
        return "找不到这个模型，请核对模型名称（如 deepseek-chat）。"
    if "timeout" in text or "timed out" in text:
        return "请求超时了（超过 120 秒），可能是网络慢，请稍后再试。"
    if "connection" in text or "resolve host" in text or "10013" in text:
        return "连不上服务器，请检查网络或 Base URL 是否填对。"
    return f"调用失败（已重试 2 次）：{str(exc)[:120]}"
# ---------------------------------------------------------------------------
# v2.2.0：原生 Function Calling；模型不支持时回退结构化 JSON 协议
# ---------------------------------------------------------------------------

TOOL_CALL_SYSTEM_SUFFIX = """
如果需要调用工具，只能输出一个 JSON 对象：
{"tool_name":"工具名","params":{参数名:参数值},"confirmed":false}
不需要工具时正常回答，不要编造工具结果。
"""


def _normalize_tool_calls(message) -> list[dict]:
    """把 OpenAI 返回的 tool_calls 归一化成 JSON 安全结构。"""
    result = []
    for item in getattr(message, "tool_calls", None) or []:
        function = getattr(item, "function", None)
        raw_arguments = getattr(function, "arguments", "{}")
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
        result.append({
            "id": getattr(item, "id", ""),
            "tool_name": getattr(function, "name", ""),
            "params": arguments if isinstance(arguments, dict) else {},
        })
    return result


def _tool_chat_client(profile: str = "content"):
    """构造支持 tools 参数的客户端。"""
    return _build_chat_client(profile)


def chat_with_tools(system_prompt: str, user_prompt: str, tools: list[dict],
                    profile: str = "content",
                    temperature: float = 0.2) -> dict:
    """原生工具调用。

    返回 {"mode":"native|text|fallback_json", "tool_calls":[...], "content":""}。
    模型不支持 Function Calling 时，让模型只输出工具调用 JSON。
    """
    client, model = _tool_chat_client(profile)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            tool_choice="auto", temperature=temperature)
        message = response.choices[0].message
        calls = _normalize_tool_calls(message)
        return {
            "mode": "native",
            "tool_calls": calls,
            "content": message.content or "",
        }
    except Exception:
        # 结构化协议回退：不吞异常，若仍失败由 _chat 的正常错误抛出。
        reply = _chat(
            profile, system_prompt + TOOL_CALL_SYSTEM_SUFFIX, user_prompt,
            temperature=0)
        try:
            data = json.loads(reply)
        except json.JSONDecodeError:
            return {"mode": "text", "tool_calls": [], "content": reply}
        if not isinstance(data, dict) or not data.get("tool_name"):
            return {"mode": "text", "tool_calls": [], "content": reply}
        return {
            "mode": "fallback_json",
            "tool_calls": [{
                "id": "",
                "tool_name": data.get("tool_name"),
                "params": data.get("params") if isinstance(data.get("params"), dict) else {},
            }],
            "content": "",
        }
