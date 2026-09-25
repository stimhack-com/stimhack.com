"""Tests that CI installs the third-party packages the Python code imports,
and the Node.js that the tests of the site script run.

Run: python3 -m unittest discover tests
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIRS = ["migration", "scripts", "tests"]
REQUIREMENTS = ROOT / "requirements.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "site.yml"

# Import names that are not the name of the package on PyPI.
DISTRIBUTIONS = {"bs4": "beautifulsoup4", "yaml": "PyYAML"}


def python_files():
    return sorted(p for d in PYTHON_DIRS for p in (ROOT / d).glob("*.py"))


def third_party_imports():
    """Return {top-level module: [file:line, ...]} for modules that are not
    in the standard library and not a module in PYTHON_DIRS."""
    local = {p.stem for p in python_files()}
    found = {}
    for path in python_files():
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in local:
                    continue
                found.setdefault(top, []).append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def required_distributions():
    if not REQUIREMENTS.exists():
        return set()
    names = set()
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(re.split(r"[\s\[<>=!~;]", line)[0].lower())
    return names


def build_steps():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["build"]["steps"]


def step_index(steps, predicate, what):
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    raise AssertionError(f"no step in {WORKFLOW.relative_to(ROOT)} {what}")


class Requirements(unittest.TestCase):
    def test_every_third_party_import_is_in_requirements(self):
        imports = third_party_imports()
        self.assertTrue(imports, "found no third-party imports; is the scan broken?")
        required = required_distributions()
        missing = {
            module: files
            for module, files in sorted(imports.items())
            if DISTRIBUTIONS.get(module, module).lower() not in required
        }
        self.assertEqual(missing, {}, f"imported but not in {REQUIREMENTS.name}")

    def test_workflow_installs_requirements_before_python_runs(self):
        steps = build_steps()
        setup = step_index(
            steps, lambda s: str(s.get("uses", "")).startswith("actions/setup-python@"),
            "uses actions/setup-python",
        )
        install = step_index(
            steps, lambda s: re.search(r"\bpip install -r requirements\.txt\b", s.get("run", "")),
            "runs pip install -r requirements.txt",
        )
        self.assertLess(setup, install, "setup-python must come before pip install")
        for i, step in enumerate(steps):
            if re.search(r"\bpython3?\b", step.get("run", "")) and "pip install" not in step["run"]:
                self.assertLess(install, i, f"step {step.get('name')!r} runs Python before pip install")
        self.assertTrue(
            any("unittest" in s.get("run", "") for s in steps[install + 1:]),
            "no unit test step after pip install",
        )

    def test_setup_python_version_has_tomllib(self):
        steps = build_steps()
        setup = steps[step_index(
            steps, lambda s: str(s.get("uses", "")).startswith("actions/setup-python@"),
            "uses actions/setup-python",
        )]
        version = str(setup.get("with", {}).get("python-version", ""))
        match = re.fullmatch(r"3\.(\d+)", version)
        self.assertIsNotNone(match, f"python-version {version!r} is not a pinned 3.x minor version")
        # tomllib, which tests/test_layouts.py imports, was added in 3.11.
        self.assertGreaterEqual(int(match.group(1)), 11)


# Print the ID of each test in the directory argv[1] that unittest skips
# before it runs, because the test or its class has a skip decorator.
SKIPPED_TESTS = r"""
import sys, unittest
loader = unittest.TestLoader()
def tests(suite):
    for test in suite:
        yield from tests(test) if isinstance(test, unittest.TestSuite) else [test]
for test in tests(loader.discover(sys.argv[1])):
    method = getattr(type(test), test._testMethodName)
    if getattr(type(test), "__unittest_skip__", False) or getattr(method, "__unittest_skip__", False):
        print(test.id())
if loader.errors:
    sys.exit("\\n".join(loader.errors))
"""


def skipped_tests(env):
    """Return the IDs of the tests in tests/ that are skipped before they run when the environment is env."""
    run = subprocess.run([sys.executable, "-c", SKIPPED_TESTS, str(ROOT / "tests")],
                         env=env, cwd=ROOT, capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr)
    return set(run.stdout.split())


class Node(unittest.TestCase):
    def test_workflow_sets_up_node_before_the_unit_tests(self):
        steps = build_steps()
        setup = step_index(
            steps, lambda s: str(s.get("uses", "")).startswith("actions/setup-node@"),
            "uses actions/setup-node",
        )
        for i, step in enumerate(steps):
            if "unittest" in step.get("run", ""):
                self.assertLess(setup, i, f"step {step.get('name')!r} runs the tests before setup-node")

    def test_setup_node_version_has_the_features_the_tests_use(self):
        steps = build_steps()
        setup = steps[step_index(
            steps, lambda s: str(s.get("uses", "")).startswith("actions/setup-node@"),
            "uses actions/setup-node",
        )]
        version = str(setup.get("with", {}).get("node-version", ""))
        match = re.fullmatch(r"(\d+)(\.\d+){0,2}", version)
        self.assertIsNotNone(match, f"node-version {version!r} is not a pinned version")
        # MOBILE_NAV in tests/test_layouts.py calls
        # Array.prototype.findLastIndex. `node -e 'console.log(typeof
        # [].findLastIndex)'` prints "undefined" with Node.js 13.14.0 and
        # "function" with 23.4.0 and 24.4.1. The bound of 18 is not checked
        # against a Node.js 18 install.
        self.assertGreaterEqual(int(match.group(1)), 18)

    def test_tests_do_not_skip_in_ci_when_node_is_missing(self):
        # GitHub Actions always sets CI=true: the default environment
        # variables at
        # https://docs.github.com/en/actions/reference/workflows-and-actions/variables
        # say "CI: Always set to true." (checked 2026-09-25). A test that
        # skips there when node is missing lets the job pass with the site
        # script untested.
        with tempfile.TemporaryDirectory() as without_node, tempfile.TemporaryDirectory() as with_node:
            node = Path(with_node) / "node"
            node.write_text("#!/bin/sh\nexit 1\n")
            node.chmod(0o755)
            skipped = {
                path: skipped_tests({**os.environ, "CI": "true", "PATH": path})
                for path in [without_node, with_node]
            }
        self.assertEqual(sorted(skipped[without_node] - skipped[with_node]), [],
                         "skipped in CI when node is not on PATH")


if __name__ == "__main__":
    unittest.main()
