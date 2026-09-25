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
2. Every URL on this site in the built HTML must point to a file. The check
   reads the href, src, poster, data-src and srcset attributes, the url in a
   meta refresh tag (Hugo's alias pages redirect with one), and the content
   of og:image and og:url meta tags. Relative paths, such as an image
   referenced by file name from a post's folder, are resolved against the
   URL of the page they are on. An http, https or //host URL is on this site
   when its host is stimhack.com, www.stimhack.com or the host of the
   canonical link in the built index.html, which Hugo writes from the
   baseURL of the build. Other URLs with a scheme (mailto:, data: and so
   on), URLs on other hosts, and values that are only a #fragment or a
   ?query are not checked.
3. No page loads an image from an address that no longer serves images. The
   check reads the src, poster, data-src and srcset attributes and the
   content of og:image meta tags.

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
# Attributes in LINK_ATTRS that can hold the URL of an image. srcset holds a
# list of image URLs.
IMAGE_ATTRS = {"src", "poster", "data-src"}
# Meta tags whose content attribute is a URL.
META_URL_PROPERTIES = {"og:image", "og:url"}
# The URL in the content of a meta refresh tag, such as "0; url=/a/". The
# delay can be followed by a semicolon, a comma or spaces, "url=" can be left
# out, and the URL can be in quotes.
REFRESH_URL = re.compile(r"""\s*[\d.]*(?:\s*[;,]\s*|\s+)(?:url\s*=\s*)?(?:(["'])(.*?)(?:\1|$)|(.*))""", re.I | re.S)
# Hosts of the production site. The host of the built site is added from its
# canonical link, since a staging build has another baseURL.
SITE_HOSTS = {"stimhack.com", "www.stimhack.com"}
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
    """Collect the URLs that the tags on a page link to, the image URLs among them, and the page's canonical URL."""

    def __init__(self):
        super().__init__()
        self.urls = []
        self.images = []
        self.canonical = None

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value is None:
                continue
            if name in LINK_ATTRS:
                self.urls.append(value.strip())
                if name in IMAGE_ATTRS:
                    self.images.append(value.strip())
            elif name == "srcset":
                self.urls.extend(srcset_urls(value))
                self.images.extend(srcset_urls(value))
        attrs = {name: value or "" for name, value in attrs}
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.canonical = attrs.get("href", "").strip()
        if tag != "meta" or "content" not in attrs:
            return
        if attrs.get("http-equiv", "").strip().lower() == "refresh":
            match = REFRESH_URL.match(attrs["content"])
            if match:
                self.urls.append((match[2] if match[1] else match[3]).strip())
        elif attrs.get("property", "").strip().lower() in META_URL_PROPERTIES:
            self.urls.append(attrs["content"].strip())
            if attrs["property"].strip().lower() == "og:image":
                self.images.append(attrs["content"].strip())


def parse(html):
    """Return the Links of a page."""
    links = Links()
    links.feed(html)
    links.close()
    return links


def built_host(public):
    """Return the host of the canonical link in the built index.html, or None if it has none."""
    home = public / "index.html"
    canonical = parse(home.read_text(errors="replace")).canonical if home.is_file() else None
    return urlsplit(canonical).hostname if canonical else None


def site_paths(page_url, html, hosts):
    """Return the decoded paths on this site that a page links to, without query or fragment.

    hosts are the lower case host names whose http, https and //host URLs are on this site.
    """
    for url in parse(html).urls:
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            if parts.scheme.lower() not in ("", "http", "https") or parts.hostname not in hosts:
                continue
            path = parts.path or "/"
        elif parts.path:
            path = parts.path
        else:
            continue
        yield unquote(urljoin(page_url, path))


def main(args=()):
    parser = argparse.ArgumentParser(description="Check a built site for broken URLs.")
    parser.add_argument("dir", nargs="?", type=Path, default=PUBLIC, help="built site (default: public/)")
    public = parser.parse_args(args).dir

    errors = []
    hosts = set(SITE_HOSTS)
    if host := built_host(public):
        hosts.add(host)
    else:
        errors.append("no canonical link with a host in /index.html, so links to the built site's host are not checked")

    for url in (ROOT / "tests" / "legacy-urls.txt").read_text().split():
        if not exists(public, unquote(urlsplit(url).path)):
            errors.append(f"legacy URL missing: {url}")

    for page in public.rglob("*.html"):
        html = page.read_text(errors="replace")
        name = page.relative_to(public).as_posix()
        for src in parse(html).images:
            if DEAD_IMAGES.match(src):
                errors.append(f"image from a dead address in /{name}: {src}")
        # public/<dir>/index.html is served at /<dir>/. A relative path
        # resolves to the same URL against either, since resolution drops
        # the part of the base after the last slash (RFC 3986, section 5.2.3).
        for path in site_paths("/" + quote(name), html, hosts):
            if path in KNOWN_BROKEN or exists(public, path):
                continue
            errors.append(f"broken link in /{name}: {path}")

    for error in sorted(set(errors)):
        print(error)
    print(f"{len(set(errors))} problems", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
