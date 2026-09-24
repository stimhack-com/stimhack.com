"""Tests for the WordPress content rewriting in migration/convert.py.

Run: python3 -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "migration"))
import convert  # noqa: E402


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


class Dates(unittest.TestCase):
    def test_offset_from_local_and_utc(self):
        self.assertEqual(convert.iso_date("2023-10-06T19:15:11", "2023-10-07T02:15:11"), "2023-10-06T19:15:11-07:00")

    def test_offset_in_winter(self):
        self.assertEqual(convert.iso_date("2014-01-02T10:00:00", "2014-01-02T18:00:00"), "2014-01-02T10:00:00-08:00")


class Excerpt(unittest.TestCase):
    def test_read_more_link_and_tags_are_removed(self):
        item = {"excerpt": {"rendered": '<p>Set review of &#8220;X&#8221;.</p>\n<p> <a class="continue-reading-link" href="/x/">Read More<i></i></a></p>\n'}}
        self.assertEqual(convert.excerpt(item), "Set review of “X”.")


if __name__ == "__main__":
    unittest.main()
