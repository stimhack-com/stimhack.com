"""Links to cardgamedb.com card and deck pages, which no longer exist.

find() looks up an Internet Archive copy of each page and records it in
migration/archived-links.json. convert.py points the links at the copies.
Links with no archived copy stay as they are.
"""
import json
import re
import sys

from archived_images import available

CARDGAMEDB_PAGE = re.compile(r"^https?://(?:www\.)?cardgamedb\.com/(?!forums/uploads/)", re.I)
IN_HREF = re.compile(r"""\bhref=["']([^"']+)""", re.I)


def load_map(path):
    return json.loads(path.read_text()) if path.exists() else {}


def cardgamedb_links_in(text):
    return {u for u in IN_HREF.findall(text) if CARDGAMEDB_PAGE.match(u)}


def rewrite(url, archived):
    return archived.get(url, url)


def find(urls, map_path, missing_report):
    """Look up an archived copy of each url not yet in the map. One query at a time."""
    archived = load_map(map_path)
    missing = []
    try:
        for url in sorted(u for u in urls if u not in archived):
            if timestamp := available(url):
                # Keep the attribute's entity encoding so the link stays valid HTML.
                archived[url] = f"https://web.archive.org/web/{timestamp}/{url}"
            else:
                missing.append(url)
    finally:
        # Saved even when the archive stops answering, so a re-run resumes.
        map_path.write_text(json.dumps(archived, indent=1, sort_keys=True) + "\n")
    missing_report.write_text("".join(f"{u}\n" for u in missing))
    print(f"archived links: {len(archived)} in the map, {len(missing)} not archived", file=sys.stderr)
