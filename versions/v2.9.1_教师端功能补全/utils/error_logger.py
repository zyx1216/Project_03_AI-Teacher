# -*- coding: utf-8 -*-
"""本地错误日志服务。"""

from __future__ import annotations

import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from utils.logger_service import sanitize_value

ERROR_LOG_DIR = config.LOG_DIR

# 常见敏感串的兜底正则，防止异常消息里带出密钥
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(token\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(password\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]+)"),
]


def _redact_text(text: str) -> str:
    """替换错误文本中的敏感值。"""
    result = text
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(r"\1【已脱敏】", result)
    return result


def log_error(error: BaseException, context: dict | None = None,
              log_dir: Path | str | None = None) -> Path:
    """把异常写入 logs/error_YYYYMMDD.log。"""
    target_dir = Path(log_dir or ERROR_LOG_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"error_{datetime.now():%Y%m%d}.log"

    lines = [
        "=" * 80,
        f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"错误类型：{type(error).__name__}",
        f"错误信息：{_redact_text(str(error))}",
    ]
    if context:
        safe_context = sanitize_value(context)
        lines.append("上下文：" + str(safe_context))
    lines.append("堆栈：")
    lines.append(_redact_text(traceback.format_exc()))
    with target.open("a", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return target


def list_log_files(log_dir: Path | str | None = None) -> list[Path]:
    """列出错误日志文件，新文件在前。"""
    target_dir = Path(log_dir or ERROR_LOG_DIR)
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("error_*.log"),
                  key=lambda item: item.stat().st_mtime, reverse=True)


def read_log_file(filename: str,
                  log_dir: Path | str | None = None) -> str:
    """读取指定错误日志，防止文件名跳出日志目录。"""
    target_dir = Path(log_dir or ERROR_LOG_DIR).resolve()
    target = (target_dir / Path(filename).name).resolve()
    if target.parent != target_dir or target.suffix != ".log":
        raise ValueError("非法日志文件名。")
    if not target.exists():
        raise FileNotFoundError("日志文件不存在。")
    return _redact_text(target.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# v2.8.0：慢查询日志 + 错误统计
# ---------------------------------------------------------------------------

def write_slow_query(statement: str, elapsed_ms: float,
                     log_dir: Path | str | None = None) -> Path:
    """把慢查询写入 logs/slow_query_YYYYMMDD.log（语句脱敏、截断）。"""
    target_dir = Path(log_dir or ERROR_LOG_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"slow_query_{datetime.now():%Y%m%d}.log"
    stmt = _redact_text(str(statement or "")).replace("\n", " ")
    if len(stmt) > 500:
        stmt = stmt[:500] + "…"
    line = (f"{datetime.now():%Y-%m-%d %H:%M:%S}\t"
            f"{float(elapsed_ms):.1f}ms\t{stmt}\n")
    with target.open("a", encoding="utf-8") as file:
        file.write(line)
    return target


def list_slow_query_files(log_dir: Path | str | None = None) -> list[Path]:
    """列出慢查询日志文件，新文件在前。"""
    target_dir = Path(log_dir or ERROR_LOG_DIR)
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("slow_query_*.log"),
                  key=lambda item: item.stat().st_mtime, reverse=True)


def error_stats(log_dir: Path | str | None = None) -> dict:
    """错误统计：总次数、按错误类型计数、高频类型（次数>=3）。"""
    by_type: dict[str, int] = {}
    total = 0
    for path in list_log_files(log_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("错误类型："):
                name = line.split("：", 1)[1].strip()
                by_type[name] = by_type.get(name, 0) + 1
                total += 1
    hot = sorted([{"type": k, "count": v} for k, v in by_type.items()
                  if v >= 3], key=lambda r: r["count"], reverse=True)
    ordered = sorted(by_type.items(), key=lambda kv: kv[1], reverse=True)
    return {"total": total, "by_type": dict(ordered), "hot": hot}
