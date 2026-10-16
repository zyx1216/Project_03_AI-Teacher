# -*- coding: utf-8 -*-
"""操作审计日志服务。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from models.models import OperationLog

# 敏感字段：写日志前直接替换成固定中文说明，不保留原值
SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "api_key", "apikey", "key", "token",
    "secret", "private_key", "authorization", "credential", "credentials",
}


def sanitize_value(value: Any) -> Any:
    """递归转成 JSON 安全结构，并对敏感字段脱敏。"""
    if isinstance(value, dict):
        result = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.lower().replace("-", "_") in SENSITIVE_KEYS:
                result[key] = "【已脱敏】"
            else:
                result[key] = sanitize_value(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def detail_to_text(detail: Any) -> str | None:
    """把详情转成 JSON 字符串；空详情返回 None。"""
    if detail is None:
        return None
    return json.dumps(sanitize_value(detail), ensure_ascii=False)


def log_operation(session: Session, action: str, module: str,
                  target: str | int | None = None,
                  detail: Any = None,
                  user: str = "teacher",
                  ip: str | None = None) -> OperationLog:
    """新增一条操作审计日志，但不提交；由外层事务统一提交。"""
    row = OperationLog(
        user=str(user or "teacher"),
        action=str(action),
        module=str(module),
        target=None if target is None else str(target),
        detail=detail_to_text(detail),
        ip=ip,
    )
    session.add(row)
    session.flush()
    return row


def operation_to_dict(row: OperationLog) -> dict:
    """转成 UI 可用的普通字典。"""
    return {
        "id": row.id,
        "用户": row.user,
        "操作": row.action,
        "模块": row.module,
        "对象": row.target or "",
        "详情": row.detail or "",
        "IP": row.ip or "",
        "时间": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
    }


def query_logs(session: Session, start_date=None, end_date=None,
               module: str | None = None, action: str | None = None,
               limit: int = 100) -> list[OperationLog]:
    """按时间、模块和操作类型查询日志。"""
    query = session.query(OperationLog)
    if start_date is not None:
        query = query.filter(OperationLog.created_at >= start_date)
    if end_date is not None:
        query = query.filter(OperationLog.created_at <= end_date)
    if module:
        query = query.filter(OperationLog.module == module)
    if action:
        query = query.filter(OperationLog.action == action)
    return (query.order_by(OperationLog.created_at.desc(),
                           OperationLog.id.desc())
            .limit(max(1, int(limit))).all())
