"""Tests for the checks in scripts/check_site.py, on a small built site."""
import contextlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_site  # noqa: E402

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
        reported = {line for line in self.problems if line.startswith("image from a dead address in ")}
        self.assertEqual(
            reported,
            {
                "image from a dead address in /dead-images/index.html: " + url
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
            if re.search(r"<img\\[bs]", path.read_text())
        }
        self.assertEqual(found - self.ALLOWED, set())


if __name__ == "__main__":
    unittest.main()


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
