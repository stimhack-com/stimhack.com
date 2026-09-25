"""Posts deleted from WordPress that other posts still link to.

The Internet Archive has copies. export.py downloads the pinned captures
into .export/wayback/ and convert.py turns them into posts at their old
URLs, with their comments.
"""
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Slug -> Wayback Machine capture timestamp (the last capture before deletion).
POSTS = {
    "drafting-with-netrunner": "20131113101435",
    "cube-drafting-revisited": "20131004012013",
}

# The site's UTC offset. WordPress used a fixed UTC-7 offset all year, not
# Pacific time with daylight saving: every local date in the export is 7
# hours behind its _gmt date, winter dates included.
OFFSET = "-07:00"
SITE_URL = re.compile(r"^https?://(?:www\.)?stimhack\.com(?::80)?")


def capture_url(slug):
    """The Wayback Machine page a reader can open."""
    return f"https://web.archive.org/web/{POSTS[slug]}/http://stimhack.com/{slug}/"


def fetch(directory):
    """Download each capture once."""
    directory.mkdir(parents=True, exist_ok=True)
    for slug in POSTS:
        dest = directory / f"{slug}.html"
        if not dest.exists():
            # id_ asks for the page as captured, without the Wayback toolbar.
            raw = f"https://web.archive.org/web/{POSTS[slug]}id_/http://stimhack.com:80/{slug}/"
            r = requests.get(raw, timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)


def _date(text, fmt):
    return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%dT%H:%M:%S") + OFFSET


def _comments(soup, uploads_root):
    out = []
    for li in soup.select("ol.commentlist li.comment"):
        article = li.find("article", recursive=False)
        meta = article.select_one(".comment-meta")
        parent = li.find_parent("li")
        avatar = article.find("img")
        avatar = SITE_URL.sub("", avatar["src"]) if avatar else ""
        if avatar.startswith("/") and not (uploads_root / avatar.lstrip("/")).exists():
            avatar = ""  # Local avatar files were deleted with the users.
        out.append({
            "id": int(li["id"].removeprefix("li-comment-")),
            "parent": int(parent["id"].removeprefix("li-comment-")) if parent else 0,
            "author": meta.find(string=True, recursive=False).strip(),
            "avatar": avatar.replace("http://", "https://"),
            "date": _date(meta.select_one(".comment-time small").get_text(), "%B %d, %Y %I:%M %p"),
            "content": meta.select_one(".comment-text").decode_contents().strip(),
        })
    return out


def parse(path, uploads_root):
    """Read one archived post page. Returns its fields, names not yet mapped to slugs."""
    soup = BeautifulSoup(Path(path).read_text(errors="replace"), "html.parser")
    meta = re.sub(r"\s+", " ", soup.select_one(".entry-meta").get_text(" ", strip=True))
    m = re.search(r"Posted by: (.+?) \| (\w+ \d+, \d{4}) \| Posted in (.+?) \|", meta)
    post_id = re.search(r"postid-(\d+)", " ".join(soup.body["class"]))
    content = soup.select_one(".entry-content")
    # Read the tags first. In both captures in .export/wayback/*.html (line 31)
    # the only rel~=tag links to /tag/ are in .entry-content div.tags, which is removed below.
    tags = [a.get_text() for a in soup.select("a[rel~=tag]") if "/tag/" in a["href"]]
    # The 2013 theme put the tag list inside the content; the new templates add their own.
    for el in content.select("div.tags, hr.divider-dotted, div.clear"):
        el.decompose()
    return {
        "title": soup.title.string.split("»", 1)[1].strip(),
        "author": m[1],
        "date": _date(m[2], "%B %d, %Y"),
        "categories": [c.strip() for c in m[3].split(",")],
        "tags": tags,
        "wp_id": int(post_id[1]),
        "content": content.decode_contents().strip(),
        "comments": _comments(soup, uploads_root),
    }
