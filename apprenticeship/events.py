"""学期事件：导师撤回证明与席位交接暂停。

这些操作返回新的 Registry（输入保持不变）与一份影响报告，
让学籍与企业分别看到自己需要重核的部分：
- 撤回证明后，记录仍在但学分不可用，相关前置资格与互换依据同时失效；
- 已完成轮岗不可回滚；尚未开始的席位可暂停交接，暂停可恢复。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from .models import (
    PROOF_WITHDRAWN,
    Registry,
)
from .seating import (
    PHASE_COMPLETED,
    PHASE_SCHEDULED,
    agreement_phase,
    all_group_statuses,
)

PAUSED = "paused"


@dataclass
class WithdrawalReport:
    proof_id: str
    learner: str
    affected_modes: tuple[str, ...]
    stale_swap_groups: tuple[str, ...]
    impacted_slots: tuple[str, ...]          # 以该证明候选能力为入场前置的席位
    completed_rotations_locked: tuple[str, ...]


@dataclass
class PauseReport:
    agreement_id: str
    slot: str
    learner: str
    phase: str
    paused: bool
    reason: str


def withdraw_proof(registry: Registry, proof_id: str,
                   as_of: date) -> tuple[Registry, WithdrawalReport]:
    """把证明标记为撤回，并汇总需要学籍/企业重核的所有下游对象。"""
    target = registry.proofs_by_id.get(proof_id)
    if target is None:
        raise KeyError(f"未知证明 {proof_id}")

    updated_proofs = [
        replace(p, state=PROOF_WITHDRAWN) if p.proof == proof_id else p
        for p in registry.proofs
    ]
    new_registry = replace(registry, proofs=updated_proofs)
    new_registry.__post_init__()

    person = registry.people_by_id[target.learner]
    affected_modes = tuple(person.mode_options)

    # 任何把该证明当作签认依据的互换组都要重核；组可能已被拒绝，
    # 但失效依据仍需留痕，避免学籍只看到“拒绝”而漏掉前置重核
    stale_groups = tuple(sorted(
        gs.group for gs in all_group_statuses(new_registry, as_of)
        if proof_id in gs.stale_sources))

    impacted_slots = tuple(sorted({
        slot.slot for slot in registry.slots
        if any(req in target.uses for req in slot.requires)}))

    locked = tuple(sorted({
        agr.agreement for agr in registry.agreements
        if agr.learner == target.learner
        and agreement_phase(registry, agr, as_of) == PHASE_COMPLETED}))

    return new_registry, WithdrawalReport(
        proof_id=proof_id,
        learner=target.learner,
        affected_modes=affected_modes,
        stale_swap_groups=stale_groups,
        impacted_slots=impacted_slots,
        completed_rotations_locked=locked,
    )


def pause_agreement(registry: Registry, agreement_id: str,
                    as_of: date, *, resume: bool = False) -> tuple[Registry, PauseReport]:
    """暂停（或恢复）尚未开始的席位交接；进行中/已完成的协议拒绝操作。"""
    agr = registry.agreements_by_id.get(agreement_id)
    if agr is None:
        raise KeyError(f"未知协议 {agreement_id}")
    phase = agreement_phase(registry, agr, as_of)
    if phase != PHASE_SCHEDULED:
        return registry, PauseReport(
            agreement_id, agr.slot, agr.learner, phase, False,
            f"席位处于 {phase} 阶段，不可暂停（已完成轮岗不可回滚）")

    # 暂停状态是 Registry 的显式字段，不改动原始 CSV
    paused_set = set(registry.paused_agreements)
    if resume:
        paused_set.discard(agreement_id)
        reason = "已恢复交接"
    else:
        reason = "本就处于暂停状态" if agreement_id in paused_set \
            else "席位尚未开始，交接已暂停"
        paused_set.add(agreement_id)
    new_registry = replace(registry, paused_agreements=frozenset(paused_set))
    return new_registry, PauseReport(
        agreement_id, agr.slot, agr.learner, phase, True, reason)


def paused_agreements(registry: Registry) -> frozenset[str]:
    return registry.paused_agreements
