#!/usr/bin/env python3
"""Check a built site for broken URLs.

1. Every URL in tests/legacy-urls.txt must still exist, so links from the
   forum, Reddit and search engines keep working. The list has the URL of
   each post in the WordPress export, of each page that the site kept, of
   each category, tag and author archive, the old URL of each post that
   WordPress moved, and the URL of each deleted post restored from the
   Internet Archive. It does not have the home page,
   feeds, archive pages after the first (/page/2/), date archives or
   attachment pages.
2. Every path on this site in an href, src, poster, data-src or srcset
   attribute of the built HTML must point to a file. Relative paths, such as
   an image referenced by file name from a post's folder, are resolved
   against the URL of the page they are on. URLs with a scheme (https:,
   mailto:, data: and so on), //host URLs, and values that are only a
   #fragment or a ?query are not paths on this site and are not checked.
3. No page loads an image from an address that no longer serves images.

Usage: hugo && python3 scripts/check_site.py [DIR]

DIR is the built site to check. The default is public/.
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
# Attributes that hold one URL. srcset holds a list of URLs.
LINK_ATTRS = {"href", "src", "poster", "data-src"}
IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc=["']?([^"'\s>]+)""", re.I)
# Image addresses that are gone. Use card-images.netrunnerdb.com for card scans.
DEAD_IMAGES = re.compile(
    r"^https?://(?:www\.)?(?:cardgamedb\.com/forums/uploads/"
    r"|netrunnerdb\.com/(?:web/)?(?:bundles/|card_image/))",
    re.I,
)
# Links in old posts that were already broken on the WordPress site.
KNOWN_BROKEN = {
    line.strip()
    for line in (ROOT / "tests" / "known-broken-links.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
}


def exists(public, path):
    """Return whether a decoded path such as /post/a b.png is a file on the site."""
    target = public / path.lstrip("/")
    return target.is_file() or (target / "index.html").is_file()


def srcset_urls(srcset):
    """Return the URLs in a srcset such as "a.png 300w, b.png 600w".

    A URL is a run of characters that are not spaces, so it can contain a
    comma, as a data: URL does. A comma after the descriptors, or at the end
    of a URL that has no descriptors, separates the candidates.
    """
    urls = []
    rest = srcset
    while rest := rest.lstrip(" \t\n\r\f,"):
        url = re.match(r"\S+", rest).group()
        rest = rest[len(url):]
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            rest = rest.partition(",")[2]
        urls.append(url)
    return urls


class Links(HTMLParser):
    """Collect the URLs in the link attributes of the tags on a page."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value is None:
                continue
            if name in LINK_ATTRS:
                self.urls.append(value.strip())
            elif name == "srcset":
                self.urls.extend(srcset_urls(value))


def site_paths(page_url, html):
    """Return the decoded paths on this site that a page links to, without query or fragment."""
    links = Links()
    links.feed(html)
    links.close()
    for url in links.urls:
        parts = urlsplit(url)
        if parts.scheme or parts.netloc or not parts.path:
            continue
        yield unquote(urljoin(page_url, parts.path))


def main(args=()):
    parser = argparse.ArgumentParser(description="Check a built site for broken URLs.")
    parser.add_argument("dir", nargs="?", type=Path, default=PUBLIC, help="built site (default: public/)")
    public = parser.parse_args(args).dir

    errors = []
    for url in (ROOT / "tests" / "legacy-urls.txt").read_text().split():
        if not exists(public, unquote(urlsplit(url).path)):
            errors.append(f"legacy URL missing: {url}")

    for page in public.rglob("*.html"):
        html = page.read_text(errors="replace")
        name = page.relative_to(public).as_posix()
        for src in IMG_SRC.findall(html):
            if DEAD_IMAGES.match(src):
                errors.append(f"image from a dead address in /{name}: {src}")
        # public/<dir>/index.html is served at /<dir>/. A relative path
        # resolves to the same URL against either, since resolution drops
        # the part of the base after the last slash (RFC 3986, section 5.2.3).
        for path in site_paths("/" + quote(name), html):
            if path in KNOWN_BROKEN or exists(public, path):
                continue
            errors.append(f"broken link in /{name}: {path}")

    for error in sorted(set(errors)):
        print(error)
    print(f"{len(set(errors))} problems", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
