"""Images that posts loaded from other sites that no longer serve them.

download_uploads.py fetches Internet Archive copies into
static/images/archive/<source>/, and convert.py points the posts at them.
"""
import json
import re
import sys
import time

import requests

# name -> (pattern for the original URL, with the path to keep as group 1; Wayback prefix query)
SOURCES = {
    "cardgamedb": (
        re.compile(r"""^https?://(?:www\.)?cardgamedb\.com(/forums/uploads/[^"'\s?#]+\.(?:png|jpe?g|gif))$""", re.I),
        "cardgamedb.com/forums/uploads/",
    ),
}
IN_HTML = re.compile(r"""\b(?:src|href)=["']([^"']+)""", re.I)
LOCAL_ROOT = "/images/archive"
MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8")

# Be gentle with the Internet Archive: one index query per source, then one download at a time.
DELAY = 3
MAX_RETRIES = 4

session = requests.Session()
session.headers["User-Agent"] = "stimhack-migration/1.0 (https://stimhack.com; one-time archive restore)"


def _match(url):
    """(source name, kept path) for an image from an archived source, or None."""
    for name, (pattern, _) in SOURCES.items():
        if m := pattern.match(url):
            return name, m[1]
    return None


def local_path(url):
    """Site path for an archived copy of url, or None if url is not from an archived source."""
    m = _match(url)
    return f"{LOCAL_ROOT}/{m[0]}{m[1]}" if m else None


def rewrite(url, static_root):
    """Point url at the archived copy when there is one on disk."""
    path = local_path(url)
    return path if path and (static_root / path.lstrip("/")).is_file() else url


def urls_in(html):
    return {u for u in IN_HTML.findall(html) if local_path(u)}


def _get(url, **kwargs):
    """GET with backoff. The archive answers 429 or 5xx when it wants clients to slow down."""
    for attempt in range(MAX_RETRIES):
        r = session.get(url, timeout=120, **kwargs)
        if r.status_code != 429 and r.status_code < 500:
            return r
        wait = int(r.headers.get("Retry-After", 0)) or DELAY * 10 * 2**attempt
        print(f"archive returned {r.status_code}, waiting {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise SystemExit("The Internet Archive keeps refusing requests. Try again later.")


def _captures(name, cache):
    """Map each archived path of one source to the timestamp of an image capture.

    One prefix query covers every file of the source, so the archive answers
    one index request instead of one per image. The answer is cached in cache.
    """
    pattern, prefix = SOURCES[name]
    if not cache.exists():
        r = _get(
            "https://web.archive.org/cdx/search/cdx",
            params={"url": prefix, "matchType": "prefix", "collapse": "urlkey",
                    "filter": ["statuscode:200", "mimetype:image/.*"], "fl": "original,timestamp", "output": "json"},
        )
        r.raise_for_status()
        cache.write_bytes(r.content)
    out = {}
    for original, timestamp in json.loads(cache.read_text() or "[[]]")[1:]:
        if m := pattern.match(re.sub(r":80(?=/)", "", original)):
            out.setdefault(m[1].lower(), timestamp)
    return out


def fetch(urls, static_root, export_dir):
    """Download an archived copy of each image not yet on disk.

    Writes the images the archive does not have to export_dir/missing-archived-images.txt.
    """
    missing = []
    todo = sorted(u for u in urls if not (static_root / local_path(u).lstrip("/")).exists())
    captures = {}
    for name in sorted({_match(u)[0] for u in todo}):
        captures[name] = _captures(name, export_dir / f"{name}-cdx.json")
    for i, url in enumerate(todo, 1):
        name, path = _match(url)
        timestamp = captures[name].get(path.lower())
        body = None
        if timestamp:
            time.sleep(DELAY)
            # id_ returns the file as captured, not wrapped in the Wayback page.
            r = _get(f"https://web.archive.org/web/{timestamp}id_/{url}")
            if r.ok and r.content.startswith(MAGIC):
                body = r.content
        if body is None:
            missing.append(url)
        else:
            dest = static_root / local_path(url).lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        if i % 25 == 0:
            print(f"archived images: {i}/{len(todo)}", file=sys.stderr)
    (export_dir / "missing-archived-images.txt").write_text("".join(f"{u}\n" for u in missing))
    print(f"archived images: {len(todo) - len(missing)} downloaded, {len(missing)} not archived", file=sys.stderr)
