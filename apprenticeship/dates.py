"""日历工具：日期一律按左闭右开区间 [start, end) 处理。"""
from __future__ import annotations

from datetime import date

DATE_FMT = "%Y-%m-%d"


def parse_date(value: str) -> date:
    """解析 CSV 中的 ISO 日期；空单元格视为缺失。"""
    text = (value or "").strip()
    if not text:
        raise ValueError("日期不能为空")
    return date.fromisoformat(text)


def optional_date(value: str) -> date | None:
    text = (value or "").strip()
    return parse_date(text) if text else None


def overlaps(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    """两个左闭右开区间是否相交。端点相接（一端结束日=另一端开始日）不算重叠。"""
    return start_a < end_b and start_b < end_a


def before_or_on(day: date, limit: date) -> bool:
    return day <= limit
