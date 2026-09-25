"""Tests for the rendered site built from layouts/ and content/.

Run: python3 -m unittest discover tests
"""
import html
import re
import unittest

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
