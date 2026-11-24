"""席位协议与互换承诺的状态机。

规则要点：
- 非空 group 的多条提议是一个互换承诺，任一方 declined 整组失效，原持有人保留席位；
- 全部所需签认 accepted 才生效，生效日取最后一条 accepted 的 recorded；
- pending 表示安排仍需重新确认，不能当作既成席位；
- 旧协议引用不会随提议删除，只在互换生效时被替换；
- 已完成轮岗不可回滚，尚未开始的席位可以暂停交接。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import (
    ACK_ACCEPTED,
    ACK_DECLINED,
    ACK_PENDING,
    AGR_CONFIRMED,
    AGR_PROPOSED,
    PROOF_CONFIRMED,
    Acknowledgement,
    Agreement,
    Registry,
    Slot,
)
from .recognition import active_proofs

GROUP_EFFECTIVE = "effective"      # 全部签认通过，互换已生效
GROUP_PENDING = "pending"          # 仍有签认未完成
GROUP_DECLINED = "declined"        # 有一方拒绝，整组作废
GROUP_STALE = "stale_basis"        # 签认依据的证明已撤回，需重核

# 协议在 as_of 时点所处的执行阶段
PHASE_COMPLETED = "completed"      # 轮岗已完成，锁定不可回滚
PHASE_ACTIVE = "active"            # 轮岗进行中
PHASE_SCHEDULED = "scheduled"      # 尚未开始，可暂停交接


@dataclass
class GroupStatus:
    group: str
    state: str
    members: tuple[Agreement, ...]
    replaces: tuple[str, ...]
    acks: tuple[Acknowledgement, ...]
    stale_sources: tuple[str, ...]
    effective_on: date | None
    blocking_parties: tuple[str, ...]      # 仍未完成签认的角色
    declined_parties: tuple[str, ...]


@dataclass
class Projection:
    """一组席位安排在容量与前置资格上的可兑现性。"""
    bookings: dict[str, tuple[str, ...]]
    violations: tuple[dict, ...]
    deadline_misses: tuple[dict, ...]
    ineligible: tuple[dict, ...]
    feasible: bool


def swap_groups(registry: Registry) -> dict[str, list[Agreement]]:
    groups: dict[str, list[Agreement]] = {}
    for agr in registry.agreements:
        if agr.status == AGR_PROPOSED and agr.group:
            groups.setdefault(agr.group, []).append(agr)
    return dict(sorted(groups.items()))


def _is_stale_source(registry: Registry, source_id: str | None, as_of: date) -> bool:
    if not source_id:
        return False
    proof = registry.proofs_by_id.get(source_id)
    if proof is None:
        return False
    if proof.state != PROOF_CONFIRMED:
        return True
    # 被新的确认证明替代也意味着旧依据失效
    return any(p.replaces == proof.proof and p.state == PROOF_CONFIRMED
               and p.received <= as_of for p in registry.proofs)


def group_status(registry: Registry, group_id: str, as_of: date) -> GroupStatus:
    members = tuple(swap_groups(registry).get(group_id, ()))
    if not members:
        raise KeyError(f"未知互换组 {group_id}")
    acks = tuple(k for agr in members for k in registry.acks_for(agr.agreement))
    declined = tuple(sorted({k.party for k in acks if k.state == ACK_DECLINED}))
    stale = tuple(sorted({
        k.source_id for k in acks
        if k.source_id and _is_stale_source(registry, k.source_id, as_of)
    }))
    blocking = tuple(sorted({
        k.party for k in acks
        if k.state in (ACK_PENDING, ACK_DECLINED)
    }))
    accepted_dates = [k.recorded for k in acks if k.state == ACK_ACCEPTED]
    replaces = tuple(a.replaces for a in members if a.replaces)

    if declined:
        state = GROUP_DECLINED
        effective_on = None
    elif stale:
        state = GROUP_STALE
        effective_on = None
    elif all(k.state == ACK_ACCEPTED for k in acks) and acks:
        state = GROUP_EFFECTIVE
        effective_on = max(accepted_dates)
    else:
        state = GROUP_PENDING
        effective_on = None
    return GroupStatus(
        group=group_id, state=state, members=members, replaces=replaces,
        acks=acks, stale_sources=stale, effective_on=effective_on,
        blocking_parties=blocking, declined_parties=declined,
    )


def all_group_statuses(registry: Registry, as_of: date) -> list[GroupStatus]:
    return [group_status(registry, gid, as_of) for gid in swap_groups(registry)]


def effective_group_ids(registry: Registry, as_of: date) -> set[str]:
    return {gs.group for gs in all_group_statuses(registry, as_of)
            if gs.state == GROUP_EFFECTIVE and gs.effective_on is not None
            and gs.effective_on <= as_of}


def effective_agreements(registry: Registry, as_of: date) -> list[Agreement]:
    """as_of 时点真正持有席位的协议（互换生效后旧协议被替换）。"""
    effective_groups = effective_group_ids(registry, as_of)
    replaced: set[str] = set()
    for status in all_group_statuses(registry, as_of):
        if status.group in effective_groups:
            replaced.update(status.replaces)
    result: list[Agreement] = []
    for agr in registry.agreements:
        if agr.agreement in replaced:
            continue
        if agr.status == AGR_CONFIRMED:
            result.append(agr)
        elif agr.status == AGR_PROPOSED and agr.group in effective_groups:
            result.append(agr)
    return result


def baseline_bookings(registry: Registry, as_of: date) -> dict[str, tuple[str, ...]]:
    """保留已确认席位前提下的当前占用：未生效提议不计入。"""
    bookings: dict[str, list[str]] = {s.slot: [] for s in registry.slots}
    for agr in effective_agreements(registry, as_of):
        bookings.setdefault(agr.slot, []).append(agr.learner)
    return {slot: tuple(learners) for slot, learners in bookings.items()}


def projected_bookings(registry: Registry, as_of: date,
                       group_ids: set[str] | None = None) -> dict[str, tuple[str, ...]]:
    """假设指定互换组生效后的占用；默认把所有非拒绝、非失效组都纳入假设。"""
    bookings: dict[str, list[str]] = {s.slot: [] for s in registry.slots}
    statuses = {gs.group: gs for gs in all_group_statuses(registry, as_of)}
    chosen = set(statuses) if group_ids is None else set(group_ids)
    replaced: set[str] = set()
    projected_agreements: list[Agreement] = []
    for gid in chosen:
        status = statuses[gid]
        if status.state in (GROUP_DECLINED, GROUP_STALE):
            continue
        replaced.update(status.replaces)
        projected_agreements.extend(status.members)
    for agr in registry.agreements:
        if agr.status != AGR_CONFIRMED or agr.agreement in replaced:
            continue
        projected_agreements.append(agr)
    for agr in projected_agreements:
        bookings.setdefault(agr.slot, []).append(agr.learner)
    return {slot: tuple(learners) for slot, learners in bookings.items()}


def agreement_phase(registry: Registry, agr: Agreement, as_of: date) -> str:
    slot = registry.slots_by_id[agr.slot]
    # 左闭右开：as_of 到达 end 当日学员已离场，才算完成
    if as_of >= slot.end:
        return PHASE_COMPLETED
    if as_of >= slot.start:
        return PHASE_ACTIVE
    return PHASE_SCHEDULED


def pausable_agreements(registry: Registry, as_of: date) -> list[Agreement]:
    """尚未开始、可以暂停交接的协议（已完成/进行中不可暂停）。"""
    return [agr for agr in effective_agreements(registry, as_of)
            if agreement_phase(registry, agr, as_of) == PHASE_SCHEDULED]


def completed_rotation_hours(registry: Registry, learner: str,
                             as_of: date) -> dict[str, int]:
    """已完成轮岗带来的能力时数；进行中或未开始的不提前计学分。"""
    hours: dict[str, int] = {}
    for agr in effective_agreements(registry, as_of):
        if agr.learner != learner:
            continue
        if agreement_phase(registry, agr, as_of) != PHASE_COMPLETED:
            continue
        slot = registry.slots_by_id[agr.slot]
        hours[slot.offers] = hours.get(slot.offers, 0) + slot.hours
    return hours


def evaluate_projection(registry: Registry, bookings: dict[str, tuple[str, ...]],
                        as_of: date) -> Projection:
    """对一组占用做容量、截止日与入场前置资格的完整检查。"""
    from .capacity import check_bookings
    violations = [vars(v) for v in check_bookings(registry, bookings)]

    deadline_misses: list[dict] = []
    ineligible: list[dict] = []
    for slot_id, learners in bookings.items():
        if not learners:
            continue
        slot = registry.slots_by_id[slot_id]
        for learner in dict.fromkeys(learners):
            person = registry.people_by_id[learner]
            if not slot.finishes_by(person.deadline):
                deadline_misses.append({
                    "learner": learner, "slot": slot_id,
                    "slot_end": slot.end.isoformat(),
                    "deadline": person.deadline.isoformat(),
                })
            held = _held_before_slot(registry, learner, slot, as_of)
            missing = [req for req in slot.requires if req not in held]
            if missing:
                ineligible.append({
                    "learner": learner, "slot": slot_id, "missing": tuple(missing),
                })

    feasible = not violations and not deadline_misses and not ineligible
    return Projection(
        bookings=bookings,
        violations=tuple(violations),
        deadline_misses=tuple(deadline_misses),
        ineligible=tuple(ineligible),
        feasible=feasible,
    )


def _held_before_slot(registry: Registry, learner: str, slot: Slot,
                      as_of: date) -> set[str]:
    """接席之前学员已经具备的能力：有效证明候选 + 已完成轮岗。"""
    held: set[str] = set()
    # 证明可认定的任一候选能力都视为“可具备”，具体用途仍留给认定候选
    for proof in active_proofs(registry, learner, as_of):
        held.update(proof.uses)
    for agr in effective_agreements(registry, as_of):
        if agr.learner != learner:
            continue
        done_slot = registry.slots_by_id[agr.slot]
        if done_slot.end <= slot.start:
            held.add(done_slot.offers)
    return held
