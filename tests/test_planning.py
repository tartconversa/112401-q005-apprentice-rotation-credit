"""毕业路径与整组排席：单人可行组合、导师争用、无备选方向优先。"""
import unittest

try:
    from tests._bootstrap import AS_OF, SAMPLES
except ModuleNotFoundError:
    from _bootstrap import AS_OF, SAMPLES
from apprenticeship.loader import load_registry
from apprenticeship.planning import (
    PATH_DEFICIENT,
    PATH_FEASIBLE,
    PATH_NEEDS_CONFIRMATION,
    assess_learner,
    plan_cohort,
)
from apprenticeship.seating import completed_rotation_hours


class SoloPlanningTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_a2_inspection_completed_by_held_slot(self):
        # A2 已确认 S5(trace->close 16h)，inspection 方向无需新增轮岗
        assessments = {a.mode: a for a in assess_learner(self.registry, "A2", AS_OF)}
        inspection = assessments["inspection"]
        self.assertTrue(any(not p.added_slots for p in inspection.solo_plans))

    def test_prerequisite_blocks_ineligible_slot(self):
        # A1 maintenance 下 trace 未认定，S5(requires trace) 不能作为 close 方案；
        # 只有 S4(requires diagnose) 系列候选出现
        assessments = {a.mode: a for a in assess_learner(self.registry, "A1", AS_OF)}
        added = {slot for p in assessments["maintenance"].solo_plans
                 for slot in p.added_slots}
        self.assertIn("S4", added)
        self.assertNotIn("S5", added)

    def test_deadline_filters_late_slots(self):
        # A2 截止 12-12，所有候选席位必须不晚于该日完成
        for assessment in assess_learner(self.registry, "A2", AS_OF):
            for plan in assessment.solo_plans:
                for slot_id in plan.added_slots:
                    slot = self.registry.slots_by_id[slot_id]
                    self.assertLessEqual(slot.end, self.registry.people_by_id["A2"].deadline)

    def test_completed_rotation_grants_hours(self):
        # A1 的 C1/S1 已完成，应带来 diagnose 24h
        hours = completed_rotation_hours(self.registry, "A1", AS_OF)
        self.assertEqual(hours.get("diagnose"), 24)

    def test_unresolved_use_keeps_needs_confirmation(self):
        assessments = {a.mode: a for a in assess_learner(self.registry, "A1", AS_OF)}
        self.assertEqual(assessments["inspection"].status, PATH_NEEDS_CONFIRMATION)
        self.assertEqual(assessments["maintenance"].status, PATH_FEASIBLE)


class CohortPlanningTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(SAMPLES)

    def test_cohort_respects_mentor_and_seat_capacity(self):
        result = plan_cohort(self.registry, AS_OF)
        # M9 在 11-26..12-10 只有 mentor_limit=2，close 席位无法让四人同时毕业
        self.assertLessEqual(len(result.served), 3)
        self.assertTrue(result.unserved)
        self.assertEqual(result.capacity_violations, ())

    def test_student_without_alternative_mode_prioritized(self):
        result = plan_cohort(self.registry, AS_OF)
        # A3 只有 inspection 一个方向，应优先于同样争用 close 席位的多方向学生
        self.assertIn("A3", result.served)

    def test_every_solo_feasible_but_cohort_contention_exists(self):
        # 单人视角每人都有可行路径，但整组容量不足——这是任务的核心争用场景
        for person in self.registry.people:
            statuses = [a.status for a in assess_learner(self.registry, person.learner, AS_OF)]
            self.assertTrue(any(s != PATH_DEFICIENT for s in statuses))
        result = plan_cohort(self.registry, AS_OF)
        self.assertFalse(result.feasible)

    def test_cohort_booking_uses_full_slot_set(self):
        result = plan_cohort(self.registry, AS_OF)
        # 被服务学生的已确认席位不能在联合占用里丢失
        for assignment in result.assignments:
            for slot_id in assignment.slot_ids:
                self.assertIn(assignment.learner, result.bookings.get(slot_id, ()))


if __name__ == "__main__":
    unittest.main()
