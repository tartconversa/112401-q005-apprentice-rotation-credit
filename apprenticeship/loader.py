"""CSV 读取与结构校验。

读取契约与 README 保持一致：UTF-8、首行列名、竖线分隔多值、空单元格为缺失。
结构性错误（缺列、坏枚举、悬空外键、容量声明冲突）直接抛 DataError，
让学期资料在进入认定计算之前就无法被静默误用。
"""
from __future__ import annotations

import csv
from pathlib import Path

from .dates import parse_date
from .models import (
    ACK_ACCEPTED,
    ACK_DECLINED,
    ACK_PENDING,
    AGR_CONFIRMED,
    AGR_PROPOSED,
    PARTY_FIRM,
    PARTY_LEARNER,
    PARTY_SCHOOL,
    PROOF_CONFIRMED,
    PROOF_WITHDRAWN,
    Acknowledgement,
    Agreement,
    Person,
    Proof,
    Registry,
    Requirement,
    Slot,
)

HEADERS = {
    "requirements": ("mode", "competency", "min_hours", "precedes", "version", "active_from"),
    "people": ("learner", "mode_options", "deadline"),
    "proofs": ("proof", "learner", "hours", "uses", "group", "completed", "mentor",
               "state", "replaces", "received"),
    "rotations": ("slot", "firm", "mentor", "start", "end", "requires", "offers",
                  "hours", "seats", "mentor_limit"),
    "agreements": ("agreement", "learner", "slot", "status", "group", "replaces", "recorded"),
    "acknowledgements": ("entry", "agreement", "party", "state", "source_id", "recorded"),
}

PROOF_STATES = {PROOF_CONFIRMED, PROOF_WITHDRAWN}
AGR_STATES = {AGR_CONFIRMED, AGR_PROPOSED}
ACK_STATES = {ACK_ACCEPTED, ACK_DECLINED, ACK_PENDING}
PARTIES = {PARTY_LEARNER, PARTY_SCHOOL, PARTY_FIRM}


class DataError(ValueError):
    """学期资料违反读取契约。"""


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split("|") if part.strip())


def _cell(row: dict, field: str, table: str, key: str) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise DataError(f"{table} 的 {key} 行缺少必填字段 {field}")
    return value


def _optional(row: dict, field: str) -> str | None:
    value = (row.get(field) or "").strip()
    return value or None


def _enum(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise DataError(f"{label} 取值 {value} 不合法，允许 {sorted(allowed)}")
    return value


def _read_table(path: Path, table: str) -> list[dict]:
    if not path.exists():
        raise DataError(f"找不到资料文件 {path}")
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if tuple(reader.fieldnames or ()) != HEADERS[table]:
            raise DataError(f"{table} 列名与契约不符：{reader.fieldnames}")
        rows = list(reader)
    for row in rows:
        if None in row or None in row.values():
            raise DataError(f"{table} 存在多余的未声明列")
    if not rows:
        raise DataError(f"{table} 至少要有一行资料")
    return rows


def _ensure_unique(ids: list[str], table: str, field: str) -> None:
    seen: set[str] = set()
    for value in ids:
        if value in seen:
            raise DataError(f"{table} 的 {field} 出现重复值 {value}")
        seen.add(value)


def load_registry(directory: str | Path) -> Registry:
    base = Path(directory)
    req_rows = _read_table(base / "requirements.csv", "requirements")
    people_rows = _read_table(base / "people.csv", "people")
    proof_rows = _read_table(base / "proofs.csv", "proofs")
    slot_rows = _read_table(base / "rotations.csv", "rotations")
    agr_rows = _read_table(base / "agreements.csv", "agreements")
    ack_rows = _read_table(base / "acknowledgements.csv", "acknowledgements")

    requirements = [
        Requirement(
            mode=_cell(r, "mode", "requirements", r.get("competency", "?")),
            competency=_cell(r, "competency", "requirements", r.get("mode", "?")),
            min_hours=int(_cell(r, "min_hours", "requirements", r.get("competency", "?"))),
            prerequisite=_optional(r, "precedes"),
            version=int(_cell(r, "version", "requirements", r.get("competency", "?"))),
            active_from=parse_date(_cell(r, "active_from", "requirements", r.get("competency", "?"))),
        )
        for r in req_rows
    ]

    people = [
        Person(
            learner=_cell(r, "learner", "people", r.get("learner", "?")),
            mode_options=_split(_cell(r, "mode_options", "people", r["learner"])),
            deadline=parse_date(_cell(r, "deadline", "people", r["learner"])),
        )
        for r in people_rows
    ]
    _ensure_unique([p.learner for p in people], "people", "learner")

    proofs = [
        Proof(
            proof=_cell(r, "proof", "proofs", r.get("proof", "?")),
            learner=_cell(r, "learner", "proofs", r["proof"]),
            hours=int(_cell(r, "hours", "proofs", r["proof"])),
            uses=_split(_cell(r, "uses", "proofs", r["proof"])),
            group=_optional(r, "group"),
            completed=parse_date(_cell(r, "completed", "proofs", r["proof"])),
            mentor=_cell(r, "mentor", "proofs", r["proof"]),
            state=_enum(_cell(r, "state", "proofs", r["proof"]), PROOF_STATES,
                        f"proofs 的 {r['proof']} 状态"),
            replaces=_optional(r, "replaces"),
            received=parse_date(_cell(r, "received", "proofs", r["proof"])),
        )
        for r in proof_rows
    ]
    _ensure_unique([p.proof for p in proofs], "proofs", "proof")

    slots = [
        Slot(
            slot=_cell(r, "slot", "rotations", r.get("slot", "?")),
            firm=_cell(r, "firm", "rotations", r["slot"]),
            mentor=_cell(r, "mentor", "rotations", r["slot"]),
            start=parse_date(_cell(r, "start", "rotations", r["slot"])),
            end=parse_date(_cell(r, "end", "rotations", r["slot"])),
            requires=_split(_cell(r, "requires", "rotations", r["slot"])),
            offers=_cell(r, "offers", "rotations", r["slot"]),
            hours=int(_cell(r, "hours", "rotations", r["slot"])),
            seats=int(_cell(r, "seats", "rotations", r["slot"])),
            mentor_limit=int(_cell(r, "mentor_limit", "rotations", r["slot"])),
        )
        for r in slot_rows
    ]
    _ensure_unique([s.slot for s in slots], "rotations", "slot")

    agreements = [
        Agreement(
            agreement=_cell(r, "agreement", "agreements", r.get("agreement", "?")),
            learner=_cell(r, "learner", "agreements", r["agreement"]),
            slot=_cell(r, "slot", "agreements", r["agreement"]),
            status=_enum(_cell(r, "status", "agreements", r["agreement"]), AGR_STATES,
                         f"agreements 的 {r['agreement']} 状态"),
            group=_optional(r, "group"),
            replaces=_optional(r, "replaces"),
            recorded=parse_date(_cell(r, "recorded", "agreements", r["agreement"])),
        )
        for r in agr_rows
    ]
    _ensure_unique([a.agreement for a in agreements], "agreements", "agreement")

    acks = [
        Acknowledgement(
            entry=_cell(r, "entry", "acknowledgements", r.get("entry", "?")),
            agreement=_cell(r, "agreement", "acknowledgements", r["entry"]),
            party=_enum(_cell(r, "party", "acknowledgements", r["entry"]), PARTIES,
                        f"acknowledgements 的 {r['entry']} 角色"),
            state=_enum(_cell(r, "state", "acknowledgements", r["entry"]), ACK_STATES,
                        f"acknowledgements 的 {r['entry']} 签认状态"),
            source_id=_optional(r, "source_id"),
            recorded=parse_date(_cell(r, "recorded", "acknowledgements", r["entry"])),
        )
        for r in ack_rows
    ]
    _ensure_unique([k.entry for k in acks], "acknowledgements", "entry")

    registry = Registry(requirements, people, proofs, slots, agreements, acks)
    _validate_references(registry)
    _validate_capacity(registry)
    return registry


def _validate_references(registry: Registry) -> None:
    people_ids = set(registry.people_by_id)
    proof_ids = set(registry.proofs_by_id)
    slot_ids = set(registry.slots_by_id)
    agr_ids = set(registry.agreements_by_id)

    for proof in registry.proofs:
        if proof.learner not in people_ids:
            raise DataError(f"证明 {proof.proof} 引用了未知学生 {proof.learner}")
        if proof.replaces and proof.replaces not in proof_ids:
            raise DataError(f"证明 {proof.proof} 替代了未知证明 {proof.replaces}")
        if proof.hours <= 0:
            raise DataError(f"证明 {proof.proof} 时数必须为正数")

    # 整套实作必须属于同一名学生，否则无法共同认定
    groups: dict[str, set[str]] = {}
    for proof in registry.proofs:
        if proof.group:
            groups.setdefault(proof.group, set()).add(proof.learner)
    for group, learners in groups.items():
        if len(learners) > 1:
            raise DataError(f"整套实作 {group} 混有不同学生：{sorted(learners)}")

    for agr in registry.agreements:
        if agr.learner not in people_ids:
            raise DataError(f"协议 {agr.agreement} 引用了未知学生 {agr.learner}")
        if agr.slot not in slot_ids:
            raise DataError(f"协议 {agr.agreement} 引用了未知席位 {agr.slot}")
        if agr.replaces and agr.replaces not in agr_ids:
            raise DataError(f"协议 {agr.agreement} 替代了未知协议 {agr.replaces}")

    for ack in registry.acknowledgements:
        if ack.agreement not in agr_ids:
            raise DataError(f"签认 {ack.entry} 引用了未知协议 {ack.agreement}")

    for req in registry.requirements:
        if req.min_hours <= 0:
            raise DataError(f"要求 {req.mode}/{req.competency} 时数必须为正数")
        if req.prerequisite and req.prerequisite == req.competency:
            raise DataError(f"要求 {req.mode}/{req.competency} 不能以前置自身")


def _validate_capacity(registry: Registry) -> None:
    for slot in registry.slots:
        if slot.end <= slot.start:
            raise DataError(f"席位 {slot.slot} 区间必须为非空左闭右开区间")
        if slot.seats <= 0 or slot.mentor_limit <= 0:
            raise DataError(f"席位 {slot.slot} 容量必须为正数")
        if slot.mentor_limit < slot.seats:
            raise DataError(f"席位 {slot.slot} 的导师容量小于席位数")
        if slot.hours <= 0:
            raise DataError(f"席位 {slot.slot} 认定时数必须为正数")

    # 同一导师、时间重叠的席位共用 mentor_limit，声明必须一致
    ordered = sorted(registry.slots, key=lambda s: (s.mentor, s.start, s.end))
    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            if right.mentor != left.mentor or right.start >= left.end:
                break
            if left.overlaps(right) and left.mentor_limit != right.mentor_limit:
                raise DataError(
                    f"导师 {left.mentor} 的重叠席位 {left.slot}/{right.slot} mentor_limit 不一致")
