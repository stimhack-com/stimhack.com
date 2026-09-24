#!/usr/bin/env python3
"""Export all public content from the stimhack.com WordPress REST API.

Writes one JSON file per endpoint to .export/. Safe to re-run; it fetches
everything again so posts published since the last run are picked up.
"""
import json
import sys
import time
from pathlib import Path

import requests

import wayback

API = "https://stimhack.com/wp-json/wp/v2"
OUT = Path(__file__).resolve().parent.parent / ".export"
ENDPOINTS = ["posts", "pages", "media", "categories", "tags", "users", "comments"]

session = requests.Session()
session.headers["User-Agent"] = "stimhack-migration/1.0"


def get(endpoint, offset, per_page):
    """Fetch one batch, halving the batch size when the server fails on large responses."""
    while True:
        r = session.get(
            f"{API}/{endpoint}",
            params={"per_page": per_page, "offset": offset, "orderby": "id", "order": "asc"},
            timeout=120,
        )
        if r.status_code < 500:
            r.raise_for_status()
            return r, per_page
        if per_page == 1:
            # Rendering this item's content crashes the server. Keep its metadata.
            r = session.get(
                f"{API}/{endpoint}",
                params={
                    "per_page": 1, "offset": offset, "orderby": "id", "order": "asc",
                    "_fields": "id,slug,link,parent,title,date,modified,author,status,type",
                },
                timeout=120,
            )
            r.raise_for_status()
            item = r.json()[0]
            item["export_error"] = "content failed to render"
            print(f"{endpoint}: {item['link']} exported without content", file=sys.stderr)
            r._content = json.dumps([item]).encode()
            return r, 100
        per_page = max(1, per_page // 2)
        print(f"{endpoint}: HTTP {r.status_code} at offset {offset}, retrying with {per_page}", file=sys.stderr)
        time.sleep(2)


def fetch_all(endpoint):
    items, per_page = [], 100
    while True:
        r, per_page = get(endpoint, len(items), per_page)
        batch = r.json()
        items.extend(batch)
        total = int(r.headers["X-WP-Total"])
        print(f"{endpoint}: {len(items)}/{total}", file=sys.stderr)
        if not batch or len(items) >= total:
            break
        time.sleep(0.5)
    if len(items) != total:
        raise SystemExit(f"{endpoint}: got {len(items)} items, API reports {total}")
    return items


def main():
    OUT.mkdir(exist_ok=True)
    for endpoint in ENDPOINTS:
        items = fetch_all(endpoint)
        (OUT / f"{endpoint}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
        print(f"{endpoint}: {len(items)}", file=sys.stderr)
    wayback.fetch(OUT / "wayback")


if __name__ == "__main__":
    main()
