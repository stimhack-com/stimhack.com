"""Tests for the rendered site built from layouts/ and content/.

Run: python3 -m unittest discover tests
"""
import html
import re
import unittest
from urllib.parse import urlsplit
from xml.etree import ElementTree

import yaml

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


def archive_summaries(out):
    """Return (post URL, summary text) for each post entry on the category archive pages in out."""
    found = []
    for page in sorted(out.glob("category/**/index.html")):
        for article in page.read_text().split("<article ")[1:]:
            summary = re.search(r'<div class="entry-summary">.*?<p>([^<]*)</p>', article, re.S)
            if summary:
                url = re.search(r'<h2 class="entry-title"><a href="([^"]*)"', article)[1]
                found.append((url, html.unescape(summary[1])))
    return found


def feed_descriptions(out):
    """Return (post URL, description text) for each item in the RSS feed in out."""
    items = re.findall(r"<item>.*?<link>https://stimhack\.com(/[^<]*)</link>.*?<description>([^<]*)</description>", (out / "index.xml").read_text(), re.S)
    return [(url, html.unescape(text)) for url, text in items]


def meta_description(out, url):
    """Return the text of the meta description on the page at url."""
    page = (out / url.strip("/") / "index.html").read_text()
    return html.unescape(re.search(r'<meta name="description" content="([^"]*)">', page)[1])


def front_matter_summaries(content):
    """Return {post URL: front matter summary} for each post in content that has one."""
    summaries = {}
    for path in sorted((content / "posts").rglob("*.*")):
        front = yaml.safe_load(path.read_text().split("---\n")[1])
        if front.get("summary"):
            summaries[front.get("url") or f"/{front['slug']}/"] = front["summary"]
    return summaries


def is_start_of(text, summary):
    """Tell if text is summary, or the start of summary with " …" added as Hugo's truncate does."""
    return text == summary or (text.endswith(" …") and summary.startswith(text.removesuffix(" …")))


FIXTURE = ROOT / "tests" / "fixtures" / "summaries"
LOOKALIKES = 'Lock of the Year <tm> picks, *sounds of a ruckus*, "quoted" & R&amp;D'


class FrontMatterSummaries(unittest.TestCase):
    """Migrated posts keep the WordPress excerpt as plain text in front matter summary."""

    maxDiff = None

    def test_archive_entry_shows_summary_as_written(self):
        entries = dict(archive_summaries(build(FIXTURE)))
        self.assertEqual(entries["/markup-lookalikes/"], LOOKALIKES)

    def test_feed_description_shows_summary_as_written(self):
        items = dict(feed_descriptions(build(FIXTURE)))
        self.assertEqual(items["/markup-lookalikes/"], LOOKALIKES)

    def test_meta_description_shows_summary_as_written(self):
        self.assertEqual(meta_description(build(FIXTURE), "/markup-lookalikes/"), LOOKALIKES)

    def test_summary_divider_in_content_does_not_replace_summary(self):
        out = build(FIXTURE)
        self.assertEqual(dict(archive_summaries(out))["/summary-divider/"], "The excerpt from front matter.")
        self.assertEqual(dict(feed_descriptions(out))["/summary-divider/"], "The excerpt from front matter.")

    def test_post_without_summary_uses_summary_from_content(self):
        # Hugo makes the summary from the rendered content, so the typographer
        # has made the quotes curly.
        out = build(FIXTURE)
        expected = "First paragraph of a \u201cnew\u201d post & more. Second paragraph."
        self.assertEqual(" ".join(dict(archive_summaries(out))["/new-post/"].split()), expected)
        self.assertEqual(" ".join(dict(feed_descriptions(out))["/new-post/"].split()), expected)

    def test_every_archive_entry_shows_summary_as_written(self):
        summaries = front_matter_summaries(ROOT / "content")
        wrong = [
            (url, text, summaries[url])
            for url, text in archive_summaries(build())
            if url in summaries and text != summaries[url]
        ]
        self.assertEqual(wrong, [])

    def test_every_feed_description_shows_summary_as_written(self):
        summaries = front_matter_summaries(ROOT / "content")
        wrong = [
            (url, text, summaries[url])
            for url, text in feed_descriptions(build())
            if url in summaries and text != summaries[url]
        ]
        self.assertEqual(wrong, [])

    def test_every_meta_description_shows_summary_as_written(self):
        out = build()
        wrong = []
        for url, summary in front_matter_summaries(ROOT / "content").items():
            text = meta_description(out, url)
            if not is_start_of(text, summary):
                wrong.append((url, text, summary))
        self.assertEqual(wrong, [])

    def test_templates_get_summaries_from_the_summary_partial(self):
        # .Summary renders the front matter summary as Markdown. Only
        # summary-text.html reads it, and only it and the meta description
        # guard in baseof.html read the front matter summary.
        allowed = {("layouts/baseof.html", "if .Params.summary")}
        found = []
        for path in sorted((ROOT / "layouts").rglob("*")):
            name = str(path.relative_to(ROOT))
            if path.is_file() and name != "layouts/_partials/summary-text.html":
                for action in re.findall(r"{{-?\s*(.*?)\s*-?}}", path.read_text(), re.S):
                    if re.search(r"\.(Summary|Params\.summary)\b", action) and (name, action) not in allowed:
                        found.append((name, action))
        self.assertEqual(found, [])


def head(out, url):
    """Return (title, canonical URL) from the head of the page at url."""
    page = (out / url.strip("/") / "index.html").read_text()
    title = re.search(r"<title>([^<]*)</title>", page)[1]
    canonical = re.search(r'<link rel="canonical" href="([^"]*)">', page)
    return html.unescape(title), canonical and canonical[1]


class PaginatedArchives(unittest.TestCase):
    """Page N of an archive has its own title and its own canonical URL."""

    maxDiff = None

    def test_later_page_has_own_title_and_canonical(self):
        self.assertEqual(
            head(build(), "/category/articles/page/2/"),
            ("Articles - StimHack | Page 2", "https://stimhack.com/category/articles/page/2/"),
        )

    def test_every_later_archive_page_has_own_title_and_canonical(self):
        out = build()
        wrong = []
        pages = 0
        for path in sorted(out.glob("*/*/page/*/index.html")):
            number = int(path.parent.name)
            if number == 1:
                continue  # Hugo writes page/1/ as a redirect to the first page.
            pages += 1
            url = "/" + str(path.parent.relative_to(out)) + "/"
            title, canonical = head(out, url)
            if not title.endswith(f" - StimHack | Page {number}") or canonical != "https://stimhack.com" + url:
                wrong.append((url, title, canonical))
        self.assertGreater(pages, 0)
        self.assertEqual(wrong, [])

    def test_first_page_keeps_title_and_canonical(self):
        self.assertEqual(
            head(build(), "/category/articles/"),
            ("Articles - StimHack", "https://stimhack.com/category/articles/"),
        )

    def test_post_keeps_title_and_canonical(self):
        self.assertEqual(
            head(build(), "/drafting-with-netrunner/"),
            ("Drafting with Netrunner - StimHack", "https://stimhack.com/drafting-with-netrunner/"),
        )


def pager_items(out, url):
    """Return the pager of the archive page at url as (text, href, class) items, or None when it has no pager."""
    page = (out / url.strip("/") / "index.html").read_text()
    nav = re.search(r'<nav class="pagination">(.*?)</nav>', page, re.S)
    if not nav:
        return None
    items = []
    for tag, attrs, text in re.findall(r"<(a|span)\b([^>]*)>([^<]*)</\1>", nav[1]):
        href = re.search(r"""href=["']([^"']*)["']""", attrs)
        cls = re.search(r"""class=["']([^"']*)["']""", attrs)
        items.append((html.unescape(text), href and href[1], cls and cls[1]))
    return items


def wordpress_pager(base, pages, current, span=2):
    """Return the pager items the WordPress theme showed on page current of an archive with pages pages.

    This is the pager function of the old theme: range 2, showitems 2 * range + 1.
    """
    if pages == 1:
        return None

    def url(number):
        return base if number == 1 else f"{base}page/{number}/"

    showitems = 2 * span + 1
    items = []
    if current > 2 and current > span + 1 and showitems < pages:
        items.append(("«", url(1), None))
    if current > 1 and showitems < pages:
        items.append(("‹", url(current - 1), None))
    for number in range(1, pages + 1):
        if pages <= showitems or current - span <= number <= current + span:
            if number == current:
                items.append((str(number), None, "current"))
            else:
                items.append((str(number), url(number), "inactive"))
    if current < pages and showitems < pages:
        items.append(("›", url(current + 1), None))
    if current < pages - 1 and current + span - 1 < pages and showitems < pages:
        items.append(("»", url(pages), None))
    return items


def archive_page_counts(out):
    """Return {archive URL: number of pages} for every term archive in out."""
    counts = {}
    for index in sorted(out.glob("*/*/index.html")):
        archive = index.parent
        if archive.parts[-2] not in ("category", "tag", "author"):
            continue
        numbers = [int(p.name) for p in (archive / "page").glob("*") if p.name.isdigit()]
        counts["/" + str(archive.relative_to(out)) + "/"] = max(numbers, default=1)
    return counts


class ArchivePager(unittest.TestCase):
    """The archive pager shows the same items as the pager of the WordPress theme."""

    maxDiff = None

    def test_archive_with_five_pages_shows_every_page_and_no_arrows(self):
        # Live WordPress, /category/tournament-report/ page 1:
        # <span class='current'>1</span> and links to pages 2 to 5, no arrows.
        base = "/category/tournament-report/"
        self.assertEqual(archive_page_counts(build())[base], 5)
        self.assertEqual(
            pager_items(build(), base),
            [("1", None, "current")] + [(str(n), f"{base}page/{n}/", "inactive") for n in range(2, 6)],
        )

    def test_long_archive_pages_match_wordpress(self):
        # Live WordPress, /category/articles/ (26 pages).
        base = "/category/articles/"
        p = lambda n: base if n == 1 else f"{base}page/{n}/"
        self.assertEqual(archive_page_counts(build())[base], 26)
        expected = {
            1: [("1", None, "current"), ("2", p(2), "inactive"), ("3", p(3), "inactive"),
                ("›", p(2), None), ("»", p(26), None)],
            3: [("‹", p(2), None), ("1", p(1), "inactive"), ("2", p(2), "inactive"),
                ("3", None, "current"), ("4", p(4), "inactive"), ("5", p(5), "inactive"),
                ("›", p(4), None), ("»", p(26), None)],
            4: [("«", p(1), None), ("‹", p(3), None), ("2", p(2), "inactive"),
                ("3", p(3), "inactive"), ("4", None, "current"), ("5", p(5), "inactive"),
                ("6", p(6), "inactive"), ("›", p(5), None), ("»", p(26), None)],
            25: [("«", p(1), None), ("‹", p(24), None), ("23", p(23), "inactive"),
                 ("24", p(24), "inactive"), ("25", None, "current"), ("26", p(26), "inactive"),
                 ("›", p(26), None)],
        }
        for number, items in expected.items():
            with self.subTest(page=number):
                self.assertEqual(pager_items(build(), p(number)), items)

    def test_every_archive_page_matches_wordpress(self):
        out = build()
        counts = archive_page_counts(out)
        # The build must have archives on both sides of the five page limit.
        self.assertTrue({1, 2, 5, 6, 26} <= set(counts.values()))
        wrong = []
        for base, pages in counts.items():
            for number in range(1, pages + 1):
                url = base if number == 1 else f"{base}page/{number}/"
                expected = wordpress_pager(base, pages, number)
                actual = pager_items(out, url)
                if actual != expected:
                    wrong.append((url, actual, expected))
        self.assertEqual(wrong[:5], [])


FEEDS = ["index.xml", "feed/index.html"]


def feed_guids(out, feed):
    """Return (post URL path, guid element as written) for each item in the feed file in out."""
    text = (out / feed).read_text()
    # Parse first, so a feed that is not valid XML fails here.
    ElementTree.fromstring(text.encode())
    items = re.findall(r"<item>.*?<link>([^<]*)</link>.*?(<guid[^>]*>[^<]*</guid>)", text, re.S)
    return [(urlsplit(link).path, guid) for link, guid in items]


def wordpress_ids(content):
    """Return {post URL: WordPress post ID} for each post in content that has one."""
    ids = {}
    for path in sorted((content / "posts").rglob("*.*")):
        front = yaml.safe_load(path.read_text().split("---\n")[1])
        if front.get("wp_id"):
            ids[front.get("url") or f"/{front['slug']}/"] = front["wp_id"]
    return ids


class FeedGuids(unittest.TestCase):
    """Feed readers know items by GUID, so migrated posts keep the GUID WordPress gave them."""

    maxDiff = None

    def assert_wordpress_guids(self, out):
        ids = wordpress_ids(ROOT / "content")
        for feed in FEEDS:
            with self.subTest(feed=feed):
                items = [(url, guid) for url, guid in feed_guids(out, feed) if url in ids]
                self.assertEqual(len(items), 20)
                expected = [(url, f'<guid isPermaLink="false">https://stimhack.com/?p={ids[url]}</guid>') for url, _ in items]
                self.assertEqual(items, expected)

    def test_migrated_posts_keep_wordpress_guid(self):
        self.assert_wordpress_guids(build())

    def test_staging_feed_has_production_guids(self):
        self.assert_wordpress_guids(build(environment="staging"))

    def test_post_without_wordpress_id_has_permalink_guid(self):
        out = build(FIXTURE)
        for feed in FEEDS:
            with self.subTest(feed=feed):
                guids = dict(feed_guids(out, feed))
                self.assertIn(guids["/new-post/"], [
                    "<guid>https://stimhack.com/new-post/</guid>",
                    '<guid isPermaLink="true">https://stimhack.com/new-post/</guid>',
                ])
