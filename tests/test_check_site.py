"""Tests for the checks in scripts/check_site.py, on a small built site."""
import ast
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import check_site  # noqa: E402
import convert  # noqa: E402

# Each page is served at /<dir>/ from public/<dir>/index.html.
PAGES = {
    "post/index.html": """
        <img src="hedge-fund.png" alt="exists">
        <img src="hedge-fnd.png" alt="typo">
        <img src="small.png" srcset="small.png 300w, big-missing.png 600w, /post/small.png 2x">
        <video src="clip.mp4" poster="missing-poster.jpg"></video>
        <img data-src="missing-lazy.png">
        <a href=missing-unquoted.html>unquoted</a>
        <a href="hedge-fund.png?ver=2#top">query and fragment</a>
        <a href="../other/">parent directory</a>
        <a href="/gone/">root-relative</a>
    """,
    # Only URLs that are not paths on this site, or paths that exist.
    "other/index.html": """
        <a href="https://example.com/missing">https</a>
        <a href="http://example.com/missing">http</a>
        <img src="//cdn.example.com/missing.png">
        <a href="mailto:someone@example.com">mail</a>
        <a href="tel:+15550100">phone</a>
        <a href="javascript:void(0)">script</a>
        <img src="data:image/png;base64,iVBORw0KGgo=">
        <a href="#comments">fragment</a>
        <a href="?page=2">query</a>
        <a href="">empty</a>
        <img srcset="https://example.com/a.png 1x, //cdn.example.com/b.png 2x">
        <a href="../post/hedge-fund.png">exists</a>
        <a HREF=" ../post/ ">upper case name and spaces</a>
        <img srcset="data:image/png;base64,iVBOR,w0KGgo= 1x, ../post/small.png 2x">
        <img srcset="../post/small.png, ../post/hedge-fund.png 2x">
        <a href="https://forum.stimhack.com/missing/">another host of stimhack.com</a>
        <a href="https://notstimhack.com/missing/">a host that ends in stimhack.com</a>
        <a href="https://stimhack.com.example.com/missing/">a host that starts with stimhack.com</a>
        <a href="ftp://stimhack.com/missing/">not http</a>
        <a href="https://stimhack.com/post/small.png">exists on the production host</a>
        <a href="https://static.example.com">home page of the built host, no path</a>
        <meta http-equiv="refresh" content="5">
        <meta property="og:title" content="https://stimhack.com/missing-title/">
    """,
    # Absolute URLs on this site: the production host with and without www.,
    # and the host of the built site, which index.html names in its canonical
    # link. Alias pages redirect with a meta refresh tag.
    "own-host/index.html": """
        <link rel="canonical" href="https://static.example.com/own-host/gone-canonical/">
        <a href="https://stimhack.com/gone-https/">https</a>
        <a href="http://www.stimhack.com/gone-www/">http and www.</a>
        <img src="//stimhack.com/gone-scheme-relative.png">
        <a href="HTTPS://StimHack.com/gone-upper-case/">upper case</a>
        <a href="https://stimhack.com/gone%20encoded/?p=1#top">encoded, query and fragment</a>
        <img srcset="https://static.example.com/gone-srcset.png 2x">
        <meta http-equiv="refresh" content="0; url=https://static.example.com/gone-alias/">
        <meta HTTP-EQUIV="Refresh" content="0;URL='../gone-quoted/'">
        <meta property="og:image" content="https://stimhack.com/gone-og-image.png">
        <meta property="og:url" content="https://static.example.com/gone-og-url/">
    """,
    # Images from addresses that no longer serve images, in each attribute
    # that loads an image.
    "dead-images/index.html": """
        <img src="http://cardgamedb.com/forums/uploads/img-src.jpg">
        <img src = "http://www.cardgamedb.com/forums/uploads/spaces-around-equals.jpg">
        <img src="data:image/gif;base64,R0lGOD" data-src="https://netrunnerdb.com/card_image/data-src.png">
        <img src="data:image/gif;base64,R0lGOD" srcset="https://netrunnerdb.com/web/bundles/srcset.png 2x">
        <picture><source srcset="https://netrunnerdb.com/bundles/source-srcset.png 1x"></picture>
        <video src="data:video/mp4;base64,AAAA" poster="http://cardgamedb.com/forums/uploads/poster.jpg"></video>
        <meta property="og:image" content="http://cardgamedb.com/forums/uploads/og-image.jpg">
        <img src="//www.cardgamedb.com/forums/uploads/scheme-relative.jpg">
        <img src="HTTPS://NetrunnerDB.com/card_image/upper-case.png">
        <img src="https://card-images.netrunnerdb.com/v2/large/01001.jpg">
    """,
    "index.html": '<link rel="canonical" href="https://static.example.com/">',
    # A page that is not index.html is served at its own file name, so its
    # relative links resolve against the directory it is in.
    "404.html": '<a href="post/">post</a><img src="post/small.png">',
}
FILES = ["post/hedge-fund.png", "post/small.png", "post/clip.mp4"]


def problems(public):
    """Run the check on the site in public/ and return the lines it prints."""
    out = io.StringIO()
    with mock.patch.object(check_site, "PUBLIC", public), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(io.StringIO()):
        check_site.main()
    return set(out.getvalue().splitlines())


class BrokenLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public = Path(tempfile.mkdtemp(prefix="check-site-")) / "public"
        cls.addClassCleanup(shutil.rmtree, cls.public.parent)
        for name, html in PAGES.items():
            (cls.public / name).parent.mkdir(parents=True, exist_ok=True)
            (cls.public / name).write_text(html)
        for name in FILES:
            (cls.public / name).write_bytes(b"")
        cls.problems = problems(cls.public)
        cls.broken = {line for line in cls.problems if line.startswith("broken link in ")}

    def test_reports_missing_relative_and_root_relative_targets(self):
        reported = {line for line in self.broken if line.startswith("broken link in /post/")}
        self.assertEqual(
            reported,
            {
                "broken link in /post/index.html: /post/hedge-fnd.png",
                "broken link in /post/index.html: /post/big-missing.png",
                "broken link in /post/index.html: /post/missing-poster.jpg",
                "broken link in /post/index.html: /post/missing-lazy.png",
                "broken link in /post/index.html: /post/missing-unquoted.html",
                "broken link in /post/index.html: /gone/",
            },
            f"reported: {sorted(reported)}",
        )

    def test_reports_missing_targets_of_absolute_urls_on_this_site(self):
        reported = {line for line in self.broken if line.startswith("broken link in /own-host/")}
        self.assertEqual(
            reported,
            {
                "broken link in /own-host/index.html: /own-host/gone-canonical/",
                "broken link in /own-host/index.html: /gone-https/",
                "broken link in /own-host/index.html: /gone-www/",
                "broken link in /own-host/index.html: /gone-scheme-relative.png",
                "broken link in /own-host/index.html: /gone-upper-case/",
                "broken link in /own-host/index.html: /gone encoded/",
                "broken link in /own-host/index.html: /gone-srcset.png",
                "broken link in /own-host/index.html: /gone-alias/",
                "broken link in /own-host/index.html: /gone-quoted/",
                "broken link in /own-host/index.html: /gone-og-image.png",
                "broken link in /own-host/index.html: /gone-og-url/",
            },
            f"reported: {sorted(reported)}",
        )

    def test_skips_urls_that_are_not_paths_on_this_site(self):
        self.assertEqual(
            {line for line in self.broken if not line.startswith(("broken link in /post/", "broken link in /own-host/"))},
            set(),
        )

    def test_reports_images_from_dead_addresses_in_each_image_attribute(self):
        reported = {line for line in self.problems if line.startswith("file from a dead address in ")}
        self.assertEqual(
            reported,
            {
                "file from a dead address in /dead-images/index.html: " + url
                for url in [
                    "http://cardgamedb.com/forums/uploads/img-src.jpg",
                    "http://www.cardgamedb.com/forums/uploads/spaces-around-equals.jpg",
                    "https://netrunnerdb.com/card_image/data-src.png",
                    "https://netrunnerdb.com/web/bundles/srcset.png",
                    "https://netrunnerdb.com/bundles/source-srcset.png",
                    "http://cardgamedb.com/forums/uploads/poster.jpg",
                    "http://cardgamedb.com/forums/uploads/og-image.jpg",
                    "//www.cardgamedb.com/forums/uploads/scheme-relative.jpg",
                    "HTTPS://NetrunnerDB.com/card_image/upper-case.png",
                ]
            },
            f"reported: {sorted(reported)}",
        )

    def test_checks_the_directory_given_on_the_command_line(self):
        result = subprocess.run(
            [sys.executable, str(check_site.ROOT / "scripts" / "check_site.py"), str(self.public)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("broken link in /post/index.html: /post/hedge-fnd.png", result.stdout.splitlines())


class NoCanonicalLink(unittest.TestCase):
    def test_reports_a_home_page_without_a_canonical_link(self):
        public = Path(tempfile.mkdtemp(prefix="check-site-")) / "public"
        self.addCleanup(shutil.rmtree, public.parent)
        public.mkdir()
        (public / "index.html").write_text('<a href="https://static.example.com/gone/">built host</a>')
        out = io.StringIO()
        with mock.patch.object(check_site, "PUBLIC", public), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            check_site.main()
        problems = [line for line in out.getvalue().splitlines() if not line.startswith(("legacy URL missing: ", "WordPress ID"))]
        self.assertEqual(len(problems), 1, f"problems: {problems}")
        self.assertIn("canonical", problems[0])


class ImageUrlsReadWithTheParser(unittest.TestCase):
    # A regular expression on "<img ... src=" misses srcset, poster, data-src
    # and other spellings of the tag. Read image URLs with check_site.Links.
    ALLOWED = {
        # Reads the WordPress export, not the built site. It is run once, by hand.
        "migration/check_external_images.py",
        # Removes whole img tags. check_site.py finds any icon it leaves in the built site.
        "migration/nrdb_images.py",
    }

    def test_no_new_regular_expression_reads_img_tags(self):
        found = {
            path.relative_to(check_site.ROOT).as_posix()
            for folder in ("scripts", "migration")
            for path in (check_site.ROOT / folder).rglob("*.py")
            if img_patterns(path.read_text())
        }
        self.assertEqual(found - self.ALLOWED, set())

    def test_finds_each_spelling_of_an_img_pattern(self):
        for source in [
            'import re\nre.compile(r"<img\\b[^>]*src")',
            'import re\nre.compile(r"""<img[^>]*src=["\']([^"\']+)""", re.I)',
            'import re\nre.findall("<img ", html)',
            'import re\nre.search("<IMG", html)',
            'import re\nre.compile("(?i)<img")',
            'import re\nre.compile(f"<img{ATTRIBUTES}")',
            'import re\nTAG = "<im" + "g"\n\ndef find(html):\n    return re.findall(TAG + " src", html)',
            'import re\nIMG = "<img"\nPATTERN = IMG + "[^>]*src"\nre.compile(PATTERN)',
            'import re\nre.sub(pattern="<img[^>]*>", repl="", string=html)',
            'import re as regex\nregex.match("<img", html)',
            'from re import finditer\nfinditer("<img", html)',
            'from re import split as cut\ncut("<img", html)',
            *(f'import re\nre.{name}("<img", html)' for name in sorted(RE_FUNCTIONS)),
        ]:
            with self.subTest(source=source):
                self.assertNotEqual(img_patterns(source), [])

    def test_ignores_img_text_that_is_not_a_pattern(self):
        for source in [
            'html = "<img src=x>"\nprint(html)',
            'import re\nre.sub("<picture>", "<img>", html)',
            'import re\nre.compile("<image")',
        ]:
            with self.subTest(source=source):
                self.assertEqual(img_patterns(source), [])


RE_FUNCTIONS = {"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}


def img_patterns(source):
    """Return the line of each regular expression in source whose pattern contains "<img" in any case.

    A pattern counts when it is the pattern argument of a function of the re
    module, written in the call or held by a name that the source assigns
    anywhere. The text of a pattern is every string constant in it and in the
    names it uses, joined, so a pattern built from pieces also counts.
    """
    tree = ast.parse(source)
    modules, functions, assigned = set(), set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.asname or alias.name for alias in node.names if alias.name == "re"}
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            functions |= {alias.asname or alias.name for alias in node.names if alias.name in RE_FUNCTIONS}
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)

    def text(node, seen):
        parts = []
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                parts.append(child.value)
            elif isinstance(child, ast.Name) and child.id not in seen:
                parts.extend(text(value, seen | {child.id}) for value in assigned.get(child.id, []))
        return "".join(parts)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
            and func.attr in RE_FUNCTIONS
            or isinstance(func, ast.Name)
            and func.id in functions
        ):
            continue
        patterns = node.args[:1] + [keyword.value for keyword in node.keywords if keyword.arg == "pattern"]
        if any("<img" in text(pattern, set()).lower() for pattern in patterns):
            found.append(node.lineno)
    return found


class WordPressIds(unittest.TestCase):
    """The check compares /wp-ids.json in the build with the IDs in tests/wp-ids.txt."""

    def problems(self, wp_ids_json):
        """Run the check on a site whose /wp-ids.json has the text wp_ids_json, or no /wp-ids.json if it is None."""
        root = Path(tempfile.mkdtemp(prefix="check-site-"))
        self.addCleanup(shutil.rmtree, root)
        public = root / "public"
        public.mkdir()
        (public / "index.html").write_text('<link rel="canonical" href="https://static.example.com/">')
        if wp_ids_json is not None:
            (public / "wp-ids.json").write_text(wp_ids_json)
        (root / "wp-ids.txt").write_text("2 /about/\n\n1879 /articles-and-guides/\n7011 /café/\n")
        with mock.patch.object(check_site, "WP_IDS", root / "wp-ids.txt"):
            return {line for line in problems(public) if line.startswith("WordPress ID")}

    def test_accepts_a_map_with_every_listed_id_and_more(self):
        self.assertEqual(
            self.problems('{"2": "/about/", "1879": "/articles-and-guides/", "7011": "/caf%C3%A9/", "5": "/new/"}'), set()
        )

    def test_reports_a_listed_id_that_the_map_does_not_have(self):
        self.assertEqual(
            self.problems('{"1879": "/articles-and-guides/", "7011": "/café/"}'),
            {"WordPress ID missing from /wp-ids.json: 2 /about/"},
        )

    def test_reports_a_listed_id_that_goes_to_another_url(self):
        self.assertEqual(
            self.problems('{"2": "/about-us/", "1879": "/articles-and-guides/", "7011": "/café/"}'),
            {"WordPress ID goes to the wrong URL in /wp-ids.json: 2 /about-us/, not /about/"},
        )

    def test_reports_every_listed_id_when_the_map_is_missing_or_not_an_object(self):
        missing = {
            "WordPress ID missing from /wp-ids.json: 2 /about/",
            "WordPress ID missing from /wp-ids.json: 1879 /articles-and-guides/",
            "WordPress ID missing from /wp-ids.json: 7011 /café/",
        }
        # Hugo writes null when no content file has a wp_id.
        for text, reason in [("null", "is not a JSON object"), ("[]", "is not a JSON object"),
                             ("{", "cannot be read"), (None, "cannot be read")]:
            with self.subTest(text=text):
                problems = self.problems(text)
                self.assertLessEqual(missing, problems)
                [other] = problems - missing
                self.assertIn(reason, other)


class LegacyUrls(unittest.TestCase):
    """The check looks in the build for each URL in tests/legacy-urls.txt."""

    def test_reports_the_listed_urls_that_the_build_does_not_serve(self):
        root = Path(tempfile.mkdtemp(prefix="check-site-"))
        self.addCleanup(shutil.rmtree, root)
        public = root / "public"
        # /no-index/ is a directory without an index.html, so it serves nothing.
        for name in ["index.html", "kept/index.html", "café menu/index.html", "uploads/card.png", "no-index/other.html"]:
            (public / name).parent.mkdir(parents=True, exist_ok=True)
            (public / name).write_text('<link rel="canonical" href="https://static.example.com/">')
        (root / "tests").mkdir()
        (root / "tests" / "legacy-urls.txt").write_text(
            "/kept/\n/uploads/card.png\n/caf%C3%A9%20menu/\n\n/gone/\n/no-index/\n/caf%C3%A9-gone/\n/uploads/gone.png\n"
        )
        with mock.patch.object(check_site, "ROOT", root):
            reported = {line for line in problems(public) if line.startswith("legacy URL missing: ")}
        self.assertEqual(
            reported,
            {
                "legacy URL missing: /gone/",
                "legacy URL missing: /no-index/",
                "legacy URL missing: /caf%C3%A9-gone/",
                "legacy URL missing: /uploads/gone.png",
            },
        )


class KnownBrokenLinks(unittest.TestCase):
    """The check skips each path in tests/known-broken-links.txt and reports other broken links, also ones like it."""

    def test_skips_only_the_listed_paths(self):
        self.assertNotEqual(check_site.KNOWN_BROKEN, set())
        public = Path(tempfile.mkdtemp(prefix="check-site-")) / "public"
        self.addCleanup(shutil.rmtree, public.parent)
        (public / "links").mkdir(parents=True)
        (public / "index.html").write_text('<link rel="canonical" href="https://static.example.com/">')
        unlisted = set()
        for path in check_site.KNOWN_BROKEN:
            # A longer path, the path with a trailing slash, the same file
            # name in another folder and another file in the same folder.
            unlisted |= {path + "x", path + "/", "/unlisted" + path, path.rpartition("/")[0] + "/unlisted.png"}
        (public / "links" / "index.html").write_text(
            "".join(f'<a href="{quote(path)}">link</a>' for path in sorted(check_site.KNOWN_BROKEN | unlisted))
        )
        reported = {line for line in problems(public) if line.startswith("broken link in ")}
        self.assertEqual(reported, {f"broken link in /links/index.html: {path}" for path in unlisted - check_site.KNOWN_BROKEN})


class SrcsetSpaces(unittest.TestCase):
    """Only space, tab, line feed, form feed and carriage return separate the parts of a srcset.

    A no-break space (&nbsp; in the HTML) or a vertical tab is part of a URL.
    """

    SRCSETS = [
        "\xa0a.png 1x",
        "\x0ba.png 1x",
        "a.png\xa01x, b.png 2x",
        "\x1c a.png 1x,\u2003b.png",
        " \t\n\r\fa.png\f1x,\rb.png",
        "small.png 300w, big-missing.png 600w, /post/small.png 2x",
        "data:image/png;base64,iVBOR,w0KGgo= 1x, ../post/small.png 2x",
        "../post/small.png, ../post/hedge-fund.png 2x",
        "https://example.com/i?u=,https://stimhack.com/y.png 1x, https://stimhack.com/z.png 2x",
    ]

    def test_a_url_can_start_with_a_space_that_is_not_ascii(self):
        self.assertEqual(check_site.srcset_urls("\xa0a.png 1x"), ["\xa0a.png"])
        self.assertEqual(check_site.srcset_urls("\x0ba.png 1x"), ["\x0ba.png"])
        self.assertEqual(check_site.srcset_urls("a.png\xa01x, b.png 2x"), ["a.png\xa01x", "b.png"])

    def test_convert_finds_the_same_urls_as_the_check(self):
        for srcset in self.SRCSETS:
            with self.subTest(srcset=srcset):
                found = []
                with mock.patch.object(convert, "rewrite_url", side_effect=lambda url: found.append(url) or url):
                    self.assertEqual(convert.rewrite_srcset(srcset), srcset)
                self.assertEqual(found, check_site.srcset_urls(srcset))

    def test_the_check_reports_a_url_that_starts_with_a_no_break_space(self):
        public = Path(tempfile.mkdtemp(prefix="check-site-")) / "public"
        self.addCleanup(shutil.rmtree, public.parent)
        (public / "post").mkdir(parents=True)
        (public / "index.html").write_text('<link rel="canonical" href="https://static.example.com/">')
        (public / "post" / "a.png").write_bytes(b"")
        # The URL is "\xa0a.png", not "a.png", and the site has no file with that name.
        (public / "post" / "index.html").write_text('<img srcset="&nbsp;a.png 1x">')
        reported = {line for line in problems(public) if line.startswith("broken link in ")}
        self.assertEqual(reported, {"broken link in /post/index.html: /post/\xa0a.png"})


def post_problems(test, markup, site="https://static.example.com/", outside=()):
    """Return the problems that the check reports for a site at the URL site whose /post/ page has markup and whose /post/a.png exists.

    outside are the names of files to write in the directory that holds public/.
    """
    public = Path(tempfile.mkdtemp(prefix="check-site-")) / "public"
    test.addCleanup(shutil.rmtree, public.parent)
    (public / "post").mkdir(parents=True)
    for name in outside:
        (public.parent / name).write_bytes(b"")
    (public / "index.html").write_text(f'<link rel="canonical" href="{site}">')
    (public / "post" / "a.png").write_bytes(b"")
    (public / "post" / "index.html").write_text(markup)
    return problems(public)


class UrlSpaces(unittest.TestCase):
    """A browser removes C0 controls and spaces from the ends of a URL, and tabs and line breaks inside it.

    Other white space, such as a no-break space (&nbsp;) or an em space
    (&#x2003;), is part of the URL. In a meta refresh tag, only ASCII white
    space separates the delay, "url=" and the URL. Chromium 153 requested the
    same URLs from this markup.
    """

    # Markup on /post/, where a.png exists, and the broken paths that the
    # check must report for it.
    BROKEN = [
        ('<a href="&nbsp;a.png">', {"/post/\xa0a.png"}),
        ('<img src="&#x2003;a.png">', {"/post/ a.png"}),
        ('<video poster="a.png&nbsp;"></video>', {"/post/a.png\xa0"}),
        ('<img data-src="&nbsp;a.png">', {"/post/\xa0a.png"}),
        ('<meta property="og:image" content="&nbsp;a.png">', {"/post/\xa0a.png"}),
        ('<meta property="og:url" content="https://stimhack.com/post/a.png&nbsp;">', {"/post/a.png\xa0"}),
        ('<meta http-equiv="refresh" content="0; url=&nbsp;a.png">', {"/post/\xa0a.png"}),
        ('<meta http-equiv="refresh" content="0;&nbsp;url=a.png">', {"/post/\xa0url=a.png"}),
        ('<meta http-equiv="refresh" content="0;\x0burl=a.png">', {"/post/url=a.png"}),
        # A no-break space after the delay stops the refresh.
        ('<meta http-equiv="refresh" content="0&nbsp;url=gone.png">', set()),
        ('<a href=" \t\n\f\ra.png\x01\x1f">', set()),
        ('<img src="a\t.p\nng">', set()),
        ('<img srcset="a.png\x0b 1x">', set()),
        ("<meta http-equiv=\"refresh\" content=\"0;url='a.png\x01'\">", set()),
    ]
    # Markup and the image URLs that the check must report as from a dead address.
    DEAD = [
        ('<img src="\x01https://netrunnerdb.com/card_image/x.png">', {"https://netrunnerdb.com/card_image/x.png"}),
        ('<img srcset="\x0bhttps://netrunnerdb.com/card_image/y.png 1x">', {"https://netrunnerdb.com/card_image/y.png"}),
        # A path on this site, since the no-break space is part of the URL.
        ('<img src="&nbsp;https://netrunnerdb.com/card_image/z.png">', set()),
    ]

    def check(self, markup):
        return post_problems(self, markup)

    def test_reports_the_path_that_a_browser_requests(self):
        for markup, paths in self.BROKEN:
            with self.subTest(markup=markup):
                prefix = "broken link in /post/index.html: "
                broken = {line.removeprefix(prefix) for line in self.check(markup) if line.startswith("broken link in ")}
                self.assertEqual(broken, paths, f"{markup!r} reported {sorted(broken)}")

    def test_reports_an_image_that_a_browser_loads_from_a_dead_address(self):
        for markup, urls in self.DEAD:
            with self.subTest(markup=markup):
                prefix = "file from a dead address in /post/index.html: "
                dead = {line.removeprefix(prefix) for line in self.check(markup) if line.startswith(prefix)}
                self.assertEqual(dead, urls, f"{markup!r} reported {sorted(dead)}")


class UrlPaths(unittest.TestCase):
    """The check resolves a URL on this site to the path that a browser requests.

    For an http or https URL, and so for a relative URL on a page of this
    site, a browser keeps a semicolon and the text after it in the path, reads
    a backslash before the query as a slash, and reads %2e as a dot in a "."
    or ".." segment (URL Standard, https://url.spec.whatwg.org/#path-state).
    The expected paths are the pathname that whatwg-url 16.0.1, the reference
    implementation of the URL Standard, gives for each URL against
    https://stimhack.com/post/, decoded.
    """

    # Markup on /post/, where a.png exists, and the broken paths that the
    # check must report for it.
    BROKEN = [
        ('<img src="a.png;">', {"/post/a.png;"}),
        ('<a href="/post/a.png;">', {"/post/a.png;"}),
        ('<a href="https://stimhack.com/post/a.png;">', {"/post/a.png;"}),
        ('<a href="//stimhack.com/post/a.png;">', {"/post/a.png;"}),
        ('<img src="a.png;x">', {"/post/a.png;x"}),
        ('<img src="..;/a.png">', {"/post/..;/a.png"}),
        (r'<img src="\a.png">', {"/a.png"}),
        (r'<img src="gone.png\">', {"/post/gone.png/"}),
        (r'<img src="sub\..\a.png">', set()),
        (r'<img src="gone.png?a\b#c\d">', {"/post/gone.png"}),
        (r'<a href="https:\\stimhack.com\gone.png">', {"/gone.png"}),
        (r'<a href="https://stimhack.com\post\a.png;">', {"/post/a.png;"}),
        (r'<a href="\\stimhack.com\gone.png">', {"/gone.png"}),
        (r'<a href="/\stimhack.com/gone.png">', {"/gone.png"}),
        ('<img src="x/%2e%2e/a.png">', set()),
        ('<img src="x/.%2E/a.png">', set()),
        ('<img src="%2e%2e/%2e%2e/gone.png">', {"/gone.png"}),
        ('<a href="x/%2e">', {"/post/x/"}),
    ]

    def test_reports_the_path_that_a_browser_requests(self):
        for markup, paths in self.BROKEN:
            with self.subTest(markup=markup):
                prefix = "broken link in /post/index.html: "
                broken = {line.removeprefix(prefix) for line in post_problems(self, markup) if line.startswith("broken link in ")}
                self.assertEqual(broken, paths, f"{markup!r} reported {sorted(broken)}")


class FilePaths(unittest.TestCase):
    """The check finds a file for a path only where a static server finds one.

    A file name with a slash after it names no file (path_resolution(7),
    "Trailing slashes"), so /post/a.png/ is broken when /post/a.png is a file.
    A server serves only the files in its root, so a path that goes out of
    public/, such as /../a.png from a link to /..%2Fa.png, is broken.
    """

    # Markup on /post/, where a.png exists and outside.png exists next to
    # public/, and the broken paths that the check must report for it.
    BROKEN = [
        ('<img src="a.png/">', {"/post/a.png/"}),
        (r'<img src="a.png\">', {"/post/a.png/"}),
        ('<a href="/post/a.png/">', {"/post/a.png/"}),
        ('<a href="https://stimhack.com/post/a.png/">', {"/post/a.png/"}),
        ('<a href="a.png/.">', {"/post/a.png/"}),
        ('<a href="/..%2Foutside.png">', {"/../outside.png"}),
        ('<img src="..%2F..%2Foutside.png">', {"/post/../../outside.png"}),
        ('<a href="./">', set()),
        ('<a href="/post">', set()),
        ('<img src="a.png">', set()),
    ]

    def test_reports_the_paths_that_a_server_has_no_file_for(self):
        for markup, paths in self.BROKEN:
            with self.subTest(markup=markup):
                prefix = "broken link in /post/index.html: "
                problems = post_problems(self, markup, outside=["outside.png"])
                broken = {line.removeprefix(prefix) for line in problems if line.startswith("broken link in ")}
                self.assertEqual(broken, paths, f"{markup!r} reported {sorted(broken)}")


class UrlSchemes(unittest.TestCase):
    """The check reads an http or https URL without "//" after the scheme as a browser does.

    When the scheme is the scheme of the page, the URL is relative to the
    page, so "https:gone.png" on an https page is "gone.png". When the scheme
    is another one, the text after the scheme is a host, so "http:gone.png"
    on an https page is on the host gone.png. A browser ignores each slash or
    backslash before a host, so "https:///stimhack.com/" is on the host
    stimhack.com (URL Standard, scheme state and special authority ignore
    slashes state, https://url.spec.whatwg.org/#scheme-state). The pages of
    the site have the scheme of its canonical link. The expected paths are
    the pathname that whatwg-url 16.0.1, the reference implementation of the
    URL Standard, gives for each URL against https://stimhack.com/post/ or
    http://stimhack.com/post/, decoded.
    """

    # Markup on /post/ of an https site, where a.png exists, and the broken
    # paths that the check must report for it.
    BROKEN = [
        ('<img src="https:gone.png">', {"/post/gone.png"}),
        ('<img src="HTTPS:gone.png">', {"/post/gone.png"}),
        ('<img src="https:/gone.png">', {"/gone.png"}),
        (r'<img src="https:\gone.png">', {"/gone.png"}),
        (r'<img src="https:..\gone.png">', {"/gone.png"}),
        ('<img src="https:a.png">', set()),
        ('<a href="https:">', set()),
        ('<a href="https:?q">', set()),
        ('<a href="https:///stimhack.com/gone.png">', {"/gone.png"}),
        ('<a href="https:////stimhack.com/gone.png">', {"/gone.png"}),
        (r'<a href="https:/\stimhack.com/gone.png">', {"/gone.png"}),
        ('<a href="///stimhack.com/gone.png">', {"/gone.png"}),
        (r'<a href="\\\stimhack.com/gone.png">', {"/gone.png"}),
        ('<a href="http:stimhack.com/gone.png">', {"/gone.png"}),
        ('<a href="http:///stimhack.com/gone.png">', {"/gone.png"}),
        ('<a href="http:gone.png">', set()),
        ('<a href="http:/gone.png">', set()),
        ('<a href="http:">', set()),
        # Not a valid URL, since the host is empty.
        ('<a href="http:@/gone.png">', set()),
        ('<a href="https:@/gone.png">', {"/post/@/gone.png"}),
    ]
    # Markup on /post/ of an http site and the broken paths.
    BROKEN_ON_HTTP = [
        ('<img src="http:gone.png">', {"/post/gone.png"}),
        ('<img src="http:/gone.png">', {"/gone.png"}),
        ('<a href="http:stimhack.com/gone.png">', {"/post/stimhack.com/gone.png"}),
        ('<a href="https:///stimhack.com/gone.png">', {"/gone.png"}),
        ('<img src="https:gone.png">', set()),
        ('<a href="https:">', set()),
    ]

    # Markup on /post/ of an https site and the image URLs that the check must
    # report as from a dead address.
    DEAD = [
        ('<img src="https:///netrunnerdb.com/card_image/a.png">', {"https:///netrunnerdb.com/card_image/a.png"}),
        ('<img src="http:netrunnerdb.com/card_image/b.png">', {"http:netrunnerdb.com/card_image/b.png"}),
        (r'<img src="https:\\netrunnerdb.com\card_image\c.png">', {r"https:\\netrunnerdb.com\card_image\c.png"}),
        ('<img src="https://netrunnerdb.com/x/../card_image/e.png">', {"https://netrunnerdb.com/x/../card_image/e.png"}),
        ('<img src="//NetrunnerDB.com:443/card_image/f.png">', {"//NetrunnerDB.com:443/card_image/f.png"}),
        # A path on this site, /post/netrunnerdb.com/card_image/d.png.
        ('<img src="https:netrunnerdb.com/card_image/d.png">', set()),
    ]

    def test_reports_an_image_that_a_browser_loads_from_a_dead_address(self):
        for markup, urls in self.DEAD:
            with self.subTest(markup=markup):
                prefix = "file from a dead address in /post/index.html: "
                dead = {line.removeprefix(prefix) for line in post_problems(self, markup) if line.startswith(prefix)}
                self.assertEqual(dead, urls, f"{markup!r} reported {sorted(dead)}")

    def check(self, site, cases):
        for markup, paths in cases:
            with self.subTest(site=site, markup=markup):
                prefix = "broken link in /post/index.html: "
                problems = post_problems(self, markup, site)
                broken = {line.removeprefix(prefix) for line in problems if line.startswith("broken link in ")}
                self.assertEqual(broken, paths, f"{markup!r} reported {sorted(broken)}")

    def test_reports_the_path_that_a_browser_requests_on_an_https_site(self):
        self.check("https://static.example.com/", self.BROKEN)

    def test_reports_the_path_that_a_browser_requests_on_an_http_site(self):
        self.check("http://static.example.com/", self.BROKEN_ON_HTTP)


class HostsReadWithSplitUrl(unittest.TestCase):
    # urlsplit and a pattern such as "^https?://host" find no host in
    # "http:host/a.png" or "https:///host/a.png", which a browser loads from
    # host. Read the host of a URL in the built HTML with check_site.split_url.
    ALLOWED = {
        "split_url: parts.hostname",
        "split_url: '//'",
        # The canonical link of the built home page, which Hugo writes as
        # scheme://host/ from the baseURL.
        "main: site.hostname",
    }

    def test_no_new_code_in_scripts_reads_the_host_of_a_url(self):
        found = {
            f"{path.name}: {text}"
            for path in (check_site.ROOT / "scripts").rglob("*.py")
            for text in host_reads(path.read_text())
            if text not in self.ALLOWED
        }
        self.assertEqual(found, set())

    def test_finds_each_spelling(self):
        for source in [
            "urlsplit(url).hostname",
            "parts.netloc",
            'import re\nre.compile(r"^(?:https?:)?//(?:www\\.)?example\\.com")',
            'HOST = f"https://{name}/"',
        ]:
            with self.subTest(source=source):
                self.assertNotEqual(host_reads(source), [])

    def test_ignores_docstrings_and_other_text(self):
        for source in [
            '"""See https://url.spec.whatwg.org/."""',
            'def f():\n    """Read //host URLs."""',
            'print("a/b")',
            "parts.path",
        ]:
            with self.subTest(source=source):
                self.assertEqual(host_reads(source), [])


def host_reads(source):
    """Return "<function>: <source text>" for each place in source that can read the host of a URL.

    A place counts when it reads a hostname or netloc attribute, or when it is
    a string constant with "//" in it that is not a docstring. The function is
    the top level function that has the place in it, or <module>.
    """
    tree = ast.parse(source)
    function = {
        id(child): node.name
        for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for child in ast.walk(node)
    }
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("hostname", "netloc") \
                or isinstance(node, ast.Constant) and isinstance(node.value, str) and "//" in node.value \
                and id(node) not in docstrings:
            found.append(f"{function.get(id(node), '<module>')}: {ast.unparse(node)}")
    return found


class UrlsTrimmedWithUrlText(unittest.TestCase):
    # str.strip(), str.split() and \s in a pattern remove a no-break space,
    # which a browser keeps in a URL. Trim a URL with check_site.url_text.
    ALLOWED = {
        # Lines of the lists in tests/, not HTML.
        "line.strip()",
        "line.split()",
        "(ROOT / 'tests' / 'legacy-urls.txt').read_text().split()",
        # Keywords, not URLs. A browser does not strip http-equiv, so the
        # check can read a refresh that a browser ignores. That adds a
        # report and does not hide a broken link.
        "attrs.get('rel', '').lower().split()",
        "attrs.get('http-equiv', '').strip()",
        "attrs.get('property', '').strip()",
        "attrs['property'].strip()",
    }

    def test_no_new_code_in_scripts_removes_unicode_white_space(self):
        found = {
            f"{path.name}: {text}"
            for path in (check_site.ROOT / "scripts").rglob("*.py")
            for text in unicode_space_calls(path.read_text())
            if text not in self.ALLOWED
        }
        self.assertEqual(found, set())

    def test_finds_each_spelling(self):
        for source in [
            "value.strip()",
            "value.lstrip()",
            "value.rstrip()",
            "value.split()",
            'import re\nre.compile(r"\\s*url")',
            'import re\nre.match(f"[^\\s{x}]", value)',
            'import re as regex\nregex.sub(r"\\s+", " ", value)',
        ]:
            with self.subTest(source=source):
                self.assertNotEqual(unicode_space_calls(source), [])

    def test_ignores_code_that_keeps_unicode_white_space(self):
        for source in [
            "value.strip(URL_TRIM)",
            'value.split(",")',
            'import re\nre.compile(r"[\\t\\n\\f\\r ]*\\S")',
            'print(r"\\s")',
        ]:
            with self.subTest(source=source):
                self.assertEqual(unicode_space_calls(source), [])


def unicode_space_calls(source):
    """Return the source text of each call in source that removes or matches Unicode white space.

    A call counts when it is strip(), lstrip(), rstrip() or split() without
    arguments, or a function of the re module whose pattern argument has a
    string constant with \\s in it.
    """
    tree = ast.parse(source)
    modules = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names if alias.name == "re"
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if func.attr in ("strip", "lstrip", "rstrip", "split") and not node.args and not node.keywords:
            found.append(ast.unparse(node))
        elif isinstance(func.value, ast.Name) and func.value.id in modules and func.attr in RE_FUNCTIONS:
            patterns = node.args[:1] + [keyword.value for keyword in node.keywords if keyword.arg == "pattern"]
            if any(
                isinstance(child, ast.Constant) and isinstance(child.value, str) and "\\s" in child.value
                for pattern in patterns for child in ast.walk(pattern)
            ):
                found.append(ast.unparse(node))
    return found


class UrlPathsFoundWithServedFile(unittest.TestCase):
    # A Path drops a slash at the end, so out / "post/a.png/".lstrip("/") is
    # the file post/a.png, which a server does not serve for /post/a.png/.
    # Find the file for a URL path with check_site.served_file.
    ALLOWED = {
        # The file names that the script makes for archived images. They
        # do not end in a slash.
        "migration/archived_images.py: static_root / (path := local_path(url, ext)).lstrip('/')",
        "migration/archived_images.py: static_root / path.lstrip('/')",
        "tests/test_archived_images.py: root / archived_images.local_path(URL, '.png').lstrip('/')",
        # Files of the WordPress site to download or keep before the build.
        # The site check reads the links that the build makes to them.
        "migration/download_uploads.py: STATIC / path.lstrip('/')",
        "migration/download_uploads.py: STATIC / p.lstrip('/')",
        "migration/wayback.py: uploads_root / avatar.lstrip('/')",
        # The src of a script in the built site, which the site check reads
        # in missing_targets() in tests/test_layouts.py.
        "tests/test_layouts.py: out / script.lstrip('/')",
    }

    def test_no_new_code_joins_a_url_path_to_a_path(self):
        found = {
            f"{path.relative_to(check_site.ROOT).as_posix()}: {text}"
            for folder in ("scripts", "migration", "tests")
            for path in (check_site.ROOT / folder).rglob("*.py")
            for text in url_path_joins(path.read_text())
        }
        self.assertEqual(found - self.ALLOWED, set())

    def test_finds_each_spelling(self):
        for source in [
            'out / url.lstrip("/")',
            'out / url.strip("/")',
            'out / url.removeprefix("/")',
            '(out / path.lstrip("/")).is_file()',
            'out.joinpath(url.lstrip("/"))',
            'Path(out, url.lstrip("/"))',
        ]:
            with self.subTest(source=source):
                self.assertNotEqual(url_path_joins(source), [])

    def test_ignores_other_joins(self):
        for source in [
            'out / url.strip("/") / "index.html"',
            'os.path.join(out, url.lstrip("/"))',
            'out / name',
            'url.lstrip("/")',
        ]:
            with self.subTest(source=source):
                self.assertEqual(url_path_joins(source), [])


def url_path_joins(source):
    """Return the source text of each place in source that joins a URL path to a Path.

    A place counts when it is a / operator, a joinpath() call or a Path()
    call with a value that has its slashes removed with lstrip("/"),
    strip("/") or removeprefix("/"). A / operator with "index.html" after it
    does not count, since a slash at the end of the URL path then names a
    folder.
    """
    def url_path(node):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("lstrip", "strip", "removeprefix") \
            and [ast.unparse(arg) for arg in node.args] == ["'/'"]

    tree = ast.parse(source)
    index_folders = {
        id(node.left)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant) and node.right.value == "index.html"
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and url_path(node.right) \
                and id(node) not in index_folders:
            found.append(ast.unparse(node))
        elif isinstance(node, ast.Call) and any(map(url_path, node.args)) and (
            isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath"
            or isinstance(node.func, ast.Name) and node.func.id in ("Path", "PurePath", "PurePosixPath")
        ):
            found.append(ast.unparse(node))
    return found


class DeadAudio(unittest.TestCase):
    """The check reports audio from an address that no longer serves it.

    Podbean served podcast files at signed URLs such as
    http://s60.podbean.com/pb/<hash>/<expiry>/.../Episode47-Final.mp3. They
    expired: in November 2026 they returned an HTML page, not audio. The
    files of the show are now at mcdn.podbean.com.
    """

    def test_reports_audio_from_an_expired_podbean_address(self):
        old = "http://s60.podbean.com/pb/9f8ef36bedb0a4741296446ac6dbd415/55e43e39/data4/blogs60/708615/uploads/Episode47-Final.mp3"
        new = "https://mcdn.podbean.com/mf/web/7f2xv5/Episode46-Final.mp3"
        problems = post_problems(self, f'<audio src="{old}" controls></audio><audio src="{new}" controls></audio>')
        dead = [line for line in problems if "from a dead address" in line]
        self.assertEqual(dead, [f"file from a dead address in /post/index.html: {old}"])


if __name__ == "__main__":
    unittest.main()
