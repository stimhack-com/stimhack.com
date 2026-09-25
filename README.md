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

A change to `SITE_ENV` does not start a build. After you change it, run the
workflow (Actions > Build and deploy > Run workflow) or push a commit.

### Set up a new repository

1. In Settings > Pages, set Source to "GitHub Actions". The first deploy
   fails until you do this.
2. In Settings > Pages, set the custom domain to `static.stimhack.com`. A
   deploy from a workflow ignores a `CNAME` file, so this setting is the
   only place for the domain.
3. In the DNS for stimhack.com, which is on Cloudflare, add a CNAME record
   from `static.stimhack.com` to `stimhack-com.github.io`. The recommended
   proxy status is "DNS only", not "Proxied", so that GitHub can issue the
   HTTPS certificate.
4. Optional: verify stimhack.com for the organization in the organization's
   GitHub settings. This stops other GitHub accounts from using the domain
   for their Pages sites.

Until the custom domain is set, GitHub serves the site at
`https://stimhack-com.github.io/stimhack.com/`. Links there that start
with `/` are broken, because the site expects to be at the root of its
domain.

### Go live

Set `SITE_ENV` to `production` and run the workflow. Change the custom
domain in Settings > Pages to `stimhack.com`, and point the DNS record
for stimhack.com at GitHub Pages.

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

By default `convert.py` keeps the content files and `data/decklists.yaml`
that exist, because contributors edit posts, author pages and
`data/decklists.yaml` after the migration. A run writes the posts, pages,
categories, tags and authors that do not have a file yet, and adds the URLs
of the export to `tests/legacy-urls.txt`. It lists each kept file that
the export has a different version of; to take the export version of one,
delete the file and run `convert.py` again. It prints the WordPress
tournament results that `data/decklists.yaml` does not contain; add them to
the file by hand.
`python3 migration/convert.py --overwrite` writes every file from the
export again and discards all edits. Use it only before anyone edits the
repository.

`export.py` also downloads Internet Archive copies of two posts that were
deleted from WordPress but are still linked from other posts
(`migration/wayback.py`), and `convert.py` restores them.

Old posts loaded images from sites that no longer serve them, such as
cardgamedb.com and BoardGameGeek's old image server. `download_uploads.py`
downloads Internet Archive copies into `static/images/archive/<host>/` and
records them in `migration/archived-images.json`
(`migration/archived_images.py`). For links to cardgamedb pages that no
longer exist, it finds an Internet Archive copy of each page and records
its web.archive.org URL in `migration/archived-links.json`
(`migration/archived_links.py`). It does not download these pages.
`convert.py` points the posts at the image copies and at the archived
pages. All requests to the archive are sequential with a pause between
them, and a re-run only asks for what is still missing. `convert.py` also
changes old NetrunnerDB card image links to card-images.netrunnerdb.com
(`migration/nrdb_images.py`).

`export.py` and `download_uploads.py` read the live WordPress site, so run
them before it is shut down. `convert.py` reads only `.export/` and the
files in the repository. Without `--overwrite`, it does not change posts
that people edited in this repository.
