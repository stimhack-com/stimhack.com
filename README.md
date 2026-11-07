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

Pushes to `main` build the site and deploy it to GitHub Pages at
`https://stimhack.com/`. A pull request runs the same build and checks
without a deploy, so merging it deploys it.

### Set up a new repository

1. In Settings > Pages, set Source to "GitHub Actions". The first deploy
   fails until you do this.
2. In Settings > Pages, set the custom domain to `stimhack.com`. A deploy
   from a workflow ignores a `CNAME` file, so this setting is the only
   place for the domain.
3. In the DNS for stimhack.com, which is on Cloudflare, point the domain
   at GitHub Pages. GitHub lists the current addresses in
   [Managing a custom domain for your GitHub Pages site](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site):
   - `stimhack.com` A records: `185.199.108.153`, `185.199.109.153`,
     `185.199.110.153`, `185.199.111.153`
   - `stimhack.com` AAAA records: `2606:50c0:8000::153`,
     `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153`
   - `www.stimhack.com` CNAME record: `stimhack-com.github.io`

   Set every record to "DNS only", not "Proxied", so that GitHub can issue
   the HTTPS certificate. When it has, turn on "Enforce HTTPS" in
   Settings > Pages.
4. Verify stimhack.com for the organization in the organization's GitHub
   settings. This stops other GitHub accounts from using the domain or its
   subdomains for their Pages sites.

Until the custom domain is set, GitHub serves the site at
`https://stimhack-com.github.io/stimhack.com/`. Links there that start
with `/` are broken, because the site expects to be at the root of its
domain.

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
| `scripts/check_site.py` | Checks the built site for missing old URLs, old ID links and broken links. |

## Migration from WordPress

The site ran on WordPress until 2026. The migration scripts read the public
WordPress REST API. They need the Python packages in `requirements.txt`
(`python3 -m pip install -r requirements.txt`).

```sh
python3 migration/export.py                 # writes .export/*.json
python3 migration/check_external_images.py  # finds images other sites no longer serve
python3 migration/download_uploads.py       # downloads uploads and archived copies to static/
python3 migration/convert.py                # writes content/, data/, tests/legacy-urls.txt and tests/wp-ids.txt
```

By default `convert.py` keeps the content files and `data/decklists.yaml`
that exist, because contributors edit posts, author pages and
`data/decklists.yaml` after the migration. A run writes the posts, pages,
categories, tags and authors that do not have a file yet, and adds the URLs
of the export to `tests/legacy-urls.txt` and their WordPress IDs to
`tests/wp-ids.txt`. It lists each kept file that
the export has a different version of; to take the export version of one,
delete the file and run `convert.py` again. It prints the WordPress
tournament results that `data/decklists.yaml` does not contain; add them to
the file by hand.
If the slug or date of a post or page changed in WordPress, the export gives
its `wp_id` a new path. The run keeps the file at the old path, does not
write the new one, and prints both paths. Move the file to the new path,
change it to the new slug or date, and add its old URL to `aliases`.
The unit tests fail if two content files have the same `wp_id`.
`python3 migration/convert.py --overwrite` writes every file from the
export again and discards all edits. It also removes the file at the old
path of a post or page that has a new path. Use it only before anyone edits
the repository.

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

The WordPress site was shut down on 2026-11-06, so `export.py` and
`download_uploads.py`, which read it, can no longer run. The last export is
in `.export/`, which is not in the repository. `convert.py` reads only
`.export/` and the files in the repository. Without `--overwrite`, it does
not change posts that people edited in this repository.
