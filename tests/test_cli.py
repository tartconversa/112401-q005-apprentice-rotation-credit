"""CLI 冒烟：每个子命令在样例资料上都能退出并产出文本/JSON。"""
import io
import json
import unittest
from contextlib import redirect_stdout

try:
    from tests._bootstrap import AS_OF, SAMPLES
except ModuleNotFoundError:
    from _bootstrap import AS_OF, SAMPLES
from apprenticeship.cli import main


class CliSmokeTests(unittest.TestCase):
    def run_cli(self, *extra: str, expect_json: bool = False) -> str:
        buffer = io.StringIO()
        argv = ["--data", str(SAMPLES), "--as-of", AS_OF.isoformat()]
        if expect_json:
            argv.append("--json")
        argv.extend(extra)
        with redirect_stdout(buffer):
            code = main(argv)
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        if expect_json:
            json.loads(output)
        return output

    def test_all_commands_text(self):
        self.assertIn("A1", self.run_cli("credit", "A1"))
        self.assertIn("P6", self.run_cli("ledger", "A1"))
        self.assertIn("SW1", self.run_cli("swaps"))
        self.assertIn("整组联合排席", self.run_cli("plan"))
        self.assertIn("席位", self.run_cli("seats"))
        self.assertIn("撤回", self.run_cli("withdraw", "P2"))
        self.assertIn("暂停", self.run_cli("pause", "C2"))

    def test_json_mode(self):
        output = self.run_cli("plan", expect_json=True)
        payload = json.loads(output)
        self.assertIn("cohort", payload)
        self.assertTrue(payload["learners"])

    def test_bad_proof_fails_cleanly(self):
        with self.assertRaises(SystemExit):
            main(["--data", str(SAMPLES), "--as-of", AS_OF.isoformat(),
                  "withdraw", "NOPE"])


if __name__ == "__main__":
    unittest.main()
