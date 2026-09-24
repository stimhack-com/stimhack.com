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
python3 migration/export.py            # writes .export/*.json
python3 migration/download_uploads.py  # downloads uploads to static/
python3 migration/convert.py           # writes content/, data/ and tests/legacy-urls.txt
```

`export.py` also downloads Internet Archive copies of two posts that were
deleted from WordPress but are still linked from other posts
(`migration/wayback.py`), and `convert.py` restores them.

`convert.py` overwrites the files it generated. Do not run it after the
WordPress site is shut down, or after people have edited migrated posts in
this repository.
