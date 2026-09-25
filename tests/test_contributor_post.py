"""Tests that the checks of content/ still pass after a contributor adds a post.

CONTRIBUTING.md tells a contributor to add a post as a folder
content/posts/<year>/<name>/ with an index.md made from archetypes/posts.md
and the images of the post. CI runs the unit tests before it builds and
deploys the site, so a check that fails on such a post stops every deploy.

Run: python3 -m unittest discover tests
"""
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
    featured_image. The other entries of ROOT are copies, or symbolic links
    for the entries in LINKED.
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
            check=True, capture_output=True,
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


# A date as `hugo new` writes it: not quoted, so YAML reads a datetime.
NEW_DATE = "date: 2026-09-20T12:00:00-07:00"


class ContributorPost(unittest.TestCase):
    """A post added as CONTRIBUTING.md says does not make the unit tests fail."""

    maxDiff = None

    def test_content_walkers_skip_the_images_in_a_post_folder(self):
        root = contributor_root(("probe-post", NEW_DATE, [], True))
        self.assertEqual(walker_errors(root), [])
        self.assertIn("/probe-post/", test_layouts.all_posts(root / "content"))

    def test_content_walkers_give_a_post_the_url_of_its_folder(self):
        # A post folder has no slug. Hugo serves the post at the folder name,
        # in lower case.
        root = contributor_root(("probe-post", NEW_DATE, [], False), ("Probe-Case", NEW_DATE, [], False))
        self.assertEqual(walker_errors(root), [])
        posts = test_layouts.all_posts(root / "content")
        out = build(root / "content")
        for url in ["/probe-post/", "/probe-case/"]:
            with self.subTest(url=url):
                self.assertIn(url, posts)
                self.assertTrue((out / url.strip("/") / "index.html").is_file())

    def test_category_feed_check_reads_dates_that_are_not_quoted(self):
        # A slug, so that the post URL does not stop the check before it reads the date.
        # Hugo reads a date without an offset in the timeZone of hugo.toml.
        root = contributor_root(
            ("probe-post", NEW_DATE, ["slug: probe-post"], False),
            ("probe-local", "date: 2026-09-19T12:00:00", ["slug: probe-local"], False),
            ("probe-day", "date: 2026-09-18", ["slug: probe-day"], False),
        )
        content = root / "content"
        self.assertEqual(test_layouts.category_feed_errors(build(content), content), [])

    def test_site_checks_pass_with_a_new_post(self):
        # Run every test of test_layouts with this content/ in place of the real one.
        # A new loader: the default one keeps the -k patterns of the command line.
        # Five new posts in articles give its archive one page more than WordPress had.
        root = contributor_root(
            ("probe-post", NEW_DATE, [], True),
            *((f"probe-post-{n}", f"date: 2026-09-1{n}T12:00:00-07:00", [], False) for n in range(1, 5)),
        )
        default = lambda content=None, environment=None: site_build.build(content or root / "content", environment)
        result = unittest.TestResult()
        with mock.patch.object(test_layouts, "ROOT", root), mock.patch.object(test_layouts, "build", default):
            unittest.TestLoader().loadTestsFromModule(test_layouts).run(result)
        self.assertGreater(result.testsRun, 50)
        failed = [(test.id(), trace.strip().splitlines()[-1]) for test, trace in result.failures + result.errors]
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
