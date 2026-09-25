#!/usr/bin/env python3
"""Convert the WordPress export in .export/ into Hugo content.

Migrated posts and pages keep their WordPress HTML as .html content files,
so they render as they did. The script writes content/posts/<year>/<slug>.html,
content/pages/<slug>.html, taxonomy _index.md files, data/decklists.yaml,
tests/legacy-urls.txt and tests/wp-ids.txt. It points images and cardgamedb
links at the copies recorded in migration/archived-images.json and
migration/archived-links.json, which download_uploads.py writes, and old
NetrunnerDB card images at card-images.netrunnerdb.com.

Contributors edit these files after the migration. By default a run does
not change a post, page, _index.md or data/decklists.yaml file that exists.
For a post, page or _index.md file at the path that the export gives it,
it prints a line if the file differs from the export (save). The list below
says what it prints when a wp_id moves to a new path. For
data/decklists.yaml it prints only the WordPress rows that the file does
not contain, so a file that has all of them and other rows too gives no
output (save_decklists). It does not look at a file that no item of the
export writes, such as a content file whose wp_id is no longer in the
export: that file is kept and nothing is printed (save and write_item only
visit the items of the export). It does change tests/legacy-urls.txt and
tests/wp-ids.txt:

- A post, page or _index.md file that does not exist yet is written. One
  that exists is kept, and listed if the export has a different version.
  Delete a listed file and run again to take the export version.
- If the slug or date of a post or page changed in WordPress, the export
  can give a wp_id that a content file has to a new path. The file is
  kept, the new path is not written, and both are listed. If both files
  were there and the slug changed, the site would serve the post at two
  URLs. If only the date of a post changed, both files have the same
  slug, so the permalink /:slugorcontentbasename/ (hugo.toml, line 46)
  gives them the same URL. The CI build then stops on the duplicate
  target path: it runs hugo with --printPathWarnings --panicOnWarning
  (.github/workflows/site.yml, line 57), and Hugo logs duplicate target
  paths as a warning (hugolib/hugo_sites_build.go, printPathWarningsOnce).
  Move the file to the new path, change it to the new slug or date, and
  add its old URL to aliases.
- data/decklists.yaml is kept if it exists. The WordPress rows that it
  does not contain are printed, to add by hand.
- tests/legacy-urls.txt gets the URLs of the export added and is written
  again in sorted order. No URL is removed, because the files of posts
  removed from WordPress are kept.
- tests/wp-ids.txt gets the ID and URL of each post and page of the
  export, and is written again in order of ID. The line of an ID that the
  export does not have is kept, for the same reason.

--overwrite writes every file from the export and discards all edits.
It removes a content file that has the wp_id of a post or page the export
gives a new path. Use it only before anyone edits the repository.
"""
import argparse
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
import front_matter
import nrdb_images
import wayback

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / ".export"
CONTENT = ROOT / "content"

# Pages that only made sense on WordPress.
SKIP_PAGES = {"landing", "under-maintenance", "submission-successful", "decklist-submssion"}

SITE_URL = re.compile(r"^(?:https?:)?//(?:www\.)?stimhack\.com(?=/|$)")
URL_ATTR = re.compile(r"""\b(href|src|srcset|poster|data-src)=(["'])(.*?)\2""", re.S)
# One srcset candidate: a URL, which ends at a space, tab, line feed, carriage
# return or form feed and loses trailing commas, then either those commas or
# descriptors up to the next comma. Other white space, such as a no-break
# space, is part of the URL. A comma inside parentheses in a descriptor also
# ends the candidate. No srcset in .export/posts.json or .export/pages.json has
# parentheses. srcset_urls() in scripts/check_site.py splits a srcset the same
# way, which tests/test_check_site.py checks.
SRCSET_CANDIDATE = re.compile(r"([ \t\n\r\f,]*)([^ \t\n\r\f]*[^ \t\n\r\f,])(,+|[^,]*)")
IFRAME_HTTP = re.compile(r"""(<iframe\b[^>]*\bsrc=["'])http://""", re.I)
# wc-shortcodes tags that appear in the export.
SHORTCODE_TAG = re.compile(r"\[/?(?:accordion|pane|one_fourth)\b[^\]]*\]")
# Shortcodes of other plugins. content.rendered in .export/posts.json and
# .export/pages.json has them as text.
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


def site_relative(url):
    """Rewrite an absolute stimhack.com URL to root-relative."""
    stripped = url.strip()
    return url.replace(stripped, SITE_URL.sub("", stripped) or "/") if SITE_URL.match(stripped) else url


def rewrite_url(value):
    value = nrdb_images.rewrite(archived_images.rewrite(site_relative(value), ARCHIVED))
    value = archived_links.rewrite(value, ARCHIVED_LINKS)
    return MOVED.get(value, value)


def rewrite_srcset(value):
    return SRCSET_CANDIDATE.sub(lambda m: f"{m[1]}{rewrite_url(m[2])}{m[3]}", value)


def rewrite_urls(body):
    body = URL_ATTR.sub(
        lambda m: f"{m[1]}={m[2]}{(rewrite_srcset if m[1] == 'srcset' else rewrite_url)(m[3])}{m[2]}", body
    )
    return IFRAME_HTTP.sub(r"\1https://", body)


def shortcode_attr(raw):
    """Read title="..." from a shortcode whose quotes WordPress curled into entities."""
    m = re.search(r"title=(?:&#8221;|&#8220;|&quot;|\")(.*?)(?:&#8221;|&#8220;|&#8243;|&quot;|\")", raw)
    return m[1] if m else ""


def convert_shortcodes(body):
    """Render the wc-shortcodes tags that content.rendered in .export/posts.json has as text.

    [one_fourth] becomes a column, consecutive columns share a row;
    [accordion][pane title="x"] becomes collapsible <details> sections.
    Tags left without a partner are removed. The one unclosed [pane] in the
    export, in post 1773 of .export/posts.json, repeats the heading above
    it and would wrap the whole post.
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


def save(path, content, overwrite):
    """Write content to path. Without overwrite, keep a file that exists and say if it differs."""
    if path.exists() and not overwrite:
        # newline="" returns line endings as written (python3 -c "help(open)").
        # read_text() opens the file with the default newline=None, which
        # changes "\r" and "\r\n" to "\n" (Path.read_text in the Python 3.12 pathlib.py).
        with path.open(newline="") as f:
            differs = f.read() != content
        if differs:
            print(f"kept {path.relative_to(ROOT)}: the export has a different version")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write(path, front, body, overwrite):
    fm = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, width=10_000)
    save(path, f"---\n{fm}---\n{body.strip()}\n", overwrite)


def wp_id_files():
    """Map each wp_id in the front matter of a content file to the paths of the files that have it."""
    files = {}
    for path, front in front_matter.content_files(CONTENT):
        if "wp_id" in front:
            files.setdefault(front["wp_id"], set()).add(path)
    return files


def write_item(path, front, body, overwrite, files):
    """write() a post or page. files is wp_id_files() from before the first write.

    Another file with the same wp_id is the post at an older path, or a copy
    of it. Without overwrite it is kept and path is not written. With
    overwrite it is removed.
    """
    others = files.get(front["wp_id"], set()) - {path}
    for other in sorted(others):
        if overwrite:
            other.unlink()
            print(f"removed {other.relative_to(ROOT)}: the export has wp_id {front['wp_id']} at {path.relative_to(ROOT)}")
        else:
            print(
                f"kept {other.relative_to(ROOT)} and did not write {path.relative_to(ROOT)}:"
                f" the export has wp_id {front['wp_id']} at the second path"
            )
    if others and not overwrite:
        return
    write(path, front, body, overwrite)


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


def post_images(post, media, attached):
    """The featured_image and thumbnail front matter of a post. download_uploads.py downloads these."""
    if post["featured_media"] in media:
        full, thumbnail = media[post["featured_media"]]
        return {"featured_image": full, "thumbnail": thumbnail}
    if post["id"] in attached:
        # Without a featured image, Tempera used the first image uploaded to the post.
        return {"thumbnail": media[attached[post["id"]]][1]}
    return {}


def post_url(post, page_paths):
    """Return the URL of a post on the site. page_paths are the URLs of the pages."""
    link = path_of(post["link"])
    # WordPress served the page at this URL and the post only by ID.
    return f"/{post['slug']}-2/" if link in page_paths else link


def convert_posts(posts, users, cats, tags, media, attached, comments, page_paths, overwrite):
    files = wp_id_files()
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
        front.update(post_images(p, media, attached))
        if p["id"] in comments:
            front["comments"] = comments[p["id"]]
        if old := [old for old, new in MOVED.items() if new == path_of(p["link"])]:
            front["aliases"] = old
        if path_of(p["link"]) in page_paths:
            front["url"] = post_url(p, page_paths)
        front["wp_id"] = p["id"]
        # The feed writes this as the item GUID, so feed readers know the post.
        front["wp_guid"] = html.unescape(p["guid"]["rendered"])
        write_item(
            CONTENT / "posts" / p["date"][:4] / f"{p['slug']}.html", front, clean_body(p["content"]["rendered"]), overwrite, files
        )


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


def save_decklists(rows, overwrite):
    """Write data/decklists.yaml. Without overwrite, keep the file and print the rows it does not have."""
    path = ROOT / "data" / "decklists.yaml"
    dump = lambda rows: yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=10_000)
    if path.exists() and not overwrite:
        # Contributors add results to this file too, so the export cannot replace it.
        have = yaml.safe_load(path.read_text()) or []
        if missing := [r for r in rows if r not in have]:
            print(f"kept {path.relative_to(ROOT)}: add these WordPress rows by hand:\n{dump(missing)}")
        return
    save(path, dump(rows), overwrite)


def convert_pages(pages, comments, overwrite):
    files = wp_id_files()
    for p in pages:
        if p["slug"] in SKIP_PAGES:
            continue
        body = p["content"]["rendered"]
        if p["slug"] == "tournament-decklists":
            intro, rows, older = split_decklists(body)
            save_decklists(rows, overwrite)
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
        write_item(CONTENT / "pages" / f"{p['slug']}.html", front, clean_body(body), overwrite, files)


def convert_wayback_posts(users, cats, tags, overwrite):
    """Write the deleted posts in wayback.POSTS.

    Returns the category and tag slugs they use, and {wp_id: URL} of the posts.
    """
    by_name = lambda terms: {html.unescape(t["name"]).lower(): t["slug"] for t in terms}
    users, cats, tags = by_name(users), by_name(cats), by_name(tags)
    used = set()
    ids = {}
    files = wp_id_files()
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
            # The archived page does not show the GUID. Every post in the export
            # with an ID below 13959 has the GUID http://stimhack.com/?p=<ID>.
            "wp_guid": f"http://stimhack.com/?p={post['wp_id']}",
            "archived_from": wayback.capture_url(slug),
        }
        used |= set(front["categories"]) | set(front["tags"])
        ids[front["wp_id"]] = f"/{slug}/"
        note = (
            f'<p><em>This article was deleted from the WordPress site. It is restored from the '
            f'<a href="{front["archived_from"]}">Internet Archive copy</a> of '
            f'{datetime.strptime(timestamp[:8], "%Y%m%d"):%B %-d, %Y}.</em></p>\n'
        )
        write_item(CONTENT / "posts" / post["date"][:4] / f"{slug}.html", front, note + clean_body(post["content"]), overwrite, files)
    return used, ids


def convert_terms(kind, terms, overwrite, extra=None, used=frozenset()):
    for t in terms:
        if t.get("count", 1) == 0 and t["slug"] not in used:
            continue
        front = {"title": html.unescape(t["name"]), "slug": t["slug"]}
        if t.get("description"):
            front["description"] = html.unescape(t["description"]).strip()
        front.update((extra or {}).get(t["id"], {}))
        write(CONTENT / kind / t["slug"] / "_index.md", front, "", overwrite)


def legacy_urls(posts, pages, cats, tags, users, overwrite):
    """Write tests/legacy-urls.txt, which scripts/check_site.py checks against the build.

    The list has the URL of each post, of each page not in SKIP_PAGES (and
    of decklist-submssion, which the site still serves), of each category,
    tag and author archive that has posts, the old URL of each post in
    MOVED, and the URL of each post in wayback.POSTS. It does not have the home page, feeds, archive pages
    after the first, date archives or attachment pages.

    Without overwrite the URLs in the file are kept: the files of posts
    removed from WordPress since the last run are kept, so the site still serves them.
    """
    urls = {path_of(p["link"]) for p in posts} | set(MOVED) | {f"/{slug}/" for slug in wayback.POSTS}
    urls |= {path_of(p["link"]) for p in pages if p["slug"] not in SKIP_PAGES - {"decklist-submssion"}}
    for terms in (cats, tags, users):
        urls |= {path_of(t["link"]) for t in terms if t.get("count", 1)}
    path = ROOT / "tests" / "legacy-urls.txt"
    if path.exists() and not overwrite:
        urls |= set(path.read_text().split())
    path.write_text("\n".join(sorted(urls)) + "\n")


def wp_ids(posts, pages, page_paths, archived, overwrite):
    """Write tests/wp-ids.txt, which scripts/check_site.py checks against /wp-ids.json in the build.

    Each line is the WordPress ID and the URL of a post or page that the site
    serves, and /?p=<ID> and /?page_id=<ID> go to that URL. The list has
    each post, each page not in SKIP_PAGES (and decklist-submssion, which
    content/pages/decklist-submission.md replaces), and each post in
    wayback.POSTS: archived is {wp_id: URL} of those.

    Without overwrite the lines of IDs that the export does not have are
    kept, for the same reason as in legacy_urls.
    """
    ids = {p["id"]: post_url(p, page_paths) for p in posts} | archived
    ids |= {p["id"]: path_of(p["link"]) for p in pages if p["slug"] not in SKIP_PAGES - {"decklist-submssion"}}
    path = ROOT / "tests" / "wp-ids.txt"
    if path.exists() and not overwrite:
        kept = dict(line.split() for line in path.read_text().splitlines() if line.strip())
        ids = {int(wp_id): url for wp_id, url in kept.items()} | ids
    path.write_text("".join(f"{wp_id} {url}\n" for wp_id, url in sorted(ids.items())))


def main(overwrite=False):
    posts, pages, media = load("posts"), load("pages"), load("media")
    cats, tags, users = load("categories"), load("tags"), load("users")
    authors_with_posts = {p["author"] for p in posts}
    users = [u for u in users if u["id"] in authors_with_posts]
    comments = comments_by_post(load("comments"))
    page_paths = {path_of(p["link"]) for p in pages if p["slug"] not in SKIP_PAGES}
    convert_posts(
        posts,
        {u["id"]: u["slug"] for u in users},
        {c["id"]: c["slug"] for c in cats},
        {t["id"]: t["slug"] for t in tags},
        media_paths(media),
        first_attachments(media),
        comments,
        page_paths,
        overwrite,
    )
    convert_pages(pages, comments, overwrite)
    used, archived = convert_wayback_posts(users, cats, tags, overwrite)
    convert_terms("categories", cats, overwrite, used=used)
    convert_terms("tags", tags, overwrite, used=used)
    convert_terms("authors", users, overwrite, {u["id"]: {"avatar": u["avatar_urls"].get("96", "")} for u in users})
    legacy_urls(posts, pages, cats, tags, users, overwrite)
    wp_ids(posts, pages, page_paths, archived, overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--overwrite", action="store_true", help="write every file from the export and discard edits made since the last run"
    )
    main(parser.parse_args().overwrite)
