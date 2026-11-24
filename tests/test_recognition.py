"""学分认定规则：一次性时数、整套实作、撤回/替代链、候选不自动决定。"""
import unittest

try:
    from tests._bootstrap import AS_OF, SAMPLES
except ModuleNotFoundError:
    from _bootstrap import AS_OF, SAMPLES
from apprenticeship.loader import load_registry
from apprenticeship.recognition import (
    LEDGER_ACTIVE,
    LEDGER_SUPERSEDED,
    LEDGER_WITHDRAWN,
    active_proofs,
    best_scenarios,
    enumerate_scenarios,
    proof_ledger,
)


class ProofLedgerTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_withdrawn_proof_keeps_record_but_no_credit(self):
        entries = {e.proof.proof: e for e in
                   proof_ledger(self.registry, "A1", AS_OF)}
        self.assertEqual(entries["P6"].ledger_state, LEDGER_WITHDRAWN)
        active = {p.proof for p in active_proofs(self.registry, "A1", AS_OF)}
        self.assertEqual(active, {"P1", "P2"})

    def test_superseded_chain(self):
        # 构造一条被新确认证明替代的旧证明
        from dataclasses import replace
        registry = self.registry
        new_proof = replace(registry.proofs_by_id["P6"],
                            proof="P6B", state="confirmed", replaces="P2")
        merged = replace(registry, proofs=registry.proofs + [new_proof])
        merged.__post_init__()
        entries = {e.proof.proof: e for e in proof_ledger(merged, "A1", AS_OF)}
        self.assertEqual(entries["P2"].ledger_state, LEDGER_SUPERSEDED)
        self.assertEqual(entries["P2"].superseded_by, "P6B")
        self.assertEqual(entries["P6"].ledger_state, LEDGER_WITHDRAWN)

    def test_pending_proof_hidden_before_received(self):
        # 基准日早于所有证明收到日（10-20）时，没有任何证明可携带学分
        early = proof_ledger(self.registry, "A1", AS_OF.replace(month=10, day=19))
        self.assertTrue(early)
        self.assertTrue(all(e.ledger_state != LEDGER_ACTIVE for e in early))


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_hours_used_once_across_competencies(self):
        scenarios = enumerate_scenarios(self.registry, "A1", "maintenance", AS_OF)
        for scenario in scenarios:
            # 每份有效证明在一个方向里最多出现一次
            uses = [u for u in scenario.assignment.values() if u is not None]
            self.assertEqual(len(uses), len(set(
                p for p, u in scenario.assignment.items() if u is not None)))
        # P1=12h measure、P2=20h diagnose 时 diagnose 只有 20/24，仍有缺口
        best = best_scenarios(scenarios)[0]
        diagnose_gap = next(g for g in best.gaps if g.competency == "diagnose")
        self.assertEqual(diagnose_gap.current_hours, 20)
        self.assertEqual(diagnose_gap.missing_hours, 4)

    def test_candidate_uses_are_not_auto_decided(self):
        scenarios = enumerate_scenarios(self.registry, "A1", "inspection", AS_OF)
        best = best_scenarios(scenarios)
        # 最优分配可能唯一，但 P1 的 measure|trace 用途无法从记录区分，
        # 系统必须把它标为未决、留给学籍人员确认，而不是自动当成学校决定
        self.assertTrue(all("P1" in s.unresolved_proofs for s in best))
        self.assertTrue(all(not s.determined for s in best))
        # 全部候选里确实保留了 P1 的不同用途分支
        p1_uses = {s.assignment["P1"] for s in scenarios}
        self.assertIn("measure", p1_uses)
        self.assertIn("trace", p1_uses)

    def test_group_proofs_only_taken_together(self):
        scenarios = enumerate_scenarios(self.registry, "A2", "maintenance", AS_OF)
        for scenario in scenarios:
            group_used = {p for p, use in scenario.assignment.items()
                          if use is not None and self.registry.proofs_by_id[p].group}
            # B1 要么 P3/P4 同时认定，要么都不认定
            self.assertIn(group_used, [set(), {"P3", "P4"}])

    def test_group_proofs_cover_full_mode(self):
        scenarios = enumerate_scenarios(self.registry, "A2", "maintenance", AS_OF)
        complete = [s for s in scenarios if s.complete]
        # P3 measure 12h + P4 diagnose 20h 仍差 diagnose 4h，无人能单靠证明毕业
        self.assertEqual(complete, [])

    def test_prerequisite_chain_blocks_gap(self):
        scenarios = enumerate_scenarios(self.registry, "A1", "maintenance", AS_OF)
        best = best_scenarios(scenarios)[0]
        close_gap = next(g for g in best.gaps if g.competency == "close")
        self.assertTrue(close_gap.blocked)
        self.assertEqual(close_gap.prerequisite, "diagnose")

    def test_hours_counted_toward_named_competency_only(self):
        inspection = enumerate_scenarios(self.registry, "A3", "inspection", AS_OF)
        # A3 只有 P5(measure 12h)：measure 满足，trace/close 仍是缺口
        best = best_scenarios(inspection)[0]
        self.assertEqual(best.hours_by_competency.get("measure"), 12)
        self.assertIn("measure", best.satisfied)
        self.assertEqual({g.competency for g in best.gaps}, {"trace", "close"})


if __name__ == "__main__":
    unittest.main()
