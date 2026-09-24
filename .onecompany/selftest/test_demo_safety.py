"""Safety assertions use observed fixture state, never caller flags."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.demo_safety import preflight, require_safe_demo
SOURCE_ONLY = (ROOT / "scripts" / "phase1_vertical_smoke.py").is_file()
if SOURCE_ONLY:
    import phase1_vertical_smoke as vertical
else:
    vertical = None

PLAN = {"authorization": "NOT_GRANTED", "mode": "READ_ONLY_PROPOSAL"}


@unittest.skipUnless(SOURCE_ONLY, "disposable demo is source-only, absent from fresh bootstrap")
class DemoSafetyTests(unittest.TestCase):
    def setUp(self):
        self.server, self.store = vertical._local_app().start_server(0)
        self.addCleanup(self.store.close)
        self.addCleanup(self.server.server_close)

    def test_actual_local_ephemeral_fixture_is_verified(self):
        report = preflight(self.server, self.store, PLAN)
        self.assertTrue(report["verified"])
        self.assertFalse(report["deployable"])
        self.assertFalse(report["approved"])

    def test_actual_non_local_bind_is_refused(self):
        with patch.object(self.server, "server_address", ("0.0.0.0", 10001)):
            result = preflight(self.server, self.store, PLAN)
        self.assertFalse(result["verified"])
        self.assertIn("non_local_bind", result["blockers"])

    def test_real_persisted_data_and_authority_are_refused(self):
        self.store.create("not an empty fixture")
        report = preflight(self.server, self.store,
                           {"authorization": "GRANTED",
                            "mode": "READ_ONLY_PROPOSAL"})
        self.assertIn("nonempty_disposable_store", report["blockers"])
        self.assertIn("execution_authority_not_permitted", report["blockers"])

    def test_actual_demo_run_refuses_before_http_worker(self):
        from onboard import analyze
        from product_brief import make_draft
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "new"
            assessment = analyze(target, repository="demo/new")
            draft = make_draft(assessment, {
                "audience": "Families", "problem": "Track small tasks",
                "outcome": "See checklist", "first_feature": "Add item",
            })
            with patch.object(vertical, "require_safe_demo",
                              side_effect=ValueError("DISPOSABLE_DEMO_SAFETY_BLOCKED")):
                with patch.object(vertical.threading.Thread, "start",
                                  side_effect=AssertionError("HTTP worker started")):
                    with self.assertRaisesRegex(ValueError, "DISPOSABLE_DEMO_SAFETY_BLOCKED"):
                        vertical.run(assessment, draft, "a"*40, "b"*40)


if __name__ == "__main__":
    unittest.main()
