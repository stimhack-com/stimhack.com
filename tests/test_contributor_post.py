"""Tests that the checks of content/ still pass after a contributor adds a post.

CONTRIBUTING.md tells a contributor to add a post as a folder
content/posts/<year>/<name>/ with an index.md made from archetypes/posts.md
and the images of the post. CI runs the unit tests before it builds and
deploys the site, so a check that fails on such a post stops every deploy.

Run: python3 -m unittest discover tests
"""
import ast
import atexit
import re
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

    Each post is (folder name, date line, extra front matter lines, image). An
    extra line replaces the line of the archetype with the same key in any
    case. A folder
    name such as "name/index.html" also gives the name of the content file,
    which is index.md when it is not given. The post is made with `hugo new`
    from the archetype and then changed as CONTRIBUTING.md says: draft false,
    an author, and the image as its featured_image. The folder names start
    with contributor-test-, in any case and with a space or a hyphen, so that
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
        name, _, file_name = name.partition("/")
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
        for line in extra:
            key = line.split(":")[0] + ":"
            same = [i for i, old in enumerate(lines) if old.lower().startswith(key.lower())]
            if same:
                lines[same[0]] = line
            else:
                lines.insert(1, line)
        index.write_text("\n".join(lines) + "\n")
        if file_name:
            index.rename(index.with_name(file_name))
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


# Tests that test_site_checks_pass_with_new_posts_and_stop_posts_for_later does
# not run again. This one opens the home page once for each of about 1900 IDs
# and takes most of the time of test_layouts. It reads content/ with
# wordpress_ids(), which test_content_walkers_* check.
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
        # A post without a slug is served at the name of its folder, and a
        # post with a slug at the slug. Hugo makes a URL of the name, in
        # lower case with a hyphen for a space, and reads the slug key in any
        # case. It does not publish a post whose pubdate or published is in
        # the future, or whose unpublishdate has passed.
        root = contributor_root(
            ("contributor-test-post", NEW_DATE, [], False),
            ("Contributor-Test-Case", NEW_DATE, [], False),
            ("Contributor Test Space", NEW_DATE, [], False),
            ("contributor-test-slug", NEW_DATE, ["slug: Contributor Test Slug"], False),
            ("contributor-test-key", NEW_DATE, ["Slug: contributor-test-upper-key"], False),
            ("contributor-test-html/index.html", NEW_DATE, [], False),
            ("contributor-test-pubdate", NEW_DATE, ["pubdate: 2099-01-01"], False),
            ("contributor-test-published", NEW_DATE, ["published: 2099-01-01"], False),
            ("contributor-test-unpublished", NEW_DATE, ["unpublishdate: 2026-01-01"], False),
        )
        self.assertEqual(walker_errors(root), [])
        new = set(test_layouts.all_posts(root / "content")) - set(test_layouts.all_posts(ROOT / "content"))
        self.assertEqual(sorted(new), [
            "/contributor-test-case/",
            "/contributor-test-html/",
            "/contributor-test-post/",
            "/contributor-test-slug/",
            "/contributor-test-space/",
            "/contributor-test-upper-key/",
        ])
        out = build(root / "content")
        for url in new:
            with self.subTest(url=url):
                self.assertTrue((out / url.strip("/") / "index.html").is_file())

    def test_content_walkers_read_a_post_without_a_date(self):
        # Hugo publishes a post without a date, with the zero time. The build
        # then stops on it (PostDatesAndCategories), but CI runs the unit
        # tests first, so the walkers must read it.
        root = contributor_root(("contributor-test-no-date", "# No date.", [], False))
        self.assertEqual(walker_errors(root), [])
        self.assertIn("/contributor-test-no-date/", test_layouts.all_posts(root / "content"))

    def test_migrated_content_leaves_out_the_folders_of_new_posts(self):
        # Hugo makes a page bundle of a folder with an index file in any
        # content format, and the images in the folder are its resources.
        root = contributor_root(
            ("contributor-test-post", NEW_DATE, [], True),
            ("contributor-test-html/index.html", NEW_DATE, [], True),
        )
        migrated = test_layouts.migrated_content(root / "content")
        left = [path.name for path in (migrated / "posts" / "2026").glob("contributor-test-*")]
        self.assertEqual(left, [])

    def test_category_feed_check_reads_dates_that_are_not_quoted(self):
        # Hugo reads a date without an offset in the timeZone of hugo.toml. The
        # check compares the dates of the posts that are not in a feed with the
        # dates in it, so the posts with these dates are older than the feeds.
        root = contributor_root(
            ("contributor-test-post", NEW_DATE, [], False),
            ("contributor-test-local", "date: 2013-06-01T12:00:00", [], False),
            ("contributor-test-day", "date: 2013-06-02", [], False),
        )
        content = root / "content"
        self.assertEqual(test_layouts.category_feed_errors(build(content), content), [])

    def test_site_checks_pass_with_new_posts_and_stop_posts_for_later(self):
        # Run every test of test_layouts with this content/ in place of the real one.
        # A new loader: the default one keeps the -k patterns of the command line.
        # The new posts in articles give its archive at least one page more than WordPress had.
        # CONTRIBUTING.md says that Hugo does not publish a draft or a post with
        # a date in the future, so a pull request can add one.
        # The build step of CI does not build a post for later, but the first
        # deploy after its date does. A post for later that that build would
        # stop must stop the pull request, and the error must name its file.
        stopped = {
            "contributor-test-later-bare": ("date: 2099-01-01T12:00:00-07:00", ["authors: []", "categories: []", "summary: Later."]),
            "contributor-test-expired-bare": (NEW_DATE, ["expiryDate: 2026-01-01", "authors: [contributor-test-nobody]", "summary: Gone."]),
            "contributor-test-publish-bare": (NEW_DATE, ["publishdate: 2099-01-01", "categories: []", "summary: Not yet."]),
        }
        root = contributor_root(
            *((name, date, extra, False) for name, (date, extra) in stopped.items()),
            ("contributor-test-post", NEW_DATE, [], True),
            *((f"contributor-test-post-{n}", f"date: 2026-09-1{n}T12:00:00-07:00", [], False) for n in range(1, 5)),
            ("contributor-test-later", "date: 2099-01-01T12:00:00-07:00", ["summary: A post for later."], False),
            ("contributor-test-draft", NEW_DATE, ["draft: true", "summary: A draft."], False),
            ("contributor-test-expired", NEW_DATE, ["expiryDate: 2026-01-01", "summary: Gone."], False),
            ("contributor-test-publish", NEW_DATE, ["publishdate: 2099-01-01", "summary: Not yet."], False),
            ("contributor-test-pubdate", NEW_DATE, ["pubdate: 2099-01-01", "summary: Not yet."], False),
            # URLs that Hugo makes from a folder name, a slug and a bundle of an index.html.
            ("Contributor Test Space", "date: 2026-09-21T12:00:00-07:00", ["summary: A space."], False),
            ("contributor-test-slug", "date: 2026-09-22T12:00:00-07:00", ["slug: Contributor Test Slug"], False),
            ("contributor-test-key", "date: 2026-09-23T12:00:00-07:00", ["Slug: contributor-test-upper-key"], False),
            ("contributor-test-html/index.html", "date: 2026-09-24T12:00:00-07:00", ["summary: HTML."], True),
            # Hugo reads the keys of front matter in any case.
            ("contributor-test-categories", "date: 2026-09-15T12:00:00-07:00", ["Categories: [strategy]", "Summary: Keys."], False),
        )
        default = lambda content=None, environment=None: site_build.build(content or root / "content", environment)
        tests = unittest.TestSuite(
            test for test in each_test(unittest.TestLoader().loadTestsFromModule(test_layouts)) if test.id() not in SLOW
        )
        result = unittest.TestResult()
        with mock.patch.object(test_layouts, "ROOT", root), mock.patch.object(test_layouts, "build", default):
            tests.run(result)
        self.assertGreater(result.testsRun, 50)
        files = {name: str(root / "content" / "posts" / "2026" / name / "index.md") for name in stopped}
        traces = [(test.id(), trace) for test, trace in result.failures + result.errors]
        failed = [
            (test, trace.strip().splitlines()[-1])
            for test, trace in traces
            if not any(file in trace for file in files.values())
        ]
        self.assertEqual(failed, [])
        named = sorted(name for name, file in files.items() if any(file in trace for _, trace in traces))
        self.assertEqual(named, sorted(stopped))


class DraftPreview(unittest.TestCase):
    """The preview in CONTRIBUTING.md shows a new post before the contributor fills in its front matter.

    CONTRIBUTING.md says to make the post with `hugo new content` and to
    preview it with `hugo server -D`, before the step that adds the author.
    `hugo --buildDrafts` renders the same pages as `hugo server -D`.
    """

    maxDiff = None

    def test_preview_with_drafts_shows_a_new_post(self):
        root = contributor_root(
            # The archetype as `hugo new` writes it.
            ("contributor-test-draft", None, ["draft: true", "authors: []"], False),
            ("contributor-test-bare", "# No date.", ["draft: true", "authors: []", "categories: []"], False),
            ("contributor-test-unknown", None, ["draft: true", "authors: [contributor-test-nobody]"], False),
        )
        with tempfile.TemporaryDirectory() as out:
            result = subprocess.run(
                [*hugo(), "--source", str(root), "--destination", out, "--buildDrafts"],
                capture_output=True,
                text=True,
            )
            built = sorted(page.parent.name for page in Path(out).glob("contributor-test-*/index.html"))
        self.assertEqual((result.returncode, result.stderr.strip()), (0, ""))
        self.assertEqual(built, ["contributor-test-bare", "contributor-test-draft", "contributor-test-unknown"])


class PostAuthors(unittest.TestCase):
    """A published post without a known author stops the CI build, and the error names its file.

    CONTRIBUTING.md says that authors is required and that the author slug
    needs a file content/authors/<slug>/_index.md. Without an author the post
    has an empty author line and no creator in the feed. With a slug that
    has no such file, Hugo makes an author page from the slug alone.
    """

    maxDiff = None

    def test_post_without_a_known_author_fails_the_build_and_names_its_file(self):
        root = contributor_root(
            ("contributor-test-empty", NEW_DATE, ["authors: []"], False),
            ("contributor-test-missing", NEW_DATE, [], False),
            ("contributor-test-unknown", NEW_DATE, ["authors: [contributor-test-nobody]"], False),
            # The build step does not build these. A draft needs no author
            # (DraftPreview), and test_layouts.PostsForLater checks a post for later.
            ("contributor-test-draft", NEW_DATE, ["draft: true", "authors: []"], False),
            ("contributor-test-later", "date: 2099-01-01T12:00:00-07:00", ["authors: []"], False),
        )
        content = root / "content"
        missing = content / "posts" / "2026" / "contributor-test-missing" / "index.md"
        missing.write_text("".join(line for line in missing.read_text().splitlines(True) if not line.startswith("authors:")))
        with tempfile.TemporaryDirectory() as out:
            # The flags of the build step in .github/workflows/site.yml.
            result = subprocess.run(
                [*hugo(), "--source", str(ROOT), "--destination", out, "--contentDir", str(content),
                 "--printPathWarnings", "--panicOnWarning"],
                capture_output=True,
                text=True,
            )
            authors = {}
            for page in sorted(Path(out).glob("contributor-test-*/index.html")):
                line = re.search(r'<span class="author vcard">(.*?)<span class="bl_sep">', page.read_text(), re.S)
                authors[page.parent.name] = re.sub(r"<[^>]*>", "", line[1]).strip()
        self.assertNotEqual(result.returncode, 0, f"The build succeeded. Author lines: {authors}")
        output = result.stdout + result.stderr
        names = ["empty", "missing", "unknown", "draft", "later"]
        named = [f"contributor-test-{n}" for n in names if str(content / "posts" / "2026" / f"contributor-test-{n}" / "index.md") in output]
        self.assertEqual(named, ["contributor-test-empty", "contributor-test-missing", "contributor-test-unknown"])
        self.assertIn("Add your author slug", output)
        self.assertIn("content/authors/contributor-test-nobody/_index.md", output)


class PostDatesAndCategories(unittest.TestCase):
    """A published post without a date or a category stops the CI build, and the error names its file.

    CONTRIBUTING.md says that date and categories are required. A post
    without a category is in no category archive or category feed, and not
    on the home page, which lists the posts of params.homeCategory. Hugo
    gives a post without a date the zero time, so it is the oldest post in
    each archive and feed.
    """

    maxDiff = None

    def test_post_without_a_date_or_a_category_fails_the_build_and_names_its_file(self):
        root = contributor_root(
            ("contributor-test-empty", NEW_DATE, ["categories: []"], False),
            ("contributor-test-missing", NEW_DATE, [], False),
            ("contributor-test-no-date", "# No date.", [], False),
            # The build step does not build these. A draft needs no category or
            # date (DraftPreview), and test_layouts.PostsForLater checks a post for later.
            ("contributor-test-draft", "# No date.", ["draft: true", "categories: []"], False),
            ("contributor-test-later", "date: 2099-01-01T12:00:00-07:00", ["categories: []"], False),
        )
        content = root / "content"
        missing = content / "posts" / "2026" / "contributor-test-missing" / "index.md"
        missing.write_text("".join(line for line in missing.read_text().splitlines(True) if not line.startswith("categories:")))
        with tempfile.TemporaryDirectory() as out:
            # The flags of the build step in .github/workflows/site.yml.
            result = subprocess.run(
                [*hugo(), "--source", str(ROOT), "--destination", out, "--contentDir", str(content),
                 "--printPathWarnings", "--panicOnWarning"],
                capture_output=True,
                text=True,
            )
            published = {}
            for page in sorted(Path(out).glob("contributor-test-*/index.html")):
                date = re.search(r'<span class="onDate date updated">(.*?)</span>', page.read_text(), re.S)
                category = Path(out) / "category"
                archives = sorted({a.relative_to(category).parts[0] for a in category.rglob("index.html") if f"/{page.parent.name}/" in a.read_text()})
                published[page.parent.name] = (re.sub(r"<[^>]*>", "", date[1]).strip(), archives)
        self.assertNotEqual(result.returncode, 0, f"The build succeeded. Date and category archives: {published}")
        output = result.stdout + result.stderr
        names = ["empty", "missing", "no-date", "draft", "later"]
        named = [f"contributor-test-{n}" for n in names if str(content / "posts" / "2026" / f"contributor-test-{n}" / "index.md") in output]
        self.assertEqual(named, ["contributor-test-empty", "contributor-test-missing", "contributor-test-no-date"])
        self.assertIn("Add a category slug", output)
        self.assertIn("Add a date", output)


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


def bundle_file_names():
    """Return file:line for each comparison with the name "index.md" or "_index.md" in the code.

    Hugo makes a page bundle of the folder of a content file named index,
    and a branch bundle of one named _index, in any content format
    (common/paths/pathparser.go in the Hugo source). A check of the file
    name that also knows index.md finds only some of the bundles.
    """
    names = {"index.md", "_index.md"}
    found = []
    for folder in ["migration", "scripts", "tests"]:
        for path in sorted((ROOT / folder).glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                if isinstance(node, ast.Compare):
                    operands = [node.left, *node.comparators]
                    operands += [e for o in operands if isinstance(o, (ast.Tuple, ast.List, ast.Set)) for e in o.elts]
                    if any(isinstance(o, ast.Constant) and o.value in names for o in operands):
                        found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


class ContentWalks(unittest.TestCase):
    def test_code_walks_content_only_with_content_files(self):
        self.assertEqual(content_walks(), [])

    def test_code_finds_bundles_by_the_stem_of_the_file_name(self):
        self.assertEqual(bundle_file_names(), [])


if __name__ == "__main__":
    unittest.main()
