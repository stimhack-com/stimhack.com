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
2. /wp-ids.json maps every WordPress ID in tests/wp-ids.txt to the URL
   that the list gives for it, so the old links /?p=<ID> and
   /?page_id=<ID> keep working. Hugo writes the map from the wp_id front
   matter of the content files (layouts/home.wpids.json), so a file that
   loses its wp_id takes the ID out of it.
3. Every URL on this site in the built HTML must point to a file. The check
   reads the href, src, poster, data-src and srcset attributes, the url in a
   meta refresh tag (Hugo's alias pages redirect with one), and the content
   of og:image and og:url meta tags. Relative paths, such as an image
   referenced by file name from a post's folder, are resolved against the
   URL of the page they are on. An http, https or //host URL is on this site
   when its host is stimhack.com, www.stimhack.com or the host of the
   canonical link in the built index.html, which Hugo writes from the
   baseURL of the build. An http or https URL without "//" after the scheme,
   such as https:a.png, is relative to the page when its scheme is the
   scheme of the canonical link, as in a browser. Other URLs with a scheme
   (mailto:, data: and so on), URLs on other hosts, and values that are only
   a #fragment or a ?query are not checked.
4. No page loads an image from an address that no longer serves images. The
   check reads the src, poster, data-src and srcset attributes and the
   content of og:image meta tags.

Usage: hugo && python3 scripts/check_site.py [DIR]

DIR is the built site to check. The default is public/.
"""
import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
# WordPress ID and URL of each post and page that migration/convert.py wrote.
WP_IDS = ROOT / "tests" / "wp-ids.txt"
# Attributes that hold one URL. srcset holds a list of URLs.
LINK_ATTRS = {"href", "src", "poster", "data-src"}
# Attributes in LINK_ATTRS that can hold the URL of an image. srcset holds a
# list of image URLs.
IMAGE_ATTRS = {"src", "poster", "data-src"}
# Meta tags whose content attribute is a URL.
META_URL_PROPERTIES = {"og:image", "og:url"}
# The URL in the content of a meta refresh tag, such as "0; url=/a/". The
# delay can be followed by a semicolon, a comma or spaces, "url=" can be left
# out, and the URL can be in quotes. Only ASCII white space (tab, line feed,
# form feed, carriage return and space) counts as a space here, so a no-break
# space is part of the URL (HTML Standard, shared declarative refresh steps,
# https://html.spec.whatwg.org/multipage/semantics.html#shared-declarative-refresh-steps).
REFRESH_URL = re.compile(
    r"""[\t\n\f\r ]*[\d.]*(?:[\t\n\f\r ]*[;,][\t\n\f\r ]*|[\t\n\f\r ]+)"""
    r"""(?:url[\t\n\f\r ]*=[\t\n\f\r ]*)?(?:(["'])(.*?)(?:\1|$)|(.*))""",
    re.I | re.S,
)
# The characters that the URL parser removes from the start and the end of a
# URL: the C0 controls U+0000 to U+001F and space. It also removes each tab,
# line feed and carriage return inside the URL. Other white space, such as a
# no-break space, is part of the URL (URL Standard, basic URL parser,
# https://url.spec.whatwg.org/#concept-basic-url-parser). _WHATWG_C0_CONTROL_OR_SPACE
# in Lib/urllib/parse.py is the same set.
URL_TRIM = "".join(map(chr, range(0x21)))
# The characters that separate the URLs and descriptors in a srcset: space,
# tab, line feed, carriage return and form feed. Other white space, such as a
# no-break space, is part of a URL.
SRCSET_SPACE = " \t\n\r\f"
# The segments of a URL path that the URL parser reads as "." (1) or ".."
# (2), in lower case (URL Standard, single-dot and double-dot URL path
# segments, https://url.spec.whatwg.org/#single-dot-path-segment).
DOT_SEGMENTS = {".": 1, "%2e": 1, "..": 2, ".%2e": 2, "%2e.": 2, "%2e%2e": 2}
# Hosts of the production site. The host of the built site is added from its
# canonical link, since a build with another baseURL, such as one made with
# hugo --baseURL, links to its own host.
SITE_HOSTS = {"stimhack.com", "www.stimhack.com"}
# Image addresses that are gone. Use card-images.netrunnerdb.com for card scans.
# The pattern matches the host and the path of an image URL.
DEAD_IMAGES = re.compile(
    r"^(?:www\.)?(?:cardgamedb\.com/forums/uploads/"
    r"|netrunnerdb\.com/(?:web/)?(?:bundles/|card_image/))",
    re.I,
)
# Links in old posts that were already broken on the WordPress site.
KNOWN_BROKEN = {
    line.strip()
    for line in (ROOT / "tests" / "known-broken-links.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
}


def served_file(public, path):
    """Return the file in public that a decoded path such as /post/a b.png gets, or None when it gets no file.

    The path is joined as text, not as a Path, since a Path drops a slash at
    the end (_parse_path in Lib/pathlib.py) and a file name with a slash
    after it names no file (path_resolution(7), "Trailing slashes"). A file
    that the path finds outside public, such as /../a.png from a link to
    /..%2Fa.png, is not on the site.
    """
    target = os.path.join(public, path.lstrip("/"))
    for name in (target, os.path.join(target, "index.html")):
        if os.path.isfile(name):
            name = Path(name)
            return name if name.resolve().is_relative_to(Path(public).resolve()) else None
    return None


def exists(public, path):
    """Return whether a decoded path such as /post/a b.png is a file on the site."""
    return served_file(public, path) is not None


def id_problems(public):
    """Return a problem for each WordPress ID in WP_IDS that /wp-ids.json in public does not map to its URL."""
    problems = []
    try:
        urls = json.loads((public / "wp-ids.json").read_text())
    except (OSError, ValueError) as error:
        urls = {}
        problems.append(f"WordPress ID map /wp-ids.json cannot be read: {error}")
    if not isinstance(urls, dict):
        urls = {}
        problems.append("WordPress ID map /wp-ids.json is not a JSON object")
    for line in WP_IDS.read_text().splitlines():
        if not line.strip():
            continue
        wp_id, url = line.split()
        built = urls.get(str(int(wp_id)))
        if built is None:
            problems.append(f"WordPress ID missing from /wp-ids.json: {wp_id} {url}")
        elif unquote(built) != url:
            problems.append(f"WordPress ID goes to the wrong URL in /wp-ids.json: {wp_id} {built}, not {url}")
    return problems


def url_text(value):
    """Return a URL from an attribute value without the characters that the URL parser removes from it."""
    return value.strip(URL_TRIM).translate(dict.fromkeys(map(ord, "\t\n\r")))


def srcset_urls(srcset):
    """Return the URLs in a srcset such as "a.png 300w, b.png 600w".

    A URL is a run of characters that are not in SRCSET_SPACE, so it can
    contain a no-break space, and it can contain a comma, as the data: URL in
    tests/test_check_site.py does. A comma after the descriptors, or at the
    end of a URL that has no descriptors, separates the candidates. A comma inside parentheses in a descriptor also separates
    them. No srcset in .export/posts.json or .export/pages.json has
    parentheses. SRCSET_CANDIDATE in migration/convert.py splits the same way,
    which tests/test_check_site.py checks.
    """
    urls = []
    rest = srcset
    while rest := rest.lstrip(SRCSET_SPACE + ","):
        url = re.match(f"[^{SRCSET_SPACE}]+", rest).group()
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
                self.urls.append(url_text(value))
                if name in IMAGE_ATTRS:
                    self.images.append(url_text(value))
            elif name == "srcset":
                self.urls.extend(map(url_text, srcset_urls(value)))
                self.images.extend(map(url_text, srcset_urls(value)))
        attrs = {name: value or "" for name, value in attrs}
        if tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.canonical = url_text(attrs.get("href", ""))
        if tag != "meta" or "content" not in attrs:
            return
        if attrs.get("http-equiv", "").strip().lower() == "refresh":
            match = REFRESH_URL.match(attrs["content"])
            if match:
                self.urls.append(url_text(match[2] if match[1] else match[3]))
        elif attrs.get("property", "").strip().lower() in META_URL_PROPERTIES:
            self.urls.append(url_text(attrs["content"]))
            if attrs["property"].strip().lower() == "og:image":
                self.images.append(url_text(attrs["content"]))


def parse(html):
    """Return the Links of a page."""
    links = Links()
    links.feed(html)
    links.close()
    return links


def built_url(public):
    """Return the urlsplit parts of the canonical link in the built index.html, or None if it has none."""
    home = public / "index.html"
    canonical = parse(home.read_text(errors="replace")).canonical if home.is_file() else None
    return urlsplit(canonical) if canonical else None


def request_path(page_url, path):
    """Return the path that a browser requests for a path in a link on the page at page_url.

    The steps are those of the path state of the URL parser for an http or
    https URL (URL Standard, https://url.spec.whatwg.org/#path-state). They
    differ from urljoin: a ";" at the end of the path stays, and %2e is a dot
    in a "." or ".." segment.
    """
    if path.startswith("/"):
        segments = []
        path = path[1:]
    else:
        segments = page_url.split("/")[1:-1]
    names = path.split("/")
    for index, name in enumerate(names):
        dots = DOT_SEGMENTS.get(name.lower(), 0)
        if dots == 2 and segments:
            segments.pop()
        if not dots:
            segments.append(name)
        elif index == len(names) - 1:
            segments.append("")
    return "/" + "/".join(segments)


def split_url(url, scheme):
    """Return the host and the path of an http, https or relative URL on a page whose scheme is scheme, without query or fragment.

    The host is lower case, empty when the URL has a host part with no host
    in it, or None when the URL is relative to the page. The path of a URL
    that is not relative starts with a slash. Return None for a URL with
    another scheme.
    """
    url_scheme, url = re.match(r"(?:([A-Za-z][A-Za-z0-9+.-]*):)?(.*)", url, re.S).groups()
    url_scheme = (url_scheme or "").lower()
    if url_scheme not in ("", "http", "https"):
        return None
    # In an http or https URL, and so in a relative URL on a page of this
    # site, the URL parser reads a backslash before the query or the
    # fragment as a slash (URL Standard, https://url.spec.whatwg.org/#special-authority-ignore-slashes-state
    # and https://url.spec.whatwg.org/#path-state).
    before, rest = re.match(r"([^?#]*)(.*)", url, re.S).groups()
    before = before.replace("\\", "/")
    # The URL parser reads the text after the scheme of the page as a URL
    # relative to the page, so "https:a.png" on an https page is "a.png".
    # After another scheme, and after "//", it ignores each slash and reads a
    # host, so "http:a.png" on an https page is on the host a.png (URL
    # Standard, https://url.spec.whatwg.org/#scheme-state,
    # https://url.spec.whatwg.org/#special-relative-or-authority-state,
    # https://url.spec.whatwg.org/#relative-slash-state and
    # https://url.spec.whatwg.org/#special-authority-ignore-slashes-state).
    if url_scheme not in ("", scheme) or before.startswith("//"):
        parts = urlsplit("//" + before.lstrip("/") + rest)
        return parts.hostname or "", parts.path or "/"
    return None, before


def site_paths(page_url, html, hosts, scheme):
    """Return the decoded paths on this site that a page links to, without query or fragment.

    hosts are the lower case host names whose http, https and //host URLs are
    on this site, and scheme is the lower case scheme of the page's URL.
    """
    for url in parse(html).urls:
        split = split_url(url, scheme)
        if split is None:
            continue
        host, path = split
        if host is None and path or host in hosts:
            yield unquote(request_path(page_url, path))


def main(args=()):
    parser = argparse.ArgumentParser(description="Check a built site for broken URLs.")
    parser.add_argument("dir", nargs="?", type=Path, default=PUBLIC, help="built site (default: public/)")
    public = parser.parse_args(args).dir

    errors = []
    hosts = set(SITE_HOSTS)
    site = built_url(public)
    if site and site.hostname:
        hosts.add(site.hostname)
    else:
        errors.append("no canonical link with a host in /index.html, so links to the built site's host are not checked")
    # The baseURL in hugo.toml is https.
    scheme = site.scheme.lower() if site and site.scheme else "https"

    for url in (ROOT / "tests" / "legacy-urls.txt").read_text().split():
        if not exists(public, unquote(urlsplit(url).path)):
            errors.append(f"legacy URL missing: {url}")
    errors += id_problems(public)

    for page in public.rglob("*.html"):
        html = page.read_text(errors="replace")
        name = page.relative_to(public).as_posix()
        for src in parse(html).images:
            host, path = split_url(src, scheme) or (None, "")
            if host and DEAD_IMAGES.match(host + request_path("/", path)):
                errors.append(f"image from a dead address in /{name}: {src}")
        # public/<dir>/index.html is served at /<dir>/. A relative path
        # resolves to the same URL against either, since resolution drops
        # the part of the base after the last slash (RFC 3986, section 5.2.3).
        for path in site_paths("/" + quote(name), html, hosts, scheme):
            if path in KNOWN_BROKEN or exists(public, path):
                continue
            errors.append(f"broken link in /{name}: {path}")

    for error in sorted(set(errors)):
        print(error)
    print(f"{len(set(errors))} problems", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
