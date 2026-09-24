"""Tests for archived copies of dead images (migration/archived_images.py)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import archived_images  # noqa: E402

URL = "http://www.cardgamedb.com/forums/uploads/an/ffg_noise-core.png"


class LocalPath(unittest.TestCase):
    def test_keeps_host_and_path(self):
        self.assertEqual(
            archived_images.local_path(URL, ".png"),
            "/images/archive/cardgamedb.com/forums/uploads/an/ffg_noise-core.png",
        )

    def test_query_strings_get_a_stable_hash_and_the_detected_extension(self):
        a = archived_images.local_path("https://encrypted-tbn3.gstatic.com/images?q=tbn:ABC&amp;s=1", ".jpg")
        b = archived_images.local_path("https://encrypted-tbn3.gstatic.com/images?q=tbn:XYZ", ".jpg")
        self.assertRegex(a, r"^/images/archive/encrypted-tbn3\.gstatic\.com/images-[0-9a-f]{10}\.jpg$")
        self.assertNotEqual(a, b)

    def test_entity_encoded_and_plain_urls_share_a_path(self):
        self.assertEqual(
            archived_images.local_path("http://a.example/x.png?a=1&amp;b=2", ".png"),
            archived_images.local_path("http://a.example/x.png?a=1&b=2", ".png"),
        )

    def test_unsafe_characters_are_replaced(self):
        self.assertEqual(
            archived_images.local_path("http://a.example/some%20dir/card%3F.png", ".png"),
            "/images/archive/a.example/some_dir/card_.png",
        )


class Rewrite(unittest.TestCase):
    def test_uses_the_map(self):
        archived = {URL: "/images/archive/cardgamedb.com/forums/uploads/an/ffg_noise-core.png"}
        self.assertEqual(archived_images.rewrite(URL, archived), archived[URL])
        self.assertEqual(archived_images.rewrite("http://i.imgur.com/a.png", archived), "http://i.imgur.com/a.png")


class MapExisting(unittest.TestCase):
    def test_records_copies_on_disk_and_skips_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy = root / archived_images.local_path(URL, ".png").lstrip("/")
            copy.parent.mkdir(parents=True)
            copy.write_bytes(b"\x89PNG")
            map_path = root / "map.json"
            archived = archived_images.map_existing({URL, "http://gone.example/x.png"}, root, map_path)
            self.assertEqual(archived, {URL: archived_images.local_path(URL, ".png")})
            self.assertEqual(json.loads(map_path.read_text()), archived)


class CardgamedbUrlsIn(unittest.TestCase):
    def test_finds_cardgamedb_images_in_src_and_href(self):
        linked = "http://www.cardgamedb.com/forums/uploads/an/linked.png"
        text = (
            f'<img src="{URL}"><a href="{linked}">x</a>'
            '<img src="http://i.imgur.com/a.png"><a href="http://www.cardgamedb.com/index.php/netrunner">x</a>'
        )
        self.assertEqual(archived_images.cardgamedb_urls_in(text), {URL, linked})


if __name__ == "__main__":
    unittest.main()
