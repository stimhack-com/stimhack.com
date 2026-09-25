# stimhack.com

The source of [stimhack.com](https://stimhack.com/), an Android: Netrunner
community site. It is a [Hugo](https://gohugo.io/) site published on GitHub
Pages. To write a post or add a tournament result, read
[CONTRIBUTING.md](CONTRIBUTING.md).

## Build locally

Install Hugo extended 0.166.0 or later, then run:

```sh
hugo server
```

The preview is at `http://localhost:1313/`.

## Deployment

Pushes to `main` deploy to GitHub Pages. The repository variable `SITE_ENV`
selects the build:

- `staging` (the default) builds for `https://static.stimhack.com/` and asks
  search engines not to index the site. Use it to review the site before it
  replaces WordPress.
- `production` builds for `https://stimhack.com/`.

To go live, set `SITE_ENV` to `production`, change the custom domain in the
repository's Pages settings to `stimhack.com`, and point the DNS record at
GitHub Pages.

## Layout

| Path | Contents |
|---|---|
| `content/posts/` | Posts. Migrated posts are `.html`; new posts are Markdown. |
| `content/pages/` | Pages such as About. Each page sets its own `url`. |
| `content/authors/`, `categories/`, `tags/` | Titles and descriptions for archive pages. |
| `data/decklists.yaml` | The tournament winners table. |
| `layouts/` | Templates. They copy the markup of the old Tempera WordPress theme. |
| `assets/css/vendor/` | CSS from the Tempera theme and WordPress plugins (GPL). |
| `static/wp-content/uploads/` | Files uploaded to WordPress, at their old URLs. |
| `migration/` | The scripts that exported the WordPress site and converted it. |
| `scripts/check_site.py` | Checks the built site for missing old URLs and broken links. |

## Migration from WordPress

The site ran on WordPress until 2026. The migration scripts read the public
WordPress REST API:

```sh
python3 migration/export.py                 # writes .export/*.json
python3 migration/check_external_images.py  # finds images other sites no longer serve
python3 migration/download_uploads.py       # downloads uploads and archived copies to static/
python3 migration/convert.py                # writes content/, data/ and tests/legacy-urls.txt
```

`export.py` also downloads Internet Archive copies of two posts that were
deleted from WordPress but are still linked from other posts
(`migration/wayback.py`), and `convert.py` restores them.

Old posts loaded images from sites that no longer serve them, such as
cardgamedb.com and BoardGameGeek's old image server. `download_uploads.py`
downloads Internet Archive copies into `static/images/archive/<host>/` and
records them in `migration/archived-images.json`
(`migration/archived_images.py`). Dead cardgamedb page links get the same
treatment in `migration/archived-links.json`. `convert.py` points the
posts at the copies. All requests to the archive are sequential with a
pause between them, and a re-run only asks for what is still missing. It also moves old NetrunnerDB card
image links to card-images.netrunnerdb.com (`migration/nrdb_images.py`).

`convert.py` overwrites the files it generated. Do not run it after the
WordPress site is shut down, or after people have edited migrated posts in
this repository.
