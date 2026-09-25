# Contributing to Stimhack

Stimhack is a static site built with [Hugo](https://gohugo.io/). You add or
change content with a GitHub pull request. When a maintainer merges the pull
request, GitHub Actions builds the site and publishes it.

## Write a post

You can do all of this in the GitHub web editor. You do not need to install
anything.

1. Fork the repository, or create a branch if you have write access.
2. Create a folder for the post under `content/posts/<year>/`. The folder name
   becomes the URL. For example, `content/posts/2026/weyland-primer/` is
   published at `https://stimhack.com/weyland-primer/`.
3. In that folder, create `index.md`. Copy the front matter from
   `archetypes/posts.md` and fill it in.
4. Put the post's images in the same folder and refer to them by file name:
   `![Hedge Fund](hedge-fund.png)`. Set `featured_image` to the image that
   the home page and archives show.
5. For a card image, use NetrunnerDB's image server with the five-digit card
   code: `https://card-images.netrunnerdb.com/v2/large/01001.jpg`.
6. Remove `draft: true`, or set it to `false`. Drafts are not published.
   A post with a date in the future is not published either. It appears
   only after a build that runs after that date, and builds run only when
   someone pushes to `main` or runs the workflow. No build runs on a
   schedule.
7. Open a pull request. The build check runs on it and reports problems such
   as a broken internal link.

The folder name must not match an existing post or page. The build fails when
two pages have the same URL.

If you have Hugo installed, `hugo new content posts/2026/weyland-primer/index.md`
creates the file from the template, and `hugo server -D` shows a live preview at
`http://localhost:1313/`. The template sets `draft: true`, and `hugo server`
without `-D` does not show drafts.

### Front matter

| Field | Required | Meaning |
|---|---|---|
| `title` | Yes | The post title. |
| `date` | Yes | The publish date, for example `2026-09-23T12:00:00-07:00`. |
| `authors` | Yes | A list with your author slug, for example `[sneakysly]`. |
| `categories` | Yes | Category slugs from `content/categories/`. Posts in `articles` show on the home page. |
| `tags` | No | Free-form tags. A new tag creates a new tag page. |
| `featured_image` | No | An image file in the post folder. |
| `summary` | No | Text for archive pages and link previews. If you leave it out, Hugo uses the start of the post. |
| `format` | No | Set to `video` for a post that is mainly an embedded video. Archive pages then show the whole post. |

The checks on a pull request fail when a post that is not a draft has no
title, date, authors or categories, or has an author slug that has no
`_index.md` file in `content/authors/`. The checks also apply to a post
with a date in the future. When `date` is not set, Hugo uses `publishDate`
or else `lastmod` as the date. A draft can have no date, authors or
categories, so `hugo server -D` shows a new post before you fill them in.

### Add yourself as an author

Create `content/authors/<your-slug>/_index.md`:

```markdown
---
title: Your Name
slug: your-slug
description: One or two sentences about you.
avatar: https://example.com/your-avatar.png
---
```

Your author page is published at `https://stimhack.com/author/<your-slug>/`.

## Add a tournament result

Tournament winners are in `data/decklists.yaml`. Add an entry at the top of the
list:

```yaml
- pack: Elevation
  location: Game Store, City
  url: /link-to-the-tournament-report/
  type: Regional
  players: 24
  winner: Player Name
  runner: 'Esâ Afontov: Eco-Insurrectionist'
  corp: 'Haas-Bioroid: Precision Design'
```

`url` is optional. Put quotes around a value that contains a colon.

## Posts migrated from WordPress

The posts from before the move to Hugo are HTML files with front matter, for
example `content/posts/2014/some-post.html`. They keep the WordPress markup so
that they look the same as before. You can edit them like any other file, but
write new posts in Markdown.

Uploaded files from WordPress are in `static/wp-content/uploads/` at their
old paths, so links to them from other sites keep working. Do not move or
rename them.

## Checks

Every pull request runs these checks:

- `python3 -m unittest discover tests` tests the site check script, the
  templates, and these migration scripts: `convert.py`, `wayback.py`,
  `download_uploads.py`, `archived_images.py`, `archived_links.py` and
  `nrdb_images.py`. It does not test `export.py` or
  `check_external_images.py`. The template tests build the site with Hugo.
- `hugo --printPathWarnings --panicOnWarning` fails when two pages have the
  same URL.
- `python3 scripts/check_site.py` fails when the URL of an old WordPress
  post, page or archive is missing, when an old `/?p=<ID>` or
  `/?page_id=<ID>` link in `tests/wp-ids.txt` does not go to its post or
  page, when a page links to a path on this site that does not
  exist, or when a page loads an image from an old cardgamedb.com or
  netrunnerdb.com address that no longer works. The link check reads the
  `href`, `src`, `poster`, `data-src` and `srcset` attributes, the URL in
  a meta refresh tag (Hugo's alias pages redirect with one), and the
  `og:image` and `og:url` meta tags. It checks paths that start with `/`,
  relative paths such as `hedge-fund.png`, which it resolves against the
  URL of the page, and `http`, `https` and `//host` URLs on
  `stimhack.com`, `www.stimhack.com` or the host of the build's
  `baseURL`, which it reads from the canonical link in `index.html`. It
  does not check other URLs with a scheme (`mailto:`, `data:`), URLs on
  other hosts, or values that are only a `#fragment` or a `?query`. Old
  links that were already broken on WordPress are listed in
  `tests/known-broken-links.txt`. If you fix or remove one of these
  links, or add a page at its path, remove its line from that file. The
  test `KnownBrokenLinks` in `tests/test_layouts.py` fails when a line in
  the file is not a broken link in the built site. The site finds the post or page of an
  old ID link by the `wp_id` in its front matter, so keep that line when
  you edit a migrated post or page.
  To check a site that you built to a different directory, give the
  directory: `python3 scripts/check_site.py <dir>`.
- The build fails when the built site is 950 MB or larger. The GitHub
  Pages limit is 1 GB.

To run the checks locally, install Hugo, Python 3.11 or later and Node.js.
CI uses Node.js 24. The tests need `Array.prototype.findLastIndex`, which
Node.js 13 does not have. Without Node.js the tests that run the site script skip, or
fail when the `CI` environment variable is set. Then install the Python
packages that the checks use, for example in a virtual environment:

```sh
python3 -m pip install -r requirements.txt
```

Then run the checks from the root of the repository:

```sh
python3 -m unittest discover tests
hugo --cleanDestinationDir --printPathWarnings --panicOnWarning
python3 scripts/check_site.py
```

`--cleanDestinationDir` removes the files in `public/` that are not in
`static/` before Hugo writes the pages. Without it, pages from an earlier
build stay in `public/`. A link to such a page then passes the check on your
computer, but fails in CI, which builds from a new checkout.

Do not build with `--minify`. The HTML minifier breaks the XML feed at `/feed/`.
