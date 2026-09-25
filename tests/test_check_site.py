"""Tests for the broken link check in scripts/check_site.py, on a small built site."""
import contextlib
import io
import shutil
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
    """,
    # A page that is not index.html is served at its own file name, so its
    # relative links resolve against the directory it is in.
    "404.html": '<a href="post/">post</a><img src="post/small.png">',
}
FILES = ["post/hedge-fund.png", "post/small.png", "post/clip.mp4"]


def broken_links(public):
    """Run the check on the site in public/ and return the broken link lines."""
    out = io.StringIO()
    with mock.patch.object(check_site, "PUBLIC", public), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(io.StringIO()):
        check_site.main()
    return {line for line in out.getvalue().splitlines() if line.startswith("broken link in ")}


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
        cls.broken = broken_links(cls.public)

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

    def test_skips_urls_that_are_not_paths_on_this_site(self):
        self.assertEqual({line for line in self.broken if not line.startswith("broken link in /post/")}, set())


if __name__ == "__main__":
    unittest.main()
