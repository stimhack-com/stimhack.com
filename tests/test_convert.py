"""Tests for the WordPress content rewriting in migration/convert.py.

Run: python3 -m unittest discover tests
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import convert  # noqa: E402

# Shortcodes in the WordPress export whose plugins the static site does not run:
# wc-shortcodes, a contact form plugin, Font Awesome icons and Easy Media Gallery.
RAW_SHORTCODE = re.compile(r"\[/?(?:accordion|pane|one_fourth|Form|icon|easy-media)\b[^\]]*\]")


class RewriteUrls(unittest.TestCase):
    def test_site_links_become_root_relative(self):
        body = '<a href="http://stimhack.com/about/">x</a><img src="https://www.stimhack.com/wp-content/uploads/a.png">'
        self.assertEqual(
            convert.rewrite_urls(body),
            '<a href="/about/">x</a><img src="/wp-content/uploads/a.png">',
        )

    def test_bare_domain_becomes_home(self):
        self.assertEqual(convert.rewrite_urls('<a href="https://stimhack.com">h</a>'), '<a href="/">h</a>')

    def test_subdomains_are_left_alone(self):
        body = '<a href="http://forum.stimhack.com/t/1">f</a><a href="https://meteor.stimhack.com/">m</a>'
        self.assertEqual(convert.rewrite_urls(body), body)

    def test_lookalike_domains_are_left_alone(self):
        body = '<a href="https://stimhack.com.example.org/x">x</a>'
        self.assertEqual(convert.rewrite_urls(body), body)

    def test_every_srcset_candidate_is_rewritten(self):
        body = '<img srcset="https://stimhack.com/a-300.png 300w, https://stimhack.com/a.png 900w">'
        self.assertEqual(convert.rewrite_urls(body), '<img srcset="/a-300.png 300w, /a.png 900w">')

    def test_text_mentions_are_not_rewritten(self):
        body = "<p>Visit https://stimhack.com/about/ today</p>"
        self.assertEqual(convert.rewrite_urls(body), body)

    def test_links_to_moved_posts_point_to_the_new_url(self):
        self.assertEqual(
            convert.rewrite_urls('<a href="http://stimhack.com/the-two-year-turn-how-i-learned-netrunner-by-noah-mckee/">x</a>'),
            '<a href="/the-two-year-turn/">x</a>',
        )

    def test_http_iframes_are_upgraded(self):
        self.assertEqual(
            convert.rewrite_urls('<iframe width="9" src="http://www.youtube.com/embed/x"></iframe>'),
            '<iframe width="9" src="https://www.youtube.com/embed/x"></iframe>',
        )


class Shortcodes(unittest.TestCase):
    def test_consecutive_columns_share_one_row(self):
        out = convert.convert_shortcodes("[one_fourth]a[/one_fourth]\n[one_fourth]b[/one_fourth]\n<p>after</p>")
        self.assertEqual(
            out,
            '<div class="sh-cols"><div class="sh-col">a</div>\n<div class="sh-col">b</div>\n</div>\n<p>after</p>',
        )

    def test_panes_become_details_with_curly_quoted_titles(self):
        out = convert.convert_shortcodes("[accordion][pane title=&#8221;Pick&#8217;s Analysis&#8221;]body[/pane][/accordion]")
        self.assertEqual(out, "<details><summary>Pick&#8217;s Analysis</summary>body</details>")

    def test_pane_title_may_close_with_a_left_curly_quote(self):
        out = convert.convert_shortcodes("[pane title=&#8221;X&#8220;]b[/pane]")
        self.assertEqual(out, "<details><summary>X</summary>b</details>")

    def test_unclosed_pane_is_removed(self):
        # Post 1773 opens a pane with no [/pane]; its title repeats the paragraph above it.
        out = convert.convert_shortcodes(
            "<p><strong>Austin</strong></p>\n[pane title=&#8221;<strong>Austin</strong>&#8220;]\n<p>Stimhack x 3</p>"
        )
        self.assertEqual(out, "<p><strong>Austin</strong></p>\n\n<p>Stimhack x 3</p>")

    def test_forms_become_a_closed_note(self):
        # The contact form plugin is gone and a static site cannot take submissions.
        out = convert.convert_shortcodes("<p>Fill out the following:</p>\n[Form id=&#8221;10&#8243;]")
        self.assertEqual(out, "<p>Fill out the following:</p>\n<p><em>This form is closed.</em></p>")

    def test_font_awesome_3_icons_become_font_awesome_4_icons(self):
        out = convert.convert_shortcodes('<td>[icon name=icon-facetime-video] <a href="/x/">X</a></td>')
        self.assertEqual(out, '<td><i class="fa fa-video-camera" aria-hidden="true"></i> <a href="/x/">X</a></td>')

    def test_easy_media_gallery_is_removed(self):
        # The gallery post it names is not in the export.
        out = convert.convert_shortcodes("[easy-media med=&#8221;5326&#8243;]\n<p>Spaces Between</p>")
        self.assertEqual(out, "\n<p>Spaces Between</p>")

    def test_generated_content_has_no_raw_shortcodes(self):
        root = Path(__file__).resolve().parent.parent
        found = [
            f"{path.relative_to(root)}: {m[0]}"
            for path in sorted([*(root / "content").rglob("*"), *(root / "data").rglob("*")])
            if path.is_file()
            for m in RAW_SHORTCODE.finditer(path.read_text())
        ]
        self.maxDiff = None
        self.assertEqual(found, [])


class Dates(unittest.TestCase):
    def test_offset_from_local_and_utc(self):
        self.assertEqual(convert.iso_date("2023-10-06T19:15:11", "2023-10-07T02:15:11"), "2023-10-06T19:15:11-07:00")

    def test_offset_in_winter(self):
        self.assertEqual(convert.iso_date("2014-01-02T10:00:00", "2014-01-02T18:00:00"), "2014-01-02T10:00:00-08:00")


class Excerpt(unittest.TestCase):
    def test_read_more_link_and_tags_are_removed(self):
        item = {"excerpt": {"rendered": '<p>Set review of &#8220;X&#8221;.</p>\n<p> <a class="continue-reading-link" href="/x/">Read More<i></i></a></p>\n'}}
        self.assertEqual(convert.excerpt(item), "Set review of “X”.")

    def test_shortcodes_are_removed(self):
        item = {"excerpt": {"rendered": "<p>Austin [pane title=&#8221;Austin&#8220;] 1st Place</p>"}}
        self.assertEqual(convert.excerpt(item), "Austin 1st Place")

    def test_forms_become_a_closed_note(self):
        item = {"excerpt": {"rendered": "<p>[Form id=&#8221;12&#8243;]</p>\n"}}
        self.assertEqual(convert.excerpt(item), "This form is closed.")


class PageComments(unittest.TestCase):
    """Run main() on a one page export and read the page it writes."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        export = root / ".export"
        export.mkdir()
        (root / "tests").mkdir()
        page = {
            "id": 19, "slug": "drafting", "link": "https://stimhack.com/drafting/",
            "title": {"rendered": "Drafting"}, "content": {"rendered": "<p>Body.</p>"},
            "date": "2013-04-06T00:36:49", "date_gmt": "2013-04-06T07:36:49",
            "modified": "2014-01-26T23:05:43", "modified_gmt": "2014-01-27T06:05:43",
        }
        comment = {
            "id": 318, "post": 19, "parent": 0, "author_name": "Reader",
            "author_avatar_urls": {"48": "https://example.org/a.png"},
            "date": "2014-02-01T10:00:00", "date_gmt": "2014-02-01T18:00:00",
            "content": {"rendered": "<p>Nice.</p>\n"},
        }
        export_files = {"posts": [], "pages": [page], "media": [], "categories": [], "tags": [], "users": [], "comments": [comment]}
        for name, items in export_files.items():
            (export / f"{name}.json").write_text(json.dumps(items))
        with mock.patch.multiple(convert, ROOT=root, EXPORT=export, CONTENT=root / "content"), \
                mock.patch.object(convert.wayback, "POSTS", {}):
            convert.main()
        written = (root / "content" / "pages" / "drafting.html").read_text()
        self.front = yaml.safe_load(written.split("---\n")[1])

    def test_page_comments_are_in_front_matter(self):
        self.assertEqual(self.front.get("comments"), [{
            "id": 318, "parent": 0, "author": "Reader", "avatar": "https://example.org/a.png",
            "date": "2014-02-01T10:00:00-08:00", "content": "<p>Nice.</p>",
        }])


class TermDescriptions(unittest.TestCase):
    """WordPress stores descriptions with HTML entities; the term template escapes on output."""

    def test_description_entities_are_decoded(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(convert, "CONTENT", Path(tmp)):
            convert.convert_terms("authors", [{"id": 7, "slug": "ian", "name": "Ian L", "description": "Ian &amp; his wife"}])
            written = (Path(tmp) / "authors" / "ian" / "_index.md").read_text()
        self.assertEqual(yaml.safe_load(written.split("---\n")[1])["description"], "Ian & his wife")


if __name__ == "__main__":
    unittest.main()
