"""学期事件：撤回重核、席位暂停/恢复、已完成轮岗锁定。"""
import unittest

try:
    from tests._bootstrap import AS_OF, SAMPLES
except ModuleNotFoundError:
    from _bootstrap import AS_OF, SAMPLES
from apprenticeship.events import (
    pause_agreement,
    paused_agreements,
    withdraw_proof,
)
from apprenticeship.loader import load_registry
from apprenticeship.planning import assess_learner
from apprenticeship.seating import PHASE_COMPLETED, PHASE_SCHEDULED, agreement_phase


class WithdrawalTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_withdrawal_removes_credit_but_keeps_record(self):
        new_registry, report = withdraw_proof(self.registry, "P2", AS_OF)
        self.assertEqual(report.learner, "A1")
        # 原 registry 不变，新 registry 中 P2 撤回
        self.assertEqual(self.registry.proofs_by_id["P2"].state, "confirmed")
        self.assertEqual(new_registry.proofs_by_id["P2"].state, "withdrawn")

    def test_withdrawal_flags_swap_relying_on_proof(self):
        _, report = withdraw_proof(self.registry, "P6", AS_OF)
        self.assertIn("SW1", report.stale_swap_groups)

    def test_withdrawal_triggers_prerequisite_recheck(self):
        new_registry, report = withdraw_proof(self.registry, "P2", AS_OF)
        # S4/S5 以 measure/diagnose/trace 为入场前置，P2 候选用途命中
        self.assertTrue(set(report.impacted_slots) & {"S4", "S5"})
        # 撤回后仍能重核路径，不会抛异常
        reassessment = assess_learner(new_registry, "A1", AS_OF)
        self.assertTrue(reassessment)

    def test_completed_rotation_locked_against_rollback(self):
        _, report = withdraw_proof(self.registry, "P1", AS_OF)
        self.assertIn("C1", report.completed_rotations_locked)


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_scheduled_slot_can_pause_and_resume(self):
        paused, report = pause_agreement(self.registry, "C2", AS_OF)
        self.assertTrue(report.paused)
        self.assertIn("C2", paused_agreements(paused))
        resumed, report2 = pause_agreement(paused, "C2", AS_OF, resume=True)
        self.assertNotIn("C2", paused_agreements(resumed))
        self.assertTrue(report2.paused)

    def test_completed_slot_cannot_pause(self):
        registry, report = pause_agreement(self.registry, "C1", AS_OF)
        self.assertFalse(report.paused)
        self.assertEqual(report.phase, PHASE_COMPLETED)
        self.assertEqual(paused_agreements(registry), frozenset())

    def test_phase_labels(self):
        by_id = self.registry.agreements_by_id
        self.assertEqual(agreement_phase(self.registry, by_id["C1"], AS_OF),
                         PHASE_COMPLETED)
        self.assertEqual(agreement_phase(self.registry, by_id["C2"], AS_OF),
                         PHASE_SCHEDULED)


if __name__ == "__main__":
    unittest.main()
