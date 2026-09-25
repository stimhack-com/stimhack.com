"""Tests that .gitignore leaves the site source in git."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ["archetypes", "assets", "config", "content", "data", "layouts", "static"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


class SiteSource(unittest.TestCase):
    def test_no_source_file_matches_an_ignore_pattern(self):
        # Tracked and untracked files both, so a tracked file that a pattern
        # matches also fails.
        out = git("ls-files", "--cached", "--others", "--ignored", "--exclude-standard", "--", *SOURCE_DIRS)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.splitlines(), [])

    def test_build_output_names_are_ignored_only_at_the_root(self):
        at_root = ["public/index.html", "resources/_gen/x.css"]
        in_source = [f"{d}/x/{name}/y.png" for d in SOURCE_DIRS for name in ("public", "resources")]
        out = git("check-ignore", "--no-index", "--", *at_root, *in_source)
        self.assertEqual(out.stdout.splitlines(), at_root)


if __name__ == "__main__":
    unittest.main()
