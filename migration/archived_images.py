"""Images that posts loaded from other sites that no longer serve them.

download_uploads.py fetches Internet Archive copies into
static/images/archive/<host>/ and records each one in
migration/archived-images.json. convert.py points the posts at them.
"""
import hashlib
import html
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import requests

# cardgamedb.com served every card image from one folder. It no longer serves any of them.
CARDGAMEDB = re.compile(r"""^https?://(?:www\.)?cardgamedb\.com/forums/uploads/[^"'\s?#]+\.(?:png|jpe?g|gif)$""", re.I)
CARDGAMEDB_PREFIX = "cardgamedb.com/forums/uploads/"
IN_HTML = re.compile(r"""\b(?:src|href)=["']([^"']+)""", re.I)
LOCAL_ROOT = "/images/archive"
EXTENSIONS = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"GIF8": ".gif", b"RIFF": ".webp"}

ARCHIVE_ERA = "2015"

# Be gentle with the Internet Archive: one request at a time, a pause before each.
DELAY = 5
MAX_RETRIES = 4
# A longer Retry-After stops the run. The maps are saved, so a later run resumes.
MAX_WAIT = 3600

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


def retry_after(value):
    """Seconds to wait from a Retry-After header, or None if it is missing, unreadable or not in the future.

    The value is a number of seconds or an HTTP date (RFC 9110 section 10.2.3).
    """
    value = (value or "").strip()
    if re.fullmatch(r"[0-9]+", value):
        return int(value) or None
    try:
        when = parsedate_to_datetime(value)
    except ValueError:
        return None
    # HTTP dates are in GMT. parsedate_to_datetime returns a naive datetime for the
    # asctime form, which has no zone (Lib/email/utils.py, parsedate_to_datetime).
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    wait = math.ceil((when - datetime.now(timezone.utc)).total_seconds())
    return wait if wait > 0 else None


def get_with_backoff(url, **kwargs):
    """GET with backoff. The archive answers 429 or 5xx when it wants clients to slow down."""
    for attempt in range(MAX_RETRIES):
        r = session.get(url, timeout=120, **kwargs)
        if r.status_code != 429 and r.status_code < 500:
            return r
        wait = retry_after(r.headers.get("Retry-After")) or DELAY * 10 * 2**attempt
        if wait > MAX_WAIT:
            raise SystemExit(f"The Internet Archive asks clients to wait {wait}s. Try again later.")
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


def available(url):
    """Timestamp of an archived copy of url that was served with status 200, or None.

    Uses the availability API, which stays up when the CDX index API is overloaded.
    It returns the capture closest to the given time. Without one it returns the
    newest capture, which for a dead page is usually the error, so ask for 2015,
    when the site was most active and most of what it linked to still worked.
    """
    time.sleep(DELAY)
    r = get_with_backoff(
        "https://archive.org/wayback/available", params={"url": html.unescape(url), "timestamp": ARCHIVE_ERA}
    )
    r.raise_for_status()
    closest = r.json().get("archived_snapshots", {}).get("closest") or {}
    return closest.get("timestamp") if closest.get("available") and closest.get("status") == "200" else None


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
            timestamp = cardgamedb.get(_key(url)) if CARDGAMEDB.match(url) else available(url)
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
