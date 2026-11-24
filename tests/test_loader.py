"""读取契约：成功加载样例，并拒绝结构性坏资料。"""
import csv
import tempfile
import unittest
from pathlib import Path

try:
    from tests._bootstrap import SAMPLES
except ModuleNotFoundError:
    from _bootstrap import SAMPLES
from apprenticeship.loader import DataError, load_registry

HEADER_COPY = {
    "requirements": "mode,competency,min_hours,precedes,version,active_from",
    "people": "learner,mode_options,deadline",
    "proofs": "proof,learner,hours,uses,group,completed,mentor,state,replaces,received",
    "rotations": "slot,firm,mentor,start,end,requires,offers,hours,seats,mentor_limit",
    "agreements": "agreement,learner,slot,status,group,replaces,recorded",
    "acknowledgements": "entry,agreement,party,state,source_id,recorded",
}


class LoaderContractTests(unittest.TestCase):
    def test_samples_load_with_indexes(self):
        registry = load_registry(SAMPLES)
        self.assertEqual({p.learner for p in registry.people},
                         {"A1", "A2", "A3", "A4"})
        self.assertIn("P1", registry.proofs_by_id)
        self.assertIn("S1", registry.slots_by_id)
        self.assertIn("C1", registry.agreements_by_id)

    def test_dangling_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._copy_samples(tmp)
            self._rewrite(Path(tmp) / "proofs.csv",
                          lambda rows: [
                              {**r, "learner": "NOBODY"} if r["proof"] == "P1" else r
                              for r in rows])
            with self.assertRaises(DataError):
                load_registry(tmp)

    def test_bad_enum_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._copy_samples(tmp)
            self._rewrite(Path(tmp) / "proofs.csv",
                          lambda rows: [
                              {**r, "state": "frozen"} if r["proof"] == "P1" else r
                              for r in rows])
            with self.assertRaises(DataError):
                load_registry(tmp)

    def test_inconsistent_mentor_limit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._copy_samples(tmp)
            self._rewrite(Path(tmp) / "rotations.csv",
                          lambda rows: [
                              {**r, "mentor_limit": "2"} if r["slot"] == "S1" else r
                              for r in rows])
            with self.assertRaises(DataError):
                load_registry(tmp)

    def test_non_positive_capacity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._copy_samples(tmp)
            self._rewrite(Path(tmp) / "rotations.csv",
                          lambda rows: [
                              {**r, "seats": "0"} if r["slot"] == "S1" else r
                              for r in rows])
            with self.assertRaises(DataError):
                load_registry(tmp)

    def test_group_mixing_learners_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._copy_samples(tmp)
            self._rewrite(Path(tmp) / "proofs.csv",
                          lambda rows: [
                              {**r, "group": "B1"} if r["proof"] == "P1" else r
                              for r in rows])
            with self.assertRaises(DataError):
                load_registry(tmp)

    def _copy_samples(self, tmp: str) -> None:
        for csv_path in SAMPLES.glob("*.csv"):
            Path(tmp, csv_path.name).write_text(csv_path.read_text(encoding="utf-8"),
                                                encoding="utf-8")

    def _rewrite(self, path: Path, mutate) -> None:
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            fieldnames = reader.fieldnames
            rows = mutate(list(reader))
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
