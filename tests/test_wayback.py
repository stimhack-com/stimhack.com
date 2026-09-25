"""Tests for reading archived post pages in migration/wayback.py."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import wayback  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "wayback-post.html"


class Parse(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as uploads:
            self.post = wayback.parse(FIXTURE, Path(uploads))

    def test_metadata_from_the_meta_line(self):
        self.assertEqual(self.post["title"], "Drafting with Netrunner")
        self.assertEqual(self.post["author"], "SneakySly")
        self.assertEqual(self.post["date"], "2013-04-16T00:00:00-07:00")
        self.assertEqual(self.post["categories"], ["Cube Drafting"])
        self.assertEqual(self.post["wp_id"], 52)

    def test_tags_come_from_the_tag_footer_and_exclude_the_category_link(self):
        # The archived pages link their tags only in the footer that parse() removes from the content.
        self.assertEqual(self.post["tags"], ["Draft", "Drafting"])

    def test_old_theme_tag_footer_is_removed_from_content(self):
        self.assertEqual(self.post["content"], "<p>Body text.</p>")

    def test_replies_keep_their_parent_and_pingbacks_are_skipped(self):
        self.assertEqual([(c["id"], c["parent"]) for c in self.post["comments"]], [(8, 0), (9, 8)])

    def test_comment_fields(self):
        first = self.post["comments"][0]
        self.assertEqual(first["author"], "QBert")
        self.assertEqual(first["date"], "2013-04-17T18:56:00-07:00")
        self.assertEqual(first["content"], "<p>Does it work 2p?</p>")
        self.assertEqual(first["avatar"], "https://0.gravatar.com/avatar/abc?s=60")

    def test_deleted_local_avatars_are_dropped(self):
        self.assertEqual(self.post["comments"][1]["avatar"], "")


if __name__ == "__main__":
    unittest.main()
