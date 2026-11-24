"""席位与导师容量校验。

容量有两层：
- 单个席位的 seats：同一 slot 最多安排多少名学生；
- mentor_limit：同一导师、区间重叠的席位共用上限，事件扫描按左闭右开区间统计并发占用。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import Registry, Slot


@dataclass(frozen=True)
class Violation:
    kind: str               # seat / mentor
    label: str              # 席位号或导师号
    at: date                # 触发日期（区间起点）
    capacity: int
    occupants: tuple[str, ...]
    detail: str


def check_bookings(registry: Registry,
                   bookings: dict[str, tuple[str, ...]]) -> list[Violation]:
    """校验 {slot_id: 学生元组} 是否同时满足席位与导师容量。"""
    violations: list[Violation] = []
    slots = [registry.slots_by_id[slot_id] for slot_id in bookings]

    for slot in slots:
        occupants = tuple(dict.fromkeys(bookings[slot.slot]))
        if len(occupants) > slot.seats:
            violations.append(Violation(
                kind="seat", label=slot.slot, at=slot.start,
                capacity=slot.seats, occupants=occupants,
                detail=f"席位 {slot.slot} 容量 {slot.seats}，实际 {len(occupants)} 人"))

    for mentor in sorted({s.mentor for s in slots}):
        mentor_slots = [s for s in slots if s.mentor == mentor]
        limit = mentor_slots[0].mentor_limit
        # 左闭右开：在每个重叠区间起点结算一次并发占用
        checkpoints = sorted({s.start for s in mentor_slots})
        for point in checkpoints:
            active: list[str] = []
            for slot in mentor_slots:
                if slot.start <= point < slot.end:
                    active.extend(bookings[slot.slot])
            occupants = tuple(dict.fromkeys(active))
            if len(occupants) > limit:
                violations.append(Violation(
                    kind="mentor", label=mentor, at=point,
                    capacity=limit, occupants=occupants,
                    detail=(f"导师 {mentor} 在 {point.isoformat()} 并发 {len(occupants)} 人，"
                            f"超过 mentor_limit {limit}")))
    return violations


def available_seats(registry: Registry, bookings: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """在给定占用下，每个席位还剩多少空位（不考虑导师合并容量）。"""
    free: dict[str, int] = {}
    for slot in registry.slots:
        used = len(dict.fromkeys(bookings.get(slot.slot, ())))
        free[slot.slot] = max(0, slot.seats - used)
    return free


def slot_is_open(slot: Slot, as_of: date) -> bool:
    """as_of 当日席位是否尚未开始（可暂停交接）。"""
    return as_of < slot.start
