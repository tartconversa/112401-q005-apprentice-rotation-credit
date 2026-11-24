"""毕业路径与轮岗排席规划。

两层问题分开回答：
- 单人视角：在保留已确认席位的前提下，哪些轮岗组合能在截止日前补齐缺口；
- 整组视角：多名学生同时安排时，席位 seats 与导师 mentor_limit 是否仍可兑现。

搜索基于小规模学期资料做有界枚举，所有组合都经过容量与前置资格检查，
不会产出“单独看可行、放在一起争用导师”的安排。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .capacity import check_bookings
from .models import Registry, Slot
from .recognition import Scenario, enumerate_scenarios
from .seating import (
    PHASE_COMPLETED,
    agreement_phase,
    baseline_bookings,
    completed_rotation_hours,
    effective_agreements,
)

# 毕业路径三分类
PATH_ON_TRACK = "on_track"              # 现有认定即可按期毕业
PATH_FEASIBLE = "feasible"              # 需新增轮岗，单人组合可兑现
PATH_NEEDS_CONFIRMATION = "needs_confirmation"  # 依赖待确认用途或互换
PATH_DEFICIENT = "deficient"            # 截止日前无可行组合

PLAN_CAP = 200


@dataclass(frozen=True)
class SoloPlan:
    learner: str
    mode: str
    scenario: Scenario
    fixed_slots: tuple[str, ...]        # 已确认、必须保留的席位
    added_slots: tuple[str, ...]        # 新增轮岗席位（按开始日排序）
    all_slots: tuple[str, ...]


@dataclass
class ModeAssessment:
    learner: str
    mode: str
    status: str
    best_scenarios: tuple[Scenario, ...]
    solo_plans: tuple[SoloPlan, ...]
    unresolved_proofs: frozenset[str]
    blocking_gaps: tuple[str, ...]


@dataclass
class CohortAssignment:
    learner: str
    mode: str
    slot_ids: tuple[str, ...]
    status: str


@dataclass
class CohortResult:
    as_of: date
    bookings: dict[str, tuple[str, ...]]
    assignments: tuple[CohortAssignment, ...]
    served: tuple[str, ...]
    unserved: tuple[dict, ...]
    feasible: bool
    capacity_violations: tuple[dict, ...] = field(default_factory=tuple)


def _fixed_slot_ids(registry: Registry, learner: str, as_of: date) -> tuple[str, ...]:
    ids: list[str] = []
    for agr in effective_agreements(registry, as_of):
        if agr.learner != learner:
            continue
        if agreement_phase(registry, agr, as_of) == PHASE_COMPLETED:
            continue
        ids.append(agr.slot)
    return tuple(sorted(set(ids)))


def _held_before(registry: Registry, learner: str, mode: str, as_of: date,
                 scenario: Scenario, fixed_slots: list[Slot],
                 chosen: list[Slot], slot: Slot) -> set[str]:
    """接席开始日前真正已具备的能力。

    证明只按当前认定候选实际满足的能力计入，不把“可认定但未认定”提前算作资格；
    已完成轮岗与开始日前结束的席位按 offers 计入。
    """
    held = set(scenario.satisfied)
    held.update(completed_rotation_hours(registry, learner, as_of))
    for done in fixed_slots + chosen:
        if done.end <= slot.start:
            held.add(done.offers)
    return held


def _candidate_slots(registry: Registry, learner: str, mode: str,
                     as_of: date) -> list[Slot]:
    person = registry.people_by_id[learner]
    requirements = {s.competency for s in registry.requirements if s.mode == mode}
    fixed = set(_fixed_slot_ids(registry, learner, as_of))
    candidates: list[Slot] = []
    for slot in sorted(registry.slots, key=lambda s: (s.start, s.slot)):
        if slot.slot in fixed:
            continue
        if slot.offers not in requirements:
            continue
        if not slot.finishes_by(person.deadline):
            continue
        candidates.append(slot)
    return candidates


def solo_plans(registry: Registry, learner: str, mode: str,
               as_of: date, scenario: Scenario | None = None) -> list[SoloPlan]:
    """枚举单人在截止日前可补齐缺口的轮岗组合（含必须保留的已确认席位）。"""
    fixed_ids = _fixed_slot_ids(registry, learner, as_of)
    fixed_slots = [registry.slots_by_id[sid] for sid in fixed_ids]
    completed_hours = completed_rotation_hours(registry, learner, as_of)

    if scenario is None:
        scenario = enumerate_scenarios(registry, learner, mode, as_of,
                                       completed_hours)[0]

    # 已确认但未完成的席位按期提供 offers，可直接冲抵缺口；其余缺口才需新增轮岗
    fixed_offers = {slot.offers for slot in fixed_slots}
    open_gaps = {gap.competency for gap in scenario.gaps
                 if gap.competency not in fixed_offers}
    if not open_gaps:
        return [SoloPlan(learner, mode, scenario, fixed_ids, (), fixed_ids)]

    candidates = _candidate_slots(registry, learner, mode, as_of)

    plans: list[SoloPlan] = []
    seen: set[tuple[str, ...]] = set()

    def search(chosen: list[Slot], remaining: set[str], pool: list[Slot]) -> None:
        if len(plans) >= PLAN_CAP:
            return
        if not remaining:
            key = tuple(sorted(s.slot for s in chosen))
            if key not in seen:
                seen.add(key)
                added = tuple(s.slot for s in sorted(chosen, key=lambda s: s.start))
                plans.append(SoloPlan(
                    learner, mode, scenario, fixed_ids, added,
                    tuple(sorted(set(fixed_ids) | set(added)))))
            return
        for index, slot in enumerate(pool):
            if slot.offers not in remaining:
                continue
            held = _held_before(registry, learner, mode, as_of, scenario,
                                fixed_slots, chosen, slot)
            if any(req not in held for req in slot.requires):
                continue
            search(chosen + [slot], remaining - {slot.offers}, pool[index + 1:])

    search([], set(open_gaps), candidates)
    return plans


def assess_mode(registry: Registry, learner: str, mode: str,
                as_of: date) -> ModeAssessment:
    completed_hours = completed_rotation_hours(registry, learner, as_of)
    scenarios = enumerate_scenarios(registry, learner, mode, as_of, completed_hours)
    best = min(len(s.gaps) for s in scenarios)
    best_scenarios = tuple(s for s in scenarios if len(s.gaps) == best)
    unresolved = frozenset().union(*(s.unresolved_proofs for s in best_scenarios)) \
        if best_scenarios else frozenset()

    plans: list[SoloPlan] = []
    if best > 0:
        for scenario in best_scenarios:
            plans.extend(solo_plans(registry, learner, mode, as_of, scenario))

    blocking = tuple(sorted({gap.competency for s in best_scenarios
                             for gap in s.gaps}))
    if best == 0:
        status = PATH_NEEDS_CONFIRMATION if unresolved else PATH_ON_TRACK
    elif plans:
        status = PATH_NEEDS_CONFIRMATION if unresolved else PATH_FEASIBLE
    else:
        status = PATH_DEFICIENT
    return ModeAssessment(learner, mode, status, best_scenarios,
                          tuple(plans[:PLAN_CAP]), unresolved, blocking)


def assess_learner(registry: Registry, learner: str,
                   as_of: date) -> list[ModeAssessment]:
    person = registry.people_by_id[learner]
    return [assess_mode(registry, learner, mode, as_of)
            for mode in person.mode_options]


def plan_cohort(registry: Registry, as_of: date,
                learners: list[str] | None = None) -> CohortResult:
    """整组联合排席：在同一套席位/导师容量下最大化可按期毕业人数。"""
    chosen_learners = learners or [p.learner for p in registry.people]
    fixed = baseline_bookings(registry, as_of)

    options: dict[str, list[tuple[str, SoloPlan]]] = {}
    for learner in chosen_learners:
        picks: list[tuple[str, SoloPlan]] = []
        seen_plans: set[tuple[str, tuple[str, ...]]] = set()
        for assessment in assess_learner(registry, learner, as_of):
            for plan in assessment.solo_plans:
                key = (assessment.mode, plan.all_slots)
                if key in seen_plans:
                    continue
                seen_plans.add(key)
                picks.append((assessment.mode, plan))
        options[learner] = picks

    # 无备选方向的学生先排（A3 只有 inspection），同档按学号保证结果稳定
    def option_count(learner: str) -> int:
        return len(registry.people_by_id[learner].mode_options)

    order = sorted(chosen_learners, key=lambda l: (option_count(l), l))

    def served_score(learner_ids: tuple[str, ...]) -> tuple:
        # 同规模时优先保住方向选择少的学生，其次按学号稳定输出
        return (tuple(sorted((option_count(l), l) for l in learner_ids)),)

    holder: dict[str, object] = {"served": -1, "score": None, "selection": {}}

    def bookings_with(selection: dict[str, tuple[str, SoloPlan]]
                      ) -> dict[str, tuple[str, ...]]:
        # 以计划的全部席位（含保留的已确认席位）重建联合占用
        bookings: dict[str, list[str]] = {s.slot: [] for s in registry.slots}
        for learner, (_, plan) in selection.items():
            for slot_id in plan.all_slots:
                bookings.setdefault(slot_id, []).append(learner)
        # 本轮未排入的学生仍保留其既有确认席位
        selected = set(selection)
        for slot_id, learners in fixed.items():
            for learner in learners:
                if learner not in selected:
                    bookings.setdefault(slot_id, []).append(learner)
        return {slot: tuple(dict.fromkeys(ls)) for slot, ls in bookings.items()}

    def search(index: int, selection: dict[str, tuple[str, SoloPlan]]) -> None:
        if index == len(order):
            served = len(selection)
            score = served_score(tuple(sorted(selection.keys())))
            better = served > holder["served"] or (
                served == holder["served"]
                and (holder["score"] is None or score < holder["score"]))
            if better:
                probe = bookings_with(selection)
                if not check_bookings(registry, probe):
                    holder["served"] = served
                    holder["score"] = score
                    holder["selection"] = dict(selection)
            return
        # 只在连追平已知最优都不可能时剪枝；同规模但成员不同的解必须保留，
        # 否则无备选方向的学生（如 A3）会被先找到的组合挤出结果
        if len(selection) + (len(order) - index) < holder["served"]:
            return
        learner = order[index]
        for mode, plan in options.get(learner, ()):
            trial = dict(selection)
            trial[learner] = (mode, plan)
            probe = bookings_with(trial)
            if check_bookings(registry, probe):
                continue  # 该组合已触发容量冲突，不能继续扩展
            search(index + 1, trial)
        search(index + 1, selection)  # 该学生本轮无法排入

    search(0, {})
    best: dict[str, tuple[str, SoloPlan]] = holder["selection"]
    best_served = holder["served"]
    final_bookings = bookings_with(best)
    violations = tuple(vars(v) for v in check_bookings(registry, final_bookings))
    assignments = tuple(
        CohortAssignment(learner=learner, mode=mode,
                         slot_ids=plan.all_slots, status="served")
        for learner, (mode, plan) in sorted(best.items()))
    served = tuple(sorted(best))
    unserved = []
    for learner in order:
        if learner in best:
            continue
        assessment = assess_learner(registry, learner, as_of)
        reasons = tuple(sorted({
            gap.competency for a in assessment
            for s in a.best_scenarios for gap in s.gaps}))
        unserved.append({"learner": learner, "reason": "capacity_contention",
                         "open_gaps": reasons})
    return CohortResult(
        as_of=as_of,
        bookings=final_bookings,
        assignments=assignments,
        served=served,
        unserved=tuple(unserved),
        feasible=not unserved,
        capacity_violations=violations,
    )
