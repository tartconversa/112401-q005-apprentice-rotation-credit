"""席位容量与互换承诺：半开区间、导师上限、分组签认、拒绝保留原席。"""
import unittest

try:
    from tests._bootstrap import AS_OF, SAMPLES
except ModuleNotFoundError:
    from _bootstrap import AS_OF, SAMPLES
from apprenticeship.capacity import check_bookings
from apprenticeship.loader import load_registry
from apprenticeship.seating import (
    GROUP_DECLINED,
    GROUP_EFFECTIVE,
    GROUP_STALE,
    PHASE_COMPLETED,
    PHASE_SCHEDULED,
    agreement_phase,
    all_group_statuses,
    baseline_bookings,
    effective_agreements,
    evaluate_projection,
    group_status,
    projected_bookings,
)


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_seat_limit_enforced(self):
        bookings = {s.slot: () for s in self.registry.slots}
        bookings["S5"] = ("A1", "A2", "A3")  # seats=2
        violations = check_bookings(self.registry, bookings)
        self.assertTrue(any(v.kind == "seat" and v.label == "S5" for v in violations))

    def test_mentor_limit_over_half_open_overlap(self):
        # S1 与 S3 同导师 M7、区间重叠，mentor_limit=1
        bookings = {s.slot: () for s in self.registry.slots}
        bookings["S1"] = ("A1",)
        bookings["S3"] = ("A3",)
        violations = check_bookings(self.registry, bookings)
        self.assertTrue(any(v.kind == "mentor" and v.label == "M7" for v in violations))

    def test_touching_endpoints_do_not_overlap(self):
        # S2 [11-10,11-20) 与 S6 [11-20,11-26) 端点相接，M8 容量 1 不冲突
        bookings = {s.slot: () for s in self.registry.slots}
        bookings["S2"] = ("A3",)
        bookings["S6"] = ("A2",)
        self.assertEqual(check_bookings(self.registry, bookings), [])


class SwapGroupTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_declined_group_keeps_original_holders(self):
        status = group_status(self.registry, "SW1", AS_OF)
        self.assertEqual(status.state, GROUP_DECLINED)
        self.assertIn("firm", status.declined_parties)
        effective_ids = {a.agreement for a in effective_agreements(self.registry, AS_OF)}
        # 被拒互换不生效：C1/C2 保留，C4/C5 不进场
        self.assertIn("C1", effective_ids)
        self.assertIn("C2", effective_ids)
        self.assertNotIn("C4", effective_ids)
        self.assertNotIn("C5", effective_ids)

    def test_effective_group_replaces_old_agreement(self):
        status = group_status(self.registry, "SW2", AS_OF)
        self.assertEqual(status.state, GROUP_EFFECTIVE)
        self.assertEqual(status.effective_on.isoformat(), "2026-10-26")
        effective_ids = {a.agreement for a in effective_agreements(self.registry, AS_OF)}
        self.assertIn("C6", effective_ids)
        self.assertNotIn("C3", effective_ids)  # 被 C6 替换

    def test_stale_basis_when_source_proof_withdrawn(self):
        # K3 依据 P6，P6 已撤回；SW1 同时有 declined，状态仍报 declined，
        # 但 stale_sources 必须留痕供学籍重核
        status = group_status(self.registry, "SW1", AS_OF)
        self.assertIn("P6", status.stale_sources)

    def test_pending_group_blocks_effectiveness(self):
        from dataclasses import replace
        from apprenticeship.seating import GROUP_PENDING
        # 去掉 K4 的拒绝；再让 K3 依据的 P6 恢复有效，SW1 回到纯 pending
        acks = [k for k in self.registry.acknowledgements if k.entry != "K4"]
        proofs = [replace(p, state="confirmed") if p.proof == "P6" else p
                  for p in self.registry.proofs]
        registry = replace(self.registry, acknowledgements=acks, proofs=proofs)
        registry.__post_init__()
        status = group_status(registry, "SW1", AS_OF)
        self.assertEqual(status.state, GROUP_PENDING)
        self.assertEqual(status.blocking_parties, ("school",))
        # pending 期间互换不生效，原持有人保留席位
        effective_ids = {a.agreement for a in effective_agreements(registry, AS_OF)}
        self.assertIn("C1", effective_ids)
        self.assertNotIn("C4", effective_ids)

    def test_projection_flags_mentor_contention(self):
        projection = evaluate_projection(
            self.registry, projected_bookings(self.registry, AS_OF), AS_OF)
        self.assertFalse(projection.feasible)
        self.assertTrue(any(v["kind"] == "mentor" for v in projection.violations))

    def test_baseline_bookings_only_effective(self):
        baseline = baseline_bookings(self.registry, AS_OF)
        occupied = {slot: learners for slot, learners in baseline.items() if learners}
        self.assertEqual(occupied["S1"], ("A1",))
        self.assertEqual(occupied["S5"], ("A2",))
        self.assertEqual(occupied["S3"], ("A3",))  # SW2 已生效，A3 在 S3

    def test_phases_lock_completed_and_allow_pause(self):
        phases = {a.agreement: agreement_phase(self.registry, a, AS_OF)
                  for a in effective_agreements(self.registry, AS_OF)}
        self.assertEqual(phases["C1"], PHASE_COMPLETED)       # S1 11-12 结束
        self.assertEqual(phases["C6"], PHASE_COMPLETED)       # S3 11-25 结束（半开）
        self.assertEqual(phases["C2"], PHASE_SCHEDULED)       # S5 11-26 开始


if __name__ == "__main__":
    unittest.main()
