"""Tests for pointing dead cardgamedb page links at archived copies (migration/archived_links.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import archived_links  # noqa: E402

PAGE = "http://www.cardgamedb.com/index.php/netrunner/android-netrunner-card-spoilers/_/core/hedge-fund-core"


class CardgamedbLinksIn(unittest.TestCase):
    def test_finds_page_links_but_not_images(self):
        text = (
            f'<a href="{PAGE}">Hedge Fund</a>'
            '<a href="http://www.cardgamedb.com/forums/uploads/an/ffg_hedge-fund-core.png">img</a>'
            '<img src="http://www.cardgamedb.com/index.php/x.png">'
            '<a href="https://netrunnerdb.com/en/card/01110">NRDB</a>'
        )
        self.assertEqual(archived_links.cardgamedb_links_in(text), {PAGE})


class Rewrite(unittest.TestCase):
    def test_uses_the_map_and_leaves_unknown_links(self):
        archived = {PAGE: f"https://web.archive.org/web/20140101000000/{PAGE}"}
        self.assertEqual(archived_links.rewrite(PAGE, archived), archived[PAGE])
        self.assertEqual(archived_links.rewrite("https://netrunnerdb.com/", archived), "https://netrunnerdb.com/")


if __name__ == "__main__":
    unittest.main()
