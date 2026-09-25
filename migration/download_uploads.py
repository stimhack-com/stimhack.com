#!/usr/bin/env python3
"""Download every upload the site uses into static/wp-content/uploads/.

Collects the original file of every media item (other sites link to them),
the featured image and thumbnail that convert.py writes into each post's
front matter, and every uploads URL referenced in post and page HTML. Other
WordPress size variants are not used and would push the site over the 1 GB
GitHub Pages limit.

Files already on disk are skipped. Files on disk that are not in the set are
moved to .export/unused-uploads/. Writes .export/missing-uploads.txt for URLs
the server no longer has.
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

import archived_images
import archived_links
import convert

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / ".export"
STATIC = ROOT / "static"
UPLOAD_RE = re.compile(r"""(?:https?:)?//(?:www\.)?stimhack\.com(/wp-content/uploads/[^"'\s<>)?#]+)""")

session = requests.Session()
session.headers["User-Agent"] = "stimhack-migration/1.0"


def upload_paths():
    media = json.loads((EXPORT / "media.json").read_text())
    paths = set()
    for m in media:
        paths.add(urlsplit(m["source_url"]).path)
    for kind in ("posts", "pages"):
        for item in json.loads((EXPORT / f"{kind}.json").read_text()):
            html = (item.get("content") or {}).get("rendered", "")
            paths.update(UPLOAD_RE.findall(html))
    paths = {unquote(p) for p in paths}
    # The featured_image and thumbnail paths that convert.py writes, already unquoted.
    images, attached = convert.media_paths(media), convert.first_attachments(media)
    for post in json.loads((EXPORT / "posts.json").read_text()):
        paths.update(convert.post_images(post, images, attached).values())
    return sorted(paths)


def move_unused(paths):
    wanted = {STATIC / p.lstrip("/") for p in paths}
    uploads = STATIC / "wp-content" / "uploads"
    for f in [f for f in uploads.rglob("*") if f.is_file() and f not in wanted]:
        dest = EXPORT / "unused-uploads" / f.relative_to(uploads)
        dest.parent.mkdir(parents=True, exist_ok=True)
        f.rename(dest)


def fetch(path):
    dest = STATIC / path.lstrip("/")
    if dest.exists():
        return path, "cached"
    r = session.get("https://stimhack.com" + path, timeout=120)
    if r.status_code != 200 or r.headers.get("content-type", "").startswith("text/html"):
        return path, f"HTTP {r.status_code}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return path, "ok"


def main():
    paths = upload_paths()
    print(f"{len(paths)} upload paths", file=sys.stderr)
    missing = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (path, status) in enumerate(pool.map(fetch, paths), 1):
            if status.startswith("HTTP"):
                missing.append(f"{status} {path}")
            if i % 250 == 0:
                print(f"{i}/{len(paths)}", file=sys.stderr)
    (EXPORT / "missing-uploads.txt").write_text("\n".join(missing) + "\n")
    print(f"missing: {len(missing)}", file=sys.stderr)
    move_unused(paths)
    html = "".join(
        (item.get("content") or {}).get("rendered", "")
        for kind in ("posts", "pages")
        for item in json.loads((EXPORT / f"{kind}.json").read_text())
    )
    # Dead external images, found by check_external_images.py.
    checked = EXPORT / "external-image-check.json"
    dead = {u for u, s in json.loads(checked.read_text()).items() if s != "ok"} if checked.exists() else set()
    archived_images.fetch(
        archived_images.cardgamedb_urls_in(html) | dead, STATIC, EXPORT, ROOT / "migration" / "archived-images.json"
    )
    archived_links.find(
        archived_links.cardgamedb_links_in(html),
        ROOT / "migration" / "archived-links.json",
        EXPORT / "missing-archived-links.txt",
    )


if __name__ == "__main__":
    main()
