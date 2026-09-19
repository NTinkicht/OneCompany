"""Load focused adapter tests only when optional MCP runtime is installed.

The base-trusted OneCompany Validate workflow deliberately runs the source
suite without third-party adapter dependencies. It checks source integration,
while the Render build installs optional dependencies for pilot verification.
"""
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DIR = _ROOT / "services" / "github_app_adapter" / "tests"
if all(importlib.util.find_spec(name) is not None
       for name in ("starlette", "jwt", "mcp")):
    sys.path.insert(0, str(_DIR))
    from test_adapter import TestGrokAppAdapter  # noqa: F401
else:
    class TestGrokAdapterDependencies(unittest.TestCase):
        """Do not claim the optional third-party adapter suite ran in source CI."""

        @unittest.skip("Optional MCP adapter dependencies not installed in source CI")
        def test_optional_adapter_runtime(self):
            """Adapter tests run in its own pip-installed environment."""
