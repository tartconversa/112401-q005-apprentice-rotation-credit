"""检查演练资料的读取契约和关联锚点。"""
import csv
from pathlib import Path
import unittest

INPUTS = Path(__file__).resolve().parent.parent / "samples"

HEADERS = {'requirements': ('mode', 'competency', 'min_hours', 'precedes', 'version', 'active_from'), 'people': ('learner', 'mode_options', 'deadline'), 'proofs': ('proof', 'learner', 'hours', 'uses', 'group', 'completed', 'mentor', 'state', 'replaces', 'received'), 'rotations': ('slot', 'firm', 'mentor', 'start', 'end', 'requires', 'offers', 'hours', 'seats', 'mentor_limit'), 'agreements': ('agreement', 'learner', 'slot', 'status', 'group', 'replaces', 'recorded'), 'acknowledgements': ('entry', 'agreement', 'party', 'state', 'source_id', 'recorded')}
REFERENCES = [('proofs', 'learner', 'people', 'learner'), ('agreements', 'slot', 'rotations', 'slot'), ('acknowledgements', 'agreement', 'agreements', 'agreement'), ('proofs', 'replaces', 'proofs', 'proof')]
EXAMPLES = [['proofs', 'replaces', 'P2', 1], ['agreements', 'group', 'SW1', 2], ['rotations', 'mentor', 'M7', 2]]


class SampleInputContract(unittest.TestCase):
    def read(self, table):
        with (INPUTS / f"{table}.csv").open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            self.assertEqual(tuple(reader.fieldnames), HEADERS[table])
            rows = list(reader)
        self.assertTrue(rows, table)
        for row in rows:
            self.assertNotIn(None, row, table)
            self.assertNotIn(None, row.values(), table)
        return rows

    def test_csv_readable_with_documented_columns(self):
        for table in HEADERS:
            with self.subTest(table=table):
                self.read(table)

    def test_cross_source_example_references(self):
        for source, source_field, target, target_field in REFERENCES:
            with self.subTest(source=source, field=source_field, target=target):
                available = {row[target_field] for row in self.read(target)}
                actual = {value for row in self.read(source)
                          for value in row[source_field].split("|") if value}
                self.assertTrue(actual)
                self.assertEqual(actual - available, set())

    def test_example_revisions_and_overlaps_are_present(self):
        for table, field, example, expected in EXAMPLES:
            with self.subTest(table=table, field=field, example=example):
                found = sum((row[field] == example if "|" in example else example in row[field].split("|")) for row in self.read(table))
                self.assertEqual(found, expected)


if __name__ == "__main__":
    unittest.main()
