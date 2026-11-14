import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import guided_app  # noqa: E402


def tokens():
    return json.loads(guided_app.TOKENS.read_text(encoding="utf-8"))


class GuidedAppTests(unittest.TestCase):
    def test_all_screens_and_states_render(self):
        for state in guided_app.STATES:
            page = guided_app.render({k: state for k, *_ in guided_app.SCREENS})
            for key, title, _, _ in guided_app.SCREENS:
                self.assertIn(f'id="{key}"', page)
                self.assertIn(f'href="#{key}"', page)
                self.assertIn(f'data-state="{state}"', page)

    def test_default_is_not_started_and_never_claims_completion(self):
        for statuses in ({}, {k: s for k, *_ in guided_app.SCREENS for s in ["ready"]}):
            page = guided_app.render(statuses).lower()
            for word in ("complete", "done", "success", "passed", "all set"):
                self.assertNotIn(word, re.sub(r"<style>.*?</style>", "", page, flags=re.S))
        self.assertEqual(guided_app.render().count("Not started"), len(guided_app.SCREENS))

    def test_commands_are_registered(self):
        text = (ROOT / "onecompany.py").read_text(encoding="utf-8")
        for *_, cmd in guided_app.SCREENS:
            self.assertIn(f'"{cmd}":', text)

    def test_responsive_a11y_structure(self):
        page = guided_app.render()
        for needle in ('name="viewport"', 'class="skip"', '<nav aria-label="Steps">', "<main", "min-width:768px",
                       "min-width:1024px", "prefers-color-scheme:dark", ":focus-visible", "min-height:24px",
                       'lang="en"', "default-src 'none'"):
            self.assertIn(needle, page)
        self.assertNotIn("<script", page)
        self.assertIn('dir="rtl"', guided_app.render(rtl=True))
        self.assertIn('dir="ltr"', page)

    def test_deterministic(self):
        self.assertEqual(guided_app.render({"team": "error"}), guided_app.render({"team": "error"}))
        self.assertNotEqual(guided_app.render({"team": "error"}), guided_app.render())

    def test_unknown_screen_or_state_refused_with_positive_control(self):
        self.assertTrue(guided_app.render({"team": "slow"}))
        for bad in ({"nope": "ready"}, {"team": "complete"}, {"team": None}):
            with self.assertRaises(ValueError):
                guided_app.render(bad)

    def test_malformed_tokens_refused_with_positive_control(self):
        self.assertTrue(guided_app.render(tokens=tokens()))
        bad = copy.deepcopy(tokens()); bad["themes"]["dark"]["pairs"][0]["fg"] = "red"
        with self.assertRaises(ValueError):
            guided_app.render(tokens=bad)
        bad = copy.deepcopy(tokens()); bad["min_target_px"] = 8
        with self.assertRaises(ValueError):
            guided_app.render(tokens=bad)
        bad = copy.deepcopy(tokens()); del bad["themes"]["light"]
        with self.assertRaises(ValueError):
            guided_app.render(tokens=bad)
        with self.assertRaises(ValueError):
            guided_app.render(tokens=[])

    def test_cli_out_status_and_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            status = d / "s.json"; status.write_text('{"build": "slow"}')
            out = d / "o.html"
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "guided_app.py"), *a],
                                            capture_output=True, text=True)
            self.assertEqual(run("--status", str(status), "--out", str(out)).returncode, 0)
            self.assertIn('data-state="slow"', out.read_text())
            status.write_text('{"build": "bogus"}')
            self.assertEqual(run("--status", str(status)).returncode, 2)
            status.write_text("[]")
            self.assertEqual(run("--status", str(status)).returncode, 2)
            link = d / "l.html"; link.symlink_to(out)
            self.assertEqual(run("--out", str(link)).returncode, 2)
            r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "guided-app"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertIn("<!doctype html>", r.stdout)


if __name__ == "__main__":
    unittest.main()
