"""Images that posts loaded from other sites that no longer serve them.

download_uploads.py fetches Internet Archive copies into
static/images/archive/<host>/ and records each one in
migration/archived-images.json. convert.py points the posts at them.
"""
import hashlib
import html
import json
import re
import sys
import time
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import requests

# cardgamedb.com served every card image from one folder. It no longer serves any of them.
CARDGAMEDB = re.compile(r"""^https?://(?:www\.)?cardgamedb\.com/forums/uploads/[^"'\s?#]+\.(?:png|jpe?g|gif)$""", re.I)
CARDGAMEDB_PREFIX = "cardgamedb.com/forums/uploads/"
IN_HTML = re.compile(r"""\b(?:src|href)=["']([^"']+)""", re.I)
LOCAL_ROOT = "/images/archive"
EXTENSIONS = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"GIF8": ".gif", b"RIFF": ".webp"}

# Be gentle with the Internet Archive: one request at a time, a pause before each.
DELAY = 5
MAX_RETRIES = 4

session = requests.Session()
session.headers["User-Agent"] = "stimhack-migration/1.0 (https://stimhack.com; one-time archive restore)"


def load_map(path):
    return json.loads(path.read_text()) if path.exists() else {}


def rewrite(url, archived):
    """The local copy of url if there is one, else url."""
    return archived.get(url, url)


def cardgamedb_urls_in(text):
    return {u for u in IN_HTML.findall(text) if CARDGAMEDB.match(u)}


def local_path(url, extension):
    """Site path for the archived copy: /images/archive/<host>/<path>, made safe for a file system."""
    parts = urlsplit(html.unescape(url))
    path = PurePosixPath(unquote(parts.path).lstrip("/") or "index")
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", path.stem)[:80] or "image"
    if parts.query:
        stem += "-" + hashlib.sha1(parts.query.encode()).hexdigest()[:10]
    folder = "/".join(re.sub(r"[^A-Za-z0-9._-]", "_", p) for p in path.parent.parts)
    host = parts.hostname.removeprefix("www.")
    return f"{LOCAL_ROOT}/{host}/{folder + '/' if folder else ''}{stem}{extension}"


def get_with_backoff(url, **kwargs):
    """GET with backoff. The archive answers 429 or 5xx when it wants clients to slow down."""
    for attempt in range(MAX_RETRIES):
        r = session.get(url, timeout=120, **kwargs)
        if r.status_code != 429 and r.status_code < 500:
            return r
        wait = int(r.headers.get("Retry-After", 0)) or DELAY * 10 * 2**attempt
        print(f"archive returned {r.status_code}, waiting {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise SystemExit("The Internet Archive keeps refusing requests. Try again later.")


def _cdx(params):
    base = {"filter": ["statuscode:200", "mimetype:image/.*"], "fl": "original,timestamp", "output": "json"}
    r = get_with_backoff("https://web.archive.org/cdx/search/cdx", params={**base, **params})
    r.raise_for_status()
    return r.json()[1:] if r.text.strip() else []


def _key(url):
    return re.sub(r"^https?://(?:www\.)?|:80(?=/)", "", url).lower()


def _cardgamedb_captures(cache):
    """One prefix query covers every cardgamedb image. The answer is cached in cache."""
    if not cache.exists():
        cache.write_text(json.dumps([["original", "timestamp"], *_cdx(
            {"url": CARDGAMEDB_PREFIX, "matchType": "prefix", "collapse": "urlkey"})]))
    return {_key(o): t for o, t in reversed(json.loads(cache.read_text())[1:])}


def _capture(url):
    """Timestamp of an archived copy of one image, or None."""
    time.sleep(DELAY)
    rows = _cdx({"url": re.sub(r"^https?://", "", html.unescape(url)), "limit": 5})
    return rows[0][1] if rows else None


def map_existing(urls, static_root, map_path):
    """Add each url whose copy is already on disk to the map. Makes no requests."""
    archived = load_map(map_path)
    for url in urls:
        if url in archived:
            continue
        for ext in EXTENSIONS.values():
            if (static_root / (path := local_path(url, ext)).lstrip("/")).is_file():
                archived[url] = path
                break
    map_path.write_text(json.dumps(archived, indent=1, sort_keys=True) + "\n")
    return archived


def fetch(urls, static_root, export_dir, map_path):
    """Download an archived copy of each url not yet in the map at map_path.

    Writes the images the archive does not have to export_dir/missing-archived-images.txt.
    """
    archived = map_existing(urls, static_root, map_path)
    todo = sorted(u for u in urls if u not in archived)
    cardgamedb = _cardgamedb_captures(export_dir / "cardgamedb-cdx.json") if any(map(CARDGAMEDB.match, todo)) else {}
    missing = []
    try:
        for i, url in enumerate(todo, 1):
            timestamp = cardgamedb.get(_key(url)) if CARDGAMEDB.match(url) else _capture(url)
            extension = None
            if timestamp:
                time.sleep(DELAY)
                # id_ returns the file as captured, not wrapped in the Wayback page.
                r = get_with_backoff(f"https://web.archive.org/web/{timestamp}id_/{html.unescape(url)}")
                extension = next((e for magic, e in EXTENSIONS.items() if r.ok and r.content.startswith(magic)), None)
            if extension is None:
                missing.append(url)
                continue
            path = local_path(url, extension)
            (static_root / path.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
            (static_root / path.lstrip("/")).write_bytes(r.content)
            archived[url] = path
            if i % 25 == 0:
                print(f"archived images: {i}/{len(todo)}", file=sys.stderr)
    finally:
        # Saved even when the archive stops answering, so a re-run resumes.
        map_path.write_text(json.dumps(archived, indent=1, sort_keys=True) + "\n")
    (export_dir / "missing-archived-images.txt").write_text("".join(f"{u}\n" for u in missing))
    print(f"archived images: {len(archived)} in the map, {len(missing)} not archived", file=sys.stderr)
