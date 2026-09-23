import unittest

from scripts.demo_safety import preflight


class DemoSafetyTests(unittest.TestCase):
    def test_local_synthetic_demo_is_safe_but_not_deployable(self):
        result = preflight("127.0.0.1", True, False)
        self.assertTrue(result["safe"])
        self.assertFalse(result["deployable"])
        self.assertFalse(result["approved"])

    def test_non_local_host_is_refused(self):
        result = preflight("0.0.0.0", True, False)
        self.assertFalse(result["safe"])
        self.assertIn("non_local_host", result["blockers"])

    def test_real_data_or_authority_is_refused(self):
        result = preflight("localhost", False, True)
        self.assertFalse(result["safe"])
        self.assertIn("non_synthetic_data", result["blockers"])
        self.assertIn("authority_not_permitted", result["blockers"])


if __name__ == "__main__":
    unittest.main()
