"""Tests that each test file runs all of its tests when it runs as a script.

Run: python3 -m unittest discover tests
"""
import ast
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def ends_with_main_guard(source):
    """Return whether the last statement of a module is `if __name__ == "__main__":`."""
    body = ast.parse(source).body
    if not body or not isinstance(body[-1], ast.If):
        return False
    test = body[-1].test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


class MainGuard(unittest.TestCase):
    """`python3 tests/<file>.py` runs only the test classes defined before the
    guard, so a missing guard runs no test and a guard in the middle of the
    file skips the classes after it. Both exit 0."""

    def test_every_test_file_ends_with_the_main_guard(self):
        files = sorted(TESTS.glob("test_*.py"))
        self.assertTrue(files)
        missing = [f.name for f in files if not ends_with_main_guard(f.read_text())]
        self.assertEqual(missing, [])

    def test_guard_must_be_the_last_statement(self):
        guard = 'if __name__ == "__main__":\n    unittest.main()\n'
        self.assertTrue(ends_with_main_guard("import unittest\n" + guard))
        self.assertFalse(ends_with_main_guard("import unittest\n"))
        self.assertFalse(ends_with_main_guard(guard + "class Later:\n    pass\n"))


if __name__ == "__main__":
    unittest.main()
