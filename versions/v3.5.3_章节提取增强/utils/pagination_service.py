# -*- coding: utf-8 -*-
"""列表分页工具。"""

from __future__ import annotations


def page_info(total: int, page: int, page_size: int) -> dict:
    """返回分页信息；页码自动收敛到合法范围。"""
    total = max(0, int(total))
    page_size = max(1, int(page_size))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, int(page)), total_pages)
    offset = (page - 1) * page_size
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "offset": offset,
        "limit": page_size,
    }


def paginate_rows(rows: list, page: int, page_size: int) -> tuple[list, dict]:
    """按页截取列表。"""
    info = page_info(len(rows), page, page_size)
    start = info["offset"]
    return rows[start:start + info["limit"]], info
