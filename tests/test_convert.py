"""Tests for the WordPress content rewriting in migration/convert.py.

Run: python3 -m unittest discover tests
"""
import io
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
# Any shortcode with an attribute, such as [name key=value], from a plugin not listed above.
# Bracketed prose and card names in the posts do not have this shape.
ATTRIBUTE_SHORTCODE = re.compile(r"\[[A-Za-z][\w-]* [\w-]+=[^\]]*\]")


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

    def test_a_comma_in_a_link_does_not_split_it(self):
        body = '<a href="https://example.com/a,https://stimhack.com/x">x</a><img src="https://example.com/i?u=,https://stimhack.com/y.png">'
        self.assertEqual(convert.rewrite_urls(body), body)

    def test_a_comma_in_a_decklist_link_does_not_split_it(self):
        self.assertEqual(convert.site_relative("https://example.com/a,https://stimhack.com/x"), "https://example.com/a,https://stimhack.com/x")

    def test_a_comma_inside_a_srcset_url_does_not_split_it(self):
        # A srcset URL ends at whitespace; only a comma after it ends the candidate.
        body = '<img srcset="https://example.com/i?u=,https://stimhack.com/y.png 1x, https://stimhack.com/z.png 2x">'
        self.assertEqual(
            convert.rewrite_urls(body),
            '<img srcset="https://example.com/i?u=,https://stimhack.com/y.png 1x, /z.png 2x">',
        )

    def test_every_srcset_candidate_uses_its_archived_copy(self):
        old = "http://www.cardgamedb.com/forums/uploads/an/a.png"
        with mock.patch.dict(convert.ARCHIVED, {old: "/images/archive/a.png"}):
            self.assertEqual(
                convert.rewrite_urls(f'<img srcset="{old} 1x, {old} 2x">'),
                '<img srcset="/images/archive/a.png 1x, /images/archive/a.png 2x">',
            )

    def test_every_srcset_candidate_uses_the_new_netrunnerdb_image(self):
        body = '<img srcset="https://netrunnerdb.com/card_image/01001.png 1x, https://netrunnerdb.com/card_image/01002.png 2x">'
        self.assertEqual(
            convert.rewrite_urls(body),
            '<img srcset="https://card-images.netrunnerdb.com/v2/large/01001.jpg 1x, '
            'https://card-images.netrunnerdb.com/v2/large/01002.jpg 2x">',
        )

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
            for pattern in (RAW_SHORTCODE, ATTRIBUTE_SHORTCODE)
            for m in pattern.finditer(path.read_text())
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


def decklists_page(rows):
    """A tournament-decklists page whose plugin table holds rows of (pack, location, winner)."""
    trs = "".join(
        f'<tr><td class="column-1 data-pack">{pack}</td><td class="column-2 location">{location}</td>'
        f'<td class="column-3 type">GNK</td><td class="column-4 players">8</td>'
        f'<td class="column-5 winner">{winner}</td><td class="column-6 runner">Kate</td>'
        f'<td class="column-7 corp">Weyland</td></tr>'
        for pack, location, winner in rows
    )
    body = (
        '<p>Intro.</p><div id="decks"><table id="decklists"><tbody class="list">'
        f"{trs}</tbody></table></div><script>var userList = new List('decks', options);</script>"
    )
    return {
        "id": 20, "slug": "tournament-decklists", "link": "https://stimhack.com/tournament-decklists/",
        "title": {"rendered": "Tournament Decklists"}, "content": {"rendered": body},
        "date": "2013-04-06T00:36:49", "date_gmt": "2013-04-06T07:36:49",
        "modified": "2014-01-26T23:05:43", "modified_gmt": "2014-01-27T06:05:43",
    }


def post(post_id, slug):
    return {
        "id": post_id, "slug": slug, "link": f"https://stimhack.com/{slug}/",
        "title": {"rendered": slug}, "content": {"rendered": f"<p>{slug} from WordPress.</p>"},
        "excerpt": {"rendered": ""}, "format": "standard", "featured_media": 0,
        "author": 7, "categories": [3], "tags": [],
        "date": "2016-05-01T10:00:00", "date_gmt": "2016-05-01T17:00:00",
        "modified": "2016-05-01T10:00:00", "modified_gmt": "2016-05-01T17:00:00",
    }


class Rerun(unittest.TestCase):
    """Run main() again after contributors edited the output, as the final re-export will."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".export").mkdir()
        (self.root / "tests").mkdir()
        self.export = {
            "posts": [post(100, "first-post")],
            "pages": [decklists_page([("Core", "Store A", "Alice")])],
            "media": [], "tags": [], "comments": [],
            "categories": [{"id": 3, "slug": "articles", "name": "Articles", "link": "https://stimhack.com/category/articles/", "count": 1}],
            "users": [{"id": 7, "slug": "ian", "name": "Ian", "link": "https://stimhack.com/author/ian/", "avatar_urls": {}}],
        }
        self.run_convert()

    def run_convert(self, **kwargs):
        for name, items in self.export.items():
            (self.root / ".export" / f"{name}.json").write_text(json.dumps(items))
        with mock.patch.multiple(convert, ROOT=self.root, EXPORT=self.root / ".export", CONTENT=self.root / "content"), \
                mock.patch.object(convert.wayback, "POSTS", {}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            convert.main(**kwargs)
        return out.getvalue()

    def edit(self, relative, addition="Edited by a contributor.\n"):
        path = self.root / relative
        path.write_text(path.read_text() + addition)
        return path.read_text()

    def test_default_run_keeps_an_edited_post(self):
        edited = self.edit("content/posts/2016/first-post.html")
        self.run_convert()
        self.assertEqual((self.root / "content/posts/2016/first-post.html").read_text(), edited)

    def test_default_run_keeps_an_edited_page(self):
        edited = self.edit("content/pages/tournament-decklists.html")
        self.run_convert()
        self.assertEqual((self.root / "content/pages/tournament-decklists.html").read_text(), edited)

    def test_default_run_keeps_an_edited_author_page(self):
        edited = self.edit("content/authors/ian/_index.md")
        self.run_convert()
        self.assertEqual((self.root / "content/authors/ian/_index.md").read_text(), edited)

    def test_default_run_keeps_edited_decklists(self):
        edited = self.edit("data/decklists.yaml", "- pack: Added by a contributor\n")
        self.export["pages"] = [decklists_page([("Core", "Store B", "Bob"), ("Core", "Store A", "Alice")])]
        self.run_convert()
        self.assertEqual((self.root / "data/decklists.yaml").read_text(), edited)

    def test_default_run_prints_decklist_rows_that_the_file_does_not_have(self):
        self.export["pages"] = [decklists_page([("Core", "Store B", "Bob"), ("Core", "Store A", "Alice")])]
        out = self.run_convert()
        self.assertIn("location: Store B", out)
        self.assertNotIn("location: Store A", out)

    def test_default_run_does_not_list_an_unchanged_file_with_a_carriage_return(self):
        self.export["posts"] = [dict(post(100, "first-post"), content={"rendered": "<p>a\rb</p>"})]
        self.run_convert(overwrite=True)
        self.assertEqual(self.run_convert(), "")

    def test_default_run_creates_a_new_post(self):
        self.export["posts"].append(post(101, "second-post"))
        self.run_convert()
        self.assertIn("second-post from WordPress.", (self.root / "content/posts/2016/second-post.html").read_text())

    def test_default_run_adds_new_urls_and_keeps_the_others(self):
        urls = self.root / "tests/legacy-urls.txt"
        urls.write_text(urls.read_text() + "/added-by-hand/\n")
        self.export["posts"].append(post(101, "second-post"))
        self.run_convert()
        self.assertLessEqual({"/added-by-hand/", "/first-post/", "/second-post/"}, set(urls.read_text().split()))

    def test_overwrite_run_replaces_edited_files(self):
        paths = ["content/posts/2016/first-post.html", "content/authors/ian/_index.md", "data/decklists.yaml"]
        before = {p: (self.root / p).read_text() for p in paths}
        for p in paths:
            self.edit(p, "- pack: Added by a contributor\n")
        urls = self.root / "tests/legacy-urls.txt"
        urls_before = urls.read_text()
        urls.write_text(urls_before + "/added-by-hand/\n")
        self.run_convert(overwrite=True)
        self.assertEqual({p: (self.root / p).read_text() for p in paths}, before)
        self.assertEqual(urls.read_text(), urls_before)


class TermDescriptions(unittest.TestCase):
    """WordPress stores descriptions with HTML entities; the term template escapes on output."""

    def test_description_entities_are_decoded(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(convert, "CONTENT", Path(tmp)):
            convert.convert_terms("authors", [{"id": 7, "slug": "ian", "name": "Ian L", "description": "Ian &amp; his wife"}], False)
            written = (Path(tmp) / "authors" / "ian" / "_index.md").read_text()
        self.assertEqual(yaml.safe_load(written.split("---\n")[1])["description"], "Ian & his wife")


if __name__ == "__main__":
    unittest.main()
