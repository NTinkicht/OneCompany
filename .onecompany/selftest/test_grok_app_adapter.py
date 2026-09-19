# Root OneCompany CI discovers this focused test without needing the MCP
# runtime or any live credentials. It loads only settings/auth/GitHub core.
from __future__ import annotations
import sys
from pathlib import Path
_TEST_DIR = Path(__file__).resolve().parents[2] / "services" / "github_app_adapter" / "tests"
sys.path.insert(0, str(_TEST_DIR))
from test_adapter import TestGrokAppAdapter  # noqa: F401
