"""Tests for mapping old NetrunnerDB card image URLs (migration/nrdb_images.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import nrdb_images  # noqa: E402

NEW = "https://card-images.netrunnerdb.com/v2/large/08079.jpg"


class Rewrite(unittest.TestCase):
    def test_every_old_path_shape_maps_to_the_new_server(self):
        for old in (
            "https://netrunnerdb.com/card_image/08079.png",
            "https://netrunnerdb.com/card_image//large/08079.jpg",
            "http://netrunnerdb.com/web/bundles/netrunnerdbcards/images/cards/en/08079.png",
            "http://netrunnerdb.com/web/bundles/netrunnerdbcards/images/cards/en-large/08079.png",
            "http://netrunnerdb.com/bundles/netrunnerdbcards/images/cards/en/08079.png",
            "https://www.netrunnerdb.com/bundles/netrunnerdbcards/images/cards/en/08079.png",
        ):
            self.assertEqual(nrdb_images.rewrite(old), NEW, old)

    def test_card_pages_and_other_urls_are_unchanged(self):
        for url in (
            "https://netrunnerdb.com/en/card/08079",
            "http://netrunnerdb.com/bundles/netrunnerdbbuilder/images/types/ice.png",
            "https://netrunnerdb.com/card_image/0807.png",
        ):
            self.assertEqual(nrdb_images.rewrite(url), url)


class TypeIcons(unittest.TestCase):
    def test_icon_is_removed_and_heading_text_kept(self):
        html = '<h5><img decoding="async" class="type-icon" src="http://netrunnerdb.com/bundles/netrunnerdbbuilder/images/types/ice.png" alt="Barrier" /> Barrier (4)</h5>'
        self.assertEqual(nrdb_images.remove_type_icons(html), "<h5>Barrier (4)</h5>")

    def test_other_images_are_kept(self):
        html = '<img src="https://card-images.netrunnerdb.com/v2/large/01001.jpg">'
        self.assertEqual(nrdb_images.remove_type_icons(html), html)


if __name__ == "__main__":
    unittest.main()
