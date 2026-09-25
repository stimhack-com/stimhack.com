"""Tests for the rendered site built from layouts/ and content/.

Run: python3 -m unittest discover tests
"""
import re
import unittest

from site_build import build


def comment_ids(path):
    html = (build() / path / "index.html").read_text()
    return re.findall(r'<div id="comment-(\d+)">', html)


class PageComments(unittest.TestCase):
    def test_pages_show_their_imported_comments(self):
        self.assertEqual(comment_ids("drafting"), ["318"])
        self.assertEqual(comment_ids("tournament-decklists"), ["132", "133", "308"])

    def test_posts_still_show_their_comments(self):
        self.assertTrue(comment_ids("drafting-with-netrunner"))
