# Stimhack WordPress to Hugo migration

## Stage 1: Export
Goal: raw JSON of all public posts, pages, media, terms, users, comments; all referenced uploads downloaded.
Success: counts match X-WP-Total; every wp-content/uploads URL referenced in content is on disk or listed as missing.
Tests: count check in exporter; missing-asset report.
Status: Done. 2 uploads were already 404 on WordPress.

## Stage 2: Convert
Goal: Hugo content tree. Migrated posts keep their WordPress HTML (fidelity); new posts are Markdown.
Success: every post/page has a file whose URL equals the WordPress permalink; internal links and upload URLs rewritten to site-relative.
Tests: URL parity check against the exported `link` of every post, page, category, tag and author.
Status: Done. tests/legacy-urls.txt + scripts/check_site.py.

## Stage 3: Theme
Goal: Hugo theme matching Tempera look (header, nav, masonry home, post, archive, decklist table search/sort).
Success: side-by-side screenshots of home, post, category, decklists, about look the same.
Tests: visual comparison; `hugo` builds with no warnings.
Status: Done (desktop + 400px checked).

## Stage 4: Contribution flow and deploy
Goal: GitHub Actions build + Pages deploy; PR preview build check; CONTRIBUTING.md with a Markdown post template.
Success: a PR that adds a Markdown post builds green; main deploys to Pages.
Tests: CI on a test PR; link checker over built site.
Status: Workflow written, not yet run. Needs the GitHub org and repo.

## Stage 5: Cutover
Goal: custom domain, DNS switch (user action), final re-export of anything posted since.
Status: Not started. Blocked on user: org name, DNS access.
