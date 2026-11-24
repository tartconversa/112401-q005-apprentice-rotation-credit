"""学分认定：有效证明、一次性时数使用与候选分配枚举。

核心纪律：
- 同一段实作时数在一个毕业方向内只能使用一次，证明只能落在一个候选能力上；
- group 非空的整套实作要么全部认定、要么全部不用；
- 撤回的证明“记录尚在、学分不可用”；被新确认证明替代的旧证明同样退出有效集；
- 资料无法区分用途时保留全部候选，由学籍人员确认，本模块不替学校做决定。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import product

from .models import PROOF_CONFIRMED, Proof, Registry, Requirement

# 证明在账面上的状态
LEDGER_ACTIVE = "active"            # 可用于认定
LEDGER_WITHDRAWN = "withdrawn"      # 导师撤回：记录保留、学分不可用
LEDGER_SUPERSEDED = "superseded"    # 已被新的确认证明替代
LEDGER_PENDING = "pending"          # 资料尚未在 as_of 前收到


@dataclass(frozen=True)
class LedgerEntry:
    proof: Proof
    ledger_state: str
    superseded_by: str | None = None


@dataclass(frozen=True)
class Gap:
    competency: str
    required_hours: int
    current_hours: int
    missing_hours: int
    prerequisite: str | None
    prereq_met: bool

    @property
    def blocked(self) -> bool:
        return self.prerequisite is not None and not self.prereq_met


@dataclass
class Scenario:
    """一种完整的认定选择及其能力达成结果。"""
    mode: str
    assignment: dict[str, str | None]   # proof_id -> 能力（None 表示本方向不使用）
    used_groups: frozenset[str]
    hours_by_competency: dict[str, int]
    satisfied: frozenset[str]
    gaps: tuple[Gap, ...]
    unresolved_proofs: frozenset[str]   # 用途无法从记录区分、需学籍确认的证明
    determined: bool

    @property
    def complete(self) -> bool:
        return not self.gaps


def active_requirements(registry: Registry, mode: str, as_of: date) -> dict[str, Requirement]:
    """取 as_of 当日生效的公布口径：同一能力取 version 最新且已公布者。"""
    chosen: dict[str, Requirement] = {}
    for req in registry.requirements:
        if req.mode != mode or req.active_from > as_of:
            continue
        current = chosen.get(req.competency)
        if current is None or req.version > current.version:
            chosen[req.competency] = req
    return chosen


def proof_ledger(registry: Registry, learner: str, as_of: date) -> list[LedgerEntry]:
    """按学生列出证明账面状态，撤回与被替代者保留记录但不携带学分。"""
    mine = registry.proofs_for(learner)
    supersessions: dict[str, str] = {}
    for proof in mine:
        if proof.state == PROOF_CONFIRMED and proof.received <= as_of and proof.replaces:
            supersessions[proof.replaces] = proof.proof

    entries: list[LedgerEntry] = []
    for proof in mine:
        if proof.state != PROOF_CONFIRMED:
            entries.append(LedgerEntry(proof, LEDGER_WITHDRAWN))
        elif proof.received > as_of:
            entries.append(LedgerEntry(proof, LEDGER_PENDING))
        elif proof.proof in supersessions:
            entries.append(LedgerEntry(proof, LEDGER_SUPERSEDED,
                                       supersessions[proof.proof]))
        else:
            entries.append(LedgerEntry(proof, LEDGER_ACTIVE))
    return entries


def active_proofs(registry: Registry, learner: str, as_of: date) -> list[Proof]:
    return [entry.proof for entry in proof_ledger(registry, learner, as_of)
            if entry.ledger_state == LEDGER_ACTIVE]


def _valid_uses(proof: Proof, requirements: dict[str, Requirement]) -> tuple[str, ...]:
    return tuple(use for use in proof.uses if use in requirements)


def _resolve(requirements: dict[str, Requirement],
             hours_by_comp: dict[str, int]) -> tuple[frozenset[str], tuple[Gap, ...]]:
    """按前置链判定能力是否达成；前置不满足的缺口标记为 blocked。"""
    satisfied: set[str] = set()
    gaps: list[Gap] = []

    def is_met(comp: str) -> bool:
        if comp in satisfied:
            return True
        req = requirements.get(comp)
        if req is None:
            return False
        if req.prerequisite and not is_met(req.prerequisite):
            return False
        if hours_by_comp.get(comp, 0) >= req.min_hours:
            satisfied.add(comp)
            return True
        return False

    # 递归会在 is_met 中顺带记录 satisfied；缺口单独逐项展开
    for comp, req in requirements.items():
        have = hours_by_comp.get(comp, 0)
        prereq_met = req.prerequisite is None or is_met(req.prerequisite)
        if not is_met(comp):
            gaps.append(Gap(
                competency=comp,
                required_hours=req.min_hours,
                current_hours=have,
                missing_hours=max(0, req.min_hours - have),
                prerequisite=req.prerequisite,
                prereq_met=prereq_met,
            ))
    return frozenset(satisfied), tuple(gaps)


def enumerate_scenarios(registry: Registry, learner: str, mode: str,
                        as_of: date,
                        extra_hours: dict[str, int] | None = None) -> list[Scenario]:
    """枚举该学生在指定方向下所有互不相同的认定选择。

    extra_hours 用于并入已完成轮岗带来的能力时数（同样受前置链约束）。
    """
    requirements = active_requirements(registry, mode, as_of)
    if not requirements:
        raise ValueError(f"方向 {mode} 在 {as_of} 没有生效的能力口径")

    proofs = active_proofs(registry, learner, as_of)
    grouped: dict[str, list[Proof]] = {}
    loose: list[Proof] = []
    for proof in proofs:
        if proof.group:
            grouped.setdefault(proof.group, []).append(proof)
        else:
            loose.append(proof)

    # 每个决策单元的候选：dict[proof_id -> use|None]
    units: list[list[dict[str, str | None]]] = []
    for proof in loose:
        choices: list[dict[str, str | None]] = [{proof.proof: None}]
        choices.extend({proof.proof: use} for use in _valid_uses(proof, requirements))
        units.append(choices)
    for group_id, members in grouped.items():
        member_uses = [_valid_uses(proof, requirements) for proof in members]
        choices = [{p.proof: None for p in members}]  # 整套不用
        if all(member_uses):
            for combo in product(*member_uses):
                choices.append({p.proof: use for p, use in zip(members, combo)})
        units.append(choices)

    seen: set[tuple[tuple[str, str | None], ...]] = set()
    scenarios: list[Scenario] = []
    base_hours = dict(extra_hours or {})
    for combo in product(*units):
        assignment: dict[str, str | None] = {}
        for choice in combo:
            assignment.update(choice)
        key = tuple(sorted(assignment.items()))
        if key in seen:
            continue
        seen.add(key)

        hours_by_comp: dict[str, int] = dict(base_hours)
        used_groups: set[str] = set()
        unresolved: set[str] = set()
        for proof in proofs:
            use = assignment[proof.proof]
            if use is None:
                continue
            hours_by_comp[use] = hours_by_comp.get(use, 0) + proof.hours
            if proof.group:
                used_groups.add(proof.group)
            if len(_valid_uses(proof, requirements)) > 1:
                unresolved.add(proof.proof)

        satisfied, gaps = _resolve(requirements, hours_by_comp)
        scenarios.append(Scenario(
            mode=mode,
            assignment=assignment,
            used_groups=frozenset(used_groups),
            hours_by_competency=hours_by_comp,
            satisfied=satisfied,
            gaps=gaps,
            unresolved_proofs=frozenset(unresolved),
            determined=not unresolved,
        ))

    scenarios.sort(key=lambda s: (len(s.gaps), not s.determined,
                                  str(tuple(sorted(s.assignment.items())))))
    return scenarios


def best_scenarios(scenarios: list[Scenario]) -> list[Scenario]:
    """缺口最少的一组候选；存在多个即代表学籍人员需要确认。"""
    if not scenarios:
        return []
    fewest = min(len(s.gaps) for s in scenarios)
    return [s for s in scenarios if len(s.gaps) == fewest]
