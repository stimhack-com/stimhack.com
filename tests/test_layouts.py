"""Tests for the rendered site built from layouts/ and content/.

Run: python3 -m unittest discover tests
"""
import html
import json
import re
import shutil
import subprocess
import sys
import tomllib
import unittest
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import yaml

from site_build import ROOT, build

sys.path.insert(0, str(ROOT / "scripts"))
import check_site  # noqa: E402


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


def wordpress_posts(content):
    """Return {post URL: front matter} for each post in content that came from WordPress."""
    posts = {}
    for path in sorted((content / "posts").rglob("*.*")):
        front = yaml.safe_load(path.read_text().split("---\n")[1])
        if front.get("wp_id"):
            posts[front.get("url") or f"/{front['slug']}/"] = front
    return posts


class FeedGuids(unittest.TestCase):
    """Feed readers know items by GUID, so migrated posts keep the GUID WordPress gave them."""

    maxDiff = None

    def assert_wordpress_guids(self, out):
        posts = wordpress_posts(ROOT / "content")
        for feed in FEEDS:
            with self.subTest(feed=feed):
                items = [(url, guid) for url, guid in feed_guids(out, feed) if url in posts]
                self.assertEqual(len(items), 20)
                expected = [(url, f'<guid isPermaLink="false">{posts[url].get("wp_guid")}</guid>') for url, _ in items]
                self.assertEqual(items, expected)

    def test_migrated_posts_keep_wordpress_guid(self):
        self.assert_wordpress_guids(build())

    def test_staging_feed_has_production_guids(self):
        self.assert_wordpress_guids(build(environment="staging"))

    def test_older_post_keeps_its_http_guid(self):
        # WordPress wrote http: GUIDs for its older posts. The main feed shows
        # only the newest posts, so the fixture has an older one.
        out = build(FIXTURE)
        for feed in FEEDS:
            with self.subTest(feed=feed):
                guids = dict(feed_guids(out, feed))
                self.assertEqual(guids["/old-post/"], '<guid isPermaLink="false">http://stimhack.com/?p=23</guid>')

    def test_every_migrated_post_has_its_wordpress_guid(self):
        wrong = [
            (url, front.get("wp_guid"))
            for url, front in wordpress_posts(ROOT / "content").items()
            if not re.fullmatch(rf"https?://stimhack\.com/\?p={front['wp_id']}", str(front.get("wp_guid")))
        ]
        self.assertEqual(wrong[:5], [])

    def test_post_without_wordpress_id_has_permalink_guid(self):
        out = build(FIXTURE)
        for feed in FEEDS:
            with self.subTest(feed=feed):
                guids = dict(feed_guids(out, feed))
                self.assertIn(guids["/new-post/"], [
                    "<guid>https://stimhack.com/new-post/</guid>",
                    '<guid isPermaLink="true">https://stimhack.com/new-post/</guid>',
                ])


# The first three pages of https://stimhack.com/feed/ (5 items each) before cutover.
WORDPRESS_FEED = [
    "/queen-bee-2023/",
    "/a-look-back-at-the-borealis-cycle/",
    "/queen-bee-2022/",
    "/deconstructing-shellgame-by-tehepicwin/",
    "/on-the-rational-player/",
    "/skill-deepdive-tactical-2-runs/",
    "/skill-deepdive-tactical-1/",
    "/state-of-the-game-2021/",
    "/everything-you-need-to-know-about-tournaments-besides-playing-netrunner/",
    "/what-makes-netrunner-special/",
    "/dead-or-alive-2018/",
    "/skill-deepdive-strategy/",
    "/yugioh-and-you-by-sanjay/",
    "/single-sided-swiss-how-it-works-by-ysengrin/",
    "/flavor-text-power-rankings/",
]


class FeedCategories(unittest.TestCase):
    """The WordPress feed left out posts in the decklists category."""

    maxDiff = None

    def test_feed_lists_the_posts_wordpress_listed(self):
        out = build()
        for feed in FEEDS:
            with self.subTest(feed=feed):
                urls = [url for url, _ in feed_guids(out, feed)]
                self.assertEqual(urls[:len(WORDPRESS_FEED)], WORDPRESS_FEED)

    def test_feed_leaves_out_decklists(self):
        # The newest posts in decklists. All three are in other categories too.
        decklists = [
            "/why-i-hate-shaper-and-you-should-too/",
            "/no-deck-is-an-island-tech-in-context-by-eric-keilback/",
            "/pawnshop-2020-a-primer/",
        ]
        out = build()
        for feed in FEEDS:
            with self.subTest(feed=feed):
                urls = [url for url, _ in feed_guids(out, feed)]
                self.assertEqual([url for url in decklists if url in urls], [])


def served(out, url):
    """Return the text GitHub Pages serves for the URL path url, or None when it serves a 404."""
    target = out / url.lstrip("/")
    for path in (target, target / "index.html"):
        if path.is_file():
            return path.read_text()
    return None


def feed_items(text):
    """Return (post URL path, date) for each item in the RSS text."""
    items = ElementTree.fromstring(text.encode()).iter("item")
    return [
        (urlsplit(item.findtext("link")).path, parsedate_to_datetime(item.findtext("pubDate")))
        for item in items
    ]


def all_posts(content):
    """Return {post URL: front matter} for each post in content."""
    posts = {}
    for path in sorted((content / "posts").rglob("*.*")):
        if path.name != "_index.md":
            front = yaml.safe_load(path.read_text().split("---\n")[1])
            posts[front.get("url") or f"/{front['slug']}/"] = front
    return posts


CONFIG = tomllib.loads((ROOT / "hugo.toml").read_text())
EXCLUDED = set(CONFIG["params"]["feedExcludeCategories"])
FEED_LIMIT = CONFIG["services"]["rss"]["limit"]


class CategoryFeeds(unittest.TestCase):
    """WordPress served a feed for each category at /category/<slug>/feed/."""

    maxDiff = None

    def test_articles_feed_lists_the_posts_wordpress_listed(self):
        # Live WordPress, https://stimhack.com/category/articles/feed/ before cutover.
        # It leaves out why-i-hate-shaper-and-you-should-too, which is in decklists too.
        wordpress = [
            "/queen-bee-2023/",
            "/a-look-back-at-the-borealis-cycle/",
            "/queen-bee-2022/",
            "/deconstructing-shellgame-by-tehepicwin/",
            "/on-the-rational-player/",
        ]
        for url in ["/category/articles/feed/", "/category/articles/index.xml"]:
            with self.subTest(url=url):
                text = served(build(), url)
                self.assertIsNotNone(text, f"{url} is not served")
                urls = [link for link, _ in feed_items(text)]
                self.assertEqual(urls[:len(wordpress)], wordpress)

    def test_decklists_feed_is_empty(self):
        # Live WordPress, https://stimhack.com/category/decklists/feed/: no items.
        text = served(build(), "/category/decklists/feed/")
        self.assertIsNotNone(text, "/category/decklists/feed/ is not served")
        self.assertEqual(feed_items(text), [])

    def test_every_category_feed_lists_its_newest_posts_without_excluded_ones(self):
        out = build()
        posts = all_posts(ROOT / "content")
        categories = sorted(p.parent.name for p in out.glob("category/*/index.html"))
        self.assertGreater(len(categories), 10)
        wrong = []
        for slug in categories:
            for url in [f"/category/{slug}/feed/", f"/category/{slug}/index.xml"]:
                text = served(out, url)
                if text is None:
                    wrong.append((url, "not served"))
                    continue
                items = feed_items(text)
                eligible = {
                    link: datetime.fromisoformat(front["date"])
                    for link, front in posts.items()
                    if slug in (front.get("categories") or []) and not EXCLUDED & set(front.get("categories") or [])
                }
                links = [link for link, _ in items]
                dates = [date for _, date in items]
                if len(links) != min(FEED_LIMIT, len(eligible)):
                    wrong.append((url, "count", len(links), len(eligible)))
                elif not set(links) <= set(eligible):
                    wrong.append((url, "not eligible", sorted(set(links) - set(eligible))))
                elif dates != sorted(dates, reverse=True):
                    wrong.append((url, "not newest first"))
                elif links and any(eligible[link] > dates[-1] for link in set(eligible) - set(links)):
                    wrong.append((url, "misses a newer post"))
        self.assertEqual(wrong, [])

    def test_category_feed_items_keep_wordpress_guid(self):
        out = build()
        posts = wordpress_posts(ROOT / "content")
        for feed in ["category/articles/feed/index.html", "category/articles/index.xml"]:
            with self.subTest(feed=feed):
                items = feed_guids(out, feed)
                self.assertEqual(len(items), FEED_LIMIT)
                expected = [(url, f'<guid isPermaLink="false">{posts[url]["wp_guid"]}</guid>') for url, _ in items]
                self.assertEqual(items, expected)

    def test_category_feed_names_itself(self):
        text = served(build(), "/category/articles/feed/")
        self.assertIsNotNone(text, "/category/articles/feed/ is not served")
        self.assertIn('<atom:link href="https://stimhack.com/category/articles/feed/" rel="self"', text)
        self.assertIn("<link>https://stimhack.com/category/articles/</link>", text)

    def test_category_pages_link_to_their_feed(self):
        out = build()
        for url in ["/category/articles/", "/category/articles/page/2/", "/category/decklists/"]:
            with self.subTest(url=url):
                slug = url.split("/")[2]
                self.assertIn(
                    f'<link rel="alternate" type="application/rss+xml" title="StimHack &raquo; {html.escape(slug.title())} Category Feed"'
                    f' href="https://stimhack.com/category/{slug}/feed/">',
                    served(out, url),
                )

    def test_site_feed_is_still_at_its_old_urls(self):
        out = build()
        for url in ["/feed/", "/index.xml"]:
            with self.subTest(url=url):
                self.assertIn('<atom:link href="https://stimhack.com/feed/" rel="self"', served(out, url))


# Open a built page once for each query string after argv[2]: run its inline
# scripts in node with a fetch that reads files from the build and a location
# that records replace(). Print what each opening did as a JSON list.
OPEN_PAGE = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const [out, page, ...searches] = process.argv.slice(1);
const html = fs.readFileSync(path.join(out, page), "utf8");
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)]
  .filter(([, attrs]) => !/\bsrc=/.test(attrs)).map(([, , code]) => code);

async function open(search) {
  const result = {replaced: null, fetched: [], errors: []};
  const location = {href: "https://stimhack.com/" + search, origin: "https://stimhack.com",
    pathname: "/", search, hash: "", replace(url) { result.replaced = url; }};
  function fetch(url) {
    const pathname = new URL(url, location.href).pathname;
    result.fetched.push(pathname);
    const file = path.join(out, pathname);
    const found = fs.existsSync(file) && fs.statSync(file).isFile();
    return Promise.resolve({ok: found, status: found ? 200 : 404,
      json: async () => { if (!found) throw new Error("404"); return JSON.parse(fs.readFileSync(file, "utf8")); }});
  }
  const context = vm.createContext({location, fetch, URL, URLSearchParams, console,
    addEventListener() {}, document: {documentElement: {style: {}}}});
  context.window = context;
  for (const code of scripts) {
    try { vm.runInContext(code, context); } catch (e) { result.errors.push(String(e)); }
  }
  await new Promise((resolve) => setTimeout(resolve, 20));
  return result;
}

(async () => {
  const results = [];
  for (const search of searches) results.push(await open(search));
  console.log(JSON.stringify(results));
})();
"""


def open_page(out, page, *searches):
    """Return what the inline scripts of page did when it was opened with each query string in searches."""
    run = subprocess.run(["node", "-e", OPEN_PAGE, str(out), page, *searches],
                         capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def wordpress_ids(content):
    """Return {WordPress ID: URL} for each post and page in content that came from WordPress."""
    ids = {}
    for path in sorted((content / "posts").rglob("*.*")):
        front = yaml.safe_load(path.read_text().split("---\n")[1])
        if front.get("wp_id"):
            ids[front["wp_id"]] = front.get("url") or f"/{front['slug']}/"
    for path in sorted((content / "pages").glob("*.*")):
        front = yaml.safe_load(path.read_text().split("---\n")[1])
        if front.get("wp_id"):
            ids[front["wp_id"]] = front["url"]
    return ids


@unittest.skipUnless(shutil.which("node"), "needs node")
class PostIdLinks(unittest.TestCase):
    """WordPress redirected /?p=<ID> and /?page_id=<ID> to the post or page with that ID."""

    maxDiff = None

    def assert_opens(self, search, expected, page="index.html"):
        [result] = open_page(build(), page, search)
        self.assertEqual((result["replaced"], result["errors"]), (expected, []))

    def test_post_id_goes_to_the_post(self):
        self.assert_opens("?p=5525", "/2014-world-championship-report-1st-place/")

    def test_page_id_goes_to_the_page(self):
        self.assert_opens("?page_id=1879", "/articles-and-guides/")

    def test_either_parameter_takes_any_id(self):
        # Posts and pages share one WordPress ID space, so either parameter finds either.
        self.assert_opens("?p=1879", "/articles-and-guides/")
        self.assert_opens("?page_id=5525", "/2014-world-championship-report-1st-place/")

    def test_posts_restored_from_the_internet_archive_keep_their_id(self):
        self.assert_opens("?p=52", "/drafting-with-netrunner/")
        self.assert_opens("?p=798", "/cube-drafting-revisited/")

    def test_other_parameters_do_not_stop_the_redirect(self):
        self.assert_opens("?utm_source=x&p=5525&replytocom=1", "/2014-world-championship-report-1st-place/")

    def test_unknown_id_stays_on_the_home_page(self):
        for search in ["?p=999999", "?p=abc", "?p=", "?page_id=0"]:
            with self.subTest(search=search):
                self.assert_opens(search, None)

    def test_home_page_without_id_does_not_load_the_map(self):
        searches = ["", "?s=netrunner", "?paged=2", "?pp=5525"]
        results = open_page(build(), "index.html", *searches)
        self.assertEqual([(r["replaced"], r["fetched"], r["errors"]) for r in results], [(None, [], [])] * len(searches))

    def test_not_found_page_redirects_old_id_links_too(self):
        self.assert_opens("?p=5525", "/2014-world-championship-report-1st-place/", page="404.html")

    def test_every_post_and_page_id_goes_to_its_url(self):
        ids = wordpress_ids(ROOT / "content")
        self.assertGreater(len(ids), 1900)
        results = open_page(build(), "index.html", *(f"?p={wp_id}" for wp_id in ids))
        wrong = [
            (wp_id, result["replaced"], url)
            for (wp_id, url), result in zip(ids.items(), results)
            if (result["replaced"], result["errors"]) != (url, [])
        ]
        self.assertEqual(wrong[:5], [])


BUNDLES = ROOT / "tests" / "fixtures" / "bundles"


def linked_paths(out, url):
    """Return the paths on the site that the page at url links to, resolved against url."""
    return set(check_site.site_paths(url, (out / url.strip("/") / "index.html").read_text()))


class BundleFiles(unittest.TestCase):
    """A new post keeps its images and files in its folder and refers to them by file name.

    A video post shows its whole content on archive pages, so there the
    references must still point to the files in the post folder.
    """

    maxDiff = None

    def test_archive_pages_link_to_the_files_in_the_post_folder(self):
        out = build(BUNDLES)
        files = {"/bundle-video/hedge-fund.png", "/bundle-video/rules.pdf"}
        for url in ["/bundle-video/", "/category/videos-and-podcasts/", "/tag/bundles/", "/author/ian/"]:
            with self.subTest(url=url):
                paths = linked_paths(out, url)
                self.assertEqual(files - paths, set(), sorted(p for p in paths if p.endswith((".png", ".pdf"))))

    def test_no_page_has_a_broken_link(self):
        out = build(BUNDLES)
        broken = []
        for page in sorted(out.rglob("*.html")):
            url = "/" + page.relative_to(out).as_posix()
            broken += [(url, path) for path in check_site.site_paths(url, page.read_text()) if not check_site.exists(out, path)]
        self.assertEqual(broken, [])
