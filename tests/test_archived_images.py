"""Tests for pointing cardgamedb image URLs at archived copies (migration/archived_images.py)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import archived_images  # noqa: E402

URL = "http://www.cardgamedb.com/forums/uploads/an/ffg_noise-core.png"
LOCAL = "/images/archive/cardgamedb/forums/uploads/an/ffg_noise-core.png"


class LocalPath(unittest.TestCase):
    def test_scheme_and_www_do_not_matter(self):
        for url in (URL, "https://cardgamedb.com/forums/uploads/an/ffg_noise-core.png"):
            self.assertEqual(archived_images.local_path(url), LOCAL)

    def test_card_pages_are_not_images(self):
        self.assertIsNone(archived_images.local_path("http://www.cardgamedb.com/index.php/netrunner/android-netrunner-deck-builder"))

    def test_other_hosts_are_ignored(self):
        self.assertIsNone(archived_images.local_path("http://cardgamedb.com.example.org/forums/uploads/an/x.png"))


class Rewrite(unittest.TestCase):
    def test_rewrites_only_when_the_copy_is_on_disk(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            self.assertEqual(archived_images.rewrite(URL, root), URL)
            (root / LOCAL.lstrip("/")).parent.mkdir(parents=True)
            (root / LOCAL.lstrip("/")).write_bytes(b"\x89PNG")
            self.assertEqual(archived_images.rewrite(URL, root), LOCAL)


class UrlsIn(unittest.TestCase):
    def test_finds_archived_images_in_src_and_href(self):
        linked = "http://www.cardgamedb.com/forums/uploads/an/linked.png"
        html = (
            f'<img src="{URL}"><a href="{linked}">x</a>'
            '<img src="http://i.imgur.com/a.png"><a href="http://www.cardgamedb.com/index.php/netrunner">x</a>'
        )
        self.assertEqual(archived_images.urls_in(html), {URL, linked})


if __name__ == "__main__":
    unittest.main()
