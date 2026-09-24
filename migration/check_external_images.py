#!/usr/bin/env python3
"""Find images in posts that other sites no longer serve.

Requests each external image once, reading only the response headers.
Requests to one host are at least a second apart. Writes the result to
.export/external-image-check.json as {url: "ok" | "dead <reason>"}.
Images already listed there are not checked again.
"""
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / ".export"
RESULT = EXPORT / "external-image-check.json"
IMG_SRC = re.compile(r"""<img\b[^>]*\bsrc=["'](https?://[^"']+)""", re.I)
# Hosts handled elsewhere: the site itself, cardgamedb (archived_images.py), NetrunnerDB (nrdb_images.py).
SKIP_HOSTS = re.compile(r"^(?:www\.)?(?:stimhack\.com|cardgamedb\.com|netrunnerdb\.com|card-images\.netrunnerdb\.com)$")
PER_HOST_DELAY = 1.0

session = requests.Session()
session.headers["User-Agent"] = "stimhack-migration/1.0 (https://stimhack.com; one-time link check)"


def external_images():
    urls = set()
    for kind in ("posts", "pages"):
        for item in json.loads((EXPORT / f"{kind}.json").read_text()):
            urls |= set(IMG_SRC.findall((item.get("content") or {}).get("rendered", "")))
    return sorted(u for u in urls if not SKIP_HOSTS.match(u.split("/")[2].split(":")[0].lower()))


def status(url):
    try:
        # URLs are attribute text, so "&" is written "&amp;".
        r = session.get(html.unescape(url), timeout=20, stream=True)
        r.close()
    except requests.RequestException as e:
        return f"dead {type(e).__name__}"
    if r.status_code != 200:
        return f"dead HTTP {r.status_code}"
    if not r.headers.get("content-type", "").startswith("image/"):
        return f"dead not an image ({r.headers.get('content-type', '')})"
    if "removed.png" in r.url:  # imgur's placeholder for deleted images
        return "dead removed"
    return "ok"


def main():
    result = json.loads(RESULT.read_text()) if RESULT.exists() else {}
    last_request = {}
    for url in external_images():
        if url in result:
            continue
        host = url.split("/")[2]
        wait = PER_HOST_DELAY - (time.time() - last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        result[url] = status(url)
        last_request[host] = time.time()
        time.sleep(0.3)
    RESULT.write_text(json.dumps(result, indent=1, sort_keys=True))
    dead = [u for u, s in result.items() if s != "ok"]
    print(f"{len(result)} external images, {len(dead)} dead", file=sys.stderr)


if __name__ == "__main__":
    main()
