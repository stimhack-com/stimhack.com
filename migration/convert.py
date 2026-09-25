#!/usr/bin/env python3
"""Convert the WordPress export in .export/ into Hugo content.

Migrated posts and pages keep their WordPress HTML as .html content files,
so they render as they did. Only files this script owns are written:
content/posts/<year>/<slug>.html, content/pages/<slug>.html, taxonomy
_index.md files, data/decklists.yaml and tests/legacy-urls.txt.
"""
import html
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, unquote

import yaml
from bs4 import BeautifulSoup

import archived_images
import archived_links
import nrdb_images
import wayback

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / ".export"
CONTENT = ROOT / "content"

# Pages that only made sense on WordPress.
SKIP_PAGES = {"landing", "under-maintenance", "submission-successful", "decklist-submssion"}

SITE_URL = re.compile(r"^(?:https?:)?//(?:www\.)?stimhack\.com(?=/|$)")
URL_ATTR = re.compile(r"""\b(href|src|srcset|poster|data-src)=(["'])(.*?)\2""", re.S)
IFRAME_HTTP = re.compile(r"""(<iframe\b[^>]*\bsrc=["'])http://""", re.I)
# wc-shortcodes tags that appear in the export.
SHORTCODE_TAG = re.compile(r"\[/?(?:accordion|pane|one_fourth)\b[^\]]*\]")
# Shortcodes of other plugins the WordPress site no longer ran, so it showed them as raw text.
FORM_SHORTCODE = re.compile(r"\[Form\b[^\]]*\]")
ICON_SHORTCODE = re.compile(r"\[icon name=icon-([a-z-]+)\]")
EASY_MEDIA_SHORTCODE = re.compile(r"\[easy-media\b[^\]]*\]")
# Font Awesome 3 icon names in the export -> Font Awesome 4.7 names, which the site loads.
ICON_NAMES = {"facetime-video": "video-camera"}
FORM_CLOSED = "<p><em>This form is closed.</em></p>"

# Original URL -> local copy, for images other sites no longer serve (see archived_images.py).
ARCHIVED = archived_images.load_map(ROOT / "migration" / "archived-images.json")
# Original URL -> Internet Archive copy, for cardgamedb pages (see archived_links.py).
ARCHIVED_LINKS = archived_links.load_map(ROOT / "migration" / "archived-links.json")

# Posts that WordPress moved to a new URL. Links are updated and the old URL redirects.
MOVED = {
    # Republished in 2019 in memory of the author.
    "/the-two-year-turn-how-i-learned-netrunner-by-noah-mckee/": "/the-two-year-turn/",
}


def load(name):
    return json.loads((EXPORT / f"{name}.json").read_text())


def text(rendered):
    return html.unescape(re.sub(r"<[^>]+>", "", rendered)).strip()


def path_of(link):
    return unquote(urlsplit(link).path) or "/"


def site_relative(value):
    """Rewrite absolute stimhack.com URLs in one attribute value to root-relative."""
    parts = []
    for part in value.split(","):
        stripped = part.strip()
        rewritten = SITE_URL.sub("", stripped) or "/"
        parts.append(part.replace(stripped, rewritten) if SITE_URL.match(stripped) else part)
    return ",".join(parts)


def rewrite_url(value):
    value = nrdb_images.rewrite(archived_images.rewrite(site_relative(value), ARCHIVED))
    value = archived_links.rewrite(value, ARCHIVED_LINKS)
    return MOVED.get(value, value)


def rewrite_urls(body):
    body = URL_ATTR.sub(lambda m: f"{m[1]}={m[2]}{rewrite_url(m[3])}{m[2]}", body)
    return IFRAME_HTTP.sub(r"\1https://", body)


def shortcode_attr(raw):
    """Read title="..." from a shortcode whose quotes WordPress curled into entities."""
    m = re.search(r"title=(?:&#8221;|&#8220;|&quot;|\")(.*?)(?:&#8221;|&#8220;|&#8243;|&quot;|\")", raw)
    return m[1] if m else ""


def convert_shortcodes(body):
    """Render wc-shortcodes that the live site shows as raw text.

    [one_fourth] becomes a column, consecutive columns share a row;
    [accordion][pane title="x"] becomes collapsible <details> sections.
    Tags left without a partner are removed: the one unclosed [pane] in
    the export repeats the heading above it and would wrap the whole post.
    """
    body = re.sub(r"\[one_fourth\](.*?)\[/one_fourth\]", r'<div class="sh-col">\1</div>', body, flags=re.S)
    body = re.sub(
        r'((?:<div class="sh-col">.*?</div>\s*)+)',
        lambda m: f'<div class="sh-cols">{m[1]}</div>\n',
        body,
        flags=re.S,
    )
    body = re.sub(
        r"\[pane([^\]]*)\](.*?)\[/pane\]",
        lambda m: f"<details><summary>{shortcode_attr(m[1])}</summary>{m[2]}</details>",
        body,
        flags=re.S,
    )
    return plugin_shortcodes(strip_shortcodes(body))


def strip_shortcodes(body):
    return SHORTCODE_TAG.sub("", body)


def plugin_shortcodes(body):
    """Render the shortcodes of plugins other than wc-shortcodes.

    [Form] becomes a note, because a static site cannot take the
    submissions. [icon] becomes the Font Awesome 4 icon. [easy-media] is
    removed: the gallery it names is not in the export.
    """
    body = FORM_SHORTCODE.sub(FORM_CLOSED, body)
    body = ICON_SHORTCODE.sub(lambda m: f'<i class="fa fa-{ICON_NAMES[m[1]]}" aria-hidden="true"></i>', body)
    return EASY_MEDIA_SHORTCODE.sub("", body)


def clean_body(body):
    return rewrite_urls(nrdb_images.remove_type_icons(convert_shortcodes(body)))


def iso_date(local, gmt):
    """WordPress gives local time and UTC separately. Combine them into one offset timestamp."""
    offset = int((datetime.fromisoformat(local) - datetime.fromisoformat(gmt)).total_seconds() // 60)
    sign = "+" if offset >= 0 else "-"
    return f"{local}{sign}{abs(offset) // 60:02d}:{abs(offset) % 60:02d}"


def excerpt(item):
    rendered = re.sub(r'<p>\s*<a class="continue-reading-link".*?</p>', "", item["excerpt"]["rendered"], flags=re.S)
    rendered = plugin_shortcodes(strip_shortcodes(rendered))
    return re.sub(r"\s+", " ", text(rendered))


def write(path, front, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, width=10_000)
    path.write_text(f"---\n{fm}---\n{body.strip()}\n")


def media_paths(media):
    out = {}
    for m in media:
        sizes = (m.get("media_details") or {}).get("sizes", {})
        full = path_of(m["source_url"])
        out[m["id"]] = (full, path_of(sizes["medium"]["source_url"]) if "medium" in sizes else full)
    return out


def comments_by_post(comments):
    out = {}
    for c in sorted(comments, key=lambda c: c["date"]):
        out.setdefault(c["post"], []).append({
            "id": c["id"],
            "parent": c["parent"],
            "author": html.unescape(c["author_name"]),
            "avatar": c["author_avatar_urls"].get("48", ""),
            "date": iso_date(c["date"], c["date_gmt"]),
            "content": rewrite_urls(c["content"]["rendered"]).strip(),
        })
    return out


def first_attachments(media):
    """Map post ID to the ID of the first image uploaded to that post."""
    out = {}
    for m in sorted(media, key=lambda m: m["id"]):
        if m["post"] and m["mime_type"].startswith("image/"):
            out.setdefault(m["post"], m["id"])
    return out


def convert_posts(posts, users, cats, tags, media, attached, comments, page_paths):
    for p in posts:
        front = {
            "title": text(p["title"]["rendered"]),
            "slug": p["slug"],
            "date": iso_date(p["date"], p["date_gmt"]),
            "lastmod": iso_date(p["modified"], p["modified_gmt"]),
            "authors": [users[p["author"]]],
            "categories": [cats[c] for c in p["categories"]],
            "tags": [tags[t] for t in p["tags"]],
            "summary": excerpt(p),
        }
        if p["format"] != "standard":
            front["format"] = p["format"]
        if p["featured_media"] in media:
            front["featured_image"], front["thumbnail"] = media[p["featured_media"]]
        elif p["id"] in attached:
            # Without a featured image, Tempera used the first image uploaded to the post.
            front["thumbnail"] = media[attached[p["id"]]][1]
        if p["id"] in comments:
            front["comments"] = comments[p["id"]]
        if old := [old for old, new in MOVED.items() if new == path_of(p["link"])]:
            front["aliases"] = old
        if path_of(p["link"]) in page_paths:
            # WordPress served the page at this URL and the post only by ID.
            front["url"] = f"/{p['slug']}-2/"
        front["wp_id"] = p["id"]
        write(CONTENT / "posts" / p["date"][:4] / f"{p['slug']}.html", front, clean_body(p["content"]["rendered"]))


def split_decklists(body):
    """Pull the plugin-generated decklist table out into data rows.

    Returns (intro_html, rows, older_tables_html). The older TablePress
    tables stay as HTML because nobody adds to them.
    """
    soup = BeautifulSoup(body, "html.parser")
    table = soup.find("table", id="decklists")
    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cell = {td["class"][1]: td for td in tr.find_all("td")}
        link = cell["location"].find("a")
        rows.append({
            "pack": cell["data-pack"].get_text(strip=True),
            "location": cell["location"].get_text(strip=True),
            "url": site_relative(link["href"]) if link else "",
            "type": cell["type"].get_text(strip=True),
            "players": int(cell["players"].get_text(strip=True) or 0),
            "winner": cell["winner"].get_text(strip=True),
            "runner": cell["runner"].get_text(strip=True),
            "corp": cell["corp"].get_text(strip=True),
        })
    start = body.index('<div id="decks">')
    end = body.index("</script>", body.index("new List(")) + len("</script>")
    return body[:start], rows, body[end:]


def convert_pages(pages, comments):
    for p in pages:
        if p["slug"] in SKIP_PAGES:
            continue
        body = p["content"]["rendered"]
        if p["slug"] == "tournament-decklists":
            intro, rows, older = split_decklists(body)
            (ROOT / "data").mkdir(exist_ok=True)
            (ROOT / "data" / "decklists.yaml").write_text(
                yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=10_000)
            )
            intro = re.sub(r'<p style="text-align: center;">\s*$', "", intro.rstrip())
            body = intro + "\n{{< decklists >}}\n" + older
        front = {
            "title": text(p["title"]["rendered"]),
            "url": path_of(p["link"]),
            "date": iso_date(p["date"], p["date_gmt"]),
            "lastmod": iso_date(p["modified"], p["modified_gmt"]),
            "wp_id": p["id"],
        }
        if p["id"] in comments:
            front["comments"] = comments[p["id"]]
        write(CONTENT / "pages" / f"{p['slug']}.html", front, clean_body(body))


def convert_wayback_posts(users, cats, tags):
    """Write the deleted posts in wayback.POSTS. Returns the category and tag slugs they use."""
    by_name = lambda terms: {html.unescape(t["name"]).lower(): t["slug"] for t in terms}
    users, cats, tags = by_name(users), by_name(cats), by_name(tags)
    used = set()
    for slug, timestamp in wayback.POSTS.items():
        post = wayback.parse(EXPORT / "wayback" / f"{slug}.html", ROOT / "static")
        front = {
            "title": post["title"],
            "slug": slug,
            "date": post["date"],
            "authors": [users[post["author"].lower()]],
            "categories": [cats[c.lower()] for c in post["categories"]],
            "tags": [tags[t.lower()] for t in post["tags"]],
            "comments": [dict(c, content=rewrite_urls(c["content"])) for c in post["comments"]],
            "wp_id": post["wp_id"],
            "archived_from": wayback.capture_url(slug),
        }
        used |= set(front["categories"]) | set(front["tags"])
        note = (
            f'<p><em>This article was deleted from the WordPress site. It is restored from the '
            f'<a href="{front["archived_from"]}">Internet Archive copy</a> of '
            f'{datetime.strptime(timestamp[:8], "%Y%m%d"):%B %-d, %Y}.</em></p>\n'
        )
        write(CONTENT / "posts" / post["date"][:4] / f"{slug}.html", front, note + clean_body(post["content"]))
    return used


def convert_terms(kind, terms, extra=None, used=frozenset()):
    for t in terms:
        if t.get("count", 1) == 0 and t["slug"] not in used:
            continue
        front = {"title": html.unescape(t["name"]), "slug": t["slug"]}
        if t.get("description"):
            front["description"] = html.unescape(t["description"]).strip()
        front.update((extra or {}).get(t["id"], {}))
        write(CONTENT / kind / t["slug"] / "_index.md", front, "")


def legacy_urls(posts, pages, cats, tags, users):
    """Every public WordPress URL. A test checks each one still exists in the build."""
    urls = {path_of(p["link"]) for p in posts} | set(MOVED) | {f"/{slug}/" for slug in wayback.POSTS}
    urls |= {path_of(p["link"]) for p in pages if p["slug"] not in SKIP_PAGES - {"decklist-submssion"}}
    for terms in (cats, tags, users):
        urls |= {path_of(t["link"]) for t in terms if t.get("count", 1)}
    (ROOT / "tests" / "legacy-urls.txt").write_text("\n".join(sorted(urls)) + "\n")


def main():
    posts, pages, media = load("posts"), load("pages"), load("media")
    cats, tags, users = load("categories"), load("tags"), load("users")
    authors_with_posts = {p["author"] for p in posts}
    users = [u for u in users if u["id"] in authors_with_posts]
    comments = comments_by_post(load("comments"))
    convert_posts(
        posts,
        {u["id"]: u["slug"] for u in users},
        {c["id"]: c["slug"] for c in cats},
        {t["id"]: t["slug"] for t in tags},
        media_paths(media),
        first_attachments(media),
        comments,
        {path_of(p["link"]) for p in pages if p["slug"] not in SKIP_PAGES},
    )
    convert_pages(pages, comments)
    used = convert_wayback_posts(users, cats, tags)
    convert_terms("categories", cats, used=used)
    convert_terms("tags", tags, used=used)
    convert_terms("authors", users, {u["id"]: {"avatar": u["avatar_urls"].get("96", "")} for u in users})
    legacy_urls(posts, pages, cats, tags, users)


if __name__ == "__main__":
    main()
