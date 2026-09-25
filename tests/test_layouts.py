"""Tests for the rendered site built from layouts/ and content/.

Run: python3 -m unittest discover tests
"""
import re
import unittest

from site_build import ROOT, build


def comment_ids(path):
    html = (build() / path / "index.html").read_text()
    return re.findall(r'<div id="comment-(\d+)">', html)


class PageComments(unittest.TestCase):
    def test_pages_show_their_imported_comments(self):
        self.assertEqual(comment_ids("drafting"), ["318"])
        self.assertEqual(comment_ids("tournament-decklists"), ["132", "133", "308"])

    def test_posts_still_show_their_comments(self):
        self.assertTrue(comment_ids("drafting-with-netrunner"))


class TermDescriptions(unittest.TestCase):
    def test_author_description_is_escaped_once(self):
        html = (build() / "author" / "ian" / "index.html").read_text()
        description = re.search(r'<div id="author-description"><h2>Ian L</h2>(Ian .*? his wife)', html)
        self.assertEqual(description[1], "Ian &amp; his wife")


class HomeGrid(unittest.TestCase):
    def test_thumbnail_links_to_its_own_post(self):
        html = (build() / "index.html").read_text()
        boxes = html.split('<div class="wc-shortcodes-post-box ')[1:]
        thumbnails = []
        titles = []
        for box in boxes:
            thumbnail = re.search(r'wc-shortcodes-entry-thumbnail"><a href="([^"]*)" title="([^"]*)"', box)
            if thumbnail:
                thumbnails.append(thumbnail.groups())
                title = re.search(r'wc-shortcodes-entry-title"><a href="([^"]*)" rel="bookmark">([^<]*)</a>', box)
                titles.append(title.groups())
        self.assertTrue(thumbnails)
        self.assertEqual(thumbnails, titles)


def root_context_uses_in_blocks(text):
    """Yield each action that uses $. inside a range or with block."""
    stack = []
    for action in re.findall(r"{{-?\s*(.*?)\s*-?}}", text, re.S):
        keyword = action.split(maxsplit=1)[0] if action.split() else ""
        if keyword in ("range", "with", "if", "define", "block"):
            stack.append(keyword)
        elif keyword == "end":
            stack.pop()
        elif ("range" in stack or "with" in stack) and "$." in action:
            yield action


class RootContext(unittest.TestCase):
    def test_page_templates_do_not_use_root_context_in_blocks(self):
        # In a page template $ is the page that is rendered, so $. inside
        # range or with names that page and not the current item. Partials
        # are not checked: in a partial $ is the value the caller gives, and
        # term.html gives article-summary.html the post. No shortcode uses $.
        found = []
        for path in sorted((ROOT / "layouts").rglob("*")):
            parts = path.relative_to(ROOT / "layouts").parts
            if path.is_file() and parts[0] not in ("_partials", "_shortcodes"):
                found += [(str(path.relative_to(ROOT)), a) for a in root_context_uses_in_blocks(path.read_text())]
        self.assertEqual(found, [])
