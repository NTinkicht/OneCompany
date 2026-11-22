"""OC-P0-12 (#594): read-only discovery helper vectors for scripts/onboard.py.

Pins stack/test/CI detection, GitHub origin inference and installed-mode
detection against real temp directories. No network and no writes outside the
temporary tree; every analyze() call must leave the target byte-identical.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import onboard  # noqa: E402

FALLBACK = ["Unknown / repository-agnostic"]


def snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = "link" if p.is_symlink() else ("dir" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def git_repo(path: Path, origin: str | None) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    if origin is not None:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True, capture_output=True)


class DetectStackVectors(unittest.TestCase):
    MARKERS = {
        "Python": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"],
        "Node/TypeScript": ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"],
        ".NET": ["app.sln", "app.csproj"],
        "Java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "Go": ["go.mod"],
        "Rust": ["Cargo.toml"],
        "PHP": ["composer.json"],
        "Ruby": ["Gemfile"],
    }

    def test_every_marker_detects_exactly_its_ecosystem(self):
        for stack, files in self.MARKERS.items():
            for name in files:
                with self.subTest(stack=stack, marker=name), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / name).write_text("x", encoding="utf-8")
                    self.assertEqual(onboard.detect_stack(root), [stack])

    def test_empty_directory_and_unrelated_files_use_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(onboard.detect_stack(root), FALLBACK)
            (root / "README.md").write_text("x", encoding="utf-8")
            (root / "notes.sln.txt").write_text("x", encoding="utf-8")
            self.assertEqual(onboard.detect_stack(root), FALLBACK)

    def test_multi_stack_order_is_stable_and_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("Gemfile", "package.json", "yarn.lock", "go.mod", "pyproject.toml"):
                (root / name).write_text("x", encoding="utf-8")
            self.assertEqual(onboard.detect_stack(root), ["Python", "Node/TypeScript", "Go", "Ruby"])

    def test_solution_glob_is_top_level_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "nested.csproj").write_text("x", encoding="utf-8")
            self.assertEqual(onboard.detect_stack(root), FALLBACK)


class DetectTestsAndCiVectors(unittest.TestCase):
    def test_all_test_directory_names_are_reported_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("e2e", "tests", "spec", "integration-tests"):
                (root / name).mkdir()
            self.assertEqual(onboard.detect_tests(root), ["tests", "spec", "e2e", "integration-tests"])
            self.assertEqual(onboard.detect_tests(root / "missing"), [])

    def test_actions_workflows_count_yml_and_yaml_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf = root / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "a.yml").write_text("x", encoding="utf-8")
            self.assertEqual(onboard.detect_ci(root), ["GitHub Actions (1 workflow)"])
            (wf / "b.yaml").write_text("x", encoding="utf-8")
            (wf / "notes.md").write_text("x", encoding="utf-8")
            (wf / "sub.yml").mkdir()
            self.assertEqual(onboard.detect_ci(root), ["GitHub Actions (2 workflows)"])

    def test_empty_workflow_directory_and_no_ci_report_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(onboard.detect_ci(root), [])
            (root / ".github" / "workflows").mkdir(parents=True)
            self.assertEqual(onboard.detect_ci(root), [])

    def test_other_ci_markers_are_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile"):
                (root / name).write_text("x", encoding="utf-8")
            self.assertEqual(onboard.detect_ci(root), ["GitLab CI", "Azure Pipelines", "Jenkins"])


class InferRepoVectors(unittest.TestCase):
    def test_github_origins_resolve_to_owner_repo(self):
        for origin in (
            "https://github.com/acme/widget",
            "https://github.com/acme/widget.git",
            "git@github.com:acme/widget.git",
            "git@github.com:acme/widget",
        ):
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as tmp:
                git_repo(Path(tmp), origin)
                self.assertEqual(onboard.infer_repo(Path(tmp)), "acme/widget")

    def test_no_remote_or_non_github_remote_yields_none(self):
        for origin in (None, "https://gitlab.com/acme/widget.git", "/srv/git/widget.git"):
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as tmp:
                git_repo(Path(tmp), origin)
                self.assertIsNone(onboard.infer_repo(Path(tmp)))

    def test_non_repository_directory_yields_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(onboard.infer_repo(Path(tmp) / "absent"))


class DetectModeAndNonmutationVectors(unittest.TestCase):
    def test_missing_or_empty_target_is_new_and_populated_is_adopt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(onboard.detect_mode(root / "absent"), ("NEW_PROJECT", None))
            self.assertEqual(onboard.detect_mode(root), ("NEW_PROJECT", None))
            (root / ".git").mkdir()
            self.assertEqual(onboard.detect_mode(root), ("NEW_PROJECT", None), ".git alone is not content")
            (root / "app.py").write_text("x", encoding="utf-8")
            self.assertEqual(onboard.detect_mode(root), ("ADOPT_EXISTING", None))

    def test_malformed_or_non_object_config_is_installed_without_repository(self):
        for text in ("{not json", "[]", "null", '"s"', '{"project": "x"}', '{"project": {"repository": 5}}', ""):
            with self.subTest(config=text), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / ".onecompany").mkdir()
                (root / ".onecompany" / "config.json").write_text(text, encoding="utf-8")
                mode, repo = onboard.detect_mode(root)
                self.assertEqual(mode, "INSTALLED")
                self.assertNotEqual(mode, "SOURCE_REPOSITORY")
                self.assertTrue(repo is None or repo == 5)

    def test_claimed_source_repository_without_source_history_is_template_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".onecompany").mkdir()
            (root / ".onecompany" / "config.json").write_text(
                '{"project": {"repository": "%s"}}' % onboard.SOURCE_REPOSITORY, encoding="utf-8")
            mode, repo = onboard.detect_mode(root)
            self.assertEqual((mode, repo), ("TEMPLATE_COPY", onboard.SOURCE_REPOSITORY))

    def test_analyze_never_mutates_any_fixture(self):
        fixtures = {
            "new": lambda r: None,
            "node": lambda r: (r / "package.json").write_text("{}", encoding="utf-8"),
            "ci": lambda r: ((r / ".github" / "workflows").mkdir(parents=True),
                             (r / ".github" / "workflows" / "ci.yml").write_text("x", encoding="utf-8")),
            "installed": lambda r: ((r / ".onecompany").mkdir(), (r / ".onecompany" / "config.json").write_text("{", encoding="utf-8")),
            "collision": lambda r: ((r / "scripts").mkdir(), (r / "scripts" / "validate.py").write_text("x", encoding="utf-8")),
        }
        for name, build in fixtures.items():
            with self.subTest(fixture=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "t"
                root.mkdir()
                build(root)
                before = snapshot(root)
                report = onboard.analyze(root, repository="acme/widget")
                self.assertEqual(snapshot(root), before)
                self.assertEqual(report["safe_defaults"]["autonomy"], "L1")
                self.assertEqual(report["safe_defaults"]["additional_ai_spend"], 0)
                self.assertFalse(report["safe_defaults"]["workers_enabled"])


if __name__ == "__main__":
    unittest.main()
