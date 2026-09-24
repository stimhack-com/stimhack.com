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
5. Remove `draft: true`, or set it to `false`. Drafts are not published.
6. Open a pull request. The build check runs on it and reports problems such
   as a broken internal link.

The folder name must not match an existing post or page. The build fails when
two pages have the same URL.

If you have Hugo installed, `hugo new content posts/2026/weyland-primer/index.md`
creates the file from the template, and `hugo server` shows a live preview at
`http://localhost:1313/`.

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

- `python3 -m unittest discover tests` tests the WordPress conversion script.
- `hugo --printPathWarnings --panicOnWarning` fails when two pages have the
  same URL.
- `python3 scripts/check_site.py` fails when a URL from the old WordPress site
  is missing, or when a page links to a path on this site that does not
  exist. Old links that were already broken on WordPress are listed in
  `tests/known-broken-links.txt`.

Do not build with `--minify`. The HTML minifier breaks the XML feed at `/feed/`.
