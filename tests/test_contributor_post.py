"""Tests that the checks of content/ still pass after a contributor adds a post.

CONTRIBUTING.md tells a contributor to add a post as a folder
content/posts/<year>/<name>/ with an index.md made from archetypes/posts.md
and the images of the post. CI runs the unit tests before it builds and
deploys the site, so a check that fails on such a post stops every deploy.

Run: python3 -m unittest discover tests
"""
import ast
import atexit
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import site_build
import test_convert
import test_layouts
from site_build import ROOT, build, hugo

# Not in a contributor root: build output, and content/, which gets a copy of its own.
SKIP = {"content", ".git", "public", "resources", ".hugo_build.lock"}
# Too large to copy. Hugo does not read a directory that is a symbolic link, and
# the tests do not build from the root with these.
LINKED = {"static", ".export"}
COVER = ROOT / "tests" / "fixtures" / "bundles" / "posts" / "2026" / "bundle-article" / "cover.png"


def contributor_root(*posts):
    """Return a directory that is ROOT with posts added to a copy of content/.

    Each post is (folder name, date line, extra front matter lines, image). It
    is made with `hugo new` from the archetype and then changed as
    CONTRIBUTING.md says: draft false, an author, and the image as its
    featured_image. The folder names start with contributor-test-, so that
    they do not match a post that a contributor has added to content/: `hugo
    new` does not replace a file. The other entries of ROOT are copies, or
    symbolic links for the entries in LINKED.
    """
    root = Path(tempfile.mkdtemp(prefix="stimhack-contributor-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    for entry in ROOT.iterdir():
        if entry.name in LINKED:
            (root / entry.name).symlink_to(entry)
        elif entry.is_dir() and entry.name not in SKIP:
            shutil.copytree(entry, root / entry.name, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        elif entry.is_file() and entry.name not in SKIP:
            shutil.copy(entry, root / entry.name)
    content = root / "content"
    shutil.copytree(ROOT / "content", content)
    for name, date, extra, image in posts:
        subprocess.run(
            [*hugo(), "new", "content", f"posts/2026/{name}/index.md",
             "--source", str(ROOT), "--contentDir", str(content), "--quiet"],
            check=True,
        )
        index = content / "posts" / "2026" / name / "index.md"
        lines = []
        for line in index.read_text().splitlines():
            if line.startswith("date:"):
                line = date or line
            elif line == "draft: true":
                line = "draft: false"
            elif line == "authors: []":
                line = "authors: [ian]"
            elif line.startswith("featured_image:") and image:
                line = "featured_image: cover.png"
            lines.append(line)
        lines[1:1] = extra
        index.write_text("\n".join(lines) + "\n")
        if image:
            shutil.copy(COVER, index.parent / "cover.png")
    return root


def walker_errors(root):
    """Return (walker, exception) for each helper of the tests that fails to read the content of root."""
    content = root / "content"
    walkers = {
        "test_layouts.all_posts": lambda: test_layouts.all_posts(content),
        "test_layouts.front_matter_summaries": lambda: test_layouts.front_matter_summaries(content),
        "test_layouts.wordpress_posts": lambda: test_layouts.wordpress_posts(content),
        "test_layouts.wordpress_ids": lambda: test_layouts.wordpress_ids(content),
        "test_convert.shared_wp_ids": lambda: test_convert.shared_wp_ids(root),
    }
    errors = []
    for name, walk in walkers.items():
        try:
            walk()
        except Exception as error:  # noqa: BLE001  the test reports every walker that fails
            errors.append((name, repr(error)))
    return errors


def each_test(suite):
    """Yield each test case in suite and the suites in it."""
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from each_test(test)
        else:
            yield test


# Tests that test_site_checks_pass_with_a_new_post does not run again. This one
# opens the home page once for each of about 1900 IDs and takes most of the time
# of test_layouts. It reads content/ with wordpress_ids(), which
# test_content_walkers_* check.
SLOW = {"test_layouts.PostIdLinks.test_every_post_and_page_id_goes_to_its_url"}

# A date as `hugo new` writes it: not quoted, so YAML reads a datetime.
NEW_DATE = "date: 2026-09-20T12:00:00-07:00"


class ContributorPost(unittest.TestCase):
    """A post added as CONTRIBUTING.md says does not make the unit tests fail."""

    maxDiff = None

    def test_content_walkers_skip_the_images_in_a_post_folder(self):
        root = contributor_root(("contributor-test-post", NEW_DATE, [], True))
        self.assertEqual(walker_errors(root), [])
        self.assertIn("/contributor-test-post/", test_layouts.all_posts(root / "content"))

    def test_content_walkers_give_a_post_the_url_of_its_folder(self):
        # A post folder has no slug. Hugo serves the post at the folder name,
        # in lower case.
        root = contributor_root(
            ("contributor-test-post", NEW_DATE, [], False),
            ("Contributor-Test-Case", NEW_DATE, [], False),
        )
        self.assertEqual(walker_errors(root), [])
        new = set(test_layouts.all_posts(root / "content")) - set(test_layouts.all_posts(ROOT / "content"))
        self.assertEqual(sorted(new), ["/contributor-test-case/", "/contributor-test-post/"])
        out = build(root / "content")
        for url in new:
            with self.subTest(url=url):
                self.assertTrue((out / url.strip("/") / "index.html").is_file())

    def test_category_feed_check_reads_dates_that_are_not_quoted(self):
        # A slug, so that the post URL does not stop the check before it reads the date.
        # Hugo reads a date without an offset in the timeZone of hugo.toml. The
        # check compares the dates of the posts that are not in a feed with the
        # dates in it, so the posts with these dates are older than the feeds.
        root = contributor_root(
            ("contributor-test-post", NEW_DATE, ["slug: contributor-test-post"], False),
            ("contributor-test-local", "date: 2013-06-01T12:00:00", ["slug: contributor-test-local"], False),
            ("contributor-test-day", "date: 2013-06-02", ["slug: contributor-test-day"], False),
        )
        content = root / "content"
        self.assertEqual(test_layouts.category_feed_errors(build(content), content), [])

    def test_site_checks_pass_with_a_new_post(self):
        # Run every test of test_layouts with this content/ in place of the real one.
        # A new loader: the default one keeps the -k patterns of the command line.
        # Five new posts in articles give its archive one page more than WordPress had.
        root = contributor_root(
            ("contributor-test-post", NEW_DATE, [], True),
            *((f"contributor-test-post-{n}", f"date: 2026-09-1{n}T12:00:00-07:00", [], False) for n in range(1, 5)),
        )
        default = lambda content=None, environment=None: site_build.build(content or root / "content", environment)
        tests = unittest.TestSuite(
            test for test in each_test(unittest.TestLoader().loadTestsFromModule(test_layouts)) if test.id() not in SLOW
        )
        result = unittest.TestResult()
        with mock.patch.object(test_layouts, "ROOT", root), mock.patch.object(test_layouts, "build", default):
            tests.run(result)
        self.assertGreater(result.testsRun, 50)
        failed = [(test.id(), trace.strip().splitlines()[-1]) for test, trace in result.failures + result.errors]
        self.assertEqual(failed, [])


def content_walks():
    """Return file:line for each glob() or rglob() on a path under content/ outside front_matter.py.

    Such a walk also finds the images in a post folder. content_files() in
    migration/front_matter.py returns only the content files.
    """
    found = []
    for folder in ["migration", "scripts", "tests"]:
        for path in sorted((ROOT / folder).glob("*.py")):
            if path == ROOT / "migration" / "front_matter.py":
                continue
            text = path.read_text()
            for node in ast.walk(ast.parse(text, str(path))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("glob", "rglob")
                    and "content" in ast.get_source_segment(text, node.func.value).lower()
                ):
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


class ContentWalks(unittest.TestCase):
    def test_code_walks_content_only_with_content_files(self):
        self.assertEqual(content_walks(), [])


if __name__ == "__main__":
    unittest.main()
