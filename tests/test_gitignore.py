"""Tests that .gitignore leaves the site source in git."""
import shutil
import subprocess
import tempfile
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

    def test_root_names_are_ignored_when_they_are_symlinks(self):
        # A worktree can have .export as a symlink to the main checkout's
        # export data. A pattern foo/ does not match a symbolic link foo
        # (gitignore(5), EXAMPLES).
        names = [".export", "public", "resources"]
        with tempfile.TemporaryDirectory() as tmp:
            repo, target = Path(tmp) / "repo", Path(tmp) / "target"
            repo.mkdir()
            target.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            shutil.copy(ROOT / ".gitignore", repo / ".gitignore")
            for name in names:
                (repo / name).symlink_to(target, target_is_directory=True)
            out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", *names],
                                 cwd=repo, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.splitlines(), [])


if __name__ == "__main__":
    unittest.main()
