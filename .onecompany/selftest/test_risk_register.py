from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from risk_register_validate import validate_risks


POLICY = {
    "domains": ["delivery", "security", "privacy", "safety"],
    "gates": {
        "critical_residual_risk_requires_human_acceptance": True,
        "high_residual_risk_requires_named_owner": True,
        "unowned_open_risk_blocks_ready": True,
    },
}


def risk(**overrides):
    value = {
        "id": "RISK-900",
        "domain": "delivery",
        "likelihood": 5,
        "impact": 5,
        "inherent_score": 25,
        "owner": "human-owner",
        "treatment": "reduce",
        "mitigations": [{"id": "MIT-900"}],
        "residual_likelihood": 1,
        "residual_impact": 3,
        "residual_score": 3,
        "status": "treated",
    }
    value.update(overrides)
    return value


class RiskRegisterTests(unittest.TestCase):
    def test_treated_low_residual_risk_passes(self):
        self.assertEqual(validate_risks([risk()], POLICY), [])

    def test_critical_residual_requires_human_acceptance_even_when_treatment_is_reduce(self):
        errors = validate_risks([risk(residual_likelihood=4, residual_impact=5, residual_score=20)], POLICY)
        self.assertTrue(any("critical residual risk requires explicit human acceptance" in item for item in errors))

    def test_critical_residual_with_explicit_human_acceptance_passes(self):
        value = risk(
            residual_likelihood=4,
            residual_impact=5,
            residual_score=20,
            acceptance={"human": True, "approved_by": "owner-login"},
        )
        self.assertEqual(validate_risks([value], POLICY), [])

    def test_security_acceptance_cannot_be_silent(self):
        errors = validate_risks([
            risk(domain="security", treatment="accept", residual_likelihood=1, residual_impact=3, residual_score=3)
        ], POLICY)
        self.assertTrue(any("security risk cannot be silently accepted" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
