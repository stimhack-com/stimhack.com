"""Tests that CI installs the third-party packages the Python code imports.

Run: python3 -m unittest discover tests
"""
import ast
import re
import sys
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


if __name__ == "__main__":
    unittest.main()
