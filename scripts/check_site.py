#!/usr/bin/env python3
"""Check a built site in public/ for broken URLs.

1. Every URL the WordPress site served (tests/legacy-urls.txt) must still
   exist, so links from the forum, Reddit and search engines keep working.
2. Every root-relative href and src in the built HTML must point to a file.
3. No page loads an image from an address that no longer serves images.

Usage: hugo && python3 scripts/check_site.py
"""
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
LINK = re.compile(r"""\b(?:href|src)=["']?(/[^"'\s>]*)""")
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


def exists(path):
    path = unquote(urlsplit(path).path)
    target = PUBLIC / path.lstrip("/")
    return target.is_file() or (target / "index.html").is_file()


def main():
    errors = []
    for url in (ROOT / "tests" / "legacy-urls.txt").read_text().split():
        if not exists(url):
            errors.append(f"legacy URL missing: {url}")

    for page in PUBLIC.rglob("*.html"):
        html = page.read_text(errors="replace")
        for src in IMG_SRC.findall(html):
            if DEAD_IMAGES.match(src):
                errors.append(f"image from a dead address in /{page.relative_to(PUBLIC)}: {src}")
        for link in LINK.findall(html):
            if link.startswith("//") or link in KNOWN_BROKEN or exists(link):
                continue
            errors.append(f"broken link in /{page.relative_to(PUBLIC)}: {link}")

    for error in sorted(set(errors)):
        print(error)
    print(f"{len(set(errors))} problems", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
