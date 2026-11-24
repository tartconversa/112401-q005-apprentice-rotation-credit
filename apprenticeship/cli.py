"""命令行入口：按学期提交查询，输出可人工阅读或机读的结果。"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path

from .dates import parse_date
from .events import pause_agreement, withdraw_proof
from .loader import DataError, load_registry
from .planning import (
    PATH_DEFICIENT,
    PATH_FEASIBLE,
    PATH_NEEDS_CONFIRMATION,
    PATH_ON_TRACK,
    assess_learner,
    plan_cohort,
)
from .recognition import (
    LEDGER_ACTIVE,
    LEDGER_PENDING,
    LEDGER_SUPERSEDED,
    LEDGER_WITHDRAWN,
    best_scenarios,
    enumerate_scenarios,
    proof_ledger,
)
from .seating import (
    GROUP_DECLINED,
    GROUP_EFFECTIVE,
    GROUP_PENDING,
    GROUP_STALE,
    PHASE_ACTIVE,
    PHASE_COMPLETED,
    PHASE_SCHEDULED,
    agreement_phase,
    all_group_statuses,
    baseline_bookings,
    completed_rotation_hours,
    effective_agreements,
    evaluate_projection,
    group_status,
    pausable_agreements,
    projected_bookings,
)

STATUS_LABELS = {
    PATH_ON_TRACK: "按期毕业",
    PATH_FEASIBLE: "可经新增轮岗完成",
    PATH_NEEDS_CONFIRMATION: "需学籍确认用途",
    PATH_DEFICIENT: "截止日前缺毕业条件",
}
GROUP_LABELS = {
    GROUP_EFFECTIVE: "已生效",
    GROUP_PENDING: "待确认",
    GROUP_DECLINED: "被拒绝（原席位保留）",
    GROUP_STALE: "依据失效需重核",
}
PHASE_LABELS = {
    PHASE_COMPLETED: "已完成（锁定）",
    PHASE_ACTIVE: "进行中",
    PHASE_SCHEDULED: "未开始（可暂停）",
}
LEDGER_LABELS = {
    LEDGER_ACTIVE: "有效",
    LEDGER_WITHDRAWN: "已撤回：记录在、学分不可用",
    LEDGER_SUPERSEDED: "已被新证明替代",
    LEDGER_PENDING: "资料未到确认时点",
}

DEFAULT_SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, frozenset, set)):
        return [to_jsonable(v) for v in value]
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, date):
        return value.isoformat()
    return value


def _print_json(payload) -> None:
    print(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))


def _as_of(args) -> date:
    return parse_date(args.as_of) if args.as_of else date.today()


def cmd_credit(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    person = registry.people_by_id[args.learner]
    payload = {"learner": args.learner, "as_of": as_of, "modes": []}
    for mode in person.mode_options:
        # 已完成轮岗的认定时数与证明时数合并，口径与规划视图一致
        rotation_hours = completed_rotation_hours(registry, args.learner, as_of)
        scenarios = enumerate_scenarios(
            registry, args.learner, mode, as_of,
            extra_hours=rotation_hours)
        best = best_scenarios(scenarios)
        payload["modes"].append({
            "mode": mode,
            "rotation_hours": rotation_hours,
            "candidate_count": len(scenarios),
            "best": best,
        })
    if args.json:
        _print_json(payload)
        return
    print(f"学生 {args.learner} 的学分认定候选（截至 {as_of}）")
    for block in payload["modes"]:
        print(f"\n方向 {block['mode']}：共 {block['candidate_count']} 种认定选择")
        for index, scenario in enumerate(block["best"], 1):
            label = "确定" if scenario.determined else "待学籍确认"
            print(f"  候选 {index} [{label}] 缺口 {len(scenario.gaps)} 项")
            for proof_id, use in sorted(scenario.assignment.items()):
                if use is not None:
                    print(f"    {proof_id} -> {use}")
            for gap in scenario.gaps:
                flag = "（前置未满足）" if gap.blocked else ""
                print(f"    缺口 {gap.competency}: 有 {gap.current_hours}/"
                      f"{gap.required_hours} 小时，缺 {gap.missing_hours}{flag}")
            if scenario.unresolved_proofs:
                print(f"    待确认证明：{', '.join(sorted(scenario.unresolved_proofs))}")


def cmd_ledger(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    entries = proof_ledger(registry, args.learner, as_of)
    if args.json:
        _print_json({"learner": args.learner, "as_of": as_of, "entries": entries})
        return
    print(f"学生 {args.learner} 的证明账面（截至 {as_of}）")
    for entry in entries:
        proof = entry.proof
        extra = f"，替代者 {entry.superseded_by}" if entry.superseded_by else ""
        print(f"  {proof.proof} {proof.hours}h 用途 {'|'.join(proof.uses) or '（空）'}"
              f" -> {LEDGER_LABELS[entry.ledger_state]}{extra}")


def cmd_swaps(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    statuses = all_group_statuses(registry, as_of)
    if args.json:
        _print_json({"as_of": as_of, "groups": statuses})
        return
    print(f"互换承诺状态（截至 {as_of}）")
    if not statuses:
        print("  没有互换提议")
    for status in statuses:
        print(f"\n互换组 {status.group}：{GROUP_LABELS[status.state]}")
        if status.effective_on:
            print(f"  生效日期：{status.effective_on.isoformat()}")
        for agr in status.members:
            print(f"  提议 {agr.agreement}: {agr.learner} 接 {agr.slot}"
                  f"（替换 {agr.replaces or '—'}）")
        for ack in status.acks:
            print(f"  签认 {ack.entry}: {ack.party}={ack.state}"
                  f"（依据 {ack.source_id or '—'}）")
        if status.declined_parties:
            print(f"  拒绝方：{', '.join(status.declined_parties)}，原持有人保留席位")
        if status.stale_sources:
            print(f"  失效依据：{', '.join(status.stale_sources)}，需重核前置资格")


def cmd_plan(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    payload = {"as_of": as_of, "learners": [], "cohort": plan_cohort(registry, as_of)}
    for person in registry.people:
        if args.learner and person.learner != args.learner:
            continue
        payload["learners"].append({
            "learner": person.learner,
            "deadline": person.deadline,
            "assessments": assess_learner(registry, person.learner, as_of),
        })
    if args.json:
        _print_json(payload)
        return
    print(f"毕业路径与轮岗规划（截至 {as_of}）")
    for block in payload["learners"]:
        print(f"\n学生 {block['learner']}（截止 {block['deadline']}）")
        for assessment in block["assessments"]:
            print(f"  方向 {assessment.mode}: {STATUS_LABELS[assessment.status]}")
            for plan in assessment.solo_plans[:5]:
                added = ", ".join(plan.added_slots) or "无需新增轮岗"
                print(f"    单人组合：保留 {list(plan.fixed_slots)}；新增 {added}")
            if assessment.unresolved_proofs:
                print(f"    待确认用途证明：{', '.join(sorted(assessment.unresolved_proofs))}")
            if assessment.status == PATH_DEFICIENT:
                print(f"    无法补齐的能力：{', '.join(assessment.blocking_gaps)}")
    cohort = payload["cohort"]
    print("\n整组联合排席")
    print(f"  可按期毕业：{', '.join(cohort.served) or '无'}")
    for item in cohort.unserved:
        print(f"  容量争用无法排入：{item['learner']}，缺口 {item['open_gaps']}")
    for slot_id, learners in sorted(cohort.bookings.items()):
        if learners:
            print(f"  席位 {slot_id}: {', '.join(learners)}")


def cmd_seats(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    baseline = baseline_bookings(registry, as_of)
    projection_bookings = projected_bookings(registry, as_of)
    baseline_eval = evaluate_projection(registry, baseline, as_of)
    projected_eval = evaluate_projection(registry, projection_bookings, as_of)
    payload = {
        "as_of": as_of,
        "baseline": baseline_eval,
        "projected": projected_eval,
        "pausable": [vars(a) for a in pausable_agreements(registry, as_of)],
        "phases": [
            {"agreement": a.agreement, "learner": a.learner, "slot": a.slot,
             "phase": agreement_phase(registry, a, as_of)}
            for a in effective_agreements(registry, as_of)
        ],
    }
    if args.json:
        _print_json(payload)
        return
    print(f"席位占用与可兑现性（截至 {as_of}）")
    for label, evaluation in (("保留确认席位", baseline_eval),
                              ("假设全部待决互换通过", projected_eval)):
        print(f"\n{label}：{'可兑现' if evaluation.feasible else '存在冲突'}")
        for violation in evaluation.violations:
            print(f"  容量冲突：{violation['detail']}（{', '.join(violation['occupants'])}）")
        for miss in evaluation.deadline_misses:
            print(f"  超截止日：{miss['learner']} 的 {miss['slot']}")
        for bad in evaluation.ineligible:
            print(f"  前置不满足：{bad['learner']} 的 {bad['slot']} 缺 {list(bad['missing'])}")
    print("\n协议阶段")
    for item in payload["phases"]:
        print(f"  {item['agreement']} {item['learner']} {item['slot']}："
              f"{PHASE_LABELS[item['phase']]}")


def cmd_withdraw(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    new_registry, report = withdraw_proof(registry, args.proof, as_of)
    # 撤回后同一学生的认定与席位需立刻重核
    reassessment = assess_learner(new_registry, report.learner, as_of)
    payload = {"report": report, "reassessment": reassessment}
    if args.json:
        _print_json(payload)
        return
    print(f"撤回证明 {args.proof}（学生 {report.learner}）")
    print(f"  受影响方向：{', '.join(report.affected_modes)}")
    print(f"  失效互换组：{', '.join(report.stale_swap_groups) or '无'}")
    print(f"  需企业重核的席位：{', '.join(report.impacted_slots) or '无'}")
    print(f"  已完成锁定轮岗：{', '.join(report.completed_rotations_locked) or '无'}")
    print("  撤回后路径重核：")
    for assessment in reassessment:
        print(f"    {assessment.mode}: {STATUS_LABELS[assessment.status]} "
              f"缺口 {assessment.blocking_gaps or '无'}")


def cmd_pause(args) -> None:
    registry = load_registry(args.data)
    as_of = _as_of(args)
    new_registry, report = pause_agreement(registry, args.agreement, as_of,
                                           resume=args.resume)
    if args.json:
        _print_json({"report": report,
                     "paused": sorted(new_registry.paused_agreements)})
        return
    action = "恢复" if args.resume else "暂停"
    print(f"{action}协议 {args.agreement}：{report.reason}")
    if report.paused:
        print(f"  席位 {report.slot} / 学生 {report.learner} / 阶段 {PHASE_LABELS[report.phase]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apprenticeship",
        description="学徒跨企业轮岗的学分兑现与席位互换查询")
    parser.add_argument("--data", type=Path, default=DEFAULT_SAMPLES,
                        help="CSV 资料目录（默认 samples/）")
    parser.add_argument("--as-of", help="评估基准日 YYYY-MM-DD，默认今天")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("credit", help="查学生各方向的认定候选与能力缺口")
    p.add_argument("learner")
    p.set_defaults(func=cmd_credit)

    p = sub.add_parser("ledger", help="列证明账面状态（撤回/替代/有效）")
    p.add_argument("learner")
    p.set_defaults(func=cmd_ledger)

    sub.add_parser("swaps", help="查互换承诺的分组签认状态").set_defaults(func=cmd_swaps)

    p = sub.add_parser("plan", help="毕业路径、单人组合与整组联合排席")
    p.add_argument("learner", nargs="?", help="只看某个学生")
    p.set_defaults(func=cmd_plan)

    sub.add_parser("seats", help="席位容量、前置资格与暂停阶段").set_defaults(func=cmd_seats)

    p = sub.add_parser("withdraw", help="模拟撤回证明并重核下游资格")
    p.add_argument("proof")
    p.set_defaults(func=cmd_withdraw)

    p = sub.add_parser("pause", help="暂停或恢复尚未开始的席位交接")
    p.add_argument("agreement")
    p.add_argument("--resume", action="store_true")
    p.set_defaults(func=cmd_pause)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (DataError, KeyError, ValueError) as exc:
        parser.exit(2, f"错误：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
