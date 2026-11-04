import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import design_tokens_check as dtc  # noqa: E402

SHIPPED = json.loads((ROOT / "config" / "design-tokens.json").read_text(encoding="utf-8"))


class DesignTokensTests(unittest.TestCase):
    def test_known_vectors(self):
        self.assertAlmostEqual(dtc.contrast("#000000", "#FFFFFF"), 21.0, places=6)
        self.assertAlmostEqual(dtc.contrast("#FFFFFF", "#FFFFFF"), 1.0, places=6)
        self.assertLess(dtc.contrast("#777777", "#FFFFFF"), 4.5)
        self.assertGreaterEqual(dtc.contrast("#767676", "#FFFFFF"), 4.5)

    def test_shipped_tokens_pass(self):
        results, problems = dtc.check_tokens(SHIPPED)
        self.assertEqual(problems, [])
        self.assertEqual(len(results), 12)

    def mutate(self, fn):
        data = copy.deepcopy(SHIPPED)
        fn(data)
        return dtc.check_tokens(data)[1]

    def test_low_contrast_names_pair(self):
        p = self.mutate(lambda d: d["themes"]["light"]["pairs"][0].update(fg="#CCCCCC"))
        self.assertTrue(any(x.startswith("light/text-on-surface: contrast") for x in p))

    def test_missing_theme_and_focus(self):
        self.assertTrue(any("themes.dark: missing" in x for x in self.mutate(lambda d: d["themes"].pop("dark"))))
        p = self.mutate(lambda d: d["themes"]["dark"].update(
            pairs=[x for x in d["themes"]["dark"]["pairs"] if x["kind"] != "focus"]))
        self.assertTrue(any("dark: missing focus-ring" in x for x in p))

    def test_malformed_values_fail_closed(self):
        self.assertTrue(self.mutate(lambda d: d["themes"]["light"]["pairs"][0].update(bg="white")))
        self.assertTrue(self.mutate(lambda d: d["themes"]["light"]["pairs"][0].update(kind="decor")))
        self.assertTrue(self.mutate(lambda d: d.update(min_target_px=12)))
        self.assertTrue(self.mutate(lambda d: d.update(min_target_px=True)))
        self.assertTrue(self.mutate(lambda d: d.update(dir_support=["ltr"])))
        self.assertTrue(dtc.check_tokens([])[1])
        self.assertTrue(dtc.check_tokens({"themes": []})[1])

    def run_cli(self, data=None):
        args = [sys.executable, "-I", str(ROOT / "scripts" / "design_tokens_check.py")]
        if data is not None:
            f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            f.write(data)
            f.close()
            args += ["--tokens", f.name]
        return subprocess.run(args, capture_output=True, text=True)

    def test_cli_exit_codes(self):
        self.assertEqual(self.run_cli().returncode, 0)
        bad = copy.deepcopy(SHIPPED)
        bad["themes"]["light"]["pairs"][0]["fg"] = "#DDDDDD"
        self.assertEqual(self.run_cli(json.dumps(bad)).returncode, 1)
        self.assertEqual(self.run_cli("not json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
